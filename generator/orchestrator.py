"""Core generate → test → fix loop."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from generator.backends import parse_backend
from generator.context import REPO_ROOT, build_context
from generator.prompts import FIX_PROMPT, GENERATE_PROMPT, SYSTEM_PROMPT
from generator.providers import create_provider
from generator.server import (
    read_generated_code,
    setup_non_python,
    setup_venv,
    start_non_python_server,
    start_server,
    stop_server,
    wait_for_health,
)


def parse_files(response_text: str) -> dict[str, str]:
    """Extract files from <file path="...">...</file> blocks in LLM output."""
    pattern = re.compile(
        r'<file\s+path="([^"]+)">\s*\n(.*?)\n</file>',
        re.DOTALL,
    )
    files: dict[str, str] = {}
    for match in pattern.finditer(response_text):
        path = match.group(1).strip()
        content = match.group(2)
        files[path] = content
    return files


# Files that must NOT be written — they belong to the spec repo, not the generated server
_BLOCKED_FILES = {"pytest.ini", "conftest.py", "setup.cfg", "pyproject.toml"}


def write_files(output_dir: Path, files: dict[str, str]) -> None:
    """Write parsed files to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        if rel_path in _BLOCKED_FILES:
            print(f"  Skipped {rel_path} (belongs to spec repo)")
            continue
        target = output_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"  Wrote {rel_path} ({len(content)} bytes)")


def run_tests(profile: str, port: int) -> tuple[bool, str, int]:
    """Run pytest for the given profile against localhost:{port}.

    Returns (success, output_text, failure_count).
    """
    profile_path = REPO_ROOT / "profiles" / f"{profile}.ini"

    # Read testpaths from the profile
    _cfg = __import__("configparser").ConfigParser()
    _cfg.read(str(profile_path))
    _testpaths = _cfg.get("pytest", "testpaths", fallback="suites/core").split()
    # Resolve to absolute paths
    _abs_testpaths = [str(REPO_ROOT / tp) for tp in _testpaths]

    cmd = [
        sys.executable, "-m", "pytest",
        "--rootdir", str(REPO_ROOT),
        "--override-ini", f"pythonpath={REPO_ROOT}",
        "--tb=short",
        "-q",
        "--no-header",
        "-x",  # Stop on first failure — faster feedback for fix iterations
        *_abs_testpaths,
    ]
    env = {
        **__import__("os").environ,
        "CMDB_BASE_URL": f"http://localhost:{port}",
        "PYTHONPATH": str(REPO_ROOT),
        "HYPOTHESIS_PROFILE": "ci",
    }

    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        output = result.stdout + "\n" + result.stderr
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        output = (
            "pytest timed out after 300 seconds. Tests may be hanging "
            "(infinite loop, unresponsive server, or slow Hypothesis generation)."
        )
        success = False

    # Count failures from pytest output
    failure_count = 0
    for line in output.splitlines():
        # Matches "3 failed" or "3 failed, 10 passed"
        m = re.search(r"(\d+) failed", line)
        if m:
            failure_count = int(m.group(1))
            break
    if not success and failure_count == 0:
        failure_count = 1  # At least 1 failure if not successful

    return success, output, failure_count


def count_tests(output: str) -> tuple[int, int]:
    """Parse pytest output for passed/total counts."""
    passed = 0
    total = 0
    for line in output.splitlines():
        # "181 passed" or "3 failed, 178 passed, 14 skipped"
        m_passed = re.search(r"(\d+) passed", line)
        m_failed = re.search(r"(\d+) failed", line)
        m_error = re.search(r"(\d+) error", line)
        if m_passed:
            passed = int(m_passed.group(1))
            total = passed
            if m_failed:
                total += int(m_failed.group(1))
            if m_error:
                total += int(m_error.group(1))
    return passed, total


def truncate_output(text: str, max_lines: int = 200) -> str:
    """Truncate test output to avoid blowing context limits on fix prompts."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    # Keep first chunk and last chunk
    head = lines[:max_lines // 2]
    tail = lines[-(max_lines // 2):]
    return "\n".join(head + [f"\n... ({len(lines) - max_lines} lines truncated) ...\n"] + tail)


class Orchestrator:
    def __init__(
        self,
        profile: str = "minimal",
        backend: str = "python/fastapi/sqlite",
        output_dir: str = "./generated",
        max_iterations: int = 5,
        model: str = "claude-sonnet-4-6",
        port: int = 8080,
        provider: str | None = None,
        no_cache: bool = False,
        badge: bool = False,
        badge_dir: str | None = None,
    ):
        self.profile = profile
        self.backend = backend
        self.backend_spec = parse_backend(backend)
        self.output_dir = Path(output_dir).resolve()
        self.max_iterations = max_iterations
        self.model = model
        self.port = port
        self.llm = create_provider(model, provider)
        self.no_cache = no_cache
        self.badge = badge
        self.badge_dir = Path(badge_dir) if badge_dir else self.output_dir

    def _call_llm(self, system: str, user: str) -> str:
        """Send a message to the LLM and return the text response."""
        print(f"  Calling {self.llm.model_name}...")
        try:
            return self.llm.generate(system, user)
        except Exception as e:
            print(f"  ERROR from LLM provider: {type(e).__name__}: {e}")
            raise

    def _setup_env(self) -> None:
        """Set up the runtime environment for the generated server."""
        if self.backend_spec.needs_venv:
            setup_venv(self.output_dir)
        else:
            setup_non_python(self.output_dir, self.backend_spec)

    def _start_server(self) -> subprocess.Popen:
        """Start the generated server."""
        if self.backend_spec.needs_venv:
            return start_server(self.output_dir, self.port)
        else:
            return start_non_python_server(self.output_dir, self.port, self.backend_spec)

    def _generate_badge(self, test_output: str, success: bool) -> None:
        """Generate compliance badge if requested."""
        if not self.badge:
            return

        from generator.badge import generate_badge

        passed, total = count_tests(test_output)
        if total == 0:
            total = passed  # Fallback

        _, md = generate_badge(self.profile, passed, total, self.badge_dir)
        print(f"\nBadge generated: {self.badge_dir / f'badge-{self.profile}.svg'}")
        print(f"Markdown: {md}")

    def run(self) -> bool:
        """Execute the generate → test → fix loop. Returns True if all tests pass."""
        # --- Check cache ---
        if not self.no_cache:
            from generator.cache import get_cached, restore_cache, save_cache

            cached = get_cached(self.profile, self.backend)
            if cached:
                print(f"Found cached artifact for {self.profile}/{self.backend}")
                print(f"Restoring from {cached}...")
                restore_cache(cached, self.output_dir)
                print("Cached implementation restored. Run tests to verify.")
                return True

        print(f"Building context for profile '{self.profile}'...")
        ctx = build_context(self.profile)

        bs = self.backend_spec
        system = SYSTEM_PROMPT.format(
            backend=self.backend,
            port=self.port,
            entry_point=bs.entry_point,
            deps_file=bs.deps_file,
            extra_constraints=bs.extra_constraints,
        )

        failure_count = 0
        test_output = ""

        for iteration in range(1, self.max_iterations + 1):
            print(f"\n{'='*60}")
            print(f"Iteration {iteration}/{self.max_iterations}")
            print(f"{'='*60}")

            # --- Generate or fix ---
            if iteration == 1:
                print("Generating initial implementation...")
                user_prompt = GENERATE_PROMPT.format(**ctx)
            else:
                # Cooldown between iterations to respect rate limits
                import time
                print("Waiting 60s for rate limit cooldown...")
                time.sleep(60)

                print("Generating fix...")
                current_code = read_generated_code(self.output_dir)
                user_prompt = FIX_PROMPT.format(
                    failure_count=failure_count,
                    test_output=truncate_output(test_output),
                    current_code=current_code,
                )

            response_text = self._call_llm(system, user_prompt)

            # --- Parse and write files ---
            files = parse_files(response_text)
            if not files:
                print("ERROR: LLM returned no parseable files. Raw response:")
                print(response_text[:2000])
                return False

            write_files(self.output_dir, files)

            # --- Setup environment ---
            self._setup_env()

            # --- Start server ---
            print(f"Starting server on port {self.port}...")
            proc = self._start_server()

            try:
                if not wait_for_health(self.port):
                    print("ERROR: Server failed to start. stderr:")
                    stderr = proc.stderr.read().decode() if proc.stderr else ""
                    stdout = proc.stdout.read().decode() if proc.stdout else ""
                    print(stderr or stdout or "(no output)")
                    # Treat startup failure as test failure for next iteration
                    test_output = f"Server failed to start.\nstderr:\n{stderr}\nstdout:\n{stdout}"
                    failure_count = 999
                    continue

                print("Server is healthy. Running tests...")

                # --- Run tests ---
                success, test_output, failure_count = run_tests(self.profile, self.port)

                if success:
                    print(f"\nAll tests passed on iteration {iteration}!")
                    print(f"Implementation written to: {self.output_dir}")

                    # Cache successful artifact
                    if not self.no_cache:
                        from generator.cache import save_cache
                        cache_path = save_cache(self.profile, self.backend, self.output_dir)
                        print(f"Cached artifact to: {cache_path}")

                    # Generate badge
                    self._generate_badge(test_output, True)

                    return True
                else:
                    print(f"\n{failure_count} test(s) failed.")
                    # Print a summary of failures
                    for line in test_output.splitlines():
                        if line.startswith("FAILED") or "ERROR" in line:
                            print(f"  {line}")

            finally:
                stop_server(proc)

        # Generate badge even on failure (shows partial compliance)
        self._generate_badge(test_output, False)

        print(f"\nFailed to pass all tests after {self.max_iterations} iterations.")
        print(f"Last test output:\n{test_output}")
        return False
