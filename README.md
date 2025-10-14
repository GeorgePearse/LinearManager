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
- `complete: true` marks the issue done when you pass `--mark-done`
- `labels`, `assignee_email`, `state`, and `priority` can be set at defaults level or per-issue

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

# Mark completed issues as done
manager sync . --mark-done
```

The tool syncs YAML → Linear only; it never pulls changes back into the manifest.

### Legacy mode

The old single-file syntax still works for backwards compatibility:
```bash
manager path/to/issues.yaml
```
