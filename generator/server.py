"""Manage the generated CMDB server process."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from generator.backends import BackendSpec

# Detect platform for venv paths
IS_WINDOWS = sys.platform == "win32" or os.name == "nt"


def venv_python(output_dir: Path) -> str:
    venv_dir = output_dir / ".venv"
    if IS_WINDOWS:
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")


def setup_venv(output_dir: Path) -> None:
    """Create a venv and install requirements.txt."""
    venv_dir = output_dir / ".venv"
    if not venv_dir.exists():
        print("  Creating virtual environment...")
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
        )

    python = venv_python(output_dir)
    req_file = output_dir / "requirements.txt"
    if req_file.exists():
        print("  Installing dependencies...")
        subprocess.run(
            [python, "-m", "pip", "install", "-q", "-r", str(req_file)],
            check=True,
            capture_output=True,
        )


def setup_non_python(output_dir: Path, backend: BackendSpec) -> None:
    """Set up a non-Python backend (install deps via install_cmd)."""
    if not backend.install_cmd:
        return

    print(f"  Installing {backend.language} dependencies...")
    subprocess.run(
        backend.install_cmd,
        cwd=str(output_dir),
        check=True,
        capture_output=True,
    )


def start_server(output_dir: Path, port: int) -> subprocess.Popen:
    """Start a Python app.py as a subprocess, return the Popen handle."""
    python = venv_python(output_dir)
    env = {**os.environ, "PORT": str(port)}

    # Use CREATE_NEW_PROCESS_GROUP on Windows for clean shutdown
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        [python, "app.py"],
        cwd=str(output_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )
    return proc


def start_non_python_server(
    output_dir: Path,
    port: int,
    backend: BackendSpec,
) -> subprocess.Popen:
    """Start a non-Python server using the backend's start_cmd."""
    env = {**os.environ, "PORT": str(port)}

    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(
        backend.start_cmd,
        cwd=str(output_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **kwargs,
    )
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    """Gracefully stop the server process."""
    if proc.poll() is not None:
        return  # Already exited

    try:
        if IS_WINDOWS:
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def wait_for_health(port: int, timeout: float = 30.0, interval: float = 0.5) -> bool:
    """Poll GET /health until it returns 200 or timeout."""
    import httpx

    url = f"http://localhost:{port}/health"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=2.0)
            if resp.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
            pass
        time.sleep(interval)

    return False


def read_generated_code(output_dir: Path) -> str:
    """Read all generated source files into a formatted string for LLM context."""
    parts: list[str] = []
    extensions = (
        "*.py", "*.txt", "*.toml", "*.cfg", "*.json", "*.yaml", "*.yml",
        "*.go", "*.mod", "*.sum",  # Go
        "*.js", "*.ts", "*.mjs",   # Node
    )
    for ext in extensions:
        for f in sorted(output_dir.glob(ext)):
            if f.name.startswith(".") or ".venv" in str(f) or "node_modules" in str(f):
                continue
            rel = f.name
            parts.append(f'<file path="{rel}">\n{f.read_text(encoding="utf-8")}\n</file>')
    return "\n\n".join(parts)
