# Antithesis CI

Runs an Antithesis test on every PR (and on pushes to `master`), diffs the
resulting **property statuses** against a baseline, has Claude summarize the
takeaways, and posts them back to the PR as a comment + a soft check.

Workflow: [`.github/workflows/antithesis.yml`](../../.github/workflows/antithesis.yml)

## How it works

```
push → master        launch (30m) → wait → record run_id as a check-run
                                            (external_id, keyed to the commit)

pull_request         launch (10m) → wait → resolve baseline (walk base-branch
                                            commits for the antithesis-baseline
                                            check) → diff statuses → Claude
                                            summary → PR comment + soft check
```

- **Status-only diff.** We compare each property's `Passing`/`Failing` status,
  not counts or examples. A regression = a property that was `Passing` on the
  baseline and is `Failing` now.
- **Baseline selection uses the Checks API.** Each `master` run stores its
  Antithesis `run_id` in an `antithesis-baseline` check-run's `external_id`,
  keyed to the commit. A PR resolves its baseline by walking back from the
  merge-base until it finds a commit that has one. This pins the diff to the
  branch point rather than "latest master".
- **Soft gate.** The result check is posted with conclusion `neutral`, so it
  never blocks merge. Antithesis explores different fault orderings each run, so
  a single `Passing → Failing` flip can be search luck, not a code regression —
  the comment says as much. Flip the conclusion to `failure` (in the *Post
  result check* step) once your properties are proven low-noise.

## Scripts

| Script | Role |
|---|---|
| `resolve_baseline.py <owner/repo> <base_sha> [check_name]` | Walk base-branch commits, return the baseline `run_id` from the `antithesis-baseline` check. |
| `diff_runs.py <baseline\|-> <current> [--out-dir DIR]` | Fetch both runs' property statuses via `snouty`, classify transitions, write `diff.json` + `diff.md`. |
| `summarize.py` | Read `diff.json`/`diff.md`, ask Claude for takeaways, write `summary.md` (the comment body). Degrades to the table alone if no `ANTHROPIC_API_KEY`. |

All three are runnable locally (with `snouty`/`gh` authenticated) for debugging.

## Required configuration

**Secrets** (Settings → Secrets and variables → Actions):

| Secret | What |
|---|---|
| `ANTITHESIS_API_KEY` | Antithesis API key for the **rose-cheetah** tenant. |
| `ANTITHESIS_REGISTRY_KEY` | GCP service-account JSON for `us-central1-docker.pkg.dev` (the `rose-pcheetah-storage` SA — it has push on `rose-pcheetah-repository`). Used for `docker login -u _json_key`. |
| `ANTHROPIC_API_KEY` | For the Claude summary. If absent, the comment posts the diff table with no AI takeaways. |

**Variables** (optional — defaults are baked in):

| Variable | Default |
|---|---|
| `ANTITHESIS_TENANT` | `rose-cheetah` |
| `ANTITHESIS_REPOSITORY` | `us-central1-docker.pkg.dev/molten-verve-216720/rose-pcheetah-repository` |

**`snouty` install.** The workflow installs `snouty` from source as a placeholder
(`cargo install --git …`). Replace that step with your org's canonical installer
(a vendored released binary is much faster) — see the `TODO` in the workflow.

## Known limitations / upgrade paths

- **Runner is held for the whole run.** v1 waits inline (~10–15 min on PRs). The
  clean fix is a two-phase design: one workflow launches + records the `run_id`
  on the PR (a pending check), and a separate trigger — an Antithesis webhook if
  available, or a scheduled poller / `workflow_dispatch` — collects results when
  the run finishes and updates the check/comment. The three scripts here are
  already the collector; only the trigger wiring changes.
- **Status non-determinism.** Gate softly first; consider re-running once before
  treating a flip as a regression. Only hard-gate (`conclusion: failure`) once a
  property has proven stable across runs.
- **Baseline walk-back** looks back up to 50 first-parent commits. If a PR
  branches from further back than that with no tested commit in range, it
  reports "no baseline" and just shows the current failing properties.
