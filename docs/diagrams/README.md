# Diagrams

| File | What it shows |
| --- | --- |
| [`environment.excalidraw`](environment.excalidraw) | Whole environment in six zones: operator laptop, AKS namespace, Foundry account/project, Container Apps endpoints, evidence plane, ACR. Numbered flows F1 to F11 with a flow legend. Written 2026-10-09. |
| [`azure-environment.excalidraw`](azure-environment.excalidraw) / [`.svg`](azure-environment.svg) | Earlier Azure-only view. |

## How to open

- **excalidraw.com**: open the site, menu (top left) > *Open*, choose `environment.excalidraw`. Nothing is uploaded unless you share a link.
- **VS Code**: install the *Excalidraw* extension (`pomdtr.excalidraw-editor`), then open the file. It edits in place.

Arrows are bound to their shapes and labels to their containers, so moving a box moves its arrows. Zoom to fit (Shift+1) first; the canvas is large.

## Legend

| Style | Meaning |
| --- | --- |
| Green, solid | Observed / verified (dated evidence in `telemetry-map.md`, `compatibility.md`) |
| Blue, solid | AKS stand-in caller. **Not governed** by the Foundry policy. |
| Purple, solid | Foundry component (deployed, observed) |
| Teal, solid | Controlled endpoint (our code, Container Apps) |
| Orange, **dashed** | PROPOSED / UNVERIFIED (evidence workbook, Entra Agent ID, app-span link, F9) |
| Red | Blocked, denied or disabled by the platform (native A2A, enforced Deny) |

Arrow labels `F1` to `F11` are explained in the flow legend at the bottom of the diagram.

## Verified vs proposed vs assumed

- **Verified:** F1 to F3, F5 to F8, F10 (`verify_demo.py`) and the run-id join (URL path), see `telemetry-map.md` §0.12 to §0.14 (small n). Same image digest on both agents and the policy attachment (deployer readback).
- **Assumed:** the network path of F4 (AKS to the private-only account). Calls succeed, but the layering of managed VNet and egress policy is an open documentation gap (`compatibility.md` D). The model deployment name and the `foundry-account-pe` rule come from `infra/cloud` and B9g.
- **Proposed / unverified:** the evidence workbook (not applied), Entra Agent ID auth (issue #4), F9's link to missing app spans, and anything in the diagram drawn dashed orange.
- **Blocked:** native inbound A2A on hosted agents (`HOSTED_AGENT_NOT_SUPPORTED`).

The diagram is a map, not evidence. Containment evidence is the platform decision rows plus receipts for one `run-...` id; see [`../architecture-as-built.md`](../architecture-as-built.md). Digests and version numbers drift: re-read them with the `*:digest` tasks.
