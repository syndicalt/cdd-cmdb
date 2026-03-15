"""Backend stack definitions for multi-language/framework generation.

Each backend defines how to set up, install deps, and start the generated server.
The --backend flag uses the format: language/framework/database
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BackendSpec:
    language: str
    framework: str
    database: str
    entry_point: str           # e.g. "app.py", "main.go", "server.js"
    deps_file: str             # e.g. "requirements.txt", "go.mod", "package.json"
    install_cmd: list[str]     # command to install deps (run inside output_dir)
    start_cmd: list[str]       # command to start the server (run inside output_dir)
    needs_venv: bool           # whether to create a Python venv
    extra_constraints: str     # additional prompt text for this backend


# Registry of known backends
_BACKENDS: dict[str, BackendSpec] = {}


def _register(key: str, spec: BackendSpec) -> None:
    _BACKENDS[key] = spec


# --- Python backends ---

_register("python/fastapi/sqlite", BackendSpec(
    language="python",
    framework="FastAPI",
    database="SQLite",
    entry_point="app.py",
    deps_file="requirements.txt",
    install_cmd=[],  # handled by venv setup
    start_cmd=[],    # handled by server.py venv_python
    needs_venv=True,
    extra_constraints="",
))

_register("python/flask/sqlite", BackendSpec(
    language="python",
    framework="Flask",
    database="SQLite",
    entry_point="app.py",
    deps_file="requirements.txt",
    install_cmd=[],
    start_cmd=[],
    needs_venv=True,
    extra_constraints="""\
- Use Flask (not FastAPI). Use `flask run` style or `app.run()` in `if __name__ == '__main__'`.
- Do NOT use async — Flask is synchronous by default, which matches the test client.""",
))

_register("python/fastapi/postgres", BackendSpec(
    language="python",
    framework="FastAPI",
    database="PostgreSQL",
    entry_point="app.py",
    deps_file="requirements.txt",
    install_cmd=[],
    start_cmd=[],
    needs_venv=True,
    extra_constraints="""\
- Use PostgreSQL via psycopg2 or asyncpg.
- The server must create tables on startup if they don't exist.
- Connection string from DATABASE_URL env var, defaulting to postgresql://localhost:5432/cmdb.
- Do NOT use async — the test client uses synchronous httpx. Use psycopg2, not asyncpg.""",
))

_register("python/flask/postgres", BackendSpec(
    language="python",
    framework="Flask",
    database="PostgreSQL",
    entry_point="app.py",
    deps_file="requirements.txt",
    install_cmd=[],
    start_cmd=[],
    needs_venv=True,
    extra_constraints="""\
- Use Flask with PostgreSQL via psycopg2.
- Connection string from DATABASE_URL env var, defaulting to postgresql://localhost:5432/cmdb.
- Create tables on startup if they don't exist.""",
))

# --- Go backends ---

_register("go/gin/sqlite", BackendSpec(
    language="go",
    framework="Gin",
    database="SQLite",
    entry_point="main.go",
    deps_file="go.mod",
    install_cmd=["go", "mod", "tidy"],
    start_cmd=["go", "run", "."],
    needs_venv=False,
    extra_constraints="""\
- Use Go with the Gin web framework and modernc.org/sqlite (pure-Go SQLite).
- The entry point is main.go (package main).
- go.mod must declare the module and list dependencies.
- Use standard Go project layout: main.go at root, helpers in separate files if needed.
- The server must be synchronous from the test perspective (tests use httpx, not Go).""",
))

_register("go/stdlib/sqlite", BackendSpec(
    language="go",
    framework="net/http (stdlib)",
    database="SQLite",
    entry_point="main.go",
    deps_file="go.mod",
    install_cmd=["go", "mod", "tidy"],
    start_cmd=["go", "run", "."],
    needs_venv=False,
    extra_constraints="""\
- Use Go standard library net/http (no web framework).
- Use modernc.org/sqlite for SQLite.
- Route multiplexing via http.ServeMux or manual path matching.
- Entry point: main.go.""",
))

# --- Node.js backends ---

_register("node/express/sqlite", BackendSpec(
    language="node",
    framework="Express",
    database="SQLite",
    entry_point="server.js",
    deps_file="package.json",
    install_cmd=["npm", "install"],
    start_cmd=["node", "server.js"],
    needs_venv=False,
    extra_constraints="""\
- Use Node.js with Express and better-sqlite3.
- Entry point: server.js (not app.js).
- package.json must list all dependencies.
- Use CommonJS require() — the test runner doesn't care about ESM vs CJS.
- All responses must be JSON with correct Content-Type headers.""",
))

_register("node/express/mongodb", BackendSpec(
    language="node",
    framework="Express",
    database="MongoDB",
    entry_point="server.js",
    deps_file="package.json",
    install_cmd=["npm", "install"],
    start_cmd=["node", "server.js"],
    needs_venv=False,
    extra_constraints="""\
- Use Node.js with Express and mongodb (or mongoose).
- MongoDB connection from MONGODB_URI env var, defaulting to mongodb://localhost:27017/cmdb.
- Entry point: server.js.
- package.json must list all dependencies.
- Create collections/indexes on startup.""",
))

_register("node/fastify/sqlite", BackendSpec(
    language="node",
    framework="Fastify",
    database="SQLite",
    entry_point="server.js",
    deps_file="package.json",
    install_cmd=["npm", "install"],
    start_cmd=["node", "server.js"],
    needs_venv=False,
    extra_constraints="""\
- Use Node.js with Fastify and better-sqlite3.
- Entry point: server.js.
- package.json must list all dependencies.""",
))


def parse_backend(backend_str: str) -> BackendSpec:
    """Parse a backend string like 'python/fastapi/sqlite' into a BackendSpec.

    Falls back to a generic spec if not in the registry.
    """
    key = backend_str.lower().strip()
    if key in _BACKENDS:
        return _BACKENDS[key]

    # Parse as language/framework/database and create a generic spec
    parts = key.split("/")
    if len(parts) != 3:
        raise ValueError(
            f"Backend must be in format 'language/framework/database', got: {backend_str!r}\n"
            f"Known backends: {', '.join(sorted(_BACKENDS.keys()))}"
        )

    lang, framework, db = parts

    if lang == "python":
        return BackendSpec(
            language=lang, framework=framework, database=db,
            entry_point="app.py", deps_file="requirements.txt",
            install_cmd=[], start_cmd=[], needs_venv=True,
            extra_constraints=f"- Use Python with {framework} and {db}.",
        )
    elif lang == "go":
        return BackendSpec(
            language=lang, framework=framework, database=db,
            entry_point="main.go", deps_file="go.mod",
            install_cmd=["go", "mod", "tidy"], start_cmd=["go", "run", "."],
            needs_venv=False,
            extra_constraints=f"- Use Go with {framework} and {db}.",
        )
    elif lang in ("node", "nodejs"):
        return BackendSpec(
            language="node", framework=framework, database=db,
            entry_point="server.js", deps_file="package.json",
            install_cmd=["npm", "install"], start_cmd=["node", "server.js"],
            needs_venv=False,
            extra_constraints=f"- Use Node.js with {framework} and {db}.",
        )
    else:
        # Truly unknown — provide generic guidance
        return BackendSpec(
            language=lang, framework=framework, database=db,
            entry_point="app.py", deps_file="requirements.txt",
            install_cmd=[], start_cmd=[], needs_venv=False,
            extra_constraints=(
                f"- Use {lang} with {framework} and {db}. "
                f"Choose appropriate entry point and dependency file."
            ),
        )


def list_backends() -> list[str]:
    """Return sorted list of known backend keys."""
    return sorted(_BACKENDS.keys())
