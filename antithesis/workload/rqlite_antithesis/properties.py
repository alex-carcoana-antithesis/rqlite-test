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


def at_most_one_leader_per_term(max_leaders_in_any_term, details):
    # property: single-leader
    # Raft's real guarantee is one leader PER TERM, not one node in the Leader
    # state at a single wall-clock instant. A deposed leader keeps reporting
    # Leader (in its older term) until a higher-term RPC reaches it, so counting
    # raw Leader states across terms produces false positives during election
    # churn (see run 4b16...-58-3). Two nodes can never both win the same term,
    # so grouping observed leaders by term and asserting <=1 per term is exactly
    # the invariant, and it is immune to non-atomic polling across nodes.
    always(
        max_leaders_in_any_term <= 1,
        "at most one node is the Raft leader in any single term",
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


# --- Durability & ordering (Always) ---------------------------------------

def acked_write_durable(ok, details):
    # property: acked-write-survives-failover
    # A write the cluster acknowledged as committed must remain present on a
    # subsequent strong (log-serialized) read, even across faults/failover that
    # happen in between. Raft's durability guarantee: a committed entry survives
    # any minority failure.
    always(
        ok,
        "an acknowledged write is present on a subsequent strong read",
        details,
    )


def queue_preserves_fifo_order(ok, details):
    # property: queue-fifo-order
    # Writes submitted through ?queue by one client to one node must commit in
    # submission order. Rows carry an increasing seq; read back in commit order
    # (ORDER BY the auto-assigned id), the seq values must be non-decreasing.
    always(
        ok,
        "queued writes from one client commit in submission order",
        details,
    )
