# Contributing

## Workflow

1. Create a focused branch from `main`.
2. Keep firmware, ML, tools, and documentation changes in separate logical
   commits when practical.
3. Run the relevant host tests, Python compilation, and firmware build before
   opening a pull request.
4. Describe hardware changes with pinout, board, and validation details.

## Commit messages

Use Conventional Commits with an explanatory subject:

```text
feat(firmware): add measured I2S bring-up probe
fix(tools): report dropped ANC0 packets
docs(architecture): document capture-to-inference flow
chore(repo): reorganize ML package layout
```

The body should explain why the change is needed and mention verification. Do
not use vague messages such as `update`, `changes`, or `push comments`.

## Claude attribution

If using Claude Code, prevent automatic co-author trailers unless the project
explicitly wants them. Add this to `~/.claude/settings.json`:

```json
{
  "includeCoAuthoredBy": false
}
```

Never rewrite shared history without maintainer approval. This repository has
already removed historical Claude attribution from its published `main` line.

## Pull requests

Include a concise summary, affected paths, test commands and results, board
details for firmware work, and screenshots or sample metrics for dashboard/UI
changes.
