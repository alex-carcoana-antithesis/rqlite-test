#!/usr/bin/env python3
"""parallel_driver: ledger transfers + monotonic register bumps.

Each invocation performs a bounded batch of write operations, then exits so
Antithesis can interleave and branch. Writes are sent to random nodes (exercising
leader forwarding) and mix standard, queued, and bulk paths.

The transfer is a SINGLE UPDATE statement, so it is atomic in SQLite and lands as
one Raft entry: money is only moved if the source can afford it, which preserves
both the conserved-sum invariant and the no-negative-balance invariant without
any cross-statement coordination.
"""

import sys

from antithesis.random import get_random, random_choice

from rqlite_antithesis.client import NUM_ACCOUNTS, REGISTER_KEY, Rqlite, result_error
from rqlite_antithesis import properties

OPS_PER_INVOCATION = 40

# Atomic, affordability-gated transfer. If the source cannot afford `amt`, the
# WHERE subquery is false for both rows and nothing changes.
TRANSFER_SQL = (
    "UPDATE accounts SET balance = balance + "
    "CASE id WHEN ? THEN ? WHEN ? THEN ? END "
    "WHERE id IN (?, ?) "
    "AND (SELECT balance FROM accounts WHERE id = ?) >= ?"
)

BUMP_SQL = "UPDATE registers SET version = version + 1 WHERE k = ?"


def rand_int(n):
    return get_random() % n


def distinct_pair():
    """A distinct (src, dst) account pair. Self-transfers must never be issued:
    the CASE expression would debit without crediting and destroy money."""
    src = rand_int(NUM_ACCOUNTS)
    dst = (src + 1 + rand_int(NUM_ACCOUNTS - 1)) % NUM_ACCOUNTS
    return src, dst


def transfer_stmt(src, dst, amt):
    assert src != dst, "self-transfer would break conservation"
    return [TRANSFER_SQL, src, -amt, dst, amt, src, dst, src, amt]


def main():
    client = Rqlite()
    acked = False

    for _ in range(OPS_PER_INVOCATION):
        src, dst = distinct_pair()
        amt = 1 + rand_int(20)

        mode = random_choice(["standard", "queued", "bulk"])
        try:
            if mode == "standard":
                resp = client.execute([transfer_stmt(src, dst, amt)])
            elif mode == "queued":
                # Queued write with wait=true: returns only once committed.
                resp = client.execute([transfer_stmt(src, dst, amt)], queue=True, wait=True)
                if result_error(resp) is None:
                    properties.queued_wait_committed(True, {"src": src, "dst": dst, "amt": amt})
            else:
                # Bulk: several transfers + a register bump in one Raft entry.
                stmts = []
                for _ in range(3):
                    bsrc, bdst = distinct_pair()
                    stmts.append(transfer_stmt(bsrc, bdst, 1 + rand_int(5)))
                stmts.append([BUMP_SQL, REGISTER_KEY])
                resp = client.execute(stmts, transaction=True)

            if result_error(resp) is None:
                acked = True
        except Exception as exc:
            # Transient under fault injection (partition, crash, no leader). Keep going.
            print("transfer op failed (expected under faults): {}".format(exc), flush=True)

        # Bump the monotonic register on its own path too, sometimes queued.
        try:
            client.execute([[BUMP_SQL, REGISTER_KEY]], queue=(rand_int(2) == 0))
            acked = True
        except Exception:
            pass

    # Liveness: at least one write should be acknowledged across the run.
    properties.some_write_acknowledged(acked, {"acked": acked})
    return 0


if __name__ == "__main__":
    sys.exit(main())
