#!/usr/bin/env python3
"""Resolve the baseline Antithesis run_id for a PR by walking base-branch commits.

The precise commit -> run mapping lives in the GitHub Checks API: each base-branch
run records a check named `antithesis-baseline` whose `external_id` is the
Antithesis run_id. Starting at the merge-base and walking back along first-parent
history, we return the run_id of the first commit that has such a check. Not every
commit will have been tested, so the walk-back is what makes this robust.

Usage:
    resolve_baseline.py <owner/repo> <base_sha> [check_name]

Prints the run_id (or nothing if none found). Requires local git history for the
base branch and an authenticated `gh` (GITHUB_TOKEN).
"""

import subprocess
import sys

MAX_COMMITS = 50


def commits(base_sha):
    out = subprocess.run(
        ["git", "rev-list", "--first-parent", "-n", str(MAX_COMMITS), base_sha],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        return []
    return [c for c in out.stdout.split() if c]


def external_id(repo, sha, check_name):
    out = subprocess.run(
        [
            "gh",
            "api",
            "repos/{}/commits/{}/check-runs".format(repo, sha),
            "--jq",
            '.check_runs[] | select(.name=="{}") | .external_id'.format(check_name),
        ],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        line = line.strip()
        if line and line != "null":
            return line
    return None


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: resolve_baseline.py <owner/repo> <base_sha> [check_name]\n")
        return 2
    repo = sys.argv[1]
    base_sha = sys.argv[2]
    check_name = sys.argv[3] if len(sys.argv) > 3 else "antithesis-baseline"

    for sha in commits(base_sha):
        rid = external_id(repo, sha, check_name)
        if rid:
            print(rid)
            return 0
    return 0  # nothing found -> print nothing (first PR, or no baseline yet)


if __name__ == "__main__":
    sys.exit(main())
