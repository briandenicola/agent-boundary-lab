"""Portable A2A façade for a Foundry hosted agent.

Native inbound A2A is prompt-agent-only on Foundry (measured: docs/compatibility.md B5d).
This package exposes a hosted agent as A2A by running its own A2A server in front of it.
Hosted agents are still invoked through the Responses protocol; the façade only exposes
them as A2A. It is not the platform's A2A endpoint and it is not policy-governed.

Layers, each importable without the next:

* ``core``    settings, the ``AgentTarget`` interface, caller auth, context map. Pure Python.
* ``server``  the A2A protocol handler (a2a-sdk) and the Starlette app. Imports NO Foundry
              SDK and no ``target`` module; a target is injected.
* ``target``  ``ResponsesTarget``, the only place Foundry specifics live.
"""
