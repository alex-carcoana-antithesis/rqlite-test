#!/usr/bin/env python3
"""first_ command: create the schema and seed the ledger + register.

Runs once, after setup_complete, before the parallel drivers. Idempotent: safe
if Antithesis re-runs it. The seeded total (NUM_ACCOUNTS * SEED_BALANCE) is the
constant the ledger-conservation property checks against.
"""

import sys
import time

from rqlite_antithesis.client import (
    NUM_ACCOUNTS,
    REGISTER_KEY,
    SEED_BALANCE,
    Rqlite,
    first_row,
    result_error,
)


def setup(client):
    # Schema. Multiple statements in one request = one Raft entry.
    ddl = [
        ["CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, balance INTEGER NOT NULL)"],
        ["CREATE TABLE IF NOT EXISTS registers (k INTEGER PRIMARY KEY, version INTEGER NOT NULL)"],
    ]
    client.execute(ddl, transaction=True)

    # Seed accounts (INSERT OR IGNORE keeps this idempotent).
    seed = [
        ["INSERT OR IGNORE INTO accounts (id, balance) VALUES (?, ?)", i, SEED_BALANCE]
        for i in range(NUM_ACCOUNTS)
    ]
    seed.append(["INSERT OR IGNORE INTO registers (k, version) VALUES (?, ?)", REGISTER_KEY, 0])
    client.execute(seed, transaction=True)


def verify(client):
    resp = client.query("SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM accounts", level="strong")
    row = first_row(resp)
    if row is None:
        return False
    count, total = row[0], row[1]
    print("seeded accounts={} total={}".format(count, total), flush=True)
    return count == NUM_ACCOUNTS and total == NUM_ACCOUNTS * SEED_BALANCE


def main():
    client = Rqlite()
    # Retry through transient bring-up errors; this must land before drivers run.
    for attempt in range(60):
        try:
            setup(client)
            if verify(client):
                print("setup complete on attempt {}".format(attempt), flush=True)
                return 0
        except Exception as exc:
            print("setup attempt {} failed: {}".format(attempt, exc), flush=True)
        time.sleep(2.0)
    print("setup did not converge", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
