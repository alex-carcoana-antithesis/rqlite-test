#!/usr/bin/env python3
"""Diff Antithesis property *statuses* between a baseline run and the current run.

Status-only by design: we compare each property's pass/fail status (not counts,
not examples), which is exactly what gates a PR and keeps the diff a trivial set
comparison. Two nodes of nuance the summarizer is told to respect:

  * a property can flip Passing->Failing purely from search luck (different fault
    orderings each run), so a regression here means "investigate", not "bug";
  * an ABSENT->Failing property is usually a newly-added check, not a regression.

Usage:
    diff_runs.py <baseline_run_id|-> <current_run_id> [--out-dir DIR]

Writes <out-dir>/diff.json and <out-dir>/diff.md, and prints diff.md to stdout.
Pass "-" (or an empty string) as the baseline to emit the current run's statuses
with no diff (first PR, or no baseline recorded yet). Exit code is always 0; read
`has_regressions` from diff.json to decide gating.
"""

import argparse
import json
import os
import subprocess
import sys


def fetch_statuses(run_id):
    """Return {property_name: status_string} for a run via snouty.

    `snouty runs --json properties` emits line-delimited JSON, one property per
    line, each carrying at least `name` and `status`.
    """
    out = subprocess.run(
        ["snouty", "runs", "--json", "properties", run_id],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    statuses = {}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        name = obj.get("name")
        if name is None:
            continue
        statuses[name] = obj.get("status", "Unknown")
    return statuses


def is_failing(status):
    return (status or "").strip().lower() == "failing"


def classify(baseline, current):
    """Bucket every property by how its status changed from baseline to current."""
    names = sorted(set(baseline) | set(current))
    buckets = {
        "regressions": [],     # was Passing, now Failing  -> investigate
        "new_failing": [],     # absent in baseline, now Failing -> likely a new check
        "fixed": [],           # was Failing, now Passing
        "still_failing": [],   # Failing in both
        "new_passing": [],     # absent in baseline, now Passing
        "removed": [],         # present in baseline, absent now
        "unchanged": [],       # Passing in both
    }
    for n in names:
        b = baseline.get(n)          # None => absent in baseline
        c = current.get(n)           # None => absent in current
        bf, cf = is_failing(b), is_failing(c)
        row = {"name": n, "baseline": b, "current": c}
        if c is None:
            buckets["removed"].append(row)
        elif b is None:
            buckets["new_failing" if cf else "new_passing"].append(row)
        elif bf and not cf:
            buckets["fixed"].append(row)
        elif not bf and cf:
            buckets["regressions"].append(row)
        elif bf and cf:
            buckets["still_failing"].append(row)
        else:
            buckets["unchanged"].append(row)
    return buckets


def render_md(diff):
    b = diff["buckets"]
    lines = []
    lines.append(
        "**Baseline:** `{}`  •  **This run:** `{}`".format(
            diff.get("baseline_run_id") or "(none)", diff["current_run_id"]
        )
    )
    lines.append("")
    counts = {k: len(v) for k, v in b.items()}
    lines.append(
        "| Regressions | New failing | Fixed | Still failing | Unchanged |"
    )
    lines.append("|---|---|---|---|---|")
    lines.append(
        "| {regressions} | {new_failing} | {fixed} | {still_failing} | {unchanged} |".format(
            **counts
        )
    )
    lines.append("")

    def section(title, key, emoji):
        rows = b[key]
        if not rows:
            return
        lines.append("### {} {} ({})".format(emoji, title, len(rows)))
        for r in rows:
            lines.append(
                "- `{}` — {} → **{}**".format(
                    r["name"], r["baseline"] or "absent", r["current"] or "absent"
                )
            )
        lines.append("")

    if diff.get("baseline_run_id"):
        section("Regressions (Passing → Failing)", "regressions", "🔴")
        section("New failing properties", "new_failing", "🟠")
        section("Fixed (Failing → Passing)", "fixed", "🟢")
        section("Still failing", "still_failing", "⚪")
    else:
        # No baseline: just list the current failing properties, if any.
        failing = [r for r in b["new_failing"]]
        if failing:
            lines.append("_No baseline run found — showing current failing properties._")
            lines.append("")
            section("Failing", "new_failing", "🔴")
        else:
            lines.append("_No baseline run found, and no failing properties in this run._")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_run_id")
    ap.add_argument("current_run_id")
    ap.add_argument("--out-dir", default=".")
    args = ap.parse_args()

    baseline_id = args.baseline_run_id if args.baseline_run_id not in ("", "-") else None
    baseline = fetch_statuses(baseline_id) if baseline_id else {}
    current = fetch_statuses(args.current_run_id)
    buckets = classify(baseline, current)

    diff = {
        "baseline_run_id": baseline_id,
        "current_run_id": args.current_run_id,
        "has_regressions": len(buckets["regressions"]) > 0,
        "counts": {k: len(v) for k, v in buckets.items()},
        "buckets": buckets,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "diff.json"), "w") as f:
        json.dump(diff, f, indent=2)
    md = render_md(diff)
    with open(os.path.join(args.out_dir, "diff.md"), "w") as f:
        f.write(md)
    sys.stdout.write(md)

    # Expose gating signal to the workflow.
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write("has_regressions={}\n".format(str(diff["has_regressions"]).lower()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
