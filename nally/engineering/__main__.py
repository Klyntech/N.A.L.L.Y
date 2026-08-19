"""CLI entrypoint: ``python -m nally.engineering "task"``.

Runs the real engineering loop (requires a configured LLM API key) and prints a
concise summary plus the output directory. Use ``--max-refinements`` to bound
the refine stage. This is the opt-in, explicit entry; it does not change the
default Nally chat behavior.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import _cli_emit
from .protocol import NallyLLMBackend
from .toolbox import RealToolbox
from .workspace import EngineeringWorkspace


def main(argv: list = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m nally.engineering",
        description="Autonomously build a software project from a task description.",
    )
    parser.add_argument("task", help="High-level task, e.g. 'Build a CLI tool that organizes files by extension'")
    parser.add_argument("--max-refinements", type=int, default=3, help="Max refine passes (default 3)")
    parser.add_argument("--out", type=str, default=None, help="Output directory (default: data/builds/<slug>)")
    args = parser.parse_args(argv)

    try:
        backend = NallyLLMBackend()
    except Exception as exc:
        print(f"ERROR: LLM backend unavailable: {exc}", file=sys.stderr)
        print("Set OPENCODE_API_KEY or GROQ_API_KEY in your environment / .env.", file=sys.stderr)
        return 2

    workspace = EngineeringWorkspace(
        base_dir=Path(args.out) if args.out else None, task=args.task
    )
    toolbox = RealToolbox(auto_approve_ask=True)

    # Imported here to keep CLI startup light.
    from .loop import EngineeringLoop

    try:
        result = EngineeringLoop(
            backend, toolbox, workspace, max_refinements=args.max_refinements,
            emit=_cli_emit,
        ).run(args.task)
    except Exception as exc:
        print(f"ERROR: engineering run failed: {exc}", file=sys.stderr)
        return 1

    print("=" * 60)
    print(f"ENGINEERING BUILD: {result.task}")
    print(f"Status: {'SUCCESS' if result.success else 'COMPLETED WITH ISSUES'}")
    if result.chosen_approach:
        print(f"Approach: {result.chosen_approach.title} ({result.chosen_approach.category.value})")
    print(f"Refinements: {result.refinements}")
    print(f"Artifacts: {', '.join(result.artifacts) or 'none'}")
    print(f"Output dir: {workspace.dir}")
    print(f"README: {result.readme_path}")
    print("Run commands:")
    for cmd in result.run_commands:
        print(f"  {cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
