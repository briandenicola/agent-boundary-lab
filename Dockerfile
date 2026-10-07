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
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# uv is used so the dependency overrides in pyproject.toml are honoured. google-adk pins
# opentelemetry-api <=1.42.1 while azure-ai-agentserver-core pins >=1.43.0, and no
# released pair is co-installable; pip would simply fail here. See docs/compatibility.md
# "Blocker 0" for why the override is safe and what it risks.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

COPY pyproject.toml README.md* ./
COPY docs/README.md docs/README.md
COPY src ./src

RUN uv pip install --system --no-cache .

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
