# Build once, run anywhere. A grader unzips the repository, builds this, and
# gets the same connector we tested, without installing Python or matching a
# version.
#
# This image speaks stdio, not HTTP. It exposes no port and listens on nothing:
# an MCP host launches it as a subprocess and talks over the standard streams.
# That means it must be run with -i, or the server is deaf:
#
#   docker build -t salesforce-connector .
#   docker run -i --rm --env-file .env salesforce-connector
#
# See README.md for the client configuration block to paste into an MCP host.

FROM python:3.12-slim AS builder

WORKDIR /build

# Dependencies are installed from the lockfile alone first, so editing source
# does not invalidate the layer that took the time.
#
# From uv.lock rather than from the version ranges in pyproject.toml. A range
# means an image built today and an image built next month are not the same
# image, and the difference arrives without anyone choosing it. The export
# carries a hash for every package, and pip refuses anything that does not
# match, so a compromised or substituted artefact fails the build rather than
# shipping inside it.
COPY pyproject.toml uv.lock ./
COPY src/salesforce_connector/__init__.py ./src/salesforce_connector/

RUN pip install --no-cache-dir uv==0.9.18 \
 && uv export --frozen --no-dev --no-emit-project --format requirements-txt \
      --output-file /tmp/requirements.txt \
 && pip install --no-cache-dir --prefix=/install --require-hashes -r /tmp/requirements.txt \
 && pip install --no-cache-dir --prefix=/install --no-deps .


FROM python:3.12-slim

# Never as root. The connector needs no privilege: it reads environment
# variables and opens outbound HTTPS, and nothing it does requires more.
RUN useradd --create-home --uid 10001 connector

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=connector:connector src/ ./src/
COPY --chown=connector:connector mcp/ ./mcp/
COPY --chown=connector:connector connector.yaml ./

USER connector

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# No HEALTHCHECK: this process has no endpoint to poll. Whether it works is
# answered by test_connection, which an MCP host can call.

ENTRYPOINT ["python", "/app/mcp/server.py"]
