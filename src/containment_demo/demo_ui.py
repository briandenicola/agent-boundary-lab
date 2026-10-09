"""Demo test UI: a run button per agent, driving ``containment_demo.invoke``.

This exists so a presenter does not need ``kubectl exec``. It is not a third business
tool and not a second invocation path.

* **One invocation path.** Every run goes through :func:`containment_demo.invoke.invoke_agent`.
  Nothing here builds a request, parses a response, or classifies a failure.
* **No pass.** The determination shown is :data:`containment_demo.invoke.DETERMINATION`,
  always. A classified tool failure is rendered as a failure kind, never as "blocked".
  Platform evidence is NOT joined here (GATE 0 in issue #1: no telemetry field yet joins
  to ``demo_run_id``), and the page says so rather than leaving a gap that looks like a
  pass.
* **No free-text destination.** The only input is a slot, ``audit`` or ``enforced``,
  mapped to an agent name that came from startup configuration. The endpoint is built
  from configured account and project names. The route takes no URL, host or name.
* **Authenticated.** Every route except ``/healthz`` needs the configured token, as a
  bearer token or as the HTTP Basic password (a browser cannot send a bearer header).
  State-changing requests also need a custom header, which a cross-site form cannot set.
* **Nothing sensitive is shown or logged.** No prompt, response text, payload or
  authorization header. ``invoke`` already keeps only a digest of the response text.
* **Local and hosted runs are labelled apart** by a required ``run_label``.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import logging
import re
import uuid
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from containment_demo import invoke

logger = logging.getLogger(__name__)

#: The only slots the UI can run. A slot is not a name; it indexes the configured pair.
SLOTS = ("audit", "enforced")

#: Required on POST. A browser cannot attach it to a cross-site form submission.
CSRF_HEADER = "x-demo-ui"

_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class UiSettings(BaseSettings):
    """Validated startup configuration. Same ``DEMO_`` prefix as the other settings."""

    model_config = SettingsConfigDict(env_prefix="DEMO_", extra="ignore")

    foundry_account_name: str
    foundry_project_name: str
    agent_name_audit: str
    agent_name_enforced: str
    ui_token: SecretStr = Field(description="Shared secret for the UI. At least 16 characters.")
    run_label: Literal["hosted", "local"] = Field(
        description="Required. Local runs are functional tests, not containment evidence."
    )
    ui_timeout_seconds: float = Field(default=120.0, gt=0, le=300)

    @field_validator("foundry_account_name", "foundry_project_name")
    @classmethod
    def _dns_label(cls, v: str) -> str:
        if not _NAME.match(v):
            raise ValueError("must be a DNS label: alphanumerics and inner hyphens only")
        return v

    @field_validator("agent_name_audit", "agent_name_enforced")
    @classmethod
    def _agent_name(cls, v: str) -> str:
        if not _NAME.match(v):
            raise ValueError("invalid agent name")
        return v

    @field_validator("ui_token")
    @classmethod
    def _token_strength(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 16:
            raise ValueError("DEMO_UI_TOKEN must be at least 16 characters")
        return v

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self.foundry_account_name}.services.ai.azure.com"
            f"/api/projects/{self.foundry_project_name}"
        )

    def agent_for(self, slot: str) -> str:
        if slot == "audit":
            return self.agent_name_audit
        if slot == "enforced":
            return self.agent_name_enforced
        raise KeyError(slot)


def _authorised(request: Request, settings: UiSettings) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if not presented:
        return False
    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(presented, validate=True).decode("utf-8")
        except ValueError:
            return False
        presented = decoded.partition(":")[2]
    elif scheme.lower() != "bearer":
        return False
    return bool(presented) and hmac.compare_digest(presented, settings.ui_token.get_secret_value())


def _unauthorised() -> Response:
    return Response(
        "unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="containment-demo-ui"'},
    )


def build_view(result: invoke.InvocationResult, *, slot: str, run_label: str) -> dict[str, Any]:
    """The JSON the page renders. Built from the invoke record; nothing is re-derived."""
    record = result.as_dict()
    return {
        "slot": slot,
        "run_label": run_label,
        "agent_name": record["agent_name"],
        # UI-only id: generated here, appears in no platform row. Do not join on it.
        "ui_run_id": record["demo_run_id"],
        # The id(s) the tools reported using; this is what platform egress rows join on.
        # Empty when no tool record carried one. Never filled from the UI id.
        "tool_run_ids": sorted(
            {t["tool_run_id"] for t in record["results"] if t.get("tool_run_id")}
        ),
        "determination": invoke.DETERMINATION,
        "platform_evidence": (
            "not read by this UI. Observed once (one audit and one enforced run, "
            "telemetry-map 0.12): the tool run id joins egress decision rows to receipts; "
            "OperationId does not. Join them yourself; this page does not."
        ),
        "our_call": {
            "ok": record["transport_ok"],
            "error_category": record["transport_error_category"],
            "detail": record["transport_detail"],
            "response_status": record["response_status"],
        },
        "tools": record["results"],
    }


def create_app(settings: UiSettings, *, invoker: Any = None) -> Starlette:
    """``invoker`` is injectable so tests never touch the SDK or the network."""
    run = invoker or invoke.invoke_agent
    locks = {slot: asyncio.Lock() for slot in SLOTS}

    async def page(request: Request) -> Response:
        if not _authorised(request, settings):
            return _unauthorised()
        return HTMLResponse(_PAGE.replace("__RUN_LABEL__", settings.run_label))

    async def run_slot(request: Request) -> Response:
        if not _authorised(request, settings):
            return _unauthorised()
        if request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"error": "missing X-Demo-UI header"}, status_code=403)
        slot = request.path_params["slot"]
        if slot not in SLOTS:
            return JSONResponse({"error": "unknown slot", "allowed": list(SLOTS)}, status_code=404)
        lock = locks[slot]
        if lock.locked():
            return JSONResponse({"error": "a run for this agent is already in progress"}, 409)
        async with lock:
            run_id = f"ui-{uuid.uuid4().hex[:12]}"
            logger.info("ui run starting slot=%s demo_run_id=%s", slot, run_id)
            result = await asyncio.to_thread(
                run,
                endpoint=settings.endpoint,
                agent_name=settings.agent_for(slot),
                demo_run_id=run_id,
                timeout_seconds=settings.ui_timeout_seconds,
            )
        logger.info(
            "ui run finished slot=%s demo_run_id=%s transport_ok=%s",
            slot,
            run_id,
            result.transport_ok,
        )
        return JSONResponse(build_view(result, slot=slot, run_label=settings.run_label))

    async def healthz(_: Request) -> Response:
        return Response("ok")

    return Starlette(
        routes=[
            Route("/", page, methods=["GET"]),
            Route("/run/{slot}", run_slot, methods=["POST"]),
            Route("/healthz", healthz, methods=["GET"]),
        ]
    )


# Rendered with textContent only, never innerHTML: values come from a model-driven path.
_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Containment demo</title>
<style>
body{font-family:sans-serif;margin:2rem;max-width:70rem}
.cols{display:flex;gap:1.5rem}.col{flex:1;border:1px solid #888;padding:1rem}
.banner{padding:.5rem;background:#eee;border:1px solid #888;margin-bottom:1rem}
.ours{background:#fff3cd;padding:.5rem}table{border-collapse:collapse;width:100%}
td,th{border:1px solid #aaa;padding:.25rem;text-align:left}
</style></head><body>
<h1>Containment demo</h1>
<div class="banner">Run label: <b id="label">__RUN_LABEL__</b>. Every result is
<b>inconclusive-without-platform-evidence</b>. This page does not read platform evidence; a
failed call is a classified failure, not proof of a block.</div>
<div class="cols">
<div class="col" id="audit"><h2>audit</h2><button data-slot="audit">Run audit</button>
<div class="out"></div></div>
<div class="col" id="enforced"><h2>enforced</h2><button data-slot="enforced">Run enforced</button>
<div class="out"></div></div>
</div>
<script>
function add(parent, tag, text, cls){
  const e=document.createElement(tag); e.textContent=text; if(cls) e.className=cls;
  parent.appendChild(e); return e;}
async function runSlot(slot){
  const out=document.querySelector('#'+slot+' .out'); out.replaceChildren();
  add(out,'p','running...');
  let r, d;
  try{ r=await fetch('/run/'+slot,{method:'POST',headers:{'X-Demo-UI':'1'}}); d=await r.json();}
  catch(e){ out.replaceChildren(); add(out,'p','OUR request to this UI failed.','ours'); return;}
  out.replaceChildren();
  if(!r.ok){ add(out,'p','UI error: '+(d.error||r.status),'ours'); return;}
  add(out,'p','run: '+d.run_label+' / '+d.agent_name);
  add(out,'p','tool run id (joins platform egress rows): '+
    (d.tool_run_ids.length?d.tool_run_ids.join(', '):'not available in the invoke result'));
  add(out,'p','UI-only id (joins nothing): '+d.ui_run_id);
  add(out,'p','determination: '+d.determination);
  add(out,'p','platform evidence: '+d.platform_evidence);
  if(!d.our_call.ok){
    add(out,'p','OUR CALL to the platform failed ('+d.our_call.error_category+'): '+
      d.our_call.detail+' This says nothing about egress.','ours');}
  const t=add(out,'table',''); const h=add(t,'tr','');
  ['tool','attempted','succeeded','failure kind','HTTP','host'].forEach(x=>add(h,'th',x));
  d.tools.forEach(x=>{const row=add(t,'tr','');
    [x.tool_name,x.attempted,x.succeeded,x.error_category,x.http_status,x.destination_host]
      .forEach(v=>add(row,'td',v===null?'-':String(v)));});
}
document.querySelectorAll('button[data-slot]').forEach(b=>
  b.addEventListener('click',()=>runSlot(b.dataset.slot)));
</script></body></html>
"""


def main() -> None:  # pragma: no cover - process entrypoint
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = UiSettings()  # type: ignore[call-arg]
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8080, log_level="warning")  # noqa: S104


if __name__ == "__main__":  # pragma: no cover
    main()
