"""Core generate → test → fix loop."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import anthropic

from generator.context import build_context, REPO_ROOT
from generator.prompts import SYSTEM_PROMPT, GENERATE_PROMPT, FIX_PROMPT
from generator.server import (
    setup_venv,
    start_server,
    stop_server,
    wait_for_health,
    read_generated_code,
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


def write_files(output_dir: Path, files: dict[str, str]) -> None:
    """Write parsed files to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        target = output_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"  Wrote {rel_path} ({len(content)} bytes)")


def run_tests(profile: str, port: int) -> tuple[bool, str, int]:
    """Run pytest for the given profile against localhost:{port}.

    Returns (success, output_text, failure_count).
    """
    profile_path = REPO_ROOT / "profiles" / f"{profile}.ini"
    cmd = [
        sys.executable, "-m", "pytest",
        "-c", str(profile_path),
        "--tb=short",
        "-q",
        "--no-header",
    ]
    env = {
        **__import__("os").environ,
        "CMDB_BASE_URL": f"http://localhost:{port}",
        "PYTHONPATH": str(REPO_ROOT),
    }

    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )

    output = result.stdout + "\n" + result.stderr
    success = result.returncode == 0

    # Count failures from pytest output
    failure_count = 0
    for line in output.splitlines():
        # Matches "3 failed" or "3 failed, 10 passed"
        m = re.search(r"(\d+) failed", line)
        if m:
            failure_count = int(m.group(1))
            break

    return success, output, failure_count


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
    ):
        self.profile = profile
        self.backend = backend
        self.output_dir = Path(output_dir).resolve()
        self.max_iterations = max_iterations
        self.model = model
        self.port = port
        self.client = anthropic.Anthropic()

    def _call_llm(self, system: str, user: str) -> str:
        """Send a message to Claude and return the text response."""
        print(f"  Calling {self.model}...")
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16384,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Extract text from response
        text_parts = [block.text for block in response.content if block.type == "text"]
        return "\n".join(text_parts)

    def run(self) -> bool:
        """Execute the generate → test → fix loop. Returns True if all tests pass."""
        print(f"Building context for profile '{self.profile}'...")
        ctx = build_context(self.profile)

        system = SYSTEM_PROMPT.format(backend=self.backend, port=self.port)

        for iteration in range(1, self.max_iterations + 1):
            print(f"\n{'='*60}")
            print(f"Iteration {iteration}/{self.max_iterations}")
            print(f"{'='*60}")

            # --- Generate or fix ---
            if iteration == 1:
                print("Generating initial implementation...")
                user_prompt = GENERATE_PROMPT.format(**ctx)
            else:
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

            # --- Setup environment (first iteration only for venv) ---
            setup_venv(self.output_dir)

            # --- Start server ---
            print(f"Starting server on port {self.port}...")
            proc = start_server(self.output_dir, self.port)

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
                    return True
                else:
                    print(f"\n{failure_count} test(s) failed.")
                    # Print a summary of failures
                    for line in test_output.splitlines():
                        if line.startswith("FAILED") or "ERROR" in line:
                            print(f"  {line}")

            finally:
                stop_server(proc)

        print(f"\nFailed to pass all tests after {self.max_iterations} iterations.")
        print(f"Last test output:\n{test_output}")
        return False
