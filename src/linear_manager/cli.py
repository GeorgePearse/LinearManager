"""Command line entrypoints for LinearManager."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from linear_manager.sync import IssueSpec, SyncConfig, load_manifest, run_sync


def _discover_manifest_files(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(
            {
                candidate
                for pattern in ("*.yaml", "*.yml")
                for candidate in path.rglob(pattern)
                if candidate.is_file()
            }
        )
        return files
    if path.is_file():
        if path.suffix.lower() not in {".yaml", ".yml"}:
            raise RuntimeError(f"Manifest file {path} must be .yaml or .yml.")
        return [path]
    raise RuntimeError(f"Manifest path {path} does not exist.")


def _format_branch_description(issue: IssueSpec) -> str:
    branch = issue.branch or ""
    description = (issue.description or "").strip()
    first_line = description.splitlines()[0] if description else ""
    if branch and first_line:
        return f"{branch} - {first_line}"
    return branch or first_line


def _format_status(issue: IssueSpec) -> str:
    parts: list[str] = []
    if issue.state:
        parts.append(issue.state)
    if issue.complete:
        parts.append("complete")
    return ", ".join(parts)


def _table_lines(headers: list[str], rows: Iterable[list[str]]) -> list[str]:
    split_rows = [
        [cell.splitlines() or [""] for cell in row]
        for row in ([headers] + list(rows))
    ]
    column_count = len(headers)
    widths: list[int] = [0] * column_count
    for row in split_rows:
        for idx, cell_lines in enumerate(row):
            widths[idx] = max(
                widths[idx],
                *(len(line) for line in cell_lines),
            )

    def build_rule(char: str) -> str:
        return "+" + "+".join(char * (width + 2) for width in widths) + "+"

    def render_row(cell_lines: list[list[str]]) -> list[str]:
        height = max(len(lines) for lines in cell_lines)
        rendered: list[str] = []
        for line_idx in range(height):
            parts: list[str] = []
            for col_idx, lines in enumerate(cell_lines):
                text = lines[line_idx] if line_idx < len(lines) else ""
                parts.append(text.ljust(widths[col_idx]))
            rendered.append("| " + " | ".join(parts) + " |")
        return rendered

    all_lines: list[str] = [build_rule("-")]
    all_lines.extend(render_row(split_rows[0]))
    all_lines.append(build_rule("="))
    for row_cells in split_rows[1:]:
        all_lines.extend(render_row(row_cells))
    all_lines.append(build_rule("-"))
    return all_lines


def _render_issue_table(issues: list[IssueSpec]) -> str:
    headers = ["Title", "Worktree", "Branch Description", "Status"]
    rows = [
        [
            issue.title,
            issue.worktree or "",
            _format_branch_description(issue),
            _format_status(issue),
        ]
        for issue in issues
    ]
    return "\n".join(_table_lines(headers, rows))


def run_list(path: Path) -> int:
    manifest_files = _discover_manifest_files(path)
    if not manifest_files:
        raise RuntimeError(f"No YAML files found in {path}")

    issues: list[IssueSpec] = []
    for manifest_path in manifest_files:
        manifest = load_manifest(manifest_path)
        issues.extend(manifest.issues)

    if not issues:
        print("No issues found.")
        return 0

    print(_render_issue_table(issues))
    return 0


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
    sync_parser.add_argument(
        "--mark-done",
        action="store_true",
        help="Mark issues flagged as complete in manifests as done in Linear.",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="Display a summary table of issues defined in manifests.",
    )
    list_parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Path to a manifest file or directory containing manifests (defaults to current directory).",
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
    parser.add_argument(
        "--mark-done",
        action="store_true",
        help="Mark issues flagged as complete in the manifest as done in Linear.",
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
                    mark_done=args.mark_done,
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
                mark_done=args.mark_done,
            )
    elif args.command == "list":
        try:
            return run_list(args.path)
        except Exception as exc:  # pragma: no cover - top-level handler
            parser.error(str(exc))
            return 1
    else:
        # Legacy mode: direct file argument
        if not args.manifest:
            parser.print_help()
            return 1

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
