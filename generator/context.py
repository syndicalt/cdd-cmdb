"""Reads specs, schemas, and test suites into a structured context for LLM prompts."""
from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def read_openapi() -> str:
    spec_dir = REPO_ROOT / "specs" / "openapi"
    parts: list[str] = []
    for f in sorted(spec_dir.glob("*.yaml")):
        parts.append(f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def read_schemas() -> str:
    schema_dir = REPO_ROOT / "specs" / "schemas"
    parts: list[str] = []
    for f in sorted(schema_dir.glob("*.json")):
        parts.append(f"### {f.name}\n```json\n{f.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(parts)


def read_test_suites(profile: str) -> str:
    """Read all test files for the given profile.

    Parses the profile .ini to find testpaths, then reads all test_*.py files.
    """
    profile_path = REPO_ROOT / "profiles" / f"{profile}.ini"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_path}")

    config = configparser.ConfigParser()
    config.read(str(profile_path))
    testpaths = config.get("pytest", "testpaths", fallback="suites/core").split()

    parts: list[str] = []
    for tp in testpaths:
        suite_dir = REPO_ROOT / tp
        if not suite_dir.exists():
            continue
        for f in sorted(suite_dir.rglob("test_*.py")):
            rel = f.relative_to(REPO_ROOT)
            parts.append(f"### {rel}\n```python\n{f.read_text(encoding='utf-8')}\n```")

    return "\n\n".join(parts)


def read_harness_code() -> str:
    """Read harness code so the LLM understands the client contract."""
    harness_dir = REPO_ROOT / "harness"
    parts: list[str] = []
    for f in sorted(harness_dir.rglob("*.py")):
        if f.name == "__init__.py":
            continue
        rel = f.relative_to(REPO_ROOT)
        parts.append(f"### {rel}\n```python\n{f.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(parts)


def build_context(profile: str) -> dict[str, str]:
    """Build the full context dict for prompt rendering."""
    return {
        "openapi_spec": read_openapi(),
        "json_schemas": read_schemas(),
        "test_suites": read_test_suites(profile),
        "harness_code": read_harness_code(),
    }
