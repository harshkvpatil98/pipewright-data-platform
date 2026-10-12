## What this changes

<!-- What broke, or what is new. Lead with the problem. Name the roadmap phase
     or issue it belongs to. -->

## Evidence

<!-- What you ran and what it printed: test counts before and after, the
     request sequence you tried against a running stack, a screenshot for UI
     work. Passed, failed, skipped and could-not-run are four different
     results — say which. -->

## Gates

- [ ] `npm run verify` is green — ruff, the pytest bundle, web tests, ESLint, `tsc`, production build
- [ ] A new test directory is listed in `scripts/test.sh` (it is not collected otherwise)
- [ ] No invariant in `CONTRIBUTING.md` weakened, and no failing test skipped or narrowed to get green
- [ ] Any schema change is a **new** Alembic revision in `apps/api-gateway/alembic/versions/`
- [ ] New UI uses the semantic theme tokens — no raw colour literals, no icon or chart library
- [ ] `docs/HANDOFF.md` (ledger, known gaps) and `README.md` updated if what the platform can do has changed
- [ ] No secrets, `.env` files, uploaded data or build output added

## Notes

<!-- Anything deferred, and why. "Needs a live SMTP server" is a real reason;
     "will fix later" is not. -->
