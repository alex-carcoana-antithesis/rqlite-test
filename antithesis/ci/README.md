# Antithesis CI

Runs an Antithesis test on every PR (and on pushes to `master`), diffs the
resulting **property statuses** against a baseline, has Claude summarize the
takeaways, and posts them back to the PR as a comment + a soft check.

Workflow: [`.github/workflows/antithesis.yml`](../../.github/workflows/antithesis.yml)

## How it works

```
schedule (nightly)   launch (4h)  → record run_id as a check-run, then exit
                                     (does NOT wait — runs async on Antithesis)

push → master        launch (30m) → record run_id as a check-run, then exit
                                     (external_id, keyed to the commit)

pull_request         launch (10m) → wait → resolve baseline (walk base-branch
                                            commits for the antithesis-baseline
                                            check) → diff statuses → Claude
                                            summary → PR comment + soft check
```

**Baseline mode (nightly + push) launches and records without waiting.** A 4h
nightly run must not hold a GitHub runner (hosted jobs hard-cap at 6h), and any
PR that later diffs against it runs hours or days afterward — by then the run has
finished on Antithesis. Only **PR mode** waits inline (~10-15 min) because it
needs its own result immediately.

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

- **PR runs hold a runner inline (~10–15 min).** Baseline runs (nightly/push)
  do not — they launch, record, and exit. To make PRs async too, split PR mode
  into launch (record `run_id` on a pending check) + a separate collector
  triggered when the run finishes (Antithesis webhook, or a scheduled poller /
  `workflow_dispatch`). The three scripts here are already the collector; only
  the trigger wiring changes.
- **Nightly is a 4h deep run** (`cron: "0 7 * * *"`, UTC). GitHub cron only fires
  from the **default branch** and runs the workflow file **on that branch**, so
  the nightly starts working only once this workflow is on `master`. Adjust the
  time/duration in the workflow's `schedule` block and the `schedule)` case of
  the *Determine run parameters* step.
- **Status non-determinism.** Gate softly first; consider re-running once before
  treating a flip as a regression. Only hard-gate (`conclusion: failure`) once a
  property has proven stable across runs.
- **Baseline walk-back** looks back up to 50 first-parent commits. If a PR
  branches from further back than that with no tested commit in range, it
  reports "no baseline" and just shows the current failing properties.
