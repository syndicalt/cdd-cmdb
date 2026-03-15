"""Artifact caching for generated implementations.

After a successful generation, saves the output artifacts alongside a hash of
the inputs (specs + tests + profile). On subsequent runs, if the hash matches,
the cached artifact is reused — skipping the LLM call entirely.

Cache layout:
  .cache/
    {profile}_{backend_hash}/
      manifest.json    # input hash, metadata
      app.py           # cached generated files
      requirements.txt
      ...
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from generator.context import REPO_ROOT


def _hash_inputs(profile: str, backend: str) -> str:
    """Create a deterministic hash of all inputs that affect generation.

    Includes: profile config, test suite source, specs, harness code, backend string.
    """
    h = hashlib.sha256()
    h.update(f"backend={backend}\n".encode())

    # Profile config
    profile_path = REPO_ROOT / "profiles" / f"{profile}.ini"
    if profile_path.exists():
        h.update(profile_path.read_bytes())

    # Specs
    for d in ["specs/openapi", "specs/schemas"]:
        spec_dir = REPO_ROOT / d
        if spec_dir.exists():
            for f in sorted(spec_dir.rglob("*")):
                if f.is_file():
                    h.update(f.read_bytes())

    # Test suites
    suites_dir = REPO_ROOT / "suites"
    if suites_dir.exists():
        for f in sorted(suites_dir.rglob("*.py")):
            h.update(f.read_bytes())

    # Harness
    harness_dir = REPO_ROOT / "harness"
    if harness_dir.exists():
        for f in sorted(harness_dir.rglob("*.py")):
            h.update(f.read_bytes())

    # conftest.py
    conftest = REPO_ROOT / "conftest.py"
    if conftest.exists():
        h.update(conftest.read_bytes())

    return h.hexdigest()[:16]


def _cache_dir(profile: str, backend: str) -> Path:
    """Return the cache directory for a profile+backend combo."""
    # Sanitize backend for filesystem
    safe_backend = backend.replace("/", "_").replace("\\", "_")
    return REPO_ROOT / ".cache" / f"{profile}_{safe_backend}"


def get_cached(profile: str, backend: str) -> Path | None:
    """Check if a valid cache exists. Returns cache dir path or None."""
    cache = _cache_dir(profile, backend)
    manifest_path = cache / "manifest.json"

    if not manifest_path.exists():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    current_hash = _hash_inputs(profile, backend)
    if manifest.get("input_hash") != current_hash:
        print(f"  Cache stale (inputs changed since {manifest.get('created', 'unknown')})")
        return None

    return cache


def save_cache(profile: str, backend: str, output_dir: Path) -> Path:
    """Save a successful generation to the cache.

    Copies all non-venv files from output_dir to the cache directory.
    Returns the cache directory path.
    """
    cache = _cache_dir(profile, backend)

    # Clean old cache
    if cache.exists():
        shutil.rmtree(cache)
    cache.mkdir(parents=True, exist_ok=True)

    # Copy generated files (skip .venv, __pycache__, .db files)
    for item in output_dir.iterdir():
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
        if item.name.endswith(".db"):
            continue
        if item.is_file():
            shutil.copy2(item, cache / item.name)
        elif item.is_dir():
            shutil.copytree(item, cache / item.name, ignore=shutil.ignore_patterns(
                ".venv", "__pycache__", "*.pyc", "*.db",
            ))

    # Write manifest
    manifest = {
        "input_hash": _hash_inputs(profile, backend),
        "profile": profile,
        "backend": backend,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "files": [f.name for f in cache.iterdir() if f.is_file() and f.name != "manifest.json"],
    }
    (cache / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return cache


def restore_cache(cache_dir: Path, output_dir: Path) -> None:
    """Restore cached files to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for item in cache_dir.iterdir():
        if item.name == "manifest.json":
            continue
        dest = output_dir / item.name
        if item.is_file():
            shutil.copy2(item, dest)
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)


def clear_cache(profile: str | None = None, backend: str | None = None) -> int:
    """Clear cached artifacts. Returns number of caches removed.

    If profile/backend specified, clears only matching caches.
    If both are None, clears all caches.
    """
    cache_root = REPO_ROOT / ".cache"
    if not cache_root.exists():
        return 0

    removed = 0
    for d in cache_root.iterdir():
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        if profile and manifest.get("profile") != profile:
            continue
        if backend and manifest.get("backend") != backend:
            continue

        shutil.rmtree(d)
        removed += 1

    return removed
