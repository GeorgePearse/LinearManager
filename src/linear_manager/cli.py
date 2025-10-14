"""Command line entrypoints for LinearManager."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from linear_manager.sync import SyncConfig, run_sync


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linear-manager",
        description="Sync YAML-defined issues to Linear.",
    )
    parser.add_argument(
        "manifest",
        type=Path,
        help="Path to YAML manifest describing issues to sync.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifest without writing to Linear.",
    )
    parser.add_argument(
        "--mark-done",
        action="store_true",
        help="Mark issues flagged as complete in the manifest as done in Linear.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = SyncConfig(
        manifest_path=args.manifest,
        dry_run=args.dry_run,
        mark_done=args.mark_done,
    )

    try:
        run_sync(config)
    except Exception as exc:  # pragma: no cover - top-level handler
        parser.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
