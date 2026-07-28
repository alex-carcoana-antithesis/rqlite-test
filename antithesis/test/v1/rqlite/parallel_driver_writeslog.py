#!/usr/bin/env python3
"""parallel_driver: durability + queued-write FIFO ordering.

Two safety checks against the append-only `writes_log` table:

  * durability (acked-write-survives-failover): a write the cluster acknowledged
    as committed is present on a subsequent strong read, even if a fault lands in
    between. We insert one row, capture its acked auto-id, then strong-read it.

  * queue-fifo-order: writes submitted through ?queue by one client to one node
    commit in submission order. We queue a run of rows with increasing `seq` to a
    single node, then read the batch back in commit order (ORDER BY id); the seq
    values must come out non-decreasing.

Each invocation performs a bounded batch of both, then exits so Antithesis can
interleave and branch. All cluster errors are transient under fault injection and
are swallowed — the checks only fire on successful observations.
"""

import sys

from antithesis.random import get_random

from rqlite_antithesis.client import Rqlite, first_row, last_insert_id, result_error
from rqlite_antithesis import properties

OPS_PER_INVOCATION = 8
FIFO_RUN = 8

INSERT_SQL = "INSERT INTO writes_log (batch, seq) VALUES (?, ?)"


def rand_int(n):
    return get_random() % n


def durability_op(client):
    """Insert one row, and if it is acknowledged, assert it survives to a
    subsequent strong read."""
    rid = None
    try:
        resp = client.execute([[INSERT_SQL, 1 + rand_int(2**31), 0]])
        if result_error(resp) is None:
            rid = last_insert_id(resp)
    except Exception as exc:
        print("durability insert failed (expected under faults): {}".format(exc), flush=True)
        return
    if rid is None:
        return
    try:
        resp = client.query(
            "SELECT COUNT(*) FROM writes_log WHERE id = {}".format(rid), level="strong"
        )
        row = first_row(resp)
        if row is not None:
            properties.acked_write_durable(row[0] == 1, {"id": rid, "count": row[0]})
    except Exception as exc:
        print("durability read failed (expected under faults): {}".format(exc), flush=True)


def fifo_op(client):
    """Queue a run of increasing-seq rows to ONE node, then verify they committed
    in submission order."""
    batch = 1 + rand_int(2**62)
    node = client.nodes[0]
    submitted = 0
    for seq in range(FIFO_RUN):
        try:
            client.execute([[INSERT_SQL, batch, seq]], node=node, queue=True)
            submitted += 1
        except Exception:
            # Queued (wait=false) writes may be dropped under faults; that only
            # reduces how many rows appear, it never reorders them.
            pass
    if submitted == 0:
        return

    # Strong read the batch in commit order. Only assert once at least two rows
    # are visible; a subset of an ordered sequence is still ordered, so FIFO
    # implies the seqs come out non-decreasing regardless of how many landed.
    for _ in range(10):
        try:
            resp = client.query(
                "SELECT seq FROM writes_log WHERE batch = {} ORDER BY id".format(batch),
                level="strong",
            )
        except Exception:
            continue
        results = resp.get("results", [])
        if not results or results[0].get("error"):
            continue
        vals = [r[0] for r in (results[0].get("values") or [])]
        if len(vals) >= 2:
            properties.queue_preserves_fifo_order(
                vals == sorted(vals), {"batch": batch, "seqs": vals, "submitted": submitted}
            )
            return


def main():
    client = Rqlite()
    for _ in range(OPS_PER_INVOCATION):
        durability_op(client)
        fifo_op(client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
