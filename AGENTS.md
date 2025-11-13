# Agent Instructions for LinearManager

## Duplicate Issue Detection

When working with LinearManager tasks, if you encounter duplicate issues or issues that seem like they might be duplicates:

**ALWAYS ask the user which issue should be kept.**

Do not automatically:
- Delete duplicates
- Merge duplicates
- Assume which one should be preserved

Instead:
1. Identify the potentially duplicate issues
2. Present them to the user with their key details (title, description, status, assignee)
3. Ask which should be kept and what should happen to the others (delete, merge, keep both, etc.)

This ensures important context or subtle differences aren't lost without user review.
