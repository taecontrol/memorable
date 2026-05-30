FROM node:26-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        jq \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm@11.1.2

ARG AGENT_UID=1000
ARG AGENT_GID=1000

RUN groupmod -o -g $AGENT_GID node \
    && usermod -o -u $AGENT_UID -g $AGENT_GID -d /home/agent -m -l agent node \
    && mkdir -p /home/agent/.local/bin /home/agent/.local/share/opencode /home/agent/.local/share/pnpm/bin \
    && chown -R $AGENT_UID:$AGENT_GID /home/agent

ENV PNPM_HOME="/home/agent/.local/share/pnpm"
ENV PATH="/home/agent/.local/bin:${PNPM_HOME}:${PNPM_HOME}/bin:${PATH}"

USER ${AGENT_UID}:${AGENT_GID}

RUN pnpm add -g --allow-build=opencode-ai opencode-ai@latest

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /home/agent

ENTRYPOINT ["sleep", "infinity"]
