FROM python:3.12-slim

ARG NODE_VERSION=25.2.1

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        libatomic1 \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) node_arch="x64" ;; \
        arm64) node_arch="arm64" ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    node_dist="https://nodejs.org/dist/v${NODE_VERSION}"; \
    node_file="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"; \
    test -n "$node_file"; \
    curl -fsSLO "$node_dist/$node_file"; \
    curl -fsSL "$node_dist/SHASUMS256.txt" | grep -F " $node_file" | sha256sum -c -; \
    tar -xJf "$node_file" -C /usr/local --strip-components=1; \
    rm "$node_file"; \
    node --version; \
    npm --version

RUN npm install -g @openai/codex codex-sdk

RUN mkdir -p /root/.codex

WORKDIR /workspace
