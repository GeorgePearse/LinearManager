# LinearManager

Even using the Linear MCP can slow down your work nowadays. This is a simple quick solution so that maintaining your tickets doesn't take you out of your flow.

## Getting Started

```bash
uv venv --python 3.11
. .venv/bin/activate
uv pip install -e .
```

The CLI expects a Linear personal API token in `LINEAR_API_KEY`.

## Manifest Format

Create a YAML file for each issue you want to sync. Each file should contain a single issue:

```yaml
defaults:
  team_key: ENG
  state: Triage
  priority: 1

issues:
  - title: Fix webhook retries
    description: |
      Make sure failed webhooks retry with exponential backoff.
    labels: ["Infra", "Automation"]
    assignee_email: engineer@example.com
    complete: true
    branch: feature/webhook-retries
    worktree: ../worktrees/webhook-retries
```

Or update an existing issue by specifying its identifier:

```yaml
defaults:
  team_key: ENG

issues:
  - identifier: ENG-123
    title: Fix webhook retries - UPDATED
    description: |
      Make sure failed webhooks retry with exponential backoff.
      Added additional context here.
    priority: 2
```

Key fields:
- `team_key` (required per issue) chooses the Linear team
- `identifier` is optional; when present the CLI updates the existing issue instead of creating a new one
- `state` or `status` (synonyms) set the Linear workflow state (e.g., "Todo", "In Progress", "Done")
- `labels`, `assignee_email`, `state`, and `priority` can be set at defaults level or per-issue
- `branch` and `worktree` are optional helpers for tracking local development context so you can jump back into the work quickly later

## Setting Issue Status

Use `state` or `status` to set the workflow state in Linear (they're synonyms):

```yaml
defaults:
  team_key: ENG

issues:
  - identifier: ENG-123
    title: Fix critical bug
    description: Bug has been resolved
    status: Done  # Sets the issue to "Done" state in Linear
```

Or using `state`:

```yaml
defaults:
  team_key: ENG

issues:
  - identifier: ENG-124
    title: Work in progress
    description: Currently implementing
    state: In Progress  # Sets the issue to "In Progress" state
```

## Syncing

```bash
# Sync all YAML files in current directory
manager sync .

# Sync all YAML files in a specific directory
manager sync path/to/manifests

# Sync a single file
manager sync path/to/issues.yaml

# Preview changes without syncing
manager sync . --dry-run
```

The tool syncs YAML → Linear only; it never pulls changes back into the manifest.

### Legacy mode

The old single-file syntax still works for backwards compatibility:
```bash
manager path/to/issues.yaml
```
