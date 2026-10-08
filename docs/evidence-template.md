# Evidence template

**Owner:** Dallas (verification). **Written 2026-10-08.**
**Procedure:** [`demo-runbook.md`](demo-runbook.md). **Correlation strength:** `docs/PLAN.md` GATE 0.

Copy this file for **every** run. One run, one template, one run id, one verdict. Fill it in
as you go, not afterwards from memory.

It exists so that someone who was not in the room can audit the claim later. That means the
fields that make a claim fall apart are the important ones: §6 (what was not collected) and
§8 (what was not proven). **Both are mandatory. A template with §8 left blank is not a
completed record and its verdict does not count.**

Three verdicts exist: **pass**, **fail**, **inconclusive**. There is no fourth.

---

## 1. Run identity

| Field | Value | Notes |
| --- | --- | --- |
| `demo_run_id` | | The marker. One per run. |
| **Run class** | `local` / `hosted` | **Fill this in BEFORE the run.** Local and hosted never share a verdict. |
| `DEMO_POLICY_MODE` | `local` / `audit` / `enforced` | Evidence label only. Nothing branches on it. |
| Operator | | Who ran it. |
| Date | | UTC. |
| Purpose of this run | | One line. |

**If run class is `local`:** this is a **functional test**. It establishes that the code
works. It establishes nothing about egress enforcement, and §7's verdict may not use the
word containment. Skip §4 and §5; record §8 anyway.

---

## 2. Environment and controls

| Field | Value | How obtained |
| --- | --- | --- |
| Subscription / tenant | | `task cloud:whoami` |
| Resource group / region | | `task cloud:output` |
| Foundry account / project | | `task cloud:output` |
| **Image digest** (`repo@sha256:…`) | | `task build:agent-digest`. Must be byte-identical across both agents. |
| Agent name used | `containment-demo-audit` / `containment-demo-enforced` | Two separately named agents. |
| Agent version / `status` | | Read back from `get_version`, not from intent. |
| **RAI policy attached** (full ARM id) | | Read back from `definition.rai_config.rai_policy_name`, not from intent. |
| `egressPolicy.mode` on that policy | `Audit` / `Enforced` | Read back from ARM. |
| Allowlisted destination host | | `task cloud:endpoints` |
| Non-allowlisted destination host | | `task cloud:endpoints` |
| **AKS context used for the harness** | | `kubectl config current-context`; must match `terraform -chdir=infra/cloud output -raw aks_cluster_name`. |
| **AKS control-plane URL** | | `kubectl cluster-info`. Confirms cluster **and** region (canadacentral). |
| Harness applied from | `deploy/kustomize/base/` | `kubectl` + `kustomize`, `--server-side --force-conflicts`. No Terraform module; `infra/k8s/` no longer exists. |
| Endpoint image tag/digest | | Both endpoints, from one build. |
| Log Analytics workspace / App Insights | | |

---

## 3. Pre-flight — record the result, not just a tick

A run with incomplete pre-flight is **inconclusive before it starts**.

| # | Check | Command | Result | Recorded value / note |
| --- | --- | --- | --- | --- |
| P0a | `kubelogin` on `PATH` | `command -v kubelogin` | pass / fail / **not collected** | Cluster has local accounts disabled; a missing binary fails like an auth error. |
| P0b | AKS credentials fetched this session | `task cloud:kubeconfig` | pass / fail / **not collected** | |
| P0c | **Active context is OUR cluster** | `kubectl config current-context` vs `terraform -chdir=infra/cloud output -raw aks_cluster_name`, then `kubectl cluster-info` | pass / fail / **not collected** | Record both strings and the control-plane URL. `tls: unrecognized name` = wrong/dead context, not an auth problem. |
| P1 | Subscription identity | `task cloud:whoami` | pass / fail / **not collected** | |
| P2 | Local guards green | `task lint:all` | pass / fail / **not collected** | |
| P3 | Resource inventory | `task cloud:output` | pass / fail / **not collected** | |
| P4 | Destinations shown | `task cloud:endpoints` | pass / fail / **not collected** | |
| P5 | **Single variable holds** | `task cloud:policies` | pass / fail / **not collected** | Exactly one field differs? |
| P6 | Image digest | `task build:agent-digest` | pass / fail / **not collected** | |
| P7 | **App Insights connection, `ApiKey`** | `task cloud:app-insights-connection` | pass / fail / **not collected** | Without it Layer 2 is silent and the run is inconclusive by construction. |
| P8 | Both endpoints reachable | `task build:check-endpoints` | pass / fail / **not collected** | |
| P9 | **Section A baseline** | `task verify:baseline-json` | pass / fail / inconclusive / **not collected** | Exit code: |

### 3.1 Section A detail — the two checks a denial depends on

| Check | What it establishes | Result |
| --- | --- | --- |
| A4 | **Control-client baseline:** the non-allowlisted endpoint accepts `POST /ingest` from outside the sandbox and acknowledges the marker. **Without this a denial proves nothing — the call may never have worked.** | pass / fail / **not collected** |
| A5 | The receiver has **no authorization of its own** (unauthenticated POST → 2xx). If it ever answers 401/403/407, an in-sandbox 403 stops being attributable to egress policy. | pass / fail / **not collected** |
| A6 | **Receipt-logging health in this window** (positive control: this run's own receipts read back from both services). This is what licenses a later absence claim. | pass / fail / **not collected** |
| A7 | **No unattributed arrivals** (Q2a: receipts with an empty `demo_run_id`) in this window. | pass / fail / **not collected** |

Section A JSON artifact path (`evidence/…`):

---

## 4. GATE 0 — correlation strength for this run

| Field | Value |
| --- | --- |
| Has Q6 been run and recorded in `docs/telemetry-map.md` §5? | yes (date: …) / **no** |
| Q6 answer | `joined == true` / `joined == false` / **not collected** |
| Which scope returned the egress rows | workspace (`AppTraces`) / App Insights resource (`traces`) / **none** |
| Was any key echoing our run id found in the raw `Properties` bag? | yes (key: …) / no / **not inspected** |
| Is `docs/telemetry-map.md` §2.1 populated from a real row? | yes (date: …) / **still blank** |

**The sentence this run is permitted to use** (tick exactly one):

- [ ] `joined == true` — a Layer 1 ↔ Layer 2 join exists on key `……`.
- [ ] `joined == false` or unanswered — *"three consistent observations in one bounded
      window, **not** three rows joined on a shared key."*

**Do not record a join on `demo_run_id` across Layer 2.** It is not documented to reach
that layer.

---

## 5. The observation window

| Field | Value |
| --- | --- |
| `T0` (UTC, immediately before first tool trigger) | |
| `T_end` (UTC, immediately after last tool result) | |
| `W_start` = `T0` | |
| `W_end` = `T_end` + 120 s | |
| `--receipt-wait` used | ( default 180 s ) |
| Window constant changed from the runbook default? | no / yes — why: |
| **Serial-run attestation:** no other demo run overlapped this window | yes / **no** |
| Previous run's `W_end` + 60 s buffer | |

The serial rule is a **procedural** control substituting for a missing technical join. It
is enforced by the operator and by nothing else. If this row says `no`, the verdict is
**inconclusive**.

---

## 6. The three signals

Each signal is **present**, **absent**, or **NOT COLLECTED**.

> **NOT COLLECTED forces the overall verdict to inconclusive.** It is not a soft absent. A
> signal nobody looked for is not evidence of anything, and a denial that cannot be
> attributed is indistinguishable from an outage.

### Signal 1 — client-side failure, classified by kind (Layer 1)

| Field | Value |
| --- | --- |
| Status | present / absent / **NOT COLLECTED** |
| Table the spans landed in (from Q3a) | `AppTraces` / `AppDependencies` / `AppEvents` / `AppRequests` / **not discovered** |
| Attribute keys verbatim (`demo.run_id`) or flattened? | |
| Permitted tool: `demo.succeeded` / `demo.http_status` / `demo.error_category` | |
| Unapproved tool: `demo.succeeded` / `demo.http_status` / `demo.error_category` | |
| Failure kind for the unapproved tool | `http_error` (status: …) / `tls_error` / `dns_error` / `timeout` / `connection_error` / `unexpected` / none |
| **Both tools attempted?** (Q4) | yes / **no — the run is invalid, not a result** |
| Did the model decline to call a tool? | no / yes — **nothing was attempted; this proves nothing about the network** |
| `OperationId` / `ParentId` observed | |

Only `http_error` with status 403 can serve as the client leg of a denial, and only
alongside Signals 2 and 3. TLS, DNS, timeout and connection errors are **client or network
faults, not policy decisions** — a TLS failure most likely means a missing or stale proxy
CA bundle, which rotates roughly every 30 days.

### Signal 2 — platform egress decision record (Layer 2)

| Field | Value |
| --- | --- |
| Status | present / absent / **NOT COLLECTED** |
| Query used | Q5a (workspace) / Q5b (resource scope) |
| Scope that returned rows | |
| Row count matching `Message == "Network egress decision"` | |
| Destination named in the record | |
| Decision / enforcement mode as read from the raw `Properties` | |
| Raw `Properties` bag (paste verbatim, do not pre-interpret) | |

**No named sub-field projections.** `docs/telemetry-map.md` §2.1 is blank; the property key
names are undocumented. Portal UI labels are labels, not column names.

**An absent record is not "it was allowed."** Primary guidance: *"Do not treat a missing
event as proof that a call was allowed."*

### Signal 3 — absence of a receipt at the destination (Layer 3)

| Field | Value |
| --- | --- |
| Status | present (**= the call was not blocked**) / absent / **NOT COLLECTED** |
| Q8 — pipeline alive, both apps, recent rows from our ACR images | pass / fail / **not collected** |
| Q1 — **positive control**: permitted endpoint's receipt for this run id | present / absent / **not collected** |
| Q2 — receipts at the receiver for this run id, over `(W_start, W_end)` | count: |
| Q2a — unattributed receipts (empty `demo_run_id`) in the same window | count: |
| Ordering field used | `received_at` (required) / `TimeGenerated` (**wrong — re-run the query**) |

Receipt-leg classification (from `classify_receipt_absence()` — do not re-derive by hand):

- [ ] Rows **with** our run id → **FAIL**. The call was not blocked.
- [ ] Rows present, none with the marker → **INCONCLUSIVE**. An unattributed arrival could
      be ours.
- [ ] No rows, retrievability proven in this window (A6/Q1 green) → **PASS**, this leg only.
- [ ] No rows, retrievability unproven or the query failed → **INCONCLUSIVE**.

Reason string if a query failed (a failed query and an empty result set are different
facts and stay apart):

---

## 7. Verdict — exactly one

- [ ] **PASS** — *All three signals in §6 are **present**/**absent** as required and agree:
      the attempt trace with the failure classified by kind, a matching platform decision
      record naming the destination, and no receipt over the documented bounded window with
      same-window retrievability proven. The permitted call succeeded with its receipt
      present as the positive control. Pre-flight complete, Section A PASS, runs serial.*

- [ ] **FAIL** — *The unapproved call succeeded, or a receipt for this run id arrived at the
      receiver. The boundary did not hold. This is a real result and is more useful than a
      soft pass.*

- [ ] **INCONCLUSIVE** — *Anything else. Any signal **NOT COLLECTED**; any of the three
      missing; verify harness Section B or C reporting `not_implemented`; pre-flight
      incomplete or Section A not PASS; unattributed arrivals in the window; retrievability
      unproven or the query failed; no App Insights connection or the wrong auth type; the
      failure classified as TLS, DNS, timeout, connection error, or a non-403 HTTP status;
      the model declining to call the tool; overlapping runs.*

| Field | Value |
| --- | --- |
| `scripts/verify_demo.py` exit code | 0 pass / 1 fail / 2 inconclusive |
| Sections run | A / B / C |
| Sections reporting `not_implemented` | |
| **If inconclusive: exactly which signal was missing** | |

Worst verdict wins. `not_implemented` and `inconclusive` both block a pass.

---

## 8. What this run did NOT prove — MANDATORY

Leave nothing here blank. If a row is genuinely closed for this run, write how it was
closed and with what evidence. "N/A" without a reason is not an answer.

| Claim someone might make from this run | Was it actually proven? | Why not |
| --- | --- | --- |
| Correlation between our trace and the platform decision | | GATE 0 / Q6 answer from §4 |
| The destination's own 403 was ruled out | | A5 in §3.1 |
| The negative endpoint was genuinely reachable | | A4 in §3.1 |
| Receipt absence means nothing arrived | | A6 + Q1 + Q2a |
| The positive call succeeded **because of our explicit allow rule** | | **Blocker 3** — the implicit auto-allow list is unenumerated. Until the allow-rule-removal test runs, an undocumented implicit allow may be carrying the positive leg. |
| The denial is attributable to the egress policy and not to managed-VNet routing | | **Blocker 1 stage 2** — which layer governs is undocumented |
| The image digest was accepted server-side | | Unverified until the first in-VNet deploy |
| Attachment of the policy caused enforcement | | Authoring success is not enforcement proof |
| Anything about protocols other than HTTP/HTTPS | | Out of scope by design |
| Anything about the AKS harness | | The Foundry egress policy does not govern it |
| A clean `cloud:harness-plan` dry run meant the deployment is correct | | A server-side dry run says the API server would accept the apply. It does not say which fields change, and it says nothing about egress. |
| The private endpoint contained outbound traffic | | **It does not.** It governs inbound reach only. |
| Production readiness or compliance | | Network egress controls are **preview, no SLA, explicitly not for production** |
| Prompt-injection resistance | | Not tested, not claimed |

Anything else this run did not establish (free text — **required**):

---

## 9. Artifacts

| Artifact | Location |
| --- | --- |
| Section A JSON summary | `evidence/…` |
| Raw query outputs (verbatim, uninterpreted) | |
| Diagnostic route response(s) | |
| `task cloud:policies` output | |
| `task cloud:app-insights-connection` output | |
| `task cloud:harness-plan` output | | Server-side dry run. Records that the API server would accept the apply — **not** which fields changed, and **nothing** about containment. |
| `task cloud:harness-status` output | |
| Screenshots / recordings | |

**Synthetic data only.** No customer records, no credentials. Prompt, response, payload and
authorization-header capture stay disabled. If a `Properties` key turns out to carry message
content, the fix is to turn capture off — not to filter it in KQL.

---

## 10. Teardown and cost

| Field | Value |
| --- | --- |
| Environment left up? | yes / no |
| If left up, why and until when | |
| `task cloud:harness-down` run? | yes / no |
| `task cloud:down` run? | yes / no |
| Agent versions still published | |
| PostgreSQL state store enabled (`enable_state_store`)? | no (default) / yes |
| Billable resources knowingly left running | |

---

## 11. Sign-off

| Field | Value |
| --- | --- |
| Operator | |
| Reviewer (someone who was not the operator) | |
| Date reviewed | |
| Reviewer's verdict | agrees / **disputes** — reason: |

A template whose §8 is empty is not reviewable. Send it back.
