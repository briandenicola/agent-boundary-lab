# 05: Agent and tools

The Foundry-hosted Google ADK agent always registers two business tools:

| Tool | Action |
| --- | --- |
| `get_servicing_policy` | Retrieve a synthetic policy using the user's delegated authorization |
| `send_to_external_processor` | Send a synthetic record to the test receiver |

Neither accepts a model-supplied URL. Destinations are validated at startup.
The tools do not change behavior between Audit and Enforced.

## Why both must remain registered

Removing the sending tool would show that application code prevented the call.
The network experiment instead lets the tool execute and checks whether Foundry
blocks its request. The agents therefore share one image and tool configuration.

ACS is a different experiment: its ADK callback evaluates the proposed tool before
execution and may return a blocked result.

## Read the code

| Source | Look for |
| --- | --- |
| [agent.py](../../src/containment_demo/agent.py) | Both tools registered; ADK-injected context is hidden from model arguments |
| [tools.py](../../src/containment_demo/tools.py) | Verified TLS, bounded timeout, redirects off, separate error categories |
| [protocol_adapter.py](../../src/containment_demo/protocol_adapter.py) | Responses requests, fresh session state, and run markers |
| [governance/runtime.py](../../src/containment_demo/governance/runtime.py) | ACS evaluation and host enforcement |
| [policy_api](../../src/services/policy_api/) | Delegated authorization and successful-request receipts |
| [test_receiver](../../src/services/test_receiver/) | Body measured/discarded; receipt recorded |
| [a2a_facade](../../src/containment_demo/a2a_facade/) | AKS bridge from A2A to Foundry Responses |

The authenticated diagnostic route reuses these tools; it is not a third
business tool. A tool records an HTTP, TLS, DNS, timeout, or connection error
without claiming it knows the platform's decision.

## Check locally

```bash
task lint:test
task lint:ruff
task lint:types
```

These checks do not prove hosted containment.

**Next:** [06: Build and deploy](06-build-and-deploy.md)
