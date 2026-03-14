"""CLI entry point for the CMDB generator.

Usage:
    python -m generator.cli --profile minimal --backend python/fastapi/sqlite
    python -m generator.cli --profile enterprise --max-iterations 10 --model claude-opus-4-6
"""
from __future__ import annotations

import argparse
import sys

from generator.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a CMDB implementation that passes the spec's test suite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  %(prog)s --profile minimal
  %(prog)s --profile standard --backend python/flask/sqlite
  %(prog)s --profile enterprise --max-iterations 10 --model claude-opus-4-6
  %(prog)s --output ./my-cmdb --port 9000
""",
    )
    parser.add_argument(
        "--profile",
        default="minimal",
        choices=["minimal", "standard", "enterprise"],
        help="Test suite profile to target (default: minimal)",
    )
    parser.add_argument(
        "--backend",
        default="python/fastapi/sqlite",
        help="Backend stack hint for the LLM (default: python/fastapi/sqlite)",
    )
    parser.add_argument(
        "--output",
        default="./generated",
        help="Directory for the generated implementation (default: ./generated)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Max generate-test-fix cycles (default: 5)",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic model ID (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the generated server (default: 8080)",
    )

    args = parser.parse_args()

    print("CDD-CMDB Generator")
    print(f"  Profile:    {args.profile}")
    print(f"  Backend:    {args.backend}")
    print(f"  Output:     {args.output}")
    print(f"  Model:      {args.model}")
    print(f"  Port:       {args.port}")
    print(f"  Max iters:  {args.max_iterations}")
    print()

    orchestrator = Orchestrator(
        profile=args.profile,
        backend=args.backend,
        output_dir=args.output,
        max_iterations=args.max_iterations,
        model=args.model,
        port=args.port,
    )

    success = orchestrator.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
