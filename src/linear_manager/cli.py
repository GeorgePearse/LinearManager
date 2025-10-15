"""Command line entrypoints for LinearManager."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

try:  # pragma: no cover - fallback when colorama is absent
    from colorama import Fore, Style, init
except ImportError:  # pragma: no cover - fallback used in minimal environments
    class _Color:
        BLACK = BLUE = CYAN = GREEN = MAGENTA = RED = WHITE = YELLOW = ""
        RESET = ""

    class _Style:
        BRIGHT = RESET_ALL = ""

    def init(*_: object, **__: object) -> None:
        return None

    Fore = _Color()
    Style = _Style()

from linear_manager.sync import IssueSpec, SyncConfig, load_manifest, run_sync
from . import config
from .git_worktree import GitWorktreeError, create_branch_and_worktree

# Initialize colorama
init(autoreset=True)


def _get_tasks_directory() -> Path:
    """Get the tasks directory for LinearManager.

    Uses LINEAR_MANAGER_HOME environment variable if set,
    otherwise defaults to ~/LinearManager/tasks.
    """
    return config.get_tasks_directory()


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


def _format_branch_description(issue: IssueSpec, verbose: bool = False) -> str:
    branch = issue.branch or ""
    if not verbose:
        return branch
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


def _wrap_text(text: str, max_width: int) -> list[str]:
    """Wrap text to fit within max_width, breaking on word boundaries."""
    if not text:
        return [""]

    words = text.split()
    lines: list[str] = []
    current_line: list[str] = []
    current_length = 0

    for word in words:
        word_length = len(word)
        # Account for space before word (except for first word on line)
        needed_length = word_length + (1 if current_line else 0)

        if current_length + needed_length <= max_width:
            current_line.append(word)
            current_length += needed_length
        else:
            # Start new line
            if current_line:
                lines.append(" ".join(current_line))
            # Handle words longer than max_width by breaking them
            if word_length > max_width:
                for i in range(0, len(word), max_width):
                    lines.append(word[i : i + max_width])
                current_line = []
                current_length = 0
            else:
                current_line = [word]
                current_length = word_length

    if current_line:
        lines.append(" ".join(current_line))

    return lines if lines else [""]


def _table_lines(headers: list[str], rows: Iterable[list[str]]) -> list[str]:
    # Define maximum column widths (adjust these as needed)
    max_column_widths = [30, 20, 40, 20]  # Title, Worktree, Branch Description, Status

    # Wrap text in all cells and split into lines
    split_rows: list[list[list[str]]] = []
    for row in [headers] + list(rows):
        wrapped_row: list[list[str]] = []
        for idx, cell in enumerate(row):
            max_width = max_column_widths[idx] if idx < len(max_column_widths) else 40
            # First split on existing newlines, then wrap each line
            cell_lines: list[str] = []
            for line in cell.splitlines() or [""]:
                cell_lines.extend(_wrap_text(line, max_width))
            wrapped_row.append(cell_lines)
        split_rows.append(wrapped_row)

    column_count = len(headers)
    widths: list[int] = [0] * column_count
    for row_cells in split_rows:
        for idx, cell_lines in enumerate(row_cells):
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
                    parts.append(
                        f"{Fore.YELLOW}{Style.BRIGHT}{text.ljust(widths[col_idx])}{Style.RESET_ALL}"
                    )
                else:
                    parts.append(text.ljust(widths[col_idx]))
            rendered.append(
                f"{Fore.CYAN}|{Style.RESET_ALL} "
                + f" {Fore.CYAN}|{Style.RESET_ALL} ".join(parts)
                + f" {Fore.CYAN}|{Style.RESET_ALL}"
            )
        return rendered

    all_lines: list[str] = [build_rule("-")]
    all_lines.extend(render_row(split_rows[0], is_header=True))
    all_lines.append(build_rule("=", Fore.CYAN))
    for row_cells in split_rows[1:]:
        all_lines.extend(render_row(row_cells))
    all_lines.append(build_rule("-"))
    return all_lines


def _render_issue_table(issues: list[IssueSpec], verbose: bool = False) -> str:
    if verbose:
        headers = ["Title", "Worktree", "Description", "Status"]
        rows = [
            [
                issue.title,
                issue.worktree or "",
                (issue.description or "").strip().splitlines()[0] if issue.description else "",
                _format_status(issue),
            ]
            for issue in issues
        ]
    else:
        headers = ["Title", "Worktree", "Status"]
        rows = [
            [
                issue.title,
                issue.worktree or "",
                _format_status(issue),
            ]
            for issue in issues
        ]
    return "\n".join(_table_lines(headers, rows))


def run_list(path: Path, verbose: bool = False) -> int:
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

    print(_render_issue_table(issues, verbose=verbose))
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
    tasks_dir = _get_tasks_directory()

    # Ensure tasks directory exists
    tasks_dir.mkdir(parents=True, exist_ok=True)

    # Create a timestamped filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{title.lower().replace(' ', '_')[:30]}.yaml"
    filepath = tasks_dir / filename

    try:
        branch_name, worktree_path = create_branch_and_worktree(title)
    except GitWorktreeError as exc:
        raise RuntimeError(f"Failed to create git worktree: {exc}") from exc

    # Build the issue data
    issue_dict: dict[str, Any] = {
        "title": title,
        "description": description or "",
        "team_key": team_key,
        "branch": branch_name,
        "worktree": str(worktree_path),
    }

    # Add optional fields if provided
    if priority is not None:
        issue_dict["priority"] = priority
    if assignee:
        issue_dict["assignee_email"] = assignee
    if labels:
        issue_dict["labels"] = labels

    issue_data: dict[str, list[dict[str, Any]]] = {"issues": [issue_dict]}

    # Write to file
    with filepath.open("w", encoding="utf-8") as f:
        yaml.safe_dump(issue_data, f, default_flow_style=False, sort_keys=False)

    print(f"{Fore.GREEN}✓ Ticket created successfully:{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}File:{Style.RESET_ALL} {filepath}")
    print(f"  {Fore.CYAN}Title:{Style.RESET_ALL} {title}")
    print(f"  {Fore.CYAN}Team:{Style.RESET_ALL} {team_key}")
    print(f"  {Fore.CYAN}Branch:{Style.RESET_ALL} {branch_name}")
    print(f"  {Fore.CYAN}Worktree:{Style.RESET_ALL} {worktree_path}")

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
        default=None,
        help="Path to a manifest file or directory containing manifests (defaults to LinearManager/tasks).",
    )
    list_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Include full descriptions in the output.",
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
            path = args.path if args.path is not None else _get_tasks_directory()
            return run_list(path, verbose=args.verbose)
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
