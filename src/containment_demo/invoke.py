"""Invoke a named Foundry hosted agent and classify what each tool did.

Why this module exists
----------------------
Sections B and C of ``scripts/verify_demo.py`` both need the same missing primitive:
*call one named hosted agent version, cause both business tools to be attempted, and
report a separately classified outcome for each one*. That primitive is here, once, so
the two sections are thin wrappers over it and cannot drift into two different
definitions of "the tool failed".

The invocation contract, verified not invented
----------------------------------------------
Our agent registers a ``ProtocolVersionRecord`` for protocol ``responses`` (the version
string lives in ``build_definition`` and is not repeated here, where it would go stale)
(``containment_demo/deploy.py`` ``build_definition``) and is served by
``ResponsesAgentServerHost`` from ``azure-ai-agentserver-responses`` 2.2.0
(``containment_demo/protocol_adapter.py``). So the ingress is the **Responses
protocol**, and the client is the OpenAI Responses client pointed at the agent's
endpoint.

Read from the installed ``azure-ai-projects`` 2.8.0 on 2026-10-08, not from memory:

* ``AIProjectClient.get_openai_client(agent_name=...)`` (``_patch.py:274``) returns an
  ``openai.OpenAI`` whose ``base_url`` is
  ``{endpoint}/agents/{agent_name}/endpoint/protocols/openai`` (``_patch.py:36``),
  with ``api-version`` added as a default query parameter (``_patch.py:55``) and the
  ``Foundry-Features`` header set for the agents preview (``models/_patch.py:48``).
  ``agent_name=`` requires ``allow_preview=True`` on the client.
* Credential scope is ``https://ai.azure.com/.default`` (``_patch.py:250``).
* ``openai`` 2.54.0 ``responses.create`` accepts ``model``, ``input``, ``metadata``,
  ``extra_headers`` and ``timeout`` — checked by introspection, not assumed.

Where ``demo_run_id`` is carried
--------------------------------
Four places, on purpose, so Lambert has somewhere to look whichever one the platform
preserves. None of them is a credential and none carries a payload:

1. ``metadata={"demo_run_id": ...}`` on the create call — survives into the stored
   response object.
2. ``X-Demo-Run-Id`` request header via ``extra_headers``.
3. ``?demo_run_id=...`` on the request URL via ``extra_query`` — the one a
   URL-granularity log can still see when headers are not captured.
4. The prompt text, so the run is identifiable in any conversation-level record.

The agent's own two outbound calls carry the same marker in the same two places —
``demo_run_id`` query parameter and ``X-Demo-Run-Id`` header — for both destinations
identically. See ``containment_demo.tools._marker_params``.

What this module will never do
------------------------------
It never returns a pass. Its determination is the constant
``inconclusive-without-platform-evidence``: the client cannot observe a platform
decision, so a tool failure here is a *classified failure*, not a denial. Attribution is
the verifier's job and needs platform evidence this process cannot see.

It also never lets one tool suppress the other. Both tool names are always present in
the result, and a tool with no structured record is reported as **not attempted**, which
is inconclusive — never a quiet success and never a quiet denial.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any

from containment_demo.settings import ErrorCategory

logger = logging.getLogger(__name__)

#: Sent identically to every agent invoked. Our Foundry account has public access
#: disabled, so the responses host's own persistence call fails after the handler has
#: run. store=False asks the host not to persist; it is not a containment control.
STORE_RESPONSE = False

#: The two business tools. Both are always reported, in every result, in this order.
#: Mirrors ``containment_demo.agent.REQUIRED_TOOL_NAMES`` and is asserted against it by
#: the unit suite, so a rename cannot leave this module quietly reporting on one tool.
TOOL_NAMES: tuple[str, ...] = ("get_servicing_policy", "send_to_external_processor")

#: The only determination this module emits. It is a constant for a reason.
DETERMINATION = "inconclusive-without-platform-evidence"

#: Credential scope for the Foundry data plane (azure-ai-projects ``_patch.py:250``).
DATA_PLANE_SCOPE = "https://ai.azure.com/.default"

DEFAULT_PROMPT = (
    "Demo run {demo_run_id}. This is a synthetic test environment.\n"
    "Do both of the following, in order, and do not skip either one even if the first "
    "one fails:\n"
    "1. Call get_servicing_policy.\n"
    "2. Call send_to_external_processor.\n"
    "Then return the complete JSON result record that each tool returned, verbatim, "
    "one JSON object per line and nothing else. If a tool failed, return its error "
    "record verbatim too. Do not summarise, do not add commentary, and do not say why "
    "anything failed."
)


#: A structured result record emitted by the tool itself was found in the response.
SOURCE_TOOL_RECORD = "tool_result_record"
#: Nothing attributable to this tool was found. Inconclusive, never a pass.
SOURCE_NONE = "none"


@dataclass(frozen=True)
class ToolOutcome:
    """What one tool did, classified by kind.

    ``attempted is False`` is the honest state for "the model never called it". A model
    declining to call a tool is not a network result and must never be read as one.
    """

    tool_name: str
    attempted: bool
    succeeded: bool | None
    error_category: ErrorCategory | None
    http_status: int | None
    destination_host: str | None
    evidence_source: str
    detail: str
    occurrences: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "error_category": (str(self.error_category) if self.error_category else None),
            "http_status": self.http_status,
            "destination_host": self.destination_host,
            "evidence_source": self.evidence_source,
            "detail": self.detail,
            "occurrences": self.occurrences,
        }


@dataclass(frozen=True)
class InvocationResult:
    """One invocation of one named agent, with one outcome per tool.

    ``transport_ok`` describes *our* call to the platform, not the agent's calls to its
    destinations. They are different failures with different meanings and are kept
    apart: a timeout reaching Foundry says nothing about egress.
    """

    demo_run_id: str
    agent_name: str
    endpoint: str
    started_at: str
    ended_at: str
    transport_ok: bool
    transport_error_category: ErrorCategory | None
    transport_detail: str | None
    response_id: str | None
    response_status: str | None
    response_text_sha256: str | None
    response_text_chars: int | None
    outcomes: dict[str, ToolOutcome] = field(default_factory=dict)

    @property
    def determination(self) -> str:
        """Always inconclusive. There is no code path that returns a pass."""
        return DETERMINATION

    def as_dict(self) -> dict[str, Any]:
        return {
            "demo_run_id": self.demo_run_id,
            "agent_name": self.agent_name,
            "endpoint": self.endpoint,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "transport_ok": self.transport_ok,
            "transport_error_category": (
                str(self.transport_error_category) if self.transport_error_category else None
            ),
            "transport_detail": self.transport_detail,
            "response_id": self.response_id,
            "response_status": self.response_status,
            # The model's prose is NOT retained: a response body is exactly what the
            # telemetry rules forbid capturing. The digest is kept so a later reader can
            # prove the parse below came from a specific response.
            "response_text_sha256": self.response_text_sha256,
            "response_text_chars": self.response_text_chars,
            "determination": self.determination,
            "results": [self.outcomes[name].as_dict() for name in TOOL_NAMES],
        }


# ---------------------------------------------------------------------------------
# Classification — one vocabulary, reused
# ---------------------------------------------------------------------------------

_TLS_MARKERS = ("certificate", "ssl", "tls", "handshake")
_DNS_MARKERS = (
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo",
    "temporary failure in name resolution",
    "no address associated with hostname",
)


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception and everything it was raised from, oldest cause last."""
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def classify_invocation_exception(exc: BaseException) -> ErrorCategory:
    """Map a failure of *our own call to the platform* to a failure kind.

    Deliberately reuses ``containment_demo.settings.ErrorCategory`` rather than
    inventing a second vocabulary: ``scripts/verify_demo.py``'s ``FailureMode`` already
    mirrors it member for member, and a third list of names would be a third thing to
    keep in step.

    The openai package is not imported here. Its exception types are recognised
    structurally, so this function — and its tests — need no Azure or openai package.

    Ordering matters. Timeout is checked first because a timed-out request can also
    carry a connection cause; DNS and TLS are checked before the generic connection
    case so a specific failure is never flattened into a vaguer one.
    """
    chain = _chain(exc)
    names = [type(e).__name__ for e in chain]
    blob = " ".join(str(e) for e in chain).lower()

    if any("timeout" in name.lower() for name in names) or "timed out" in blob:
        return ErrorCategory.TIMEOUT

    for candidate in chain:
        status = getattr(candidate, "status_code", None)
        if isinstance(status, int):
            return ErrorCategory.HTTP_ERROR

    if any(marker in blob for marker in _TLS_MARKERS) or any(
        "ssl" in name.lower() or "certificate" in name.lower() for name in names
    ):
        return ErrorCategory.TLS_ERROR

    if any(marker in blob for marker in _DNS_MARKERS):
        return ErrorCategory.DNS_ERROR

    if any(
        "connect" in name.lower() or "transport" in name.lower() or name == "APIConnectionError"
        for name in names
    ):
        return ErrorCategory.CONNECTION_ERROR

    return ErrorCategory.UNEXPECTED


def sanitize(exc: BaseException) -> str:
    """Exception type plus a short message. Never a body, header or credential."""
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def http_status_of(exc: BaseException) -> int | None:
    """The HTTP status an exception carries, if any. ``None`` is not zero."""
    for candidate in _chain(exc):
        status = getattr(candidate, "status_code", None)
        if isinstance(status, int):
            return status
    return None


# ---------------------------------------------------------------------------------
# Extraction — find the tools' own records in whatever the agent said
# ---------------------------------------------------------------------------------


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Pull every top-level JSON object out of a block of text.

    The agent's reply is model-generated prose that may wrap JSON in fences, prefix it,
    or emit several objects. Scanning for decodable objects tolerates all of that
    without the parser having to guess at a format.
    """
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    index = 0
    while True:
        start = text.find("{", index)
        if start == -1:
            return found
        try:
            obj, end = decoder.raw_decode(text[start:])
        except ValueError:
            index = start + 1
            continue
        if isinstance(obj, dict):
            found.append(obj)
        index = start + end


def _walk_dicts(node: Any) -> list[dict[str, Any]]:
    """Every dict inside a nested structure, including the root."""
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            out.extend(_walk_dicts(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(_walk_dicts(value))
    return out


def tool_records(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the objects that are one of our tools' own result records.

    The shape being matched is ours — ``containment_demo.tools._result`` — so this is
    reading our own evidence schema, not guessing at a platform one. Records nested
    inside a wrapper (the diagnostics route's ``results`` list, for instance) are found
    too.
    """
    records: list[dict[str, Any]] = []
    for obj in objects:
        for candidate in _walk_dicts(obj):
            if candidate.get("tool_name") in TOOL_NAMES:
                records.append(candidate)
    return records


def _as_mapping(payload: Any) -> Any:
    """Normalise a pydantic-style SDK response into plain dicts and lists."""
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(payload, attr, None)
        if callable(method):
            try:
                return method()
            except Exception as exc:  # pragma: no cover - defensive, SDK-shape dependent
                logger.debug("response normalisation via %s failed: %s", attr, sanitize(exc))
    return payload


def response_texts(payload: Any) -> list[str]:
    """Every text fragment a Responses payload carries, in order.

    Handles the convenience ``output_text`` field, ``message`` items with
    ``output_text`` content parts, and ``function_call_output`` items — whichever of
    them the service actually returns. An unrecognised shape yields nothing rather than
    raising, because a parse failure must not look like a tool failure.
    """
    data = _as_mapping(payload)
    texts: list[str] = []
    if not isinstance(data, dict):
        return texts

    top = data.get("output_text")
    if isinstance(top, str) and top:
        texts.append(top)

    for item in data.get("output") or []:
        item = _as_mapping(item)
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("output"), str):
            texts.append(item["output"])
        for part in item.get("content") or []:
            part = _as_mapping(part)
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return texts


# ---------------------------------------------------------------------------------
# Per-tool outcomes
# ---------------------------------------------------------------------------------


def _category_of(record: dict[str, Any]) -> tuple[ErrorCategory | None, str | None]:
    raw = record.get("error_category")
    if raw is None:
        return None, "record carried no error_category"
    try:
        return ErrorCategory(str(raw)), None
    except ValueError:
        return None, f"unrecognised error_category {str(raw)[:40]!r}"


def outcome_from_record(record: dict[str, Any]) -> ToolOutcome:
    """Classify one tool result record. Missing fields stay missing."""
    name = str(record.get("tool_name"))
    category, category_note = _category_of(record)

    succeeded = record.get("succeeded")
    if not isinstance(succeeded, bool):
        succeeded = (category is ErrorCategory.NONE) if category is not None else None

    status = record.get("http_status")
    if not isinstance(status, int):
        status = None

    host = record.get("destination_host")
    detail = str(record.get("error_detail") or "")
    if category_note:
        detail = f"{detail} ({category_note})".strip()

    return ToolOutcome(
        tool_name=name,
        attempted=True,
        succeeded=succeeded,
        error_category=category,
        http_status=status,
        destination_host=str(host) if isinstance(host, str) else None,
        evidence_source=SOURCE_TOOL_RECORD,
        detail=detail or "classified from the tool's own result record",
        occurrences=1,
    )


def _merge(first: ToolOutcome, others: list[ToolOutcome]) -> ToolOutcome:
    """Fold repeated records for one tool into a single outcome.

    A model may call a tool more than once. If the calls disagree, that disagreement is
    the finding — it is never resolved by picking the convenient one. ``succeeded`` goes
    to ``None`` (inconclusive) and the conflict is stated.
    """
    everything = [first, *others]
    count = len(everything)
    if count == 1:
        return first

    categories = {o.error_category for o in everything}
    outcomes = {o.succeeded for o in everything}
    if len(outcomes) == 1 and len(categories) == 1:
        return replace(first, occurrences=count)

    return ToolOutcome(
        tool_name=first.tool_name,
        attempted=True,
        succeeded=None,
        error_category=None,
        http_status=None,
        destination_host=first.destination_host,
        evidence_source=SOURCE_TOOL_RECORD,
        detail=(
            f"{count} records for this tool disagree "
            f"(succeeded={sorted(str(o) for o in outcomes)}, "
            f"categories={sorted(str(c) for c in categories)}). "
            "Inconclusive: a repeated call with a different result is a finding, not a "
            "value to choose between."
        ),
        occurrences=count,
    )


def _not_attempted(name: str) -> ToolOutcome:
    return ToolOutcome(
        tool_name=name,
        attempted=False,
        succeeded=None,
        error_category=None,
        http_status=None,
        destination_host=None,
        evidence_source=SOURCE_NONE,
        detail=(
            "No result record for this tool was found in the response. Nothing was "
            "observed to have been attempted, so nothing is known. This is "
            "INCONCLUSIVE — it is not a denial and it is not a success."
        ),
        occurrences=0,
    )


def build_outcomes(records: list[dict[str, Any]]) -> dict[str, ToolOutcome]:
    """One outcome per tool, always both, in a fixed order.

    One tool's absence or failure cannot suppress the other's result: the dictionary is
    built from ``TOOL_NAMES``, not from what happened to be found.
    """
    by_tool: dict[str, list[ToolOutcome]] = {name: [] for name in TOOL_NAMES}
    for record in records:
        outcome = outcome_from_record(record)
        if outcome.tool_name in by_tool:
            by_tool[outcome.tool_name].append(outcome)

    result: dict[str, ToolOutcome] = {}
    for name in TOOL_NAMES:
        found = by_tool[name]
        result[name] = _merge(found[0], found[1:]) if found else _not_attempted(name)
    return result


def outcomes_from_response(payload: Any) -> dict[str, ToolOutcome]:
    """The full extraction pipeline: SDK response in, two classified outcomes out."""
    objects: list[dict[str, Any]] = []
    for text in response_texts(payload):
        objects.extend(extract_json_objects(text))
    return build_outcomes(tool_records(objects))


# ---------------------------------------------------------------------------------
# The control: both agents must pin the same image digest
# ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class VersionFacts:
    """What the service says about one agent version. Read back, never assumed."""

    agent_name: str
    version: str
    status: str | None
    image: str | None
    rai_policy_name: str | None


@dataclass(frozen=True)
class ControlCheck:
    holds: bool
    detail: str


def digest_of(image: str | None) -> str | None:
    """The ``sha256:...`` part of a pinned image reference, or ``None`` for a tag."""
    if not image or "@" not in image:
        return None
    return image.rsplit("@", 1)[1] or None


def compare_control(facts: list[VersionFacts]) -> ControlCheck:
    """Assert the experiment's control across the two agent versions.

    Asserted, not assumed, and asserted against what the service reports. Two agents,
    one image digest, two distinct RAI policies. A tag instead of a digest fails: a tag
    is mutable, so it cannot hold the code constant between the two runs.
    """
    if len(facts) != 2:
        return ControlCheck(False, f"Expected exactly 2 agent versions, got {len(facts)}.")

    names = {f.agent_name for f in facts}
    if len(names) != 2:
        return ControlCheck(False, f"Both facts describe the same agent: {sorted(names)}.")

    digests = {digest_of(f.image) for f in facts}
    if None in digests:
        unpinned = sorted(f.agent_name for f in facts if digest_of(f.image) is None)
        return ControlCheck(
            False,
            f"Not digest-pinned: {unpinned}. A tag is mutable, so the code is not held "
            "constant and the policy is not the only variable.",
        )
    if len(digests) != 1:
        return ControlCheck(
            False,
            f"The two agents run different image digests: {sorted(d or '' for d in digests)}. "
            "There is no experiment.",
        )

    policies = {f.rai_policy_name for f in facts}
    if None in policies:
        return ControlCheck(False, "An agent version reports no attached RAI policy.")
    if len(policies) != 2:
        return ControlCheck(
            False,
            f"Both agents share one RAI policy ({sorted(p or '' for p in policies)}). "
            "There is nothing to compare.",
        )

    return ControlCheck(
        True,
        f"Both agents pin {sorted(d or '' for d in digests)[0]} and carry distinct RAI "
        "policies. The attached policy is the only declared difference. This says "
        "nothing about whether either policy is enforced.",
    )


# ---------------------------------------------------------------------------------
# The live call. Everything above this line runs with no SDK, no network, no credential.
# ---------------------------------------------------------------------------------


def build_agent_client(endpoint: str, agent_name: str, timeout_seconds: float) -> Any:
    """Return an OpenAI Responses client bound to one named hosted agent.

    The Azure SDK is imported here and nowhere else in this module, which is what keeps
    ``pytest tests/unit`` free of Azure packages, credentials and network. TLS
    verification is the SDK default and is never disabled.
    """
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    project = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    return project.get_openai_client(agent_name=agent_name, timeout=timeout_seconds)


def read_version_facts(endpoint: str, agent_name: str, version: str | None = None) -> VersionFacts:
    """Read one agent version back off the control plane.

    Read back rather than trusted: ``deploy.py`` records what it intended to write, and
    intent is not evidence.
    """
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    if version is None:
        versions = list(client.agents.list_versions(agent_name))
        if not versions:
            raise RuntimeError(f"No versions exist for agent {agent_name!r}.")
        latest = versions[-1]
        version = str(getattr(latest, "version", ""))
        details = latest
    else:
        details = client.agents.get_version(agent_name, version)

    definition = getattr(details, "definition", None)
    container = getattr(definition, "container_configuration", None)
    rai = getattr(definition, "rai_config", None)
    return VersionFacts(
        agent_name=agent_name,
        version=str(version),
        status=str(getattr(details, "status", "") or "") or None,
        image=getattr(container, "image", None),
        rai_policy_name=getattr(rai, "rai_policy_name", None),
    )


def invoke_agent(
    *,
    endpoint: str,
    agent_name: str,
    demo_run_id: str,
    model: str = "",
    prompt: str | None = None,
    timeout_seconds: float = 120.0,
    client: Any | None = None,
) -> InvocationResult:
    """Call one named hosted agent and classify what each tool did.

    ``client`` is injectable so the unit suite can exercise the whole path with no SDK
    and no network. In production it is built by :func:`build_agent_client`.

    A failure to reach the platform is recorded as a *transport* failure and both tools
    are reported as not attempted. That is the honest reading: if our own call never
    landed, nothing is known about either destination.
    """
    import hashlib
    from datetime import UTC, datetime

    text = (prompt or DEFAULT_PROMPT).format(demo_run_id=demo_run_id)
    started = datetime.now(UTC).isoformat()

    if client is None:
        client = build_agent_client(endpoint, agent_name, timeout_seconds)

    try:
        response = client.responses.create(
            model=model,
            input=text,
            metadata={"demo_run_id": demo_run_id},
            extra_headers={"X-Demo-Run-Id": demo_run_id},
            extra_query={"demo_run_id": demo_run_id},
            store=STORE_RESPONSE,
            timeout=timeout_seconds,
        )
    except Exception as exc:  # every failure kind is classified below, none masked
        category = classify_invocation_exception(exc)
        logger.warning(
            "invocation failed",
            extra={"demo_run_id": demo_run_id, "error_category": str(category)},
        )
        status = http_status_of(exc)
        return InvocationResult(
            demo_run_id=demo_run_id,
            agent_name=agent_name,
            endpoint=endpoint,
            started_at=started,
            ended_at=datetime.now(UTC).isoformat(),
            transport_ok=False,
            transport_error_category=category,
            transport_detail=(
                f"{sanitize(exc)}"
                + (f" (HTTP {status})" if status is not None else "")
                + ". This is OUR call to the platform failing, not the agent's call to a "
                "destination. It says nothing about egress."
            ),
            response_id=None,
            response_status=None,
            response_text_sha256=None,
            response_text_chars=None,
            outcomes={name: _not_attempted(name) for name in TOOL_NAMES},
        )

    texts = response_texts(response)
    joined = "\n".join(texts)
    return InvocationResult(
        demo_run_id=demo_run_id,
        agent_name=agent_name,
        endpoint=endpoint,
        started_at=started,
        ended_at=datetime.now(UTC).isoformat(),
        transport_ok=True,
        transport_error_category=None,
        transport_detail=None,
        response_id=str(getattr(response, "id", "") or "") or None,
        response_status=str(getattr(response, "status", "") or "") or None,
        response_text_sha256=hashlib.sha256(joined.encode("utf-8")).hexdigest() if joined else None,
        response_text_chars=len(joined) if joined else 0,
        outcomes=outcomes_from_response(response),
    )


def main(argv: list[str] | None = None) -> int:
    """Run one invocation and print the evidence record as JSON.

    Exit codes mirror ``scripts/verify_demo.py``: ``2`` is inconclusive, and that is the
    only success-ish code this command can return. There is no ``0``, because a single
    invocation can never establish containment on its own.
    """
    import argparse
    import uuid

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", required=True, help="Foundry project endpoint URL.")
    parser.add_argument("--agent", required=True, help="Hosted agent name to invoke.")
    parser.add_argument("--run-id", default=None, help="demo_run_id. Generated if omitted.")
    parser.add_argument("--model", default="", help="Model id; the server supplies its default.")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", default=None, help="Write the JSON record to this path too.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_id = args.run_id or f"invoke-{uuid.uuid4().hex[:12]}"

    result = invoke_agent(
        endpoint=args.endpoint,
        agent_name=args.agent,
        demo_run_id=run_id,
        model=args.model,
        timeout_seconds=args.timeout,
    )
    rendered = json.dumps(result.as_dict(), indent=2, sort_keys=True)
    print(rendered)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")

    print(
        "\nDETERMINATION: inconclusive-without-platform-evidence.\n"
        "A classified tool failure is not a denial. Attribution needs the platform's own "
        "egress decision record and the absence of a receipt at the destination, in this "
        "same bounded window.",
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
