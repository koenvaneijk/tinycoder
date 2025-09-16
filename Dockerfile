# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Minimal deps: git for repo operations, ca-certs for TLS
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy project and install
WORKDIR /opt/tinycoder
COPY . .
RUN pip install --no-cache-dir --upgrade pip &amp;&amp; \
    pip install --no-cache-dir .

# Default working directory is where the host project will be mounted
WORKDIR /workspace

# tinycoder is a CLI installed by the package
ENTRYPOINT ["tinycoder"]
CMD []