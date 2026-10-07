"""Un-allowlisted test receiver.

The second controlled destination, deliberately left off the egress allowlist. Its job
is to be the witness for the negative half of the demo.

A failed outbound call on the agent side is weak evidence: an HTTP 403 from the egress
proxy looks the same to the caller as a 403 from the destination itself, and a DNS or
TLS failure is not a denial at all. What makes the denial attributable is the **absence
of a receipt here** for a run marker that the agent's own traces show it attempted. So
this service exists to log arrivals precisely and to be trusted when it logs none.

That makes two properties load-bearing:

* It accepts and acknowledges everything. It never rejects a request on its own
  judgement, because a rejection here would be indistinguishable from a platform denial
  and would quietly turn the experiment into an application-level check.
* It stores no content. Only the correlation marker, a timestamp and the byte count are
  recorded, so the receipt proves arrival without retaining a payload.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SERVICE_NAME = "test-receiver"


def _configure_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(SERVICE_NAME)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = _configure_logging()
app = FastAPI(
    title="Containment demo test receiver",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _run_marker(request: Request) -> str:
    return request.headers.get("x-demo-run-id") or request.query_params.get("demo_run_id") or ""


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness only, and deliberately not a receipt.

    Probe traffic must never appear in the arrival log, or 'no receipt' would stop
    meaning 'nothing arrived'.
    """
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/ingest")
async def ingest(request: Request) -> JSONResponse:
    """Acknowledge an arrival without retaining what arrived.

    The body is read only to measure it, then discarded. Nothing derived from the
    payload is logged or returned.
    """
    body = await request.body()
    receipt: dict[str, Any] = {
        "service": SERVICE_NAME,
        "event": "receipt",
        "received_at": datetime.now(UTC).isoformat(),
        "demo_run_id": _run_marker(request),
        "content_length_bytes": len(body),
    }
    logger.info(json.dumps(receipt))

    return JSONResponse(
        {
            "received": True,
            "demo_run_id": receipt["demo_run_id"],
            "received_at": receipt["received_at"],
        },
        status_code=202,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))  # noqa: S104


if __name__ == "__main__":
    main()
