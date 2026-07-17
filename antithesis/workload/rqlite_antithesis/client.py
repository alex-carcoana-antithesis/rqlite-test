"""Minimal, fault-tolerant HTTP client for rqlite.

The workload runs under fault injection: partitions, crashes, and leader churn
are expected. Every method surfaces transient failures as exceptions that the
callers are expected to swallow and retry, rather than treating them as bugs.
"""

import json
import os
import random

import requests

# Ledger model constants. INITIAL_TOTAL is the invariant the conservation
# property checks against.
NUM_ACCOUNTS = 10
SEED_BALANCE = 100
INITIAL_TOTAL = NUM_ACCOUNTS * SEED_BALANCE

# Single monotonic register used by the versioned-register read checks.
REGISTER_KEY = 0


def configured_nodes():
    raw = os.environ.get(
        "RQLITE_NODES",
        "rqlite-node-1:4001,rqlite-node-2:4001,rqlite-node-3:4001",
    )
    return [n.strip() for n in raw.split(",") if n.strip()]


class Rqlite:
    def __init__(self, nodes=None, timeout=5.0):
        self.nodes = nodes or configured_nodes()
        self.timeout = timeout
        self.session = requests.Session()

    def _url(self, node, path):
        return "http://{}{}".format(node, path)

    def pick_node(self):
        return random.choice(self.nodes)

    def execute(self, statements, node=None, queue=False, wait=False, transaction=False):
        """POST /db/execute. `statements` is a list of ["SQL", param, ...] lists."""
        node = node or self.pick_node()
        params = []
        if queue:
            params.append("queue")
        if wait:
            params.append("wait")
        if transaction:
            params.append("transaction")
        qs = ("?" + "&".join(params)) if params else ""
        r = self.session.post(
            self._url(node, "/db/execute" + qs),
            data=json.dumps(statements),
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
            allow_redirects=True,
        )
        r.raise_for_status()
        return r.json()

    def query(self, statement, level="weak", node=None, freshness=None):
        """POST /db/query at the given consistency level."""
        node = node or self.pick_node()
        params = ["level=" + level]
        if freshness is not None:
            params.append("freshness=" + str(freshness))
        qs = "?" + "&".join(params)
        r = self.session.post(
            self._url(node, "/db/query" + qs),
            data=json.dumps([statement]),
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
            allow_redirects=True,
        )
        r.raise_for_status()
        return r.json()

    def status(self, node):
        r = self.session.get(self._url(node, "/status"), timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def ready(self, node):
        try:
            r = self.session.get(self._url(node, "/readyz"), timeout=self.timeout)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def raft_state(self, node):
        """Return this node's Raft state string ("Leader"/"Follower"/...) or None."""
        try:
            st = self.status(node)
            return st.get("store", {}).get("raft", {}).get("state")
        except (requests.RequestException, ValueError):
            return None

    def applied_index(self, node):
        # fsm_index is the index of the last Raft entry applied to SQLite, so it
        # is the correct key for comparing DB *content* across replicas. (The
        # raft sub-map's own indices track the log, not the FSM/SQLite state.)
        try:
            st = self.status(node)
            val = st.get("store", {}).get("fsm_index")
            return int(val) if val is not None else None
        except (requests.RequestException, ValueError, TypeError):
            return None

    def leaders(self):
        """Nodes currently reporting themselves as Raft leader."""
        return [n for n in self.nodes if self.raft_state(n) == "Leader"]


def first_row(resp):
    """Extract the first result row values from a query response, or None."""
    results = resp.get("results", [])
    if not results:
        return None
    res = results[0]
    if res.get("error"):
        return None
    values = res.get("values")
    if not values:
        return None
    return values[0]


def result_error(resp):
    """Return the error string from the first execute/query result, if any."""
    results = resp.get("results", [])
    if not results:
        return None
    return results[0].get("error")
