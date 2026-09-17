# Recorded provider fixtures

These files were captured from real `codex exec` and `claude -p` invocations on
2026-09-17 (codex-cli 0.149.1, Claude Code 2.1.231) and then trimmed, with
failure variants added by hand.

They exist so the adapters' parsing and failure-classification can be tested
offline, deterministically, and without spending a provider call on every run of
the suite.

**They are not evidence that a live call happened.** A fixture-backed test proves
the controller reads a response correctly. Only `pw-dev doctor --probe` and a
real run establish that a provider is reachable and entitled. Nothing in this
directory should ever be cited as a live-provider result.
