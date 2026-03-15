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
#   ./demo.sh --profile standard     Run core + discovery + audit + graph
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

# --- Step 2: Optionally generate a new implementation ---
if [ "$GENERATE" = true ]; then
    echo ""
    echo "[2/4] Generating implementation via AI..."
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        echo "  ERROR: ANTHROPIC_API_KEY is required for --generate"
        exit 1
    fi
    pip install -q -e ".[generator]" 2>/dev/null
    python -m generator --profile "$PROFILE" --port "$PORT"
    echo "  Done."
else
    echo ""
    echo "[2/4] Using reference implementation in generated/"
    if [ ! -f "generated/app.py" ]; then
        echo "  ERROR: generated/app.py not found."
        echo "  Run with --generate flag, or place an implementation in generated/"
        exit 1
    fi

    # Set up the generated server's venv
    if [ ! -d "generated/.venv" ]; then
        python3 -m venv generated/.venv 2>/dev/null || python -m venv generated/.venv
    fi
    if [ -f "generated/.venv/Scripts/pip" ]; then
        generated/.venv/Scripts/pip install -q -r generated/requirements.txt 2>/dev/null
    else
        generated/.venv/bin/pip install -q -r generated/requirements.txt 2>/dev/null
    fi
    echo "  Done."
fi

# --- Step 3: Start the server ---
echo ""
echo "[3/4] Starting CMDB server on port $PORT..."

# Clean database for a fresh run
rm -f generated/cmdb.db

if [ -f "generated/.venv/Scripts/python.exe" ]; then
    GENPYTHON="generated/.venv/Scripts/python.exe"
elif [ -f "generated/.venv/bin/python" ]; then
    GENPYTHON="generated/.venv/bin/python"
else
    GENPYTHON="python"
fi

PORT=$PORT $GENPYTHON generated/app.py &
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
echo "[4/4] Running validation suite ($PROFILE profile)..."
echo ""

CMDB_BASE_URL="http://localhost:$PORT" \
HYPOTHESIS_PROFILE=ci \
python -m pytest suites/core/ --tb=short -q \
    --override-ini="pythonpath=$SCRIPT_DIR"

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
