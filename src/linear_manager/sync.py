"""Core sync logic for LinearManager - supports both push (to Linear) and pull (from Linear) operations."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml


@dataclass(frozen=True)
class SyncConfig:
    """Configuration container for a sync invocation."""

    manifest_path: Path
    dry_run: bool = False
    mark_done: bool = False


@dataclass
class ManifestDefaults:
    """Defaults that can be shared across issues."""

    team_key: str | None = None
    state: str | None = None
    labels: list[str] = field(default_factory=list)
    assignee_email: str | None = None
    priority: int | None = None
    branch: str | None = None
    worktree: str | None = None


@dataclass
class IssueSpec:
    """Single issue specification parsed from the manifest."""

    title: str
    description: str
    team_key: str
    identifier: str | None
    state: str | None
    labels: list[str]
    assignee_email: str | None
    priority: int | None
    complete: bool
    branch: str | None = None
    worktree: str | None = None


@dataclass
class Manifest:
    """Parsed manifest representation."""

    issues: list[IssueSpec]


class LinearApiError(RuntimeError):
    """Raised when the Linear API returns an error."""


def run_sync(config: SyncConfig) -> None:
    """Execute a sync according to the provided configuration."""

    manifest = load_manifest(config.manifest_path)
    token = os.environ.get("LINEAR_API_KEY")
    if not token:
        raise RuntimeError(
            "LINEAR_API_KEY environment variable is required to sync with Linear."
        )

    team_keys = sorted({issue.team_key for issue in manifest.issues})
    with LinearClient(token=token) as client:
        team_contexts = {key: client.fetch_team_context(key) for key in team_keys}

        print(f"Loaded {len(manifest.issues)} issue(s) from {config.manifest_path}.")
        for issue in manifest.issues:
            context = team_contexts[issue.team_key]
            _process_issue(client, context, issue, config)


def run_pull(team_keys: list[str], output_dir: Path, limit: int = 100) -> None:
    """Pull issues from Linear and save them as local YAML files."""
    token = os.environ.get("LINEAR_API_KEY")
    if not token:
        raise RuntimeError(
            "LINEAR_API_KEY environment variable is required to pull from Linear."
        )

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    with LinearClient(token=token) as client:
        for team_key in team_keys:
            print(f"Fetching issues for team {team_key}...")

            # Fetch team context to get state names
            context = client.fetch_team_context(team_key)

            # Fetch issues from Linear
            issues = client.fetch_team_issues(team_key, limit=limit)

            if not issues:
                print(f"  No issues found for team {team_key}.")
                continue

            # Group issues by some logical grouping (we'll use team for now)
            # Each team gets its own YAML file
            filename = f"{team_key.lower()}_issues.yaml"
            filepath = output_dir / filename

            # Convert Linear issues to our IssueSpec format
            issue_specs: list[dict[str, Any]] = []
            for issue_data in issues:
                spec: dict[str, Any] = {
                    "identifier": issue_data["identifier"],
                    "title": issue_data["title"],
                    "description": issue_data.get("description", ""),
                    "team_key": team_key,
                }

                # Add state if present
                state_info = issue_data.get("state")
                if state_info:
                    spec["state"] = state_info["name"]

                # Add priority if present
                priority = issue_data.get("priority")
                if priority is not None:
                    spec["priority"] = priority

                # Add assignee if present
                assignee = issue_data.get("assignee")
                if assignee and assignee.get("email"):
                    spec["assignee_email"] = assignee["email"]

                # Add labels if present
                labels_data = issue_data.get("labels", {}).get("nodes", [])
                if labels_data:
                    spec["labels"] = [label["name"] for label in labels_data]

                # Add branch name if present
                branch_name = issue_data.get("branchName")
                if branch_name:
                    spec["branch"] = branch_name

                issue_specs.append(spec)

            # Create manifest structure
            manifest = {
                "defaults": {
                    "team_key": team_key,
                },
                "issues": issue_specs,
            }

            # Write to file
            filepath.write_text(
                yaml.safe_dump(manifest, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )

            print(f"  Saved {len(issue_specs)} issue(s) to {filepath}")


def _process_issue(
    client: "LinearClient", context: "TeamContext", spec: IssueSpec, config: SyncConfig
) -> None:
    descriptor = f"[{context.key}] {spec.title}"

    context_notes: list[str] = []
    if spec.branch:
        context_notes.append(f"branch={spec.branch}")
    if spec.worktree:
        context_notes.append(f"worktree={spec.worktree}")
    if context_notes:
        print(f"{descriptor}: context -> {', '.join(context_notes)}")

    existing = None
    if spec.identifier:
        existing = client.fetch_issue_by_identifier(spec.identifier)
        if not existing:
            print(
                f"{descriptor}: identifier {spec.identifier} not found; will create new issue."
            )

    if existing:
        update_input: dict[str, Any] = {
            "title": spec.title,
            "description": spec.description,
        }
        if spec.priority is not None:
            update_input["priority"] = spec.priority
        if spec.labels:
            update_input["labelIds"] = context.resolve_label_ids(spec.labels)
        if spec.assignee_email:
            update_input["assigneeId"] = context.resolve_member_id(spec.assignee_email)
        if spec.state:
            update_input["stateId"] = context.resolve_state_id(spec.state)
        if spec.complete and config.mark_done:
            update_input["stateId"] = context.done_state_id

        if config.dry_run:
            print(
                f"{descriptor}: DRY RUN would update issue {existing['identifier']} ({existing['url']})."
            )
        else:
            updated = client.update_issue(existing["id"], update_input)
            print(f"{descriptor}: updated {updated['identifier']} ({updated['url']}).")

        if spec.complete and not config.mark_done:
            print(
                f"{descriptor}: complete=true but --mark-done not set; leaving issue open."
            )
        return

    create_input: dict[str, Any] = {
        "teamId": context.id,
        "title": spec.title,
        "description": spec.description,
    }
    if spec.priority is not None:
        create_input["priority"] = spec.priority
    if spec.labels:
        create_input["labelIds"] = context.resolve_label_ids(spec.labels)
    if spec.assignee_email:
        create_input["assigneeId"] = context.resolve_member_id(spec.assignee_email)
    desired_state_id = None
    if spec.complete and config.mark_done:
        desired_state_id = context.done_state_id
    elif spec.state:
        desired_state_id = context.resolve_state_id(spec.state)
    if desired_state_id:
        create_input["stateId"] = desired_state_id

    if config.dry_run:
        print(f"{descriptor}: DRY RUN would create new issue.")
        return

    created = client.create_issue(create_input)
    print(f"{descriptor}: created {created['identifier']} ({created['url']}).")


def load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise RuntimeError(f"Manifest path {path} does not exist.")
    if path.is_dir():
        raise RuntimeError(
            f"Manifest path {path} is a directory, expected a YAML file."
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raise RuntimeError(f"Manifest {path} is empty.")
    if not isinstance(raw, dict):
        raise RuntimeError("Manifest root must be a mapping.")
    issues_raw = raw.get("issues")
    if not issues_raw:
        raise RuntimeError("Manifest must include a non-empty 'issues' list.")
    if not isinstance(issues_raw, list):
        raise RuntimeError("'issues' must be a list.")

    defaults = _parse_defaults(raw.get("defaults", {}))
    issues = [
        _parse_issue(item, defaults, index)
        for index, item in enumerate(issues_raw, start=1)
    ]
    return Manifest(issues=issues)


# Backwards compatibility for callers that may still import the private name.
_load_manifest = load_manifest


def _parse_defaults(data: Any) -> ManifestDefaults:
    if not data:
        return ManifestDefaults()
    if not isinstance(data, dict):
        raise RuntimeError("'defaults' must be a mapping if provided.")
    labels = data.get("labels") or []
    if not isinstance(labels, list):
        raise RuntimeError("'defaults.labels' must be a list of strings.")
    return ManifestDefaults(
        team_key=_optional_str(data.get("team_key")),
        state=_optional_str(data.get("status") or data.get("state")),
        labels=[_require_str(label, "'defaults.labels' entries") for label in labels],
        assignee_email=_optional_str(
            data.get("assignee_email") or data.get("assignee")
        ),
        priority=_optional_int(data.get("priority")),
        branch=_optional_str(data.get("branch")),
        worktree=_optional_str(data.get("worktree")),
    )


def _parse_issue(data: Any, defaults: ManifestDefaults, index: int) -> IssueSpec:
    if not isinstance(data, dict):
        raise RuntimeError(f"Issue #{index}: entries must be mappings.")

    title = _require_str(data.get("title"), f"Issue #{index}: 'title' is required.")
    description = _optional_str(data.get("description")) or ""
    identifier = _optional_str(data.get("identifier") or data.get("id"))
    state = _optional_str(data.get("status") or data.get("state")) or defaults.state
    team_key = _optional_str(data.get("team_key")) or defaults.team_key
    if not team_key:
        raise RuntimeError(
            f"Issue #{index}: 'team_key' missing and no default provided."
        )

    labels_raw = data.get("labels")
    labels = defaults.labels.copy()
    if labels_raw:
        if not isinstance(labels_raw, list):
            raise RuntimeError(f"Issue #{index}: 'labels' must be a list of strings.")
        labels.extend(
            _require_str(label, f"Issue #{index}: label entries")
            for label in labels_raw
        )
    labels = _dedupe(labels)

    assignee_email = (
        _optional_str(data.get("assignee_email") or data.get("assignee"))
        or defaults.assignee_email
    )
    priority = _optional_int(data.get("priority"), allow_none=True)
    if priority is None:
        priority = defaults.priority

    complete_raw = data.get("complete")
    complete = bool(complete_raw) if complete_raw is not None else False
    branch = _optional_str(data.get("branch")) or defaults.branch
    worktree = _optional_str(data.get("worktree")) or defaults.worktree

    return IssueSpec(
        title=title,
        description=description,
        team_key=team_key,
        identifier=identifier,
        state=state,
        labels=labels,
        assignee_email=assignee_email,
        priority=priority,
        complete=complete,
        branch=branch,
        worktree=worktree,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _require_str(value: Any, context: str) -> str:
    if value is None:
        raise RuntimeError(context)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
        raise RuntimeError(context)
    return str(value)


def _optional_int(value: Any, allow_none: bool = False) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Priority values must be integers.") from exc
    if number < 0 or number > 4:
        raise RuntimeError("Priority must be between 0 (no priority) and 4 (urgent).")
    return number


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _normalize_key(value: str) -> str:
    return value.strip().lower()


@dataclass
class TeamContext:
    """Cached team metadata to translate manifest values into Linear IDs."""

    key: str
    id: str
    states: dict[str, str]
    available_states: list[str]
    done_state_id: str
    labels: dict[str, str]
    available_labels: list[str]
    members: dict[str, str]

    def resolve_state_id(self, state_name: str) -> str:
        lookup = _normalize_key(state_name)
        try:
            return self.states[lookup]
        except KeyError as exc:  # pragma: no cover - defensive
            options = ", ".join(self.available_states) or "none"
            raise RuntimeError(
                f"State '{state_name}' is not valid for team {self.key}. Available states: {options}."
            ) from exc

    def resolve_label_ids(self, labels: list[str]) -> list[str]:
        ids: list[str] = []
        missing: list[str] = []
        for label in labels:
            lookup = _normalize_key(label)
            label_id = self.labels.get(lookup)
            if not label_id:
                missing.append(label)
                continue
            ids.append(label_id)
        if missing:
            options = ", ".join(self.available_labels) or "none"
            raise RuntimeError(
                f"Label(s) {', '.join(missing)} not found in team {self.key}. Available labels: {options}."
            )
        return ids

    def resolve_member_id(self, email: str) -> str:
        lookup = _normalize_key(email)
        try:
            return self.members[lookup]
        except KeyError as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                f"No Linear member with email '{email}' in team {self.key}."
            ) from exc


class LinearClient:
    """Thin wrapper around the Linear GraphQL API."""

    endpoint = "https://api.linear.app/graphql"

    def __init__(self, token: str):
        self._client = httpx.Client(
            base_url=self.endpoint,
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
            },
            timeout=20,
        )

    def __enter__(self) -> "LinearClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_team_context(self, team_key: str) -> TeamContext:
        payload = self._request(
            TEAM_CONTEXT_QUERY,
            {"teamKey": team_key},
        )
        teams = payload.get("teams", {}).get("nodes", [])
        if not teams:
            raise RuntimeError(f"Linear team with key '{team_key}' not found.")

        team = teams[0]

        states_raw = team["states"]["nodes"]
        states = {_normalize_key(node["name"]): node["id"] for node in states_raw}
        available_states = [node["name"] for node in states_raw]
        done_state_id = None
        for node in states_raw:
            if (node.get("type") or "").lower() == "completed":
                done_state_id = node["id"]
                break
        if not done_state_id:
            raise RuntimeError(
                f"Team {team_key} does not have a 'completed' workflow state."
            )

        labels_raw = team.get("labels", {}).get("nodes", [])
        labels = {_normalize_key(node["name"]): node["id"] for node in labels_raw}
        available_labels = [node["name"] for node in labels_raw]

        members_raw = team.get("members", {}).get("nodes", [])
        members: dict[str, str] = {}
        for node in members_raw:
            email = node.get("email")
            if not email:
                continue
            members[_normalize_key(email)] = node["id"]

        return TeamContext(
            key=team["key"],
            id=team["id"],
            states=states,
            available_states=available_states,
            done_state_id=done_state_id,
            labels=labels,
            available_labels=available_labels,
            members=members,
        )

    def fetch_issue_by_identifier(self, identifier: str) -> dict[str, Any] | None:
        payload = self._request(
            ISSUE_BY_IDENTIFIER_QUERY,
            {"identifier": identifier},
        )
        return payload.get("issue")

    def create_issue(self, issue_input: dict[str, Any]) -> dict[str, Any]:
        payload = self._request(
            CREATE_ISSUE_MUTATION,
            {"input": issue_input},
        )
        issue = payload["issueCreate"]["issue"]
        if not issue:  # pragma: no cover - defensive
            raise LinearApiError("Linear API did not return issue data after creation.")
        return issue

    def update_issue(
        self, issue_id: str, update_input: dict[str, Any]
    ) -> dict[str, Any]:
        payload = self._request(
            UPDATE_ISSUE_MUTATION,
            {"id": issue_id, "input": update_input},
        )
        issue = payload["issueUpdate"]["issue"]
        if not issue:  # pragma: no cover - defensive
            raise LinearApiError("Linear API did not return issue data after update.")
        return issue

    def fetch_team_issues(self, team_key: str, limit: int = 100) -> list[dict[str, Any]]:
        """Fetch all issues for a team from Linear."""
        all_issues: list[dict[str, Any]] = []
        has_next_page = True
        after_cursor: str | None = None

        while has_next_page and len(all_issues) < limit:
            batch_size = min(50, limit - len(all_issues))
            payload = self._request(
                FETCH_TEAM_ISSUES_QUERY,
                {"teamKey": team_key, "first": batch_size, "after": after_cursor},
            )

            teams = payload.get("teams", {}).get("nodes", [])
            if not teams:
                break

            team = teams[0]
            issues_data = team.get("issues", {})
            issues = issues_data.get("nodes", [])
            all_issues.extend(issues)

            page_info = issues_data.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            after_cursor = page_info.get("endCursor")

            if not after_cursor:
                break

        return all_issues[:limit]

    def _request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post("", json={"query": query, "variables": variables})
        response.raise_for_status()
        payload = response.json()
        if "errors" in payload and payload["errors"]:
            message = payload["errors"][0].get("message", "Unknown Linear API error.")
            raise LinearApiError(message)
        return payload.get("data", {})


TEAM_CONTEXT_QUERY = """
query TeamContext($teamKey: String!) {
  teams(filter: { key: { eq: $teamKey }}) {
    nodes {
      id
      key
      states(first: 20) {
        nodes {
          id
          name
          type
        }
      }
      labels(first: 20) {
        nodes {
          id
          name
        }
      }
      members(first: 20) {
        nodes {
          id
          email
        }
      }
    }
  }
}
""".strip()


ISSUE_BY_IDENTIFIER_QUERY = """
query IssueByIdentifier($identifier: String!) {
  issue(id: $identifier) {
    id
    identifier
    url
    title
  }
}
""".strip()


CREATE_ISSUE_MUTATION = """
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    issue {
      id
      identifier
      url
    }
  }
}
""".strip()


UPDATE_ISSUE_MUTATION = """
mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    issue {
      id
      identifier
      url
    }
  }
}
""".strip()


FETCH_TEAM_ISSUES_QUERY = """
query FetchTeamIssues($teamKey: String!, $first: Int!, $after: String) {
  teams(filter: { key: { eq: $teamKey }}) {
    nodes {
      id
      key
      issues(first: $first, after: $after, orderBy: updatedAt) {
        nodes {
          id
          identifier
          title
          description
          url
          priority
          state {
            id
            name
            type
          }
          assignee {
            id
            email
          }
          labels {
            nodes {
              id
              name
            }
          }
          branchName
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
""".strip()
