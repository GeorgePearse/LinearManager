"""Command line entrypoints for LinearManager."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
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

from linear_manager.sync import IssueSpec, SyncConfig, load_manifest, run_sync, run_pull
from . import config
from .git_worktree import GitWorktreeError, create_branch_and_worktree

# Initialize colorama
init(autoreset=True)

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _visible_length(text: str) -> int:
    return len(_strip_ansi(text))


def _ljust_visible(text: str, width: int) -> str:
    padding = max(width - _visible_length(text), 0)
    return text + (" " * padding)


def _utc_timestamp() -> str:
    """Return an ISO-8601 timestamp in UTC."""
    return datetime.now(timezone.utc).isoformat()


def _resolve_worktree_path(manifest_path: Path, raw_path: str) -> Path:
    """Resolve a worktree path relative to a manifest."""
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (manifest_path.parent / candidate).resolve()
    return candidate


def _status_color(status: str) -> str:
    """Map a status string to a representative color."""
    mapping = {
        "pass": Fore.GREEN,
        "fail": Fore.RED,
        "pending": Fore.YELLOW,
        "skipped": Fore.BLUE,
        "cancelled": Fore.MAGENTA,
        "missing_branch": Fore.YELLOW,
        "missing_worktree": Fore.YELLOW,
        "worktree_not_found": Fore.YELLOW,
        "gh_missing": Fore.RED,
        "parse_error": Fore.RED,
        "error": Fore.RED,
        "no_checks": Fore.CYAN,
        "unknown": Fore.CYAN,
    }
    return mapping.get(status.lower(), Fore.CYAN)


def _summarize_check_buckets(checks: list[dict[str, Any]], exit_code: int) -> str:
    """Determine an overall status from gh check buckets."""
    buckets = {
        str(check.get("bucket")).lower() for check in checks if check.get("bucket")
    }
    if "fail" in buckets:
        return "fail"
    if "pending" in buckets:
        return "pending"
    if "cancel" in buckets:
        return "cancelled"
    if "skipping" in buckets:
        return "skipped"
    if "pass" in buckets:
        return "pass"
    if checks:
        return "unknown"
    if exit_code == 8:
        return "pending"
    if exit_code == 0:
        return "no_checks"
    return "error"


def _run_gh_checks(worktree: Path, branch: str) -> dict[str, Any]:
    """Invoke `gh pr checks` for the provided branch."""
    command = [
        "gh",
        "pr",
        "checks",
        branch,
        "--json",
        "name,state,bucket,workflow",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(worktree),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {
            "pass_or_fail": "gh_missing",
            "failure_reason": "GitHub CLI (gh) not found on PATH.",
            "details": [],
        }

    stdout = completed.stdout.strip()
    details: list[dict[str, Any]] = []
    if stdout:
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, list):
                for item in parsed:
                    detail: dict[str, Any] = {}
                    for key in ("name", "state", "bucket", "workflow"):
                        value = item.get(key)
                        if value is not None:
                            detail[key] = value
                    details.append(detail)
        except json.JSONDecodeError:
            return {
                "pass_or_fail": "parse_error",
                "failure_reason": "Unable to parse JSON output from gh.",
                "details": [],
                "raw": stdout,
            }

    status = _summarize_check_buckets(details, completed.returncode)
    stderr = completed.stderr.strip()

    failure_reason: str | None = None
    if status == "fail":
        failed = next(
            (item for item in details if str(item.get("bucket")).lower() == "fail"),
            None,
        )
        workflow = failed.get("workflow") if failed else None
        name = failed.get("name") if failed else None
        state = failed.get("state") if failed else None
        if workflow or name:
            label = workflow or name
            suffix = f" ({state})" if state else ""
            failure_reason = f"{label} failed{suffix}"
        elif stderr:
            failure_reason = stderr
        else:
            failure_reason = "One or more checks reported failures."
    elif status == "pending":
        failure_reason = stderr or "Checks are still running."
    elif status in {"cancelled", "skipped"}:
        failure_reason = stderr or f"Checks {status}."
    elif status == "no_checks":
        failure_reason = stderr or "No checks available for this branch."
    elif status == "error":
        failure_reason = stderr or f"`gh pr checks` exited with {completed.returncode}"
    elif status in {"gh_missing", "parse_error"}:
        failure_reason = stderr or "Unable to evaluate GitHub checks."

    result: dict[str, Any] = {
        "pass_or_fail": status,
        "failure_reason": failure_reason,
        "details": details,
        "exit_code": completed.returncode,
    }
    if stderr:
        result["message"] = stderr
    if not details and status == "error" and not stderr:
        result["message"] = f"`gh pr checks` exited with {completed.returncode}"
    return result


def _evaluate_issue_tests(issue: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    """Evaluate tests for a single issue and return a status payload."""
    timestamp = _utc_timestamp()
    tests_entry: dict[str, Any] = {"checked_at": timestamp}

    branch = issue.get("branch")
    if not branch:
        tests_entry["pass_or_fail"] = "missing_branch"
        tests_entry["failure_reason"] = "Branch not specified in manifest."
        return tests_entry

    worktree_raw = issue.get("worktree")
    if not worktree_raw:
        tests_entry["pass_or_fail"] = "missing_worktree"
        tests_entry["failure_reason"] = (
            f"No worktree path configured for branch '{branch}'."
        )
        tests_entry["branch"] = branch
        return tests_entry

    worktree_path = _resolve_worktree_path(manifest_path, str(worktree_raw))
    tests_entry["branch"] = branch
    tests_entry["worktree"] = str(worktree_path)

    if not worktree_path.exists():
        tests_entry["pass_or_fail"] = "worktree_not_found"
        tests_entry["failure_reason"] = f"Worktree path '{worktree_path}' not found."
        return tests_entry

    gh_result = _run_gh_checks(worktree_path, branch)
    tests_entry.update(gh_result)
    tests_entry.setdefault("pass_or_fail", "unknown")
    if tests_entry["pass_or_fail"] == "pass":
        tests_entry.setdefault("failure_reason", None)
    else:
        tests_entry.setdefault("failure_reason", "Unknown test state.")
    return tests_entry


def _process_manifest_for_tests(
    manifest_path: Path,
) -> list[tuple[str, dict[str, Any]]]:
    """Process a single manifest file for test status updates."""
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    issues = raw.get("issues")
    if not isinstance(issues, list):
        return []

    results: list[tuple[str, dict[str, Any]]] = []
    changed = False
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            continue
        tests_entry = _evaluate_issue_tests(issue, manifest_path)
        previous = issue.get("tests")
        if previous != tests_entry:
            issue["tests"] = tests_entry
            changed = True
        title = issue.get("title") or f"Issue {index + 1}"
        results.append((title, tests_entry))

    if changed:
        manifest_path.write_text(
            yaml.safe_dump(raw, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    return results


def run_check_tests(path: Path, max_workers: int = 4) -> int:
    """Run GitHub test checks across manifests concurrently."""
    manifest_files = _discover_manifest_files(path)
    if not manifest_files:
        print(f"No YAML files found in {path}")
        return 0

    worker_count = max(1, max_workers)
    errors = 0
    print(f"Running test checks for {len(manifest_files)} manifest file(s)...")

    with ThreadPoolExecutor(
        max_workers=min(worker_count, len(manifest_files))
    ) as executor:
        futures = {
            executor.submit(_process_manifest_for_tests, manifest): manifest
            for manifest in manifest_files
        }
        for future in as_completed(futures):
            manifest = futures[future]
            try:
                entries = future.result()
            except Exception as exc:  # pragma: no cover - defensive guard
                errors += 1
                print(f"{Fore.RED}✗ {manifest}: {exc}{Style.RESET_ALL}")
                continue

            if not entries:
                print(f"{Fore.CYAN}- {manifest}: no issues found{Style.RESET_ALL}")
                continue

            for title, tests in entries:
                status = str(tests.get("pass_or_fail", "unknown"))
                color = _status_color(status)
                print(
                    f"{Fore.CYAN}{manifest.name}{Style.RESET_ALL} "
                    f"→ {color}{status}{Style.RESET_ALL} "
                    f"({title})"
                )

    return 1 if errors else 0


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
    state = (issue.state or "").strip()
    state_key = state.lower()

    todo_states = {
        "todo",
        "to do",
        "backlog",
        "triage",
        "planned",
        "ready",
    }
    in_progress_states = {
        "in progress",
        "wip",
        "doing",
        "progress",
        "started",
        "working",
    }
    review_states = {
        "review",
        "in review",
        "feedback",
        "blocked",
        "qa",
        "testing",
    }
    done_states = {
        "done",
        "completed",
        "complete",
        "closed",
        "resolved",
    }
    cancelled_states = {
        "canceled",
        "cancelled",
        "abandoned",
        "declined",
    }

    symbol = "·"
    color = Fore.WHITE
    label_hint = state

    if state_key in done_states:
        symbol = "[x]"
        color = Fore.GREEN
        label_hint = state or "Complete"
    elif state_key in cancelled_states:
        symbol = "✖"
        color = Fore.RED
        label_hint = state or "Cancelled"
    elif state_key in in_progress_states:
        symbol = "→"
        color = Fore.CYAN
        label_hint = state or "In Progress"
    elif state_key in review_states:
        symbol = "⧖"
        color = Fore.MAGENTA
        label_hint = state or "Review"
    elif not state:
        symbol = "[ ]"
        color = Fore.YELLOW
        label_hint = "No state"
    elif state_key in todo_states:
        symbol = "[ ]"
        color = Fore.YELLOW
        label_hint = state or "Todo"
    else:
        symbol = "○"
        color = Fore.BLUE
        label_hint = state

    parts: list[str] = [f"{color}{Style.BRIGHT}{symbol}{Style.RESET_ALL}"]
    if label_hint:
        parts.append(f"{Style.DIM}{label_hint}{Style.RESET_ALL}")
    if issue.complete:
        parts.append(f"{Fore.GREEN}{Style.BRIGHT}☑{Style.RESET_ALL}")
    return " ".join(parts)


def _wrap_text(text: str, max_width: int) -> list[str]:
    """Wrap text to fit within max_width, breaking on word boundaries."""
    if not text:
        return [""]

    words = text.split()
    lines: list[str] = []
    current_line: list[str] = []
    current_length = 0

    for word in words:
        word_length = _visible_length(word)
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
                if "\x1b" in word:
                    lines.append(word)
                else:
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
    max_column_widths = [30, 25, 25, 40, 20]  # Title, Branch, Worktree, Description, Status

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
                *(_visible_length(line) for line in cell_lines),
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
                padded = _ljust_visible(text, widths[col_idx])
                if is_header:
                    parts.append(
                        f"{Fore.YELLOW}{Style.BRIGHT}{padded}{Style.RESET_ALL}"
                    )
                else:
                    parts.append(padded)
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
        headers = ["Title", "Branch", "Worktree", "Description", "Status"]
        rows = [
            [
                issue.title,
                issue.branch or "",
                issue.worktree or "",
                (issue.description or "").strip().splitlines()[0]
                if issue.description
                else "",
                _format_status(issue),
            ]
            for issue in issues
        ]
    else:
        headers = ["Title", "Branch", "Worktree", "Status"]
        rows = [
            [
                issue.title,
                issue.branch or "",
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
        description="Bidirectional sync tool for Linear issues. Push local YAML files to Linear or pull Linear issues to local YAML files.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # sync subcommand
    sync_parser = subparsers.add_parser(
        "sync",
        help="Push local YAML file(s) to Linear (create/update issues)",
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

    check_parser = subparsers.add_parser(
        "check",
        help="Run local validations against manifests.",
    )
    check_subparsers = check_parser.add_subparsers(
        dest="check_command",
        help="Check commands",
    )
    check_subparsers.required = True

    tests_parser = check_subparsers.add_parser(
        "tests",
        help="Inspect GitHub test status for tracked branches.",
    )
    tests_parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=None,
        help="Path to a manifest file or directory (defaults to LinearManager/tasks).",
    )
    tests_parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent GitHub status checks to run.",
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

    # pull subcommand
    pull_parser = subparsers.add_parser(
        "pull",
        help="Pull issues from Linear to local YAML files (read-only download)",
    )
    pull_parser.add_argument(
        "--team-keys",
        "-t",
        type=str,
        nargs="+",
        required=True,
        help="Team keys to pull issues from (e.g., ENG PROD)",
    )
    pull_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output directory for YAML files (defaults to LinearManager/tasks)",
    )
    pull_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of issues to fetch per team (default: 100)",
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
    elif args.command == "check":
        try:
            if args.check_command == "tests":
                path = args.path if args.path is not None else _get_tasks_directory()
                return run_check_tests(path, max_workers=args.workers)
            parser.error(f"Unknown check command '{args.check_command}'.")
            return 1
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
    elif args.command == "pull":
        try:
            output_dir = args.output if args.output is not None else _get_tasks_directory()
            run_pull(
                team_keys=args.team_keys,
                output_dir=output_dir,
                limit=args.limit,
            )
            return 0
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
