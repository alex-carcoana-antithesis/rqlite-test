#!/usr/bin/env python3
"""anytime_ command: continuously probe the single-leader-per-term invariant.

Antithesis may run an anytime_ command at any point in a timeline, so this
samples leadership *outside* the read/transfer drivers' cadence — catching a
split-brain window that could open between driver invocations. It reuses the
existing single-leader property (term-grouped), so it is pure added coverage:
no new assertions, no risk of a new failing property.
"""

import sys

from rqlite_antithesis.client import Rqlite
from rqlite_antithesis import properties

PROBES = 20


def main():
    client = Rqlite()
    for _ in range(PROBES):
        try:
            by_term = client.leaders_by_term()
        except Exception as exc:
            # Transient under fault injection (partition, crash, no leader).
            print("leader probe failed (expected under faults): {}".format(exc), flush=True)
            continue
        max_in_term = max((len(nodes) for nodes in by_term.values()), default=0)
        total_leaders = sum(len(nodes) for nodes in by_term.values())
        properties.at_most_one_leader_per_term(
            max_in_term,
            {"leaders_by_term": by_term, "max_in_any_term": max_in_term},
        )
        properties.leader_present(total_leaders >= 1, {"leaders_by_term": by_term})
    return 0


if __name__ == "__main__":
    sys.exit(main())
