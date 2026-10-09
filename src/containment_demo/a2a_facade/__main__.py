"""Entrypoint: ``python -m containment_demo.a2a_facade``. Composes the Foundry target."""

from __future__ import annotations

import logging

import uvicorn

from containment_demo.a2a_facade.core import FacadeSettings
from containment_demo.a2a_facade.server import build_app
from containment_demo.a2a_facade.target import ResponsesTarget


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = FacadeSettings()  # type: ignore[call-arg]  # fields come from the environment
    target = ResponsesTarget(
        endpoint=settings.endpoint,
        agent_name=settings.a2a_target_agent_name,
        timeout_seconds=settings.a2a_timeout_seconds,
    )
    # Bound to all interfaces inside the pod only; the Service is ClusterIP.
    uvicorn.run(build_app(settings, target), host="0.0.0.0", port=settings.a2a_listen_port)  # noqa: S104


if __name__ == "__main__":
    main()
