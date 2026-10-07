# Image for the two controlled endpoints.
#
# One Dockerfile builds both. SERVICE selects which app module is served, so the policy
# API and the test receiver stay byte-identical apart from their entrypoint argument and
# cannot drift apart in ways that would confound the evidence.
#
#   docker build -f services/Dockerfile --build-arg SERVICE=policy_api .
#   docker build -f services/Dockerfile --build-arg SERVICE=test_receiver .

FROM python:3.12-slim

ARG SERVICE
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# A missing or misspelled SERVICE would otherwise produce an image that builds fine and
# then crashes at startup - which during a demo run looks exactly like the endpoint being
# unreachable, the one failure mode that must never be ambiguous here.
RUN test -n "${SERVICE}" || (echo "SERVICE build-arg is required (policy_api or test_receiver)" >&2; exit 1)

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32"

COPY services ./services

RUN useradd --create-home --uid 10001 svc
USER 10001

EXPOSE 8080

# SERVICE is resolved at build time into the module path, so the running container has
# no way to be pointed at a different app.
ENV SERVICE_MODULE="services.${SERVICE}.main:app"

ENTRYPOINT ["sh", "-c", "exec uvicorn \"$SERVICE_MODULE\" --host 0.0.0.0 --port \"$PORT\""]
