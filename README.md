# LinearManager

Even using the Linear MCP can slow down your work nowadays. This is a simple quick solution so that maintaining your tickets doesn't take you out of your flow.

**LinearManager supports both push and pull operations:**
- **Push (sync)**: Upload local YAML files to Linear to create/update issues
- **Pull**: Download issues from Linear to local YAML files

<img width="1845" height="661" alt="image" src="https://github.com/user-attachments/assets/bb37838c-3cc2-4d60-a9a9-6e1c8f48d005" />


## Getting Started

```bash
uv venv --python 3.11
. .venv/bin/activate
uv pip install -e .
```

The CLI expects a Linear personal API token in `LINEAR_API_KEY`.

## Global Install

`uv tool` can install the `manager` CLI globally so it is available on your PATH without activating a virtualenv.

```bash
# Install from a local checkout
uv tool install --from . manager

# Or install directly from GitHub
uv tool install --from git+https://github.com/your-username/LinearManager manager
```

After installation you can run `manager ...` from anywhere on your machine.

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

## Bidirectional Sync Operations

LinearManager provides both **push** and **pull** operations for complete control over your Linear tickets.

### Push to Linear (sync command)

Upload local YAML files to Linear to create or update issues:

```bash
# Push all YAML files in current directory to Linear
manager sync .

# Push all YAML files in a specific directory
manager sync path/to/manifests

# Push a single file
manager sync path/to/issues.yaml

# Preview changes without pushing
manager sync . --dry-run
```

### Pull from Linear (pull command)

Download issues from Linear and save them as local YAML files:

```bash
# Pull issues from a specific team
manager pull --team-keys ENG --output ./pulled_issues

# Pull issues from multiple teams
manager pull --team-keys ENG PROD --output ./remote_issues

# Pull to the default LinearManager/tasks directory
manager pull --team-keys ENG

# Limit the number of issues fetched per team (default is 100)
manager pull --team-keys ENG --limit 50
```

Options:
- `--team-keys` / `-t` (required): One or more team keys to pull issues from
- `--output` / `-o`: Directory to save YAML files (defaults to LinearManager/tasks)
- `--limit`: Maximum number of issues to fetch per team (default: 100)

The pull command:
- Downloads issues from Linear for specified teams
- Creates one YAML file per team (e.g., `eng_issues.yaml`)
- Includes all issue metadata: identifier, title, description, state, priority, assignee, labels, and branch name
- Is read-only - doesn't push any local changes to Linear

### Common Workflows

**Backup Linear issues:**
```bash
# Pull all issues from your teams for backup
manager pull --team-keys ENG PROD DESIGN --output ./backups/$(date +%Y%m%d)
```

**Update local copies then push changes:**
```bash
# 1. Pull latest issues from Linear
manager pull --team-keys ENG --output ./tasks

# 2. Edit the YAML files locally
# ... make your changes ...

# 3. Push changes back to Linear
manager sync ./tasks
```

**Migrate issues between teams:**
```bash
# 1. Pull from source team
manager pull --team-keys OLD_TEAM --output ./migration

# 2. Edit YAML to change team_key
# ... update team_key in files ...

# 3. Push to new team
manager sync ./migration
```

> **Note**: We plan to integrate with [par](https://github.com/your-username/par) for enhanced parallel processing and workflow automation.

### Legacy mode

The old single-file syntax still works for backwards compatibility:
```bash
manager path/to/issues.yaml
```
