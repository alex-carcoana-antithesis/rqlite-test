# Antithesis build for rqlite: consensus + read-consistency testing.
#
# Two SUT-adjacent images are produced from named stages:
#   * rqlite-node     — an instrumented rqlited server (Go SDK + coverage)
#   * rqlite-workload — the Python driver + test templates
#
# We deliberately build on a glibc base (debian/bookworm) rather than the
# repo's Alpine/musl Dockerfile: the Antithesis Go instrumentor and symbol
# collection are more reliable on glibc. SQLite extensions are NOT built here
# (out of scope for consensus/consistency testing), which keeps the build lean.

########################################################################
# Stage 1: instrument + compile rqlited with the Antithesis Go SDK.
########################################################################
FROM golang:1.26-bookworm AS node-builder

# C toolchain for CGO (go-sqlite3). CGO_ENABLED=1 is REQUIRED by the SDK.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc build-essential ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

ENV CGO_ENABLED=1
ENV NO_COLOR=1
ENV GOFLAGS=-buildvcs=false

WORKDIR /src
COPY . /src

# Install the Antithesis Go instrumentor at the same version as the SDK in go.mod.
RUN go install github.com/antithesishq/antithesis-sdk-go/tools/antithesis-go-instrumentor@v0.7.2

# Instrument the whole module (default mode = coverage + assertion cataloging).
# Output tree: /instrumented/{customer,symbols,notifier}.
RUN mkdir -p /instrumented \
    && "$(go env GOPATH)/bin/antithesis-go-instrumentor" -skip_test_files=true /src /instrumented

# Build rqlited from the INSTRUMENTED tree, not the original source.
WORKDIR /instrumented/customer
RUN go build -ldflags="-w -s" -o /out/rqlited ./cmd/rqlited/. \
    && go build -ldflags="-w -s" -o /out/rqlite ./cmd/rqlite/.

########################################################################
# Stage 2: rqlite node runtime image (glibc).
########################################################################
FROM debian:stable-slim AS rqlite-node

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

ENV NO_COLOR=1

COPY --from=node-builder /out/rqlited /bin/rqlited
COPY --from=node-builder /out/rqlite  /bin/rqlite
COPY docker-entrypoint.sh /bin/docker-entrypoint.sh
RUN chmod +x /bin/docker-entrypoint.sh

# Antithesis coverage symbols must be shipped in the instrumented image.
RUN mkdir -p /symbols
COPY --from=node-builder /instrumented/symbols/ /symbols/

RUN mkdir -p /rqlite/file
EXPOSE 4001 4002
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["run"]

########################################################################
# Stage 3: Python workload / driver image.
########################################################################
FROM python:3.12-slim-bookworm AS rqlite-workload

ENV NO_COLOR=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/workload

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The Antithesis Python SDK (assertions, lifecycle, random) plus an HTTP client.
RUN pip install --no-cache-dir antithesis requests

# Shared driver library (importable by every test command).
COPY antithesis/workload/ /workload/

# Assertion cataloging (Python): Antithesis scans /opt/antithesis/catalog/ for
# the modules that define assertions so they appear in the report before a run.
RUN mkdir -p /opt/antithesis/catalog \
    && cp /workload/rqlite_antithesis/properties.py /opt/antithesis/catalog/ \
    && cp /workload/rqlite_antithesis/client.py /opt/antithesis/catalog/

# Test templates: Antithesis executes commands from /opt/antithesis/test/v1/.
RUN mkdir -p /opt/antithesis/test/v1
COPY antithesis/test/v1/ /opt/antithesis/test/v1/
RUN chmod +x /opt/antithesis/test/v1/rqlite/*

# The container's main process waits for the cluster to be healthy and then
# emits setup_complete. Antithesis only starts running test commands after that.
ENTRYPOINT ["python3", "/workload/entrypoint.py"]
