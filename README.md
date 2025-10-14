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

Create a YAML file describing the issues you want to sync:

```yaml
defaults:
  team_key: ENG
  state: Triage
  labels: ["Automation"]
  assignee_email: engineer@example.com
  priority: 1
issues:
  - identifier: ENG-123
    title: Fix webhook retries
    description: |
      Make sure failed webhooks retry with exponential backoff.
    labels: ["Infra"]
    complete: true
  - title: Ship new health check
    description: Update /health to include queue depth.
    priority: 2
```

- `team_key` (required per issue) chooses the Linear team.
- `identifier` is optional; when present the CLI updates the existing issue instead of creating a new one.
- `complete: true` marks the issue done when you pass `--mark-done`.

## Syncing

```bash
linear-manager path/to/issues.yaml            # apply changes
linear-manager path/to/issues.yaml --dry-run  # preview without touching Linear
linear-manager path/to/issues.yaml --mark-done
```

The tool syncs YAML → Linear only; it never pulls changes back into the manifest.
