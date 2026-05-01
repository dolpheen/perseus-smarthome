# Agent PR Workflow

How issues turn into merged code in this repo. Read this before opening a PR.

## Lifecycle

1. **Issue** — every behavior change starts from a GitHub issue with concrete acceptance criteria. Issues are gated by `Blocked by:` relationships; do not start an issue whose blockers are still open.
2. **Branch** — work on a feature branch. Direct pushes to `main` are blocked.
3. **PR** — open a pull request. The PR body must reference the issue with `Closes #N` (or `Fixes #N` / `Resolves #N`) so GitHub links them.
4. **Checks** — two required checks run automatically:
   - `pytest` — runs `uv run pytest -m "not e2e and not hardware"` on Python 3.13.
   - `claude-review` — runs the Claude Code reviewer using `CLAUDE.md` as the rubric.
5. **Merge** — the auto-merge workflow squash-merges the PR and deletes the branch when:
   - both required checks pass,
   - no opt-out label is set on the PR or any linked issue, and
   - every `copilot-pull-request-reviewer[bot]` inline review thread on the PR is marked Resolved (see [Parallel Reviewers](#parallel-reviewers)).

   It re-evaluates automatically on the events that change any of those conditions: `workflow_run` for `CI` and `Claude Code Review` completion, `pull_request` for label / draft / push transitions, and `pull_request_review_thread` for thread resolve/unresolve. So a green PR merges without any manual nudge once all three conditions are met — including when a maintainer's only remaining action is resolving the last Copilot thread.

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

## Parallel Reviewers

Two reviewers run on every PR and **both gate auto-merge**:

- `claude-review` — the rubric reviewer driven by `CLAUDE.md`. Auto-applies `do-not-merge` on any Blocking finding; runs as a required check.
- `copilot-pull-request-reviewer[bot]` — GitHub's built-in inline reviewer. Auto-merge counts every unresolved Copilot review thread as a block and refuses to merge until a maintainer resolves them on GitHub.

Both signals matter because they catch different things. Copilot's reviewer has flagged real defects outside the Claude rubric (e.g. PR #36's `WorkingDirectory` hardcoding mismatch with the configurable `RPI_PROJECT_DIR` — claude-review missed it cleanly). Treating either as advisory silently buries that signal at merge time.

Triage rule for the **PR author / maintainer**:

- Substantive findings (correctness, safety, spec alignment, deployment-config drift) — fold into the round-1 `@copilot` punch list alongside the Claude findings, even if Claude did not flag them. Post a supplement comment if Claude already fired without surfacing the same item. Once a fix lands, mark the Copilot thread Resolved on GitHub so auto-merge unblocks.
- Style or preference noise that you've decided not to act on — still mark the thread Resolved (with a one-line reply explaining why), since auto-merge cannot tell substantive from noise.

Implementers (including the Copilot SWE Agent) should address Copilot reviewer comments together with the Claude punch list in the same fix push, so round 2 sees a clean diff.

A maintainer override path exists: setting the `do-not-merge` label keeps merge off, and removing all Copilot threads via Resolve-with-comment is the supported way to land changes Copilot flagged but the maintainer chose not to change.

## What a Fresh-Context Coding Agent Should Do

1. Read `AGENTS.md` for project context, SDD rules, and the current milestone.
2. Read this file (`docs/agent-pr-workflow.md`) for the PR contract.
3. Read the relevant spec under `specs/` before changing behavior.
4. Pick an issue whose blockers are closed.
5. Implement the smallest change that meets the acceptance criteria.
6. Run `uv run pytest -m "not e2e and not hardware"` locally before pushing.
7. Open the PR with `Closes #N` in the body.
8. Do not tick acceptance checkboxes for yourself; the Claude reviewer will.
9. When fix commits are requested, address both the Claude punch list and any substantive `copilot-pull-request-reviewer[bot]` inline comments in the same push.
10. If the linked issue has `needs-manual-verification` or `critical`, expect the human to merge — do not retry, comment, or escalate.

## Required Status Check Names

The auto-merge workflow expects these exact names (case-sensitive):

- `pytest` — defined in `.github/workflows/ci.yml`
- `claude-review` — defined in `.github/workflows/claude-code-review.yml`

If a workflow is renamed, update `.github/workflows/auto-merge.yml` to match.
