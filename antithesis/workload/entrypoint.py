#!/usr/bin/env python3
"""Workload container entrypoint.

Runs as the container's main process. Waits until the rqlite cluster is healthy
and has elected a leader, then emits the Antithesis `setup_complete` signal.
Antithesis does not run any test commands (first_/parallel_driver_/...) until it
observes that signal, so this is the single gate between bring-up and testing.

After signalling, the process blocks forever to keep the container (and its
/opt/antithesis/test templates) alive for command execution.
"""

import sys
import time

from antithesis.lifecycle import setup_complete

from rqlite_antithesis.client import Rqlite


def wait_for_cluster(client, deadline):
    """Return True once every node is ready and exactly-or-at-least one leader exists."""
    while time.time() < deadline:
        try:
            ready = all(client.ready(n) for n in client.nodes)
            leaders = client.leaders()
            if ready and len(leaders) >= 1:
                print("cluster ready; leader(s): {}".format(leaders), flush=True)
                return True
        except Exception as exc:  # bring-up is racy; keep polling
            print("waiting for cluster: {}".format(exc), flush=True)
        time.sleep(1.0)
    return False


def main():
    client = Rqlite()
    print("workload entrypoint: waiting for {} nodes".format(len(client.nodes)), flush=True)

    # Generous bring-up budget: instrumented nodes under emulation start slowly.
    ok = wait_for_cluster(client, deadline=time.time() + 180)
    if not ok:
        # Signal anyway so the run can proceed and surface the problem in triage,
        # rather than hanging forever waiting for setup_complete.
        print("cluster did not become healthy in time; signalling anyway", flush=True)

    setup_complete({"nodes": client.nodes, "healthy": ok})
    print("emitted setup_complete", flush=True)

    # Keep the container alive for Antithesis to execute test commands inside it.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
