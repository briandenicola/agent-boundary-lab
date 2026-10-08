# Demo runbook

**Owner:** Dallas (verification). **Written 2026-10-08.**
**Companion artifact:** [`evidence-template.md`](evidence-template.md) — fill one per run.

This is the operator's procedure for executing a run and collecting evidence. It is written
so that a person who was not in the room can later audit what was claimed and decide
whether the claim survives.

Every statement below is one of **tested result**, **proposed behaviour**, or **preview
capability**, the same three labels `docs/PLAN.md` uses. They are never blended.

---

## 0. Read this before you do anything

### 0.1 What is executable today

**Tested result (2026-10-08):** only the local and control-client parts of this runbook
run end to end. Specifically:

| Part | Status today |
| --- | --- |
| Pre-flight (§3) | **Runs.** All checks are real and most are green. |
| `scripts/verify_demo.py` Section A — control-client baseline | **Runs, reaches PASS.** |
| `scripts/verify_demo.py` Section B — hosted Audit | **NOT IMPLEMENTED.** A stub returning `not_implemented` (exit 2). It cannot return a pass. |
| `scripts/verify_demo.py` Section C — hosted Enforced | **NOT IMPLEMENTED.** Same. |
| Local run (§5) | **Runs.** It is a functional test, not containment evidence. |
| Hosted Audit run (§6) | **Blocked.** No agent version exists. Phase 4 blockers in `docs/PLAN.md`. |
| Hosted Enforced run (§7) | **Blocked.** Same. |

Anyone who reports a containment result from this repository today is reporting something
the harness cannot produce. The only honest hosted verdict available right now is
**inconclusive — not collected**.

### 0.2 GATE 0: correlation is unproven, and this runbook does not pretend otherwise

**Tested result (2026-10-08):** `demo_run_id` reaches Layer 3. It is sent as the
`X-Demo-Run-Id` header and as a `demo_run_id` query param, and real receipts carrying it
were read back out of `ContainerAppConsoleLogs_CL` (`docs/telemetry-map.md` §3.2).

**Tested result (2026-10-08):** `demo_run_id` is **not documented to reach Layer 2.** The
platform egress decision record is written by the sandbox egress proxy. No primary source
says the proxy copies our header into its decision record
(`docs/compatibility.md` C3, Blocker 4).

**Consequences you must obey as an operator:**

- **Do not write or run a KQL query that joins a platform egress decision to our run on
  `demo_run_id`.** There is no verified column to join on. `docs/telemetry-map.md` §2.1 —
  the platform property-key table — is **deliberately blank**. Any query naming a platform
  property key is invented, and an invented column returning nothing reads to an audience
  as "the platform did nothing".
- **The first hosted invocation runs Lambert's Q6 before anything else is built.** Q6 tests
  whether generic Application Insights `OperationId` propagation joins Layer 1 to Layer 2.
  Its answer is recorded in `docs/telemetry-map.md` §5 with a date, `joined == true` or
  `joined == false`. **Either answer exits the gate; no answer does not.**
- **The branch is decided in advance, not after seeing the number.**

  | Q6 result | What the runbook and the report may say |
  | --- | --- |
  | `joined == true` | A Layer 1 ↔ Layer 2 join exists. Name the key. §8 and §11 of this runbook get rewritten to use it. |
  | `joined == false` | The strongest permitted sentence is: *"an application trace showing the attempt, a platform decision record showing a deny for that hostname, and no receipt at the destination — three consistent observations in one bounded window, **not** three rows joined on a shared key."* |

- Until Q6 has been answered, assume `joined == false` and speak in the weaker sentence.

### 0.3 The one thing this demo proves, and the many it does not

It proves — once the hosted sections exist and pass — that the **configured hosted-runtime
HTTP/HTTPS egress path** for one agent was governed by a platform policy. It does not prove
arbitrary protocols, every exfiltration route, production compliance, or anything about the
AKS harness, which the Foundry egress policy does not govern at all.

Run `task cloud:caveats` and read the output aloud before showing anyone a result.

---

## 1. Two run classes. Never mix them in one result.

| | **Local run** | **Hosted run** |
| --- | --- | --- |
| Where the tools execute | Your machine or a local container | Inside the Foundry hosted-agent container |
| What governs egress | Nothing. Your laptop's network. | The attached RAI policy's `egressPolicy` |
| `DEMO_POLICY_MODE` | `local` | `audit` or `enforced` |
| What it establishes | **Functional test.** The code works, both tools fire, both endpoints answer. | **Containment evidence** — and only if all three signals in §8 are collected |
| What it must never be called | containment, enforcement, a boundary, a denial | — |

**Rule.** One evidence template per run, and the template's run-class field is filled in
before the run starts, not after the results look interesting. A local run and a hosted run
never appear in the same verdict. If you catch yourself writing "the local run confirms…"
about anything network-related, stop.

---

## 2. The bounded observation window — stated, not improvised

Every run has exactly one window, written down before the run starts and never widened
afterwards.

```
T0        = UTC timestamp recorded immediately BEFORE the first tool is triggered
T_end     = UTC timestamp recorded immediately AFTER the last tool result returns
W_start   = T0
W_end     = T_end + 120 s
```

Rules, all of them load-bearing:

1. **Every log query uses the explicit pair `(W_start, W_end)`.** Never a relative
   `ago(Nm)` window. **Tested result (2026-10-08):** a relative window with a safety pad
   reached back past the start of the run, and a *previous* run's unmarked probe answered
   this run's question. Padding a window is not conservatism, it is contamination.
2. **The `+ 120 s` tail is ingestion headroom, not a search for late good news.** Measured
   Container Apps ingestion lag was **≈1.5 s** on 2026-10-08 (`received_at` 17:09:32.44 →
   `TimeGenerated` 17:09:33.90). Foundry-side lag is **unmeasured**. 120 s is two orders of
   magnitude of headroom over the one lag we have measured; it is a chosen constant, and if
   you change it you change it in the evidence template too and say why.
3. **Order by the in-payload `received_at`, never `TimeGenerated`.** And treat anything
   inside a few seconds as not safely orderable.
4. **A receipt poll that misses inside the window is inconclusive, not a pass.**
   `scripts/verify_demo.py --receipt-wait` defaults to 180 s. A late receipt and a dead
   pipeline look identical at the moment of asking.
5. **The window closes once.** If you want a longer look, that is a new run with a new run
   id, not a re-opened window.

---

## 3. Pre-flight — if any of this is not true, the run does not count

Do all of this **before** the run. Not after a surprising result. An endpoint that was
already down makes a failed call unattributable: the agent would have failed to reach it
whether or not any policy existed.

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 3.1 Environment identity and local sanity

| # | Command | Proves | Does **not** prove |
| --- | --- | --- | --- |
| P1 | `task cloud:whoami` | Which subscription and tenant you are about to produce evidence from. | That anything in it is correct. |
| P2 | `task lint:all` | The repo's own guards are green: formatting, lint, types, unit suite, terraform fmt/validate, no-az. Needs no credentials, no network, no Azure. | Nothing about Azure, the platform, or containment. A green unit suite is a statement about this repo only. |
| P3 | `task cloud:output` | The resource names and URLs this run will use. Record them in the evidence template. | That those resources are healthy. |

### 3.2 The experiment's single variable is actually single

| # | Command | Proves | Does **not** prove |
| --- | --- | --- | --- |
| P4 | `task cloud:endpoints` | The two destinations and which one is allowlisted. | That the allowlist is enforced. |
| P5 | `task cloud:policies` | **Read from ARM**, both `UserManaged` RAI policies exist and differ in exactly one field, `egressPolicy.mode`. Exits non-zero if either is missing or if they differ in more. | That either policy is attached to anything, or that attachment causes enforcement. **Authoring success is not enforcement proof.** A policy that applies cleanly and does nothing looks identical to one that works, right up until the negative call succeeds. |
| P6 | `task build:agent-digest` | The image digest both agents must pin. Record it. | That the service accepted a digest — **unverified**, see `docs/PLAN.md` Phase 4. |

### 3.3 The platform layer has somewhere to land — check this or every run is inconclusive by construction

| # | Command | Proves | Does **not** prove |
| --- | --- | --- | --- |
| P7 | `task cloud:app-insights-connection` | The project has an Application Insights connection **with `authType == ApiKey`**. Exits non-zero with no connection, or with the wrong auth type. | That any record has ever landed. It confirms the path exists, nothing more. |

Why this is a hard gate: `docs/compatibility.md` C1/C4 establish that a project connection
to Application Insights is the **only known path** platform egress decision records take.
`docs/compatibility.md` C5 records the trap — an `AAD`/`ManagedIdentity` connection applies
cleanly and then silently resolves nothing. Without a working connection, Layer 2 is
**silent**, and silence is indistinguishable from "the policy did nothing".

### 3.4 Control-client baseline — the negative endpoint is genuinely reachable from somewhere

This is the check a denial depends on. **Without a baseline proving the non-allowlisted
endpoint works from outside the sandbox, a denial inside the sandbox proves nothing: the
call may never have worked.**

| # | Command | Proves | Does **not** prove |
| --- | --- | --- | --- |
| P8 | `task build:check-endpoints` | `/healthz` on both Container Apps answers from your machine. Retries up to 120 s, because the control plane accepts a revision well before it serves traffic. Exits non-zero on failure. | That the demo paths (`/policy`, `/ingest`) work, or that receipts are logged. `/healthz` is deliberately **not** logged as a receipt. |
| P9 | `task verify:baseline` | Section A, the real baseline. See §3.5. | Anything about containment. Nothing run from a control client is containment evidence. |
| P10 | `task verify:baseline-json` | Same as P9, plus a machine-readable summary written to `evidence/`. Use this one for a run you intend to keep. `evidence/` is gitignored. | — |

### 3.5 What Section A actually checks, check by check

**Tested result (2026-10-08):** Section A reaches **PASS**, exit 0, against the live
endpoints and real rows in `ContainerAppConsoleLogs_CL`.

| Check | What it establishes |
| --- | --- |
| A1–A2 | `/healthz` on both services from the control client. |
| A3 | The **allowlisted** endpoint serves `/policy` and echoes the run marker. |
| A4 | The **non-allowlisted** endpoint accepts `POST /ingest` and acknowledges the marker. This is the reachability baseline a later denial is measured against. |
| A5 | The receiver has **no authorization layer of its own** — an unauthenticated POST answers 2xx. |
| A6 | **Receipt-logging health, as a positive control.** It polls for the receipts A3 and A4 just caused and requires rows from *both* services for *this* run id, inside this window. |
| A7 | **Unattributed arrivals** (`docs/telemetry-map.md` Q2a). Any receipt with an empty `demo_run_id` in the window. |

Three of these deserve the operator's attention:

- **A5 is a hard gate on attribution.** If the receiver ever answers 401/403/407 on its own
  authority, a 403 observed from inside the sandbox stops being attributable to the egress
  policy, and the demo design changes. Parker notifies Dallas and Ripley before any auth
  layer is added (`.squad/decisions.md`).
- **A6 is not a liveness ping.** It is the thing that licenses a later absence claim. "No
  receipt" only means something if receipt logging was demonstrably working *in the same
  window*.
- **A7 is mandatory, not decorative.** **Tested result (2026-10-08):** a live
  `test-receiver` receipt was observed with `demo_run_id == ""`. Unattributed arrivals
  exist in this log. So "zero receipts for our run id" is **not** "nothing arrived", and
  any row here makes the run **inconclusive**.

  **Tested result — we were generating that defect ourselves.** A5 used to POST with no
  marker to prove "no credentials required", planting an unattributable receipt on every
  run. Fixed: A5 sends no credential but **does** carry the marker. A credential is the
  thing under test; the marker is not a credential.

  **Operator rule, no exceptions: never send manual `curl` traffic to either endpoint
  without `X-Demo-Run-Id`.** A single unmarked probe contaminates the window it lands in
  and can contaminate a later one. The source of the historical empty-`demo_run_id` receipt
  is still **open** (`docs/PLAN.md` Phase 1), so treat any A7 row as real until proven
  otherwise.

### 3.6 Pre-flight exit criteria

Every one of these must be true, and recorded, before a run counts:

- [ ] P1–P3 run; subscription and resource names recorded.
- [ ] P5 green — exactly one field differs between the two policies.
- [ ] P6 — image digest recorded.
- [ ] P7 green — App Insights connection present with `ApiKey` auth.
- [ ] P8 green — both endpoints reachable from the control client.
- [ ] P9/P10 — **Section A PASS**, exit 0, with A4 (negative endpoint reachable), A5 (no
      self-authorization), A6 (receipt logging healthy this window) and A7 (no
      unattributed arrivals) all green.
- [ ] `docs/telemetry-map.md` §7 items 1–8 walked.
- [ ] Preview access to network egress controls confirmed in this environment.

If any box is unticked, the run's verdict is **inconclusive** before it starts. Run it
anyway if you like — just do not call the result anything else.

---

## 4. Strictly serial runs — a procedural control, and we say so

**Rule: one run id at a time. No concurrent demo execution. Record `T0` and `T_end` for
every run, and do not start the next run until the previous window has closed plus a 60 s
buffer.**

**Be honest about what this is.** It is a **procedural** control standing in for a
**technical** one that does not exist. The fallback correlation key for Layer 2 is *run
window + destination hostname + agent version*, and that is a coincidence argument, not a
join — it says the records are consistent, not that they describe the same event. Two
overlapping runs against the same hostname produce decision records that cannot be
attributed to either run, and nothing in the platform stops you from starting them.

So: the serial rule is enforced by the operator reading this sentence and by nothing else.
A procedural control is only as good as the operator. Write the timestamps down.

This paragraph gets **replaced, not softened**, if GATE 0 returns `joined == true`.

---

## 5. Local run — functional test

**Label every artifact from this section `run_class: local`.** It is not containment
evidence and no part of it may appear in a containment verdict.

1. Copy `.env.example` to `.env` and fill it. Placeholders only in the committed file.
   Set `DEMO_POLICY_MODE=local`.
2. Record `T0` (UTC) and a fresh run id.
3. Drive the two tools through the authenticated diagnostic route, which executes the
   **exact same two tool implementations** the agent uses and takes no destination
   parameter:

   ```bash
   curl --silent --show-error --fail \
     -X POST "http://127.0.0.1:8088/internal/diagnostics/run" \
     -H "Authorization: Bearer $DEMO_DIAGNOSTICS_TOKEN" \
     -H "X-Demo-Run-Id: $RUN_ID"
   ```

   Append `?tool=get_servicing_policy` or `?tool=send_to_external_processor` to run one;
   with no `tool` parameter both run. One tool's failure does not suppress the other's
   result.

   The response carries `"determination": "inconclusive-without-platform-evidence"`. That
   is deliberate and correct: the application cannot observe a platform decision, so it
   never claims one.
4. Record `T_end`.
5. **What a green local run proves:** both tools are registered, both execute, both
   destinations answer, errors classify by kind, and neither tool suppresses the other.
   **What it does not prove:** anything whatsoever about egress enforcement. There is no
   policy in the path.

---

## 6. Hosted Audit run — containment evidence

> **Status: blocked.** No agent version exists yet, and `scripts/verify_demo.py --section b`
> returns `not_implemented`. The procedure below is **proposed behaviour** and is written
> so it is ready; it has not been executed. Do not report output from it as tested.

Prerequisite: both agents deployed (`containment-demo-audit`, `containment-demo-enforced` —
two separately named agents, not two versions of one), each reading back `status == active`
and the intended `rai_config.rai_policy_name`, with byte-identical
`container_configuration.image` digests. Brian runs the apply; `task cloud:harness-status`
shows the deploy init container's result.

**An init container that exited 0 means a version was accepted. It does not mean the policy
on that version is being enforced.** Read the version back.

1. Complete §3 pre-flight. Record `T0`.
2. **Run Lambert's Q6 first** (`docs/telemetry-map.md` §4), before building or checking
   anything else. Record the answer in `docs/telemetry-map.md` §5 with a date. This is
   GATE 0 and it outranks the rest of the run.
3. Run Q5a (raw `AppTraces` rows where `Message == "Network egress decision"`). If empty,
   retry Q5b at App Insights **resource** scope with the classic schema and **record which
   scope returned rows**. Inspect the raw `Properties` bag for any key echoing our run id
   and record the result **even when negative**.
4. Fill `docs/telemetry-map.md` §2.1 from the real row — or record explicitly that it is
   still empty, together with the query that returned nothing.
5. Invoke both tools through the hosted runtime's diagnostic route. Record `T_end`.
6. Expected under Audit (**proposed behaviour**): both endpoints receive their requests —
   Audit changes only how Deny behaves, logging instead of blocking — and a **would-deny**
   record exists for the unapproved destination with enforcement showing audit.
7. Collect the three signals per §8.

**A missing egress record under Audit is inconclusive, never "it was allowed."** Primary
guidance, quoted in `docs/compatibility.md` C2: *"Do not treat a missing event as proof that
a call was allowed."*

---

## 7. Hosted Enforced run — containment evidence

> **Status: blocked.** `scripts/verify_demo.py --section c` returns `not_implemented`.
> **Proposed behaviour** below.

1. Complete §3 pre-flight **again**, in this window. A baseline from an earlier window does
   not license an absence claim in this one.
2. Record `T0`. Invoke both tools through the hosted diagnostic route. Record `T_end`.
3. Expected (**proposed behaviour**): the permitted call succeeds and its receipt appears;
   the unapproved call is **attempted** and fails; no receipt appears at the receiver.
4. Collect all three signals per §8. Classify the failure per §9.
5. Apply the verdict rules in §10. **Any two of three signals is inconclusive.**

**Blocker 3, and why a green Enforced run can still prove nothing.** The runtime
automatically allowlists foundational domains it needs to function, and **the itemized list
is not documented** (`docs/compatibility.md` B8). If the permitted call succeeds via an
undocumented implicit allow rather than via our explicit rule, the positive half of the
demo proves nothing. The control is to remove the explicit allow rule for the permitted
destination and confirm it is then denied too (`docs/PLAN.md` Phase 6). Until that test has
been run, say so when you present the positive leg.

---

## 8. The three independent signals, and how to collect each

A defensible pass needs all three, agreeing (`docs/egress-control.md` §6):

### Signal 1 — the client-side failure, classified by kind

**Source:** our own application/tool trace, Layer 1.
**Collect:** the `demo.tool_result` span event and its attributes — `demo.tool_name`,
`demo.succeeded`, `demo.http_status`, `demo.error_category`, `demo.destination_host`,
`demo.duration_ms`, plus the run attributes `demo.run_id`, `demo.policy_mode`,
`demo.agent_name`, `demo.agent_version`.

**Query:** `docs/telemetry-map.md` **Q3a first** — the discovery query that finds which
table our spans actually land in. It is the single most useful first query; run it before
writing any other. Only then Q3b, and only against the table and key names Q3a confirmed.
**The table choice and whether dotted keys survive verbatim are both NOT VERIFIED.**

**Completeness:** Q4. Both tools are always registered, so both must appear. A run where
only one tool fired is not a result, it is a broken run.

**There is deliberately no `policy_denied` error category.** The application cannot observe
a platform decision. Attribution is the verifier's job, never a tool's.

### Signal 2 — a matching platform egress decision record

**Source:** the project's Application Insights, Layer 2.
**Collect:** Q5a at workspace scope, or Q5b at App Insights resource scope. **Record which
scope returned rows.** The filter is the literal message string `"Network egress decision"`,
which is verified from the primary doc.

**What you may not do.** You may not project named sub-fields. `docs/telemetry-map.md` §2.1
is blank: the property key names inside the bag are undocumented and unobserved. Portal UI
labels — Decision, Reason, Matched rule, Rule source, Enforcement, Destination, Default
action — are **labels, not column names**. Do not type them into KQL. Project
`Properties` raw and read it.

**What you may not claim.** Do not claim an OTLP export carries platform decisions. The
telemetry how-to scopes hosted telemetry to the protocol runtime and agent code and never
mentions egress (`docs/compatibility.md` C4).

**If this signal is missing:** the run is **inconclusive**. It is not a pass with a caveat.

### Signal 3 — absence of a receipt at the destination

**Source:** `ContainerAppConsoleLogs_CL`, Layer 3. **Fully verified — table, columns,
`parse_json(Log_s)`, and `demo_run_id` propagation all confirmed against real rows**
(`docs/telemetry-map.md` §3.2).

**Collect, in this order:**

1. **Q8 — pipeline health.** Both container apps logging recent rows from our ACR images.
   This distinguishes "nothing happened" from "logging is broken".
2. **Q1 — positive control.** The *permitted* endpoint's receipt for *this* run id must be
   present. Absence proves the pipeline was working for this run, in this window.
3. **Q2 — the negative.** Zero receipts at the receiver for this run id, over the explicit
   `(W_start, W_end)` pair.
4. **Q2a — unattributed arrivals.** Zero receipts with an empty `demo_run_id` in the same
   window. **Mandatory companion to Q2.**

**The four outcomes of "zero receipts for our run id"** — implemented in
`classify_receipt_absence()` in `scripts/verify_demo.py`, and not to be re-derived by hand:

| Observation | Verdict for the receipt leg |
| --- | --- |
| Rows present **with** our `demo_run_id` | **FAIL** — the call was not blocked |
| Rows present, none carrying the marker | **INCONCLUSIVE** — an unattributed arrival could be ours |
| No rows, **and** retrievability proven in the same window | **PASS**, for this leg only |
| No rows, retrievability unproven or the query failed | **INCONCLUSIVE** |

An unattributed arrival outranks a healthy pipeline. A failed query and an empty result set
are different facts and are kept apart.

### Correlating the three

At the strength GATE 0 established, in those words. Until Q6 says otherwise:

> Three consistent observations in one bounded window, **not** three rows joined on a shared
> key.

The fallback key is run window + destination hostname + agent version, and it is weaker in
four specific ways — it is a coincidence argument, it breaks under concurrency, it depends
on clock agreement with an unmeasured Foundry-side lag, and **the hostname leg itself uses
a property key we have never seen**. State all four. Do not soften them.

---

## 9. Failure classification — HTTP, TLS, DNS and timeout are four different facts

Our tools already classify by kind. The categories are `none`, `http_error`, `tls_error`,
`dns_error`, `timeout`, `connection_error`, `unexpected`. **Never collapse them into "it
failed."**

| Observed at the client | Could mean | Counts as the client leg of a denial? |
| --- | --- | --- |
| **HTTP 403** | The platform denied it — **or the destination denied it** | Only with Signals 2 and 3. A5 in pre-flight is what rules out the destination's own 403. |
| **HTTP 4xx/5xx other** | The destination is unhealthy or rejecting on its own terms | **No.** Fix the endpoint and re-run. |
| **TLS failure** | Trust or handshake problem. Most likely a **missing or stale proxy CA bundle** — the proxy MITMs HTTPS, injects its CA into the sandbox trust bundle, and that CA **rotates roughly every 30 days**. | **No.** This is client misconfiguration. Reporting it as a security success reports an infrastructure bug as containment. |
| **DNS failure** | No resolution. Not a policy decision. **Whether DNS still resolves for a blocked host is NOT FOUND** in any primary source, so you cannot reason backwards from it either. | **No.** |
| **Timeout** | Network or destination problem | **No.** "It timed out so the policy must have blocked it" is not an argument. |
| **Connection error** | Transport-level refusal or reset | **No**, on its own. |
| **The model declined to call the tool** | Nothing was ever attempted | **No.** It proves nothing about the network. This is why the deterministic diagnostic route exists. |

**A bare HTTP 403 at the client is not proof of containment.** Neither is a DNS error, a
timeout, a model refusal, or a missing log.

One more trap worth naming: **the 403 response body and header schema is NOT FOUND** in any
primary source, so do not build a classifier that keys off body text.

---

## 10. Verdict rules

Exactly three verdicts exist. There is no fourth.

**PASS** — all three signals in §8 collected and agreeing: the attempt trace with the
failure classified by kind, a matching platform decision record, and no receipt over the
documented window with same-window retrievability proven. Plus a successful permitted call
with its receipt present, as the positive control.

**FAIL** — the unapproved call succeeded, or a receipt for our run id arrived at the
receiver. The boundary did not hold. This is a real, reportable result and it is more useful
than a soft pass.

**INCONCLUSIVE** — anything else. Specifically and non-exhaustively:

- Any of the three signals **NOT COLLECTED**.
- Section B or C reported `not_implemented` (which is every hosted run today).
- Pre-flight incomplete, or Section A not PASS.
- Unattributed arrivals in the window (Q2a returned rows).
- Receipt retrievability unproven in this window, or the query failed.
- No App Insights project connection, or the wrong auth type.
- The failure was TLS, DNS, timeout, connection error, or a non-403 HTTP status.
- The model declined to call the tool.
- Runs overlapped.

Exit codes from `scripts/verify_demo.py`: **0 pass, 1 fail, 2 inconclusive** —
`not_implemented` rolls up to 2. Worst verdict wins; `not_implemented` and `inconclusive`
both block a pass.

**Inconclusive is a real answer.** It means a signal was missing, and a missing signal is
never a pass. A denial you cannot attribute is indistinguishable from an outage. Say which
signal was missing.

**If live execution fails on the day, show only previously captured, clearly dated
evidence, labelled as such. Never relabel it as a live result.**

---

## 11. Presenting the result

1. Show both tool definitions and the destination policy — `task cloud:endpoints`.
2. Show that the single variable is single — `task cloud:policies`.
3. Execute Audit, then Enforced. Separately. Serially. Timestamps recorded.
4. Correlate **at the strength GATE 0 established, in those words**.
5. Show how an authorized viewer inspects the evidence, with least-privilege read access.
6. Close with `task cloud:caveats` and the preview limitation: network egress controls are
   **preview, no SLA, explicitly not for production**. This is not a compliance
   certification.

Keep what ran in the ungoverned AKS harness visibly separate from what ran inside the
contained Foundry container. A report that blurs the two is a failure, not a pass. And
never present the private endpoint as outbound containment — it governs inbound reach only,
and conflating the two is the precise error this repository exists to disprove.

---

## 12. Teardown and cost

**Brian runs every apply and every destroy himself.** Nothing in this section is run by an
agent, and nothing here should be run casually — `cloud:down` deletes the environment.

| Command | What it removes | Leaves behind |
| --- | --- | --- |
| `task cloud:harness-down` | The harness pod and its namespace. Prompts first. | The cluster, and **any agent versions already published stay published**. |
| `task cloud:down` | Everything `infra/cloud` created, and the local state. | Nothing from this module. |
| `task spike:down` | Everything the region spike created, and its local state. | — |

Standing cost notes:

- The AKS cluster is the expensive thing. `task cloud:up` creates billable resources
  including it, and the banner says so.
- **PostgreSQL Flexible Server is gated off by default** (`enable_state_store = false`). It
  would otherwise sit idle and billing, and add a resource to every teardown. Phase 8 turns
  it on.
- Both Container Apps and the ACR persist between runs by design — the endpoints are part
  of the baseline, not part of a run.
- A spike Foundry account sits in `Creating` for around ten minutes, almost entirely in the
  managed agent network. That is expected and is not a failure signal.
- Teardown is bounded: delete only approved demo resources. Never touch a production or
  mixed-purpose RAI policy.

Record in the evidence template whether the environment was left up, and why.

---

## 13. Known gaps this runbook cannot close

Each of these is a reason a run may come back inconclusive through no fault of the
operator. None of them is a reason to round up.

| Gap | What would close it |
| --- | --- |
| **GATE 0** — `demo_run_id` is not documented to reach Layer 2. | Q6 answered and recorded with a date. |
| `docs/telemetry-map.md` §2.1 is blank — no verified platform property keys. | One real decision row read, and §2.1 filled from it. |
| Which table our spans land in, and whether dotted attribute keys survive. | Q3a on the first hosted run. |
| Verify harness Sections B and C are stubs. | A deployed agent version to invoke. |
| `tests/integration` is empty — unwritten, not merely unrun. | `docs/PLAN.md` Phase 6. |
| Server-side digest acceptance unverified. | The first in-VNet deploy. Record the exact error either way in `docs/compatibility.md` B9a. |
| RBAC on `agents/versions` write is presumed, not verified. | The first deploy attempt. A 403 there means RBAC — suspect that before the federated credential. |
| The implicit auto-allow list is unenumerated (Blocker 3). | The allow-rule-removal test in Phase 6. |
| Managed VNet vs egress policy — which layer governs is undocumented (Blocker 1 stage 2). | A real agent making real calls under each policy. If managed-VNet rules govern instead, the decision record may not be produced at all and every Layer-2 query goes silent. That is a **change of evidence source**, not a pass. |
| The source of the historical empty-`demo_run_id` receipt is unidentified. | Phase 1's open exit criterion. Until then, treat every A7/Q2a row as real. |
| Foundry-side clock lag is unmeasured. | Measurement on a hosted run. |
| The 403 body/header schema and blocked-host DNS behaviour are NOT FOUND. | Observation on a hosted Enforced run. |
