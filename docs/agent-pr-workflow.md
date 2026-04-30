# Agent PR Workflow

How issues turn into merged code in this repo. Read this before opening a PR.

## Lifecycle

1. **Issue** — every behavior change starts from a GitHub issue with concrete acceptance criteria. Issues are gated by `Blocked by:` relationships; do not start an issue whose blockers are still open.
2. **Branch** — work on a feature branch. Direct pushes to `main` are blocked.
3. **PR** — open a pull request. The PR body must reference the issue with `Closes #N` (or `Fixes #N` / `Resolves #N`) so GitHub links them.
4. **Checks** — two required checks run automatically:
   - `pytest` — runs `uv run pytest -m "not e2e and not hardware"` on Python 3.13.
   - `claude-review` — runs the Claude Code reviewer using `CLAUDE.md` as the rubric.
5. **Merge** — the auto-merge workflow squash-merges the PR and deletes the branch when both checks pass and no opt-out label is set on the PR or any linked issue.

## Opt-out Labels

Apply these to the **issue** (preferred — labels propagate through `Closes #N`) or the PR to disable auto-merge. Auto-merge stays off until the label is removed and a new event fires (push, label change, review, etc.).

| Label | When to use |
|---|---|
| `needs-manual-verification` | Acceptance requires human-run verification CI cannot perform: smoke tests, hardware E2E, manual smoke checks on the Raspberry Pi, anything reading `RPI_MCP_URL`. |
| `critical` | Risky or sensitive change that benefits from explicit human review before merge: security-adjacent code, deployment scripts, anything that touches the GPIO allowlist or secret handling. Also escalates the Claude reviewer from Sonnet 4.6 to Opus 4.7 for a deeper pass. |
| `do-not-merge` | Generic block; use for in-flight PRs that should not merge yet. |

## Acceptance Criteria

Issue acceptance criteria are written as a checklist:

```markdown
Acceptance:
- [ ] loads gpio23_output and gpio24_input
- [ ] rejects duplicate device IDs
- [ ] rejects unsupported pin numbering
```

The Claude reviewer is expected to verify each criterion against the diff and tick the box (or comment why it cannot). Implementers should not pre-tick boxes themselves; let the reviewer be the independent verifier.

For criteria that require hardware verification (e.g. "verify GPIO23 actually toggles 3.3V"), label the issue `needs-manual-verification`. The implementer or owner runs the test on the Raspberry Pi, posts results in the PR, ticks the box manually, and merges by hand once verified.

## What a Fresh-Context Coding Agent Should Do

1. Read `AGENTS.md` for project context, SDD rules, and the current milestone.
2. Read this file (`docs/agent-pr-workflow.md`) for the PR contract.
3. Read the relevant spec under `specs/` before changing behavior.
4. Pick an issue whose blockers are closed.
5. Implement the smallest change that meets the acceptance criteria.
6. Run `uv run pytest -m "not e2e and not hardware"` locally before pushing.
7. Open the PR with `Closes #N` in the body.
8. Do not tick acceptance checkboxes for yourself; the Claude reviewer will.
9. If the linked issue has `needs-manual-verification` or `critical`, expect the human to merge — do not retry, comment, or escalate.

## Required Status Check Names

The auto-merge workflow expects these exact names (case-sensitive):

- `pytest` — defined in `.github/workflows/ci.yml`
- `claude-review` — defined in `.github/workflows/claude-code-review.yml`

If a workflow is renamed, update `.github/workflows/auto-merge.yml` to match.
