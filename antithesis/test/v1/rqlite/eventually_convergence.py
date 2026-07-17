#!/usr/bin/env python3
"""eventually_ command: replicas converge to identical state.

For each node we sample its Raft applied_index immediately before and after a
local (level=none) read of the full database contents. We only keep samples where
the index was stable across the read, so the content provably corresponds to that
exact applied index. Any two nodes at the SAME applied index must then have
byte-identical contents — otherwise the replicas have diverged (which would also
catch non-deterministic RANDOM()/datetime() rewriting differing across nodes).

Also re-checks ledger conservation on a strong read as a final safety net.
"""

import hashlib
import sys

from rqlite_antithesis.client import INITIAL_TOTAL, Rqlite, first_row
from rqlite_antithesis import properties

CONTENT_SQL = (
    "SELECT group_concat(id || ':' || balance, ',') FROM "
    "(SELECT id, balance FROM accounts ORDER BY id)"
)


def content_hash(client, node):
    resp = client.query(CONTENT_SQL, level="none", node=node)
    row = first_row(resp)
    if row is None:
        return None
    payload = "" if row[0] is None else str(row[0])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_sample(client, node):
    """Return (applied_index, content_hash) only if the index was stable across the read."""
    before = client.applied_index(node)
    if before is None:
        return None
    h = content_hash(client, node)
    after = client.applied_index(node)
    if h is None or after != before:
        return None
    return before, h


def main():
    client = Rqlite()

    # Group content hashes by the applied index they correspond to.
    by_index = {}
    for node in client.nodes:
        try:
            sample = stable_sample(client, node)
        except Exception as exc:
            print("sample failed for {} (expected under faults): {}".format(node, exc), flush=True)
            continue
        if sample is None:
            continue
        idx, h = sample
        by_index.setdefault(idx, {})[node] = h

    # Any index observed by >=2 nodes must show identical content.
    for idx, node_hashes in by_index.items():
        if len(node_hashes) < 2:
            continue
        hashes = set(node_hashes.values())
        properties.replicas_agree(
            len(hashes) == 1,
            {"applied_index": idx, "node_hashes": node_hashes},
        )

    # Final conservation check on a strong (log-serialized) read.
    try:
        resp = client.query("SELECT COALESCE(SUM(balance), 0), MIN(balance) FROM accounts", level="strong")
        row = first_row(resp)
        if row is not None:
            properties.ledger_conserved(row[0], {"total": row[0], "initial_total": INITIAL_TOTAL, "level": "strong"})
            properties.no_negative_balance(row[1], {"min_balance": row[1], "level": "strong"})
    except Exception as exc:
        print("final conservation read failed: {}".format(exc), flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
