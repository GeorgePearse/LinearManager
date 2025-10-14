"""Command line entrypoints for LinearManager."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from linear_manager.sync import SyncConfig, run_sync


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manager",
        description="Sync YAML-defined issues to Linear.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # sync subcommand
    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync YAML file(s) to Linear",
    )
    sync_parser.add_argument(
        "path",
        type=Path,
        help="Path to YAML file or directory containing YAML files to sync.",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifests without writing to Linear.",
    )

    # Legacy: direct file argument (for backwards compatibility)
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        help="Path to YAML manifest (legacy, use 'sync' subcommand instead).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate manifest without writing to Linear.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Handle sync subcommand
    if args.command == "sync":
        path = args.path
        if path.is_dir():
            # Find all YAML files recursively
            yaml_files = sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml"))
            if not yaml_files:
                parser.error(f"No YAML files found in {path}")
                return 1

            print(f"Found {len(yaml_files)} YAML file(s) to sync:")
            for yaml_file in yaml_files:
                print(f"  - {yaml_file.relative_to(path)}")
            print()

            failed_files = []
            for yaml_file in yaml_files:
                print(f"==> Syncing {yaml_file.relative_to(path)}")
                config = SyncConfig(
                    manifest_path=yaml_file,
                    dry_run=args.dry_run,
                )
                try:
                    run_sync(config)
                except Exception as exc:
                    print(f"ERROR: {exc}")
                    failed_files.append(yaml_file)
                print()

            if failed_files:
                print(f"Failed to sync {len(failed_files)} file(s):")
                for failed in failed_files:
                    print(f"  - {failed.relative_to(path)}")
                return 1
            return 0
        else:
            # Single file
            config = SyncConfig(
                manifest_path=path,
                dry_run=args.dry_run,
            )
    else:
        # Legacy mode: direct file argument
        if not args.manifest:
            parser.print_help()
            return 1

        config = SyncConfig(
            manifest_path=args.manifest,
            dry_run=args.dry_run,
        )

    try:
        run_sync(config)
    except Exception as exc:  # pragma: no cover - top-level handler
        parser.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
