---
layout: default
title: Generator
---

# Generator

The generator is a CLI that produces a runnable CMDB implementation by prompting Claude and iterating on test failures.

## How It Works

```
┌─────────────────────────────────────────────┐
│  1. Read specs, schemas, harness, tests     │
│                                             │
│  2. Prompt Claude to generate server code   │
│         ↓                                   │
│  3. Parse <file> blocks from response       │
│         ↓                                   │
│  4. Write files to output directory         │
│         ↓                                   │
│  5. Create venv, install requirements.txt   │
│         ↓                                   │
│  6. Start app.py, wait for /health          │
│         ↓                                   │
│  7. Run pytest against the server           │
│         ↓                                   │
│  ┌──── 8. All tests pass? ────┐             │
│  │ YES                   NO   │             │
│  │  ↓                    ↓    │             │
│  │ Done!         Feed failures│             │
│  │               back to      │             │
│  │               Claude → (2) │             │
│  └────────────────────────────┘             │
└─────────────────────────────────────────────┘
```

## Usage

```bash
# Prerequisites
export ANTHROPIC_API_KEY=sk-ant-...
pip install -e ".[generator]"

# Basic usage (FastAPI + SQLite, minimal profile)
python -m generator --profile minimal

# Customize everything
python -m generator \
  --profile enterprise \
  --backend python/flask/postgres \
  --output ./my-cmdb \
  --port 9000 \
  --model claude-opus-4-6 \
  --max-iterations 10
```

## CLI Options

| Flag | Default | Description |
|---|---|---|
| `--profile` | `minimal` | Test suite profile to target: `minimal`, `standard`, `enterprise` |
| `--backend` | `python/fastapi/sqlite` | Backend stack hint passed to the LLM |
| `--output` | `./generated` | Directory for the generated implementation |
| `--max-iterations` | `5` | Maximum generate-test-fix cycles |
| `--model` | `claude-sonnet-4-6` | Anthropic model ID |
| `--port` | `8080` | Port for the generated server |

## What Gets Generated

The output directory contains a self-contained Python application:

```
generated/
  app.py              # Entry point (python app.py)
  models.py           # Data models (if the LLM splits them out)
  requirements.txt    # pip dependencies
  .venv/              # Virtual environment (created automatically)
```

The generated code has **no runtime dependency** on this repository. You can copy the output directory anywhere and run it standalone.

## Architecture

### Module Breakdown

- **`generator/cli.py`** — Argument parsing and entry point. Can also be invoked as `cmdb-generate` if installed via pip.

- **`generator/orchestrator.py`** — The core loop. Creates the Anthropic client, manages iterations, coordinates file writing and server lifecycle.

- **`generator/context.py`** — Reads the specification files (OpenAPI YAML, JSON schemas, test Python files, harness code) and assembles them into a structured dict for prompt rendering.

- **`generator/server.py`** — Process management: creates venvs, starts/stops the server subprocess, polls `/health`, reads generated source files back for fix prompts.

- **`generator/prompts.py`** — Three prompt templates:
  - `SYSTEM_PROMPT` — Sets the role, constraints, and output format
  - `GENERATE_PROMPT` — Initial generation (includes full spec + tests)
  - `FIX_PROMPT` — Subsequent iterations (includes failing test output + current code)

### File Parsing

Claude outputs files in `<file path="...">` XML blocks. The orchestrator uses a regex to extract them:

```
<file path="app.py">
# Generated CMDB server
from fastapi import FastAPI
...
</file>
```

### Error Recovery

- **Server fails to start:** stderr is captured and fed to the next fix iteration as if it were a test failure.
- **Test output too long:** Truncated to 200 lines (head + tail) to stay within context limits.
- **No parseable files:** The raw response is printed and the run aborts.

## Tips

- **Start with `minimal`.** It has the fewest tests, so the LLM converges faster. Once it passes, try `standard`.
- **Use Opus for `enterprise`.** The enterprise profile includes graph traversal, audit, governance, and security — more complex logic benefits from a more capable model.
- **Inspect failures.** If the generator can't converge, look at the last test output. Sometimes a single behavioral misunderstanding cascades into many failures.
- **Edit and re-run.** You can manually fix a file in `./generated/` and re-run just the tests: `CMDB_BASE_URL=http://localhost:8080 pytest -c profiles/minimal.ini`. This avoids burning API credits.
