# Module 09: Run the demo and verify the evidence

**Duration:** about 60 minutes (the harness turn takes about 2 minutes on the CPU model; evidence ingestion needs a 3 minute wait)

## Objectives

By the end of this module you can:

- Run the harness as an allowed user and as a denied user, and say what each outcome does and does not prove.
- Predict the Audit and Enforced results for the two tools before you click.
- Run `scripts/verify_demo.py` and read **PASS / FAIL / INCONCLUSIVE** correctly.
- Label a run as local or hosted, and fill in the evidence template.

## Concepts

The claim under test: outbound network containment is enforced by the **platform**, not the application. The agent has exactly two tools. `get_servicing_policy` calls an allowlisted host (expected success). `send_to_external_processor` calls a host that is deliberately not allowlisted (expected platform denial under Enforced). The same image digest runs in both agent versions; the attached RAI policy is the only variable.

![Allowed vs denied flow](diagrams/02-allowed-vs-denied-flow.svg)

Three outcomes are reported **separately and never merged** (see [`../demo-runbook.md`](../demo-runbook.md) and [`../issue-4-demo-readiness.md`](../issue-4-demo-readiness.md)):

| Outcome | Question it answers | Not evidence of |
| --- | --- | --- |
| Identity authorization | Which actor did the request claim to be? | Anything the policy API or the platform did |
| Policy API authorization | Did the protected route accept or reject that actor (200 / 401 / 403)? | Egress containment |
| Containment evidence | Did the platform deny the egress and did the destination see no receipt? | Who the user was |

**Expected tool results**

| Tool | Audit agent | Enforced agent |
| --- | --- | --- |
| `get_servicing_policy` | 200 | 200 |
| `send_to_external_processor` | 202 (receiver got it) | 403 `http_error` from the platform |
| Platform decision row | `AuditWouldDeny` (`decision=Deny`, `enforcement=Audit`) | `Deny` / `DefaultDeny` / `Enforced` |
| Receipt at `test-receiver` | present | **absent** (only meaningful after 180 s) |

An agent-reported 403, a DNS error, a timeout, or a model refusal is **not** proof of containment. Only the platform decision row joined with the receipt presence or absence counts. Missing evidence is **INCONCLUSIVE**, never a pass.

![Evidence join](diagrams/08-evidence-join.svg)

### What is honestly demonstrable today

Per [`../demo-runbook.md`](../demo-runbook.md) (Issue #4 section), the **offline** allowed/denied tests are the authorization proof for the scoped track. In the live UI, the actor alias is display-only unless you use the external (Entra) mode, and the deployed policy API does not yet enforce an actor store, so a live click's policy outcome reflects the un-gated call. Say this out loud if you click through an allowed/denied pair live. Containment results (audit vs enforced) were TESTED in the earlier runs recorded in [`../telemetry-map.md`](../telemetry-map.md) §0.13 to §0.15.

## Walkthrough

All commands run from the repo root. They assume the environment is already deployed ([Module 06](06-build-and-deploy.md)) and identity is set up ([Module 04](04-identity.md)).

### 1. Preflight (read-only)

```bash
task app:validate                  # repo guards, Azure context, policies/endpoints, app health, identity journal
task cloud:kubeconfig              # once per machine
task cloud:app-insights-connection # if no connection is listed, every run is INCONCLUSIVE
task foundry-agent:status          # publisher log: accepted, not enforced
task build:foundry-agent-digest    # one digest that BOTH agent versions must pin
task chat-agent:network-state      # managed network, both RAI policies, policy on each agent version
task agent-bridge:verify           # facades: 401 without token, 200 with
task chat-agent:verify             # same for the harness
```

Stop if the two agents do not share one `sha256:` digest, or either version is not `active`.

### 2. The offline allowed vs denied pair

```bash
task app:run-allowed   # real policy API code path: allowed actor gets 200 on /policy
task app:run-denied    # same path: denied actor gets 403 actor_context_denied, identity_only, no payload
```

These are offline tests (`tests/unit/test_policy_actor_authorization.py`). They prove authorization behavior of the code, not platform containment.

### 3. Open the harness

**Primary: external mode** (HTTPS and Entra login, built in [Module 07](07-external-access.md)): browse to `https://<your-fqdn>`, sign in as the **allowed** test user first, then repeat in a private window as the **denied** user. In this mode the harness derives the actor alias from ingress identity headers.

**Development fallback: local port-forward** (shared token, any user name, no Entra):

```bash
task chat-agent:token   # prints the password; do this off-screen
task chat-agent:open    # http://localhost:8082 ; Ctrl-C to stop
```

Note the **UTC time you press send**. Ask for both tools in one message, for example: fetch the servicing policy, then send to the external processor, on both the audit and the enforced agent. Do not click again while the turn runs. Copy the `run-...` id shown for each side. Do not trust the model's prose; read the structured tool table.

### 4. Verify (wait at least 180 seconds first)

```bash
.venv/bin/python scripts/verify_demo.py --section b \
  --audit-run-id <run-... from audit> --audit-called-at <UTC ISO, e.g. 2026-10-09T20:17:59Z>
.venv/bin/python scripts/verify_demo.py --section c \
  --enforced-run-id <run-... from enforced> --enforced-called-at <UTC ISO>
```

| Exit code | Status | Meaning |
| --- | --- | --- |
| 0 | PASS | Decision row and receipt joined on that `run-...` id as expected |
| 1 | FAIL | Evidence contradicts the expectation |
| 2 | INCONCLUSIVE | Evidence missing, too fresh (under 180 s), wrong run id, or unresolved endpoints |

Pitfalls recorded in the runbook:

- `--*-called-at` must be when the **tools ran**, not when the chat reply finished. A value ~90 s late produced INCONCLUSIVE (`no platform decision row`). A wrong value yields INCONCLUSIVE, never a false pass.
- Compare the printed `matched_run_ids` with the id you passed. If rows return but none carry it, the result is INCONCLUSIVE ("run id mismatch").
- `--no-terraform` makes endpoints unresolvable (INCONCLUSIVE). Run from a machine with the Terraform state and a login that can read Log Analytics (the `verify` extra).
- Use `--json <path>` to write the machine-readable summary.

### 5. Local vs hosted labels

The harness carries `DEMO_RUN_LABEL` (`hosted` or `local`). **Local runs are functional tests, not containment proof.** Report them separately from hosted runs. Never mix the two in one result.

### 6. Record the result

Fill in [`../evidence-template.md`](../evidence-template.md): run ids, UTC times, which outcome category each row belongs to, verifier output, and whether the environment was left up. Keep tested results, proposed behavior and preview capability in separate sections.

## Code tour

| What | Where |
| --- | --- |
| Status enum (pass, fail, inconclusive) | [`scripts/verify_demo.py` L67-L75](../../scripts/verify_demo.py#L67-L75) |
| Failure classification (HTTP / TLS / DNS / timeout) | [`scripts/verify_demo.py` L76-L135](../../scripts/verify_demo.py#L76-L135) |
| Audit and enforced judges | [`scripts/verify_demo.py` L1522-L1650](../../scripts/verify_demo.py#L1522-L1650) |
| Exit code mapping | [`scripts/verify_demo.py` L1666-L1672](../../scripts/verify_demo.py#L1666-L1672) |
| Harness chat routes (`/chat`, `/ws`, `/healthz`) | [`src/containment_demo/harness/chat.py` L178-L432](../../src/containment_demo/harness/chat.py#L178-L432) |
| Ingress actor alias (display-safe, no raw claims) | [`src/containment_demo/harness/chat.py` L97-L123](../../src/containment_demo/harness/chat.py#L97-L123) |
| Verifier task wiring | [`tasks/Taskfile.verify.yml`](../../tasks/Taskfile.verify.yml) |
| Allowed/denied offline tasks | [`tasks/Taskfile.app.yml` L46-L56](../../tasks/Taskfile.app.yml#L46-L56) |

## Checkpoint

- [ ] Both agents show the same digest and `active`.
- [ ] You ran the harness as the allowed and the denied user and can state which outcome category each result belongs to.
- [ ] Section B (audit) and section C (enforced) each ended in PASS, or you can explain why INCONCLUSIVE is the honest result.
- [ ] The evidence template names the run ids, UTC times and local/hosted label.

Further reading: [`../demo-runbook.md`](../demo-runbook.md), [`../evidence-template.md`](../evidence-template.md).

**Next:** [Module 10: Monitoring](10-monitoring.md)
