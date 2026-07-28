#!/usr/bin/env python3
"""parallel_driver: read-side correctness checks.

Each invocation issues a bounded batch of reads and evaluates the safety
invariants an external observer can see:

  * ledger conservation and no-negative-balance hold at every consistency level
    (every applied Raft entry preserves the sum, so any consistent snapshot must
    too);
  * a linearizable or strong read never observes the monotonic register version
    going backwards within this reader's session (stale-read detection);
  * at most one node reports itself leader (no split brain).

Weak/none reads may legitimately lag, so monotonicity is only asserted for the
linearizable and strong levels.
"""

import sys

from antithesis.random import get_random, random_choice

from rqlite_antithesis.client import INITIAL_TOTAL, REGISTER_KEY, Rqlite, first_row
from rqlite_antithesis import properties

READS_PER_INVOCATION = 60


def read_ledger(client, level):
    resp = client.query(
        "SELECT COALESCE(SUM(balance), 0), MIN(balance) FROM accounts", level=level
    )
    row = first_row(resp)
    if row is None:
        return None, None
    return row[0], row[1]


def read_version(client, level):
    resp = client.query(
        "SELECT version FROM registers WHERE k = {}".format(REGISTER_KEY), level=level
    )
    row = first_row(resp)
    if row is None:
        return None
    return row[0]


def check_single_leader(client):
    try:
        by_term = client.leaders_by_term()
    except Exception:
        return
    # The real Raft invariant is <=1 leader PER TERM. Grouping by term makes the
    # check immune to the cross-term overlap seen during election churn under
    # network faults (an old leader still claiming Leader in a stale term).
    max_in_term = max((len(nodes) for nodes in by_term.values()), default=0)
    total_leaders = sum(len(nodes) for nodes in by_term.values())
    properties.at_most_one_leader_per_term(
        max_in_term,
        {"leaders_by_term": by_term, "max_in_any_term": max_in_term},
    )
    properties.leader_present(total_leaders >= 1, {"leaders_by_term": by_term})


def main():
    client = Rqlite()
    # Highest register version this reader has observed, per consistency level.
    seen = {"linearizable": -1, "strong": -1}

    for i in range(READS_PER_INVOCATION):
        level = random_choice(["none", "weak", "linearizable", "strong"])

        # Ledger invariants hold at every level.
        try:
            total, min_bal = read_ledger(client, level)
            if total is not None:
                properties.ledger_conserved(total, {"total": total, "initial_total": INITIAL_TOTAL, "level": level})
                properties.no_negative_balance(min_bal, {"min_balance": min_bal, "level": level})
        except Exception as exc:
            print("ledger read failed (expected under faults): {}".format(exc), flush=True)

        # Register monotonicity: only meaningful for linearizable/strong.
        try:
            ver = read_version(client, level)
            if ver is not None and level in seen:
                ok = ver >= seen[level]
                details = {"version": ver, "previously_seen": seen[level], "level": level}
                if level == "linearizable":
                    properties.linearizable_read_monotonic(ok, details)
                else:
                    properties.strong_read_monotonic(ok, details)
                if ver > seen[level]:
                    seen[level] = ver
        except Exception as exc:
            print("register read failed (expected under faults): {}".format(exc), flush=True)

        if i % 10 == 0:
            check_single_leader(client)

    return 0


if __name__ == "__main__":
    sys.exit(main())
