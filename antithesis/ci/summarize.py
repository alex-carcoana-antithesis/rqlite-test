#!/usr/bin/env python3
"""Turn an Antithesis status diff into a PR comment with AI takeaways.

Reads diff.json + diff.md (produced by diff_runs.py), asks Claude to summarize
the takeaways, and writes summary.md (the PR comment body). Degrades gracefully:
if the Anthropic SDK or an API key is unavailable, it emits the diff table alone
so the workflow still posts something useful.

Model defaults to claude-opus-4-8 (override with ANTHROPIC_MODEL). Auth is the
standard SDK resolution (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / profile).
"""

import json
import os
import sys

MARKER = "<!-- antithesis-ci -->"
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

PROMPT = """You are summarizing an Antithesis test run for a GitHub PR comment.

Important context about how Antithesis works:
- It explores many different fault orderings (crashes, partitions, clock skew),
  so a property's pass/fail status is NOT fully deterministic across runs. A
  property can flip Passing -> Failing purely from search luck, not from a code
  regression. Treat Passing -> Failing as "worth investigating", never as a
  confirmed regression, and say so plainly.
- A property that is failing but was absent from the baseline is usually a
  newly-added check, not a regression.
- The data-integrity properties (ledger conservation, no negative balance,
  replica agreement) are the ones that would actually break on a real bug. If a
  leader/election property flipped but those all still pass, lean toward
  "measurement artifact, not a real defect".

Write a concise summary (2-4 sentences plus, if useful, a short bullet list).
Lead with the single most important thing a reviewer should look at. If there
are no regressions, say so in one line. Do not restate the full table; it is
shown below your summary. Here is the status diff JSON:

{diff_json}
"""


def ai_takeaways(diff):
    try:
        from anthropic import Anthropic
    except Exception:
        return None
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None

    client = Anthropic()
    prompt = PROMPT.format(diff_json=json.dumps(diff, indent=2))

    def call(with_effort):
        kwargs = dict(
            model=MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
        if with_effort:
            kwargs["output_config"] = {"effort": "medium"}
        return client.messages.create(**kwargs)

    try:
        try:
            resp = call(with_effort=True)
        except TypeError:
            # Older SDK without output_config support — retry without it.
            resp = call(with_effort=False)
    except Exception as exc:
        return "_AI summary unavailable: {}_".format(exc)

    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip() or None


def main():
    with open("diff.json") as f:
        diff = json.load(f)
    diff_md = ""
    if os.path.exists("diff.md"):
        with open("diff.md") as f:
            diff_md = f.read()

    takeaways = ai_takeaways(diff)

    lines = [MARKER, "## 🧪 Antithesis test results", ""]
    if takeaways:
        lines += ["### Takeaways", "", takeaways, ""]
    if diff["has_regressions"]:
        lines += [
            "> ⚠️ One or more properties went Passing → Failing. This is a **soft** "
            "signal — re-run before treating it as a regression (status is not "
            "deterministic across fault orderings).",
            "",
        ]
    lines += ["### Property status diff", "", diff_md]

    with open("summary.md", "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
