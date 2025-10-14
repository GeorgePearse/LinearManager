"""Integration tests for the sync workflow."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from linear_manager.sync import (
    SyncConfig,
    run_sync,
    IssueSpec,
    TeamContext,
    LinearClient,
    _process_issue,
)


class TestSyncWorkflow:
    """Test complete sync workflow."""

    @pytest.fixture
    def team_context(self) -> TeamContext:
        """Create a sample TeamContext for testing."""
        return TeamContext(
            key="ENG",
            id="team-123",
            states={"backlog": "state-1", "todo": "state-2", "done": "state-3"},
            available_states=["Backlog", "Todo", "Done"],
            done_state_id="state-3",
            labels={"bug": "label-1", "feature": "label-2"},
            available_labels=["Bug", "Feature"],
            members={"dev@example.com": "user-1"},
        )

    @pytest.fixture
    def mock_linear_client(self) -> Mock:
        """Create a mock LinearClient."""
        client = Mock(spec=LinearClient)
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=None)
        return client

    def test_run_sync_missing_api_key(self) -> None:
        """Test sync fails without LINEAR_API_KEY."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("defaults:\n  team_key: ENG\nissues:\n  - title: Test\n")
            f.flush()
            path = Path(f.name)

        try:
            # Ensure LINEAR_API_KEY is not set
            old_key = os.environ.pop("LINEAR_API_KEY", None)
            try:
                config = SyncConfig(manifest_path=path)
                with pytest.raises(RuntimeError, match="LINEAR_API_KEY environment variable is required"):
                    run_sync(config)
            finally:
                if old_key:
                    os.environ["LINEAR_API_KEY"] = old_key
        finally:
            path.unlink()

    @patch("linear_manager.sync.LinearClient")
    def test_run_sync_creates_issues(self, mock_client_class: Mock) -> None:
        """Test sync creates new issues."""
        mock_client = Mock(spec=LinearClient)
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=None)
        mock_client_class.return_value = mock_client

        # Mock team context
        mock_client.fetch_team_context.return_value = TeamContext(
            key="ENG",
            id="team-123",
            states={"backlog": "state-1"},
            available_states=["Backlog"],
            done_state_id="state-done",
            labels={},
            available_labels=[],
            members={},
        )

        # Mock issue creation
        mock_client.create_issue.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("defaults:\n  team_key: ENG\nissues:\n  - title: Test Issue\n")
            f.flush()
            path = Path(f.name)

        try:
            os.environ["LINEAR_API_KEY"] = "test-token"
            config = SyncConfig(manifest_path=path)
            run_sync(config)

            # Verify issue was created
            assert mock_client.create_issue.called
        finally:
            path.unlink()
            os.environ.pop("LINEAR_API_KEY", None)

    def test_process_issue_create_new(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test processing creates a new issue."""
        spec = IssueSpec(
            title="Test Issue",
            description="Test description",
            team_key="ENG",
            identifier=None,
            state="Backlog",
            labels=[],
            assignee_email=None,
            priority=2,
            complete=False,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = None
        mock_linear_client.create_issue.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
        }

        config = SyncConfig(manifest_path=Path("test.yaml"), dry_run=False)
        _process_issue(mock_linear_client, team_context, spec, config)

        mock_linear_client.create_issue.assert_called_once()
        call_args = mock_linear_client.create_issue.call_args[0][0]
        assert call_args["title"] == "Test Issue"
        assert call_args["teamId"] == "team-123"

    def test_process_issue_update_existing(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test processing updates an existing issue."""
        spec = IssueSpec(
            title="Updated Title",
            description="Updated description",
            team_key="ENG",
            identifier="ENG-123",
            state="Todo",
            labels=[],
            assignee_email=None,
            priority=3,
            complete=False,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
            "title": "Old Title",
        }
        mock_linear_client.update_issue.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
        }

        config = SyncConfig(manifest_path=Path("test.yaml"), dry_run=False)
        _process_issue(mock_linear_client, team_context, spec, config)

        mock_linear_client.update_issue.assert_called_once()
        call_args = mock_linear_client.update_issue.call_args[0]
        assert call_args[0] == "issue-123"
        assert call_args[1]["title"] == "Updated Title"

    def test_process_issue_dry_run_create(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test dry run doesn't create issues."""
        spec = IssueSpec(
            title="Test Issue",
            description="Test description",
            team_key="ENG",
            identifier=None,
            state=None,
            labels=[],
            assignee_email=None,
            priority=None,
            complete=False,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = None

        config = SyncConfig(manifest_path=Path("test.yaml"), dry_run=True)
        _process_issue(mock_linear_client, team_context, spec, config)

        mock_linear_client.create_issue.assert_not_called()

    def test_process_issue_dry_run_update(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test dry run doesn't update issues."""
        spec = IssueSpec(
            title="Updated Title",
            description="Updated description",
            team_key="ENG",
            identifier="ENG-123",
            state=None,
            labels=[],
            assignee_email=None,
            priority=None,
            complete=False,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
            "title": "Old Title",
        }

        config = SyncConfig(manifest_path=Path("test.yaml"), dry_run=True)
        _process_issue(mock_linear_client, team_context, spec, config)

        mock_linear_client.update_issue.assert_not_called()

    def test_process_issue_mark_done(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test marking issues as done with mark_done flag."""
        spec = IssueSpec(
            title="Test Issue",
            description="Test description",
            team_key="ENG",
            identifier=None,
            state=None,
            labels=[],
            assignee_email=None,
            priority=None,
            complete=True,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = None
        mock_linear_client.create_issue.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
        }

        config = SyncConfig(manifest_path=Path("test.yaml"), mark_done=True)
        _process_issue(mock_linear_client, team_context, spec, config)

        call_args = mock_linear_client.create_issue.call_args[0][0]
        assert call_args["stateId"] == "state-3"  # done state

    def test_process_issue_complete_without_mark_done(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test complete=true without mark_done doesn't mark done."""
        spec = IssueSpec(
            title="Test Issue",
            description="Test description",
            team_key="ENG",
            identifier=None,
            state="Backlog",
            labels=[],
            assignee_email=None,
            priority=None,
            complete=True,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = None
        mock_linear_client.create_issue.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
        }

        config = SyncConfig(manifest_path=Path("test.yaml"), mark_done=False)
        _process_issue(mock_linear_client, team_context, spec, config)

        call_args = mock_linear_client.create_issue.call_args[0][0]
        assert call_args["stateId"] == "state-1"  # backlog state, not done

    def test_process_issue_with_labels(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test processing issue with labels."""
        spec = IssueSpec(
            title="Test Issue",
            description="Test description",
            team_key="ENG",
            identifier=None,
            state=None,
            labels=["Bug", "Feature"],
            assignee_email=None,
            priority=None,
            complete=False,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = None
        mock_linear_client.create_issue.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
        }

        config = SyncConfig(manifest_path=Path("test.yaml"))
        _process_issue(mock_linear_client, team_context, spec, config)

        call_args = mock_linear_client.create_issue.call_args[0][0]
        assert set(call_args["labelIds"]) == {"label-1", "label-2"}

    def test_process_issue_with_assignee(
        self, team_context: TeamContext, mock_linear_client: Mock
    ) -> None:
        """Test processing issue with assignee."""
        spec = IssueSpec(
            title="Test Issue",
            description="Test description",
            team_key="ENG",
            identifier=None,
            state=None,
            labels=[],
            assignee_email="dev@example.com",
            priority=None,
            complete=False,
        )

        mock_linear_client.fetch_issue_by_identifier.return_value = None
        mock_linear_client.create_issue.return_value = {
            "id": "issue-123",
            "identifier": "ENG-123",
            "url": "https://linear.app/issue/ENG-123",
        }

        config = SyncConfig(manifest_path=Path("test.yaml"))
        _process_issue(mock_linear_client, team_context, spec, config)

        call_args = mock_linear_client.create_issue.call_args[0][0]
        assert call_args["assigneeId"] == "user-1"
