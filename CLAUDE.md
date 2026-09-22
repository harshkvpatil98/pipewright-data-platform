# Claude Code in this repository

Read [`AGENTS.md`](AGENTS.md) for the development rules and
[`docs/HANDOFF.md`](docs/HANDOFF.md) for project status, architecture and
gotchas. Those two are the sources of truth; this file only sets the workflow.

Development uses **one Claude Code session**, working directly in the
repository. No required subagents, no delegated roles, no external model
review.

For each piece of work:

1. Read the current context and the user's request.
2. Make a brief plan appropriate to the task.
3. Implement directly in the repository.
4. Run the relevant checks, then the full gate: `npm run verify`.
5. Review the diff and fix issues the change caused.
6. Update `docs/HANDOFF.md` if project state changed.
7. Report results and limitations accurately.
