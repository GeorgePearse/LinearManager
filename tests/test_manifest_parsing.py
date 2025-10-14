"""Tests for manifest parsing and validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from linear_manager.sync import (
    ManifestDefaults,
    _load_manifest,
    _parse_defaults,
    _parse_issue,
    _optional_str,
    _require_str,
    _optional_int,
    _dedupe,
    _normalize_key,
)


class TestManifestLoading:
    """Test manifest loading from YAML files."""

    def test_load_valid_manifest(self) -> None:
        """Test loading a valid manifest file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
defaults:
  team_key: ENG
  priority: 2

issues:
  - title: Test Issue
    description: Test description
    state: Todo
""")
            f.flush()
            path = Path(f.name)

        try:
            manifest = _load_manifest(path)
            assert len(manifest.issues) == 1
            assert manifest.issues[0].title == "Test Issue"
            assert manifest.issues[0].team_key == "ENG"
            assert manifest.issues[0].priority == 2
        finally:
            path.unlink()

    def test_load_manifest_nonexistent_file(self) -> None:
        """Test loading a manifest from a nonexistent path."""
        with pytest.raises(RuntimeError, match="does not exist"):
            _load_manifest(Path("/nonexistent/path.yaml"))

    def test_load_manifest_directory(self) -> None:
        """Test loading a manifest from a directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(RuntimeError, match="is a directory"):
                _load_manifest(Path(tmpdir))

    def test_load_empty_manifest(self) -> None:
        """Test loading an empty YAML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(RuntimeError, match="is empty"):
                _load_manifest(path)
        finally:
            path.unlink()

    def test_load_manifest_missing_issues(self) -> None:
        """Test loading a manifest without issues list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("defaults:\n  team_key: ENG\n")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(
                RuntimeError, match="must include a non-empty 'issues' list"
            ):
                _load_manifest(path)
        finally:
            path.unlink()

    def test_load_manifest_invalid_issues_type(self) -> None:
        """Test loading a manifest with non-list issues."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("issues: not_a_list\n")
            f.flush()
            path = Path(f.name)

        try:
            with pytest.raises(RuntimeError, match="'issues' must be a list"):
                _load_manifest(path)
        finally:
            path.unlink()


class TestDefaultsParsing:
    """Test parsing of manifest defaults."""

    def test_parse_empty_defaults(self) -> None:
        """Test parsing empty defaults."""
        defaults = _parse_defaults({})
        assert defaults.team_key is None
        assert defaults.state is None
        assert defaults.labels == []
        assert defaults.assignee_email is None
        assert defaults.priority is None
        assert defaults.branch is None
        assert defaults.worktree is None

    def test_parse_full_defaults(self) -> None:
        """Test parsing complete defaults."""
        data = {
            "team_key": "ENG",
            "state": "Backlog",
            "labels": ["Bug", "Frontend"],
            "assignee_email": "dev@example.com",
            "priority": 3,
            "branch": "feature/test",
            "worktree": "/repos/feature-test",
        }
        defaults = _parse_defaults(data)
        assert defaults.team_key == "ENG"
        assert defaults.state == "Backlog"
        assert defaults.labels == ["Bug", "Frontend"]
        assert defaults.assignee_email == "dev@example.com"
        assert defaults.priority == 3
        assert defaults.branch == "feature/test"
        assert defaults.worktree == "/repos/feature-test"

    def test_parse_defaults_with_assignee_alias(self) -> None:
        """Test that 'assignee' is accepted as alias for 'assignee_email'."""
        data: dict[str, str] = {"assignee": "dev@example.com"}
        defaults = _parse_defaults(data)
        assert defaults.assignee_email == "dev@example.com"

    def test_parse_defaults_invalid_labels_type(self) -> None:
        """Test parsing defaults with invalid labels type."""
        with pytest.raises(RuntimeError, match="'defaults.labels' must be a list"):
            _parse_defaults({"labels": "not_a_list"})


class TestIssueParsing:
    """Test parsing of individual issues."""

    def test_parse_minimal_issue(self) -> None:
        """Test parsing an issue with minimal fields."""
        defaults = ManifestDefaults(team_key="ENG")
        data = {"title": "Test Issue"}
        issue = _parse_issue(data, defaults, 1)
        assert issue.title == "Test Issue"
        assert issue.description == ""
        assert issue.team_key == "ENG"
        assert issue.identifier is None
        assert issue.state is None
        assert issue.labels == []
        assert issue.assignee_email is None
        assert issue.priority is None
        assert issue.branch is None
        assert issue.worktree is None

    def test_parse_full_issue(self) -> None:
        """Test parsing an issue with all fields."""
        defaults = ManifestDefaults()
        data = {
            "title": "Test Issue",
            "description": "Test description",
            "team_key": "ENG",
            "identifier": "ENG-123",
            "state": "Todo",
            "labels": ["Bug", "Frontend"],
            "assignee_email": "dev@example.com",
            "priority": 2,
            "branch": "feature/test",
            "worktree": "/repos/feature-test",
        }
        issue = _parse_issue(data, defaults, 1)
        assert issue.title == "Test Issue"
        assert issue.description == "Test description"
        assert issue.team_key == "ENG"
        assert issue.identifier == "ENG-123"
        assert issue.state == "Todo"
        assert issue.labels == ["Bug", "Frontend"]
        assert issue.assignee_email == "dev@example.com"
        assert issue.priority == 2
        assert issue.branch == "feature/test"
        assert issue.worktree == "/repos/feature-test"

    def test_parse_issue_with_defaults(self) -> None:
        """Test that issue inherits from defaults."""
        defaults = ManifestDefaults(
            team_key="ENG",
            state="Backlog",
            labels=["Automation"],
            priority=1,
            branch="feature/base",
            worktree="/repos/base",
        )
        data = {"title": "Test Issue"}
        issue = _parse_issue(data, defaults, 1)
        assert issue.team_key == "ENG"
        assert issue.state == "Backlog"
        assert issue.labels == ["Automation"]
        assert issue.priority == 1
        assert issue.branch == "feature/base"
        assert issue.worktree == "/repos/base"

    def test_parse_issue_overrides_defaults(self) -> None:
        """Test that issue fields override defaults."""
        defaults = ManifestDefaults(
            team_key="ENG",
            state="Backlog",
            labels=["Automation"],
            priority=1,
            branch="feature/base",
            worktree="/repos/base",
        )
        data = {
            "title": "Test Issue",
            "team_key": "PROD",
            "state": "Todo",
            "labels": ["Bug"],
            "priority": 3,
            "branch": "feature/override",
            "worktree": "/repos/override",
        }
        issue = _parse_issue(data, defaults, 1)
        assert issue.team_key == "PROD"
        assert issue.state == "Todo"
        assert set(issue.labels) == {"Automation", "Bug"}
        assert issue.priority == 3
        assert issue.branch == "feature/override"
        assert issue.worktree == "/repos/override"

    def test_parse_issue_missing_team_key(self) -> None:
        """Test parsing issue without team_key fails."""
        defaults = ManifestDefaults()
        data = {"title": "Test Issue"}
        with pytest.raises(RuntimeError, match="'team_key' missing"):
            _parse_issue(data, defaults, 1)

    def test_parse_issue_missing_title(self) -> None:
        """Test parsing issue without title fails."""
        defaults = ManifestDefaults(team_key="ENG")
        data: dict[str, str] = {}
        with pytest.raises(RuntimeError, match="'title' is required"):
            _parse_issue(data, defaults, 1)

    def test_parse_issue_with_id_alias(self) -> None:
        """Test that 'id' is accepted as alias for 'identifier'."""
        defaults = ManifestDefaults(team_key="ENG")
        data: dict[str, str] = {"title": "Test Issue", "id": "ENG-123"}
        issue = _parse_issue(data, defaults, 1)
        assert issue.identifier == "ENG-123"

    def test_parse_issue_labels_merge(self) -> None:
        """Test that issue labels merge with default labels."""
        defaults = ManifestDefaults(labels=["Default1", "Default2"])
        data = {
            "title": "Test Issue",
            "team_key": "ENG",
            "labels": ["Issue1", "Issue2"],
        }
        issue = _parse_issue(data, defaults, 1)
        assert issue.labels == ["Default1", "Default2", "Issue1", "Issue2"]

    def test_parse_issue_labels_dedupe(self) -> None:
        """Test that duplicate labels are removed (case-insensitive)."""
        defaults = ManifestDefaults(labels=["Bug", "Frontend"])
        data = {
            "title": "Test Issue",
            "team_key": "ENG",
            "labels": ["bug", "Backend"],
        }
        issue = _parse_issue(data, defaults, 1)
        assert "Bug" in issue.labels
        assert "bug" not in issue.labels
        assert "Frontend" in issue.labels
        assert "Backend" in issue.labels

    def test_parse_issue_with_status_alias(self) -> None:
        """Test that 'status' is accepted as alias for 'state'."""
        defaults = ManifestDefaults(team_key="ENG")
        data: dict[str, str] = {"title": "Test Issue", "status": "Done"}
        issue = _parse_issue(data, defaults, 1)
        assert issue.state == "Done"

    def test_parse_issue_status_overrides_state(self) -> None:
        """Test that 'status' takes precedence when both are provided."""
        defaults = ManifestDefaults(team_key="ENG")
        data: dict[str, str] = {
            "title": "Test Issue",
            "state": "Todo",
            "status": "Done",
        }
        issue = _parse_issue(data, defaults, 1)
        assert issue.state == "Done"


class TestHelperFunctions:
    """Test helper functions for parsing."""

    def test_optional_str_none(self) -> None:
        """Test _optional_str with None."""
        assert _optional_str(None) is None

    def test_optional_str_string(self) -> None:
        """Test _optional_str with string."""
        assert _optional_str("test") == "test"

    def test_optional_str_empty(self) -> None:
        """Test _optional_str with empty string."""
        assert _optional_str("") is None
        assert _optional_str("   ") is None

    def test_optional_str_number(self) -> None:
        """Test _optional_str with number."""
        assert _optional_str(123) == "123"

    def test_require_str_valid(self) -> None:
        """Test _require_str with valid string."""
        assert _require_str("test", "context") == "test"

    def test_require_str_none(self) -> None:
        """Test _require_str with None."""
        with pytest.raises(RuntimeError, match="context"):
            _require_str(None, "context")

    def test_require_str_empty(self) -> None:
        """Test _require_str with empty string."""
        with pytest.raises(RuntimeError, match="context"):
            _require_str("", "context")

    def test_optional_int_valid(self) -> None:
        """Test _optional_int with valid values."""
        assert _optional_int(0) == 0
        assert _optional_int(2) == 2
        assert _optional_int(4) == 4

    def test_optional_int_none(self) -> None:
        """Test _optional_int with None."""
        assert _optional_int(None) is None

    def test_optional_int_string(self) -> None:
        """Test _optional_int with string number."""
        assert _optional_int("2") == 2

    def test_optional_int_invalid_range(self) -> None:
        """Test _optional_int with out-of-range values."""
        with pytest.raises(RuntimeError, match="Priority must be between 0"):
            _optional_int(5)
        with pytest.raises(RuntimeError, match="Priority must be between 0"):
            _optional_int(-1)

    def test_optional_int_invalid_type(self) -> None:
        """Test _optional_int with invalid type."""
        with pytest.raises(RuntimeError, match="Priority values must be integers"):
            _optional_int("not_a_number")

    def test_dedupe(self) -> None:
        """Test deduplication of list items (case-insensitive)."""
        result = _dedupe(["Bug", "bug", "Frontend", "FRONTEND", "Backend"])
        assert result == ["Bug", "Frontend", "Backend"]

    def test_dedupe_preserves_first(self) -> None:
        """Test that _dedupe preserves first occurrence."""
        result = _dedupe(["Bug", "BUG", "bug"])
        assert result == ["Bug"]

    def test_normalize_key(self) -> None:
        """Test key normalization."""
        assert _normalize_key("Test") == "test"
        assert _normalize_key("  Test  ") == "test"
        assert _normalize_key("TEST") == "test"
