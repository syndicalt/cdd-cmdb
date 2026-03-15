#!/usr/bin/env bash
#
# CDD-CMDB Quick Start Demo
#
# One command to see the whole system work:
#   ./demo.sh
#
# What it does:
#   1. Installs dependencies into a venv
#   2. Starts the reference CMDB server
#   3. Runs the full validation suite against it
#   4. Prints the results
#
# Options:
#   ./demo.sh --profile minimal      Run only core tests (default)
#   ./demo.sh --profile standard     Run core + discovery + audit + graph + search + diff + reconciliation
#   ./demo.sh --profile enterprise   Run the full suite
#   ./demo.sh --generate             Generate a new implementation via AI first
#                                    (requires ANTHROPIC_API_KEY)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="minimal"
PORT=9090
GENERATE=false
SERVER_PID=""

usage() {
    echo "Usage: $0 [--profile minimal|standard|enterprise] [--generate] [--port PORT]"
    exit 1
}

cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        echo ""
        echo "Stopping server (PID $SERVER_PID)..."
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Map profiles to test paths
profile_testpaths() {
    case "$1" in
        minimal)    echo "suites/core" ;;
        standard)   echo "suites/core suites/discovery suites/audit suites/graph suites/search suites/diff suites/reconciliation suites/tags suites/ttl suites/webhooks" ;;
        enterprise) echo "suites" ;;
        *)          echo "suites/core" ;;
    esac
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --profile) PROFILE="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --generate) GENERATE=true; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

echo "============================================"
echo "  CDD-CMDB Demo"
echo "============================================"
echo "  Profile:  $PROFILE"
echo "  Port:     $PORT"
echo "  Generate: $GENERATE"
echo ""

# --- Step 1: Set up Python environment ---
echo "[1/4] Setting up Python environment..."
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv 2>/dev/null || python -m venv .venv
fi

# Activate venv
if [ -f ".venv/Scripts/activate" ]; then
    source .venv/Scripts/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

pip install -q -e "." 2>/dev/null
echo "  Done."

# --- Step 2: Determine which server to use ---
if [ "$GENERATE" = true ]; then
    echo ""
    echo "[2/4] Generating implementation via AI..."
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        echo "  ERROR: ANTHROPIC_API_KEY is required for --generate"
        exit 1
    fi
    pip install -q -e ".[generator]" 2>/dev/null
    python -m generator --profile "$PROFILE" --port "$PORT"
    SERVER_APP="generated/app.py"
    echo "  Done."
else
    echo ""
    echo "[2/4] Using reference implementation..."
    SERVER_APP="reference/app.py"
    if [ ! -f "$SERVER_APP" ]; then
        echo "  ERROR: $SERVER_APP not found."
        exit 1
    fi
    echo "  Done."
fi

# --- Step 3: Start the server ---
echo ""
echo "[3/4] Starting CMDB server on port $PORT..."

# Clean database for a fresh run
rm -f cmdb.db

PORT=$PORT python "$SERVER_APP" &
SERVER_PID=$!

# Wait for health
echo "  Waiting for server to be ready..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
        echo "  Server is healthy."
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "  ERROR: Server process exited unexpectedly."
        exit 1
    fi
    sleep 1
done

if ! curl -sf "http://localhost:$PORT/health" > /dev/null 2>&1; then
    echo "  ERROR: Server did not become healthy within 30 seconds."
    exit 1
fi

# --- Step 4: Run the test suite ---
echo ""
TESTPATHS=$(profile_testpaths "$PROFILE")
echo "[4/4] Running validation suite ($PROFILE profile)..."
echo "  Test paths: $TESTPATHS"
echo ""

CMDB_BASE_URL="http://localhost:$PORT" \
HYPOTHESIS_PROFILE=ci \
python -m pytest $TESTPATHS --tb=short -q

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "============================================"
    echo "  All tests passed!"
    echo "============================================"
    echo ""
    echo "  The CMDB at http://localhost:$PORT is compliant."
    echo "  Try it:"
    echo "    curl http://localhost:$PORT/health"
    echo "    curl -X POST http://localhost:$PORT/cis -H 'Content-Type: application/json' \\"
    echo "      -d '{\"name\": \"my-server\", \"type\": \"server\", \"attributes\": {\"env\": \"prod\"}}'"
    echo ""
    echo "  Press Ctrl+C to stop the server."
    wait "$SERVER_PID" 2>/dev/null || true
else
    echo "============================================"
    echo "  Some tests failed (exit code $EXIT_CODE)"
    echo "============================================"
fi

exit $EXIT_CODE
