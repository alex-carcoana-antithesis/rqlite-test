"""Antithesis assertions for the rqlite consensus/consistency workload.

This module is copied into /opt/antithesis/catalog/ so the Antithesis Python
assertion cataloger can statically discover every assertion before a run.
Each assertion message is a unique, inline string literal (a cataloging
requirement) and maps 1:1 to a property in
antithesis/scratchbook/property-catalog.md.
"""

from antithesis.assertions import always, sometimes


# --- Safety (Always) ------------------------------------------------------

def ledger_conserved(total, details):
    # property: ledger-conservation
    always(
        total == details.get("initial_total"),
        "ledger total is conserved across all accounts",
        details,
    )


def no_negative_balance(min_balance, details):
    # property: no-negative-balance
    always(
        min_balance is None or min_balance >= 0,
        "no account balance is ever negative",
        details,
    )


def replicas_agree(agree, details):
    # property: no-replica-divergence (also covers nondeterministic-rewrite-identical)
    always(
        agree,
        "replicas at the same applied index agree on database contents",
        details,
    )


def linearizable_read_monotonic(ok, details):
    # property: linearizable-read-not-stale
    always(
        ok,
        "a linearizable read never observes a stale (decreasing) register version",
        details,
    )


def strong_read_monotonic(ok, details):
    # property: strong-read-linearized
    always(
        ok,
        "a strong read never observes a stale (decreasing) register version",
        details,
    )


def at_most_one_leader(leader_count, details):
    # property: single-leader
    always(
        leader_count <= 1,
        "at most one node is the Raft leader at any time",
        details,
    )


# --- Liveness / progress (Sometimes) --------------------------------------

def some_write_acknowledged(ok, details):
    # property: progress-under-fault
    sometimes(
        ok,
        "a write is acknowledged by the cluster under load",
        details,
    )


def leader_present(ok, details):
    # property: leader-elected-after-crash
    sometimes(
        ok,
        "the cluster has an elected leader",
        details,
    )


def queued_wait_committed(ok, details):
    # property: write-eventually-commits
    sometimes(
        ok,
        "a queued write with wait=true is acknowledged",
        details,
    )
