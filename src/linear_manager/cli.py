"""Command line entrypoints for LinearManager."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml
from colorama import Fore, Style, init

from linear_manager.sync import IssueSpec, SyncConfig, load_manifest, run_sync

# Initialize colorama
init(autoreset=True)


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
        [cell.splitlines() or [""] for cell in row] for row in ([headers] + list(rows))
    ]
    column_count = len(headers)
    widths: list[int] = [0] * column_count
    for row in split_rows:
        for idx, cell_lines in enumerate(row):
            widths[idx] = max(
                widths[idx],
                *(len(line) for line in cell_lines),
            )

    def build_rule(char: str, color: str = Fore.CYAN) -> str:
        rule = "+" + "+".join(char * (width + 2) for width in widths) + "+"
        return f"{color}{rule}{Style.RESET_ALL}"

    def render_row(cell_lines: list[list[str]], is_header: bool = False) -> list[str]:
        height = max(len(lines) for lines in cell_lines)
        rendered: list[str] = []
        for line_idx in range(height):
            parts: list[str] = []
            for col_idx, lines in enumerate(cell_lines):
                text = lines[line_idx] if line_idx < len(lines) else ""
                if is_header:
                    parts.append(f"{Fore.YELLOW}{Style.BRIGHT}{text.ljust(widths[col_idx])}{Style.RESET_ALL}")
                else:
                    parts.append(text.ljust(widths[col_idx]))
            rendered.append(f"{Fore.CYAN}|{Style.RESET_ALL} " + f" {Fore.CYAN}|{Style.RESET_ALL} ".join(parts) + f" {Fore.CYAN}|{Style.RESET_ALL}")
        return rendered

    all_lines: list[str] = [build_rule("-")]
    all_lines.extend(render_row(split_rows[0], is_header=True))
    all_lines.append(build_rule("=", Fore.CYAN))
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


def run_add(
    title: str,
    description: str | None,
    team_key: str,
    priority: int | None,
    assignee: str | None,
    labels: list[str] | None,
) -> int:
    """Add a new ticket to the tasks directory."""
    # Get the LinearManager root directory
    # Assuming cli.py is in src/linear_manager/, go up to project root
    project_root = Path(__file__).parent.parent.parent
    tasks_dir = project_root / "tasks"

    # Ensure tasks directory exists
    tasks_dir.mkdir(exist_ok=True)

    # Create a timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{title.lower().replace(' ', '_')[:30]}.yaml"
    filepath = tasks_dir / filename

    # Build the issue data
    issue_data = {
        "issues": [
            {
                "title": title,
                "description": description or "",
                "team_key": team_key,
            }
        ]
    }

    # Add optional fields if provided
    if priority is not None:
        issue_data["issues"][0]["priority"] = priority
    if assignee:
        issue_data["issues"][0]["assignee_email"] = assignee
    if labels:
        issue_data["issues"][0]["labels"] = labels

    # Write to file
    with filepath.open("w", encoding="utf-8") as f:
        yaml.safe_dump(issue_data, f, default_flow_style=False, sort_keys=False)

    print(f"{Fore.GREEN}✓ Ticket created successfully:{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}File:{Style.RESET_ALL} {filepath}")
    print(f"  {Fore.CYAN}Title:{Style.RESET_ALL} {title}")
    print(f"  {Fore.CYAN}Team:{Style.RESET_ALL} {team_key}")

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

    # add subcommand
    add_parser = subparsers.add_parser(
        "add",
        help="Add a new ticket to the tasks directory.",
    )
    add_parser.add_argument(
        "title",
        type=str,
        help="Title of the ticket",
    )
    add_parser.add_argument(
        "--description",
        "-d",
        type=str,
        help="Description of the ticket",
    )
    add_parser.add_argument(
        "--team-key",
        "-t",
        type=str,
        required=True,
        help="Team key (e.g., ENG, PROD)",
    )
    add_parser.add_argument(
        "--priority",
        "-p",
        type=int,
        choices=[0, 1, 2, 3, 4],
        help="Priority (0=None, 1=Low, 2=Medium, 3=High, 4=Urgent)",
    )
    add_parser.add_argument(
        "--assignee",
        "-a",
        type=str,
        help="Assignee email address",
    )
    add_parser.add_argument(
        "--labels",
        "-l",
        type=str,
        nargs="+",
        help="Labels for the ticket",
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
    elif args.command == "list":
        try:
            return run_list(args.path)
        except Exception as exc:  # pragma: no cover - top-level handler
            parser.error(str(exc))
            return 1
    elif args.command == "add":
        try:
            return run_add(
                title=args.title,
                description=args.description,
                team_key=args.team_key,
                priority=args.priority,
                assignee=args.assignee,
                labels=args.labels,
            )
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
        )

    try:
        run_sync(config)
    except Exception as exc:  # pragma: no cover - top-level handler
        parser.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
