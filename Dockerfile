# Hosted agent image.
#
# The Foundry hosted-agent runtime contract, verified against the installed server
# package rather than assumed: the container listens on port 8088 over plain HTTP, the
# platform terminates TLS in front of it, GET /readiness is served by the server package
# itself, and SIGTERM is the shutdown signal.
#
# The same image digest is deployed to both the Audit and the Enforced agent versions.
# That is the core of the experiment: if the image differed between runs, the policy
# would no longer be the only variable and the result would prove nothing.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/agent-venv/bin:$PATH"

WORKDIR /app

# uv is used so the dependency overrides in pyproject.toml are honoured. google-adk pins
# opentelemetry-api <=1.42.1 while azure-ai-agentserver-core pins >=1.43.0, and no
# released pair is co-installable; pip would simply fail here. See docs/compatibility.md
# "Blocker 0" for why the override is safe and what it risks.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

COPY pyproject.toml README.md* ./
COPY uv.lock ./
COPY docs/README.md docs/README.md
COPY src ./src
COPY policies/acs ./policies/acs
COPY scripts/verify_demo.py scripts/verify_governance.py ./scripts/

RUN UV_PROJECT_ENVIRONMENT=/opt/agent-venv uv sync --no-cache --locked --no-dev \
        --extra governance --no-build-package agent-control-specification --no-editable \
    && python -c "from mcp.types import CacheableResult; import litellm.responses.mcp.chat_completions_handler"

ADD https://github.com/open-policy-agent/opa/releases/download/v1.9.0/opa_linux_amd64_static /tmp/opa
RUN echo "66fa66f3b730b2fb086003863428b382b2898d343adb4b5dfab5598b4d739eed  /tmp/opa" \
        | sha256sum --check --status \
    && install -m 755 /tmp/opa /usr/local/bin/opa \
    && /usr/local/bin/opa check --strict /app/policies/acs/bundle \
    && rm /tmp/opa

# The agent-version deployer lives in its own interpreter, in this same image.
#
# Parker's init container runs the same digest-pinned image as the agent, so the deploy
# module has to be here. Keep deployment-only packages out of the agent interpreter.
# Both profiles share uv.lock; separate venvs do not isolate dependency resolution.
# The agent now explicitly uses the locked OpenAI 3 client for refreshable v1 Entra auth.
# One image, one digest, two installed profiles. The
# init container overrides the entrypoint to use this interpreter:
#   command: ["/opt/deploy-venv/bin/python", "-m", "containment_demo.deploy"]
# The A2A spike (containment_demo.a2a_spike) runs in this same venv, exec'd into the
# harness pod. The a2a extra installs alongside azure-ai-projects here, without adding
# these deployment-only packages to the agent's interpreter.
RUN UV_PROJECT_ENVIRONMENT=/opt/deploy-venv uv sync --no-cache --locked --no-dev \
        --extra deploy --extra a2a --extra verify --no-editable \
    && /opt/deploy-venv/bin/python -c "import azure.ai.projects; import azure.monitor.query; import containment_demo.governance.hosted"

# Run unprivileged. The container has no need to write anywhere outside /tmp.
RUN useradd --create-home --uid 10001 agent
USER 10001

# Plain HTTP. TLS is terminated by the platform in front of this port.
EXPOSE 8088

# The egress proxy intercepts TLS and injects its CA into the sandbox trust bundle at
# runtime. That CA is infrastructure-specific and rotates roughly monthly, so it is read
# from the environment on every HTTP client build and is deliberately never baked in,
# pinned or copied into this image.

ENTRYPOINT ["python", "-m", "containment_demo.protocol_adapter"]
