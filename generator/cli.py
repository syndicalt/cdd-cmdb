"""CLI entry point for the CMDB generator.

Usage:
    python -m generator --profile minimal --backend python/fastapi/sqlite
    python -m generator --profile enterprise --model claude-opus-4-6 --max-iterations 10
    python -m generator --model gpt-4o --provider openai
    python -m generator --model ollama/llama3
    python -m generator --badge --badge-dir ./badges
    python -m generator --clear-cache
    python -m generator --list-backends
"""
from __future__ import annotations

import argparse
import sys

from generator.backends import list_backends


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a CMDB implementation that passes the spec's test suite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
backends:
  %(prog)s --list-backends                           # show all known backends
  %(prog)s --backend python/flask/sqlite             # Flask + SQLite
  %(prog)s --backend python/fastapi/postgres         # FastAPI + PostgreSQL
  %(prog)s --backend go/gin/sqlite                   # Go + Gin + SQLite
  %(prog)s --backend node/express/sqlite             # Node + Express + SQLite
  %(prog)s --backend node/express/mongodb            # Node + Express + MongoDB

models:
  %(prog)s --model claude-sonnet-4-6                   # Anthropic (default)
  %(prog)s --model gpt-4o                            # OpenAI
  %(prog)s --model gemini-2.0-flash                  # Google Gemini
  %(prog)s --model ollama/llama3                     # Ollama (local)
  %(prog)s --model lmstudio/default                  # LM Studio (local)
  %(prog)s --model gpt-4o --provider openai          # explicit provider

caching:
  %(prog)s --no-cache                                # skip cache, always regenerate
  %(prog)s --clear-cache                             # delete all cached artifacts
  %(prog)s --clear-cache --profile minimal           # delete cache for one profile

badges:
  %(prog)s --badge                                   # generate compliance badge
  %(prog)s --badge --badge-dir ./badges              # custom badge output dir
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
        help="Backend stack: language/framework/database (default: python/fastapi/sqlite)",
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
        help=(
            "Model ID (default: claude-sonnet-4-6). "
            "Prefix with ollama/ or lmstudio/ for local models."
        ),
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["anthropic", "openai", "gemini", "ollama", "lmstudio"],
        help="LLM provider (auto-detected from model name if omitted)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for the generated server (default: 8080)",
    )

    # Caching
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip cache, always regenerate from scratch",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear cached artifacts and exit",
    )

    # Badge
    parser.add_argument(
        "--badge",
        action="store_true",
        help="Generate a compliance badge SVG after test run",
    )
    parser.add_argument(
        "--badge-dir",
        default=None,
        help="Directory for badge output (default: same as --output)",
    )

    # Utility
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="List all known backend stacks and exit",
    )

    args = parser.parse_args()

    # --- Utility commands ---

    if args.list_backends:
        print("Known backends:")
        for b in list_backends():
            print(f"  {b}")
        print("\nCustom backends also supported: language/framework/database")
        sys.exit(0)

    if args.clear_cache:
        from generator.cache import clear_cache
        removed = clear_cache(
            profile=args.profile if args.profile != "minimal" else None,
            backend=args.backend if args.backend != "python/fastapi/sqlite" else None,
        )
        print(f"Cleared {removed} cached artifact(s).")
        sys.exit(0)

    # --- Provider detection ---
    from generator.providers import detect_provider
    provider_name = args.provider or detect_provider(args.model)

    # --- Run generator ---
    print("CDD-CMDB Generator")
    print(f"  Profile:    {args.profile}")
    print(f"  Backend:    {args.backend}")
    print(f"  Output:     {args.output}")
    print(f"  Model:      {args.model}")
    print(f"  Provider:   {provider_name}")
    print(f"  Port:       {args.port}")
    print(f"  Max iters:  {args.max_iterations}")
    print(f"  Cache:      {'disabled' if args.no_cache else 'enabled'}")
    print(f"  Badge:      {'yes' if args.badge else 'no'}")
    print()

    from generator.orchestrator import Orchestrator

    orchestrator = Orchestrator(
        profile=args.profile,
        backend=args.backend,
        output_dir=args.output,
        max_iterations=args.max_iterations,
        model=args.model,
        port=args.port,
        provider=args.provider,
        no_cache=args.no_cache,
        badge=args.badge,
        badge_dir=args.badge_dir,
    )

    success = orchestrator.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
