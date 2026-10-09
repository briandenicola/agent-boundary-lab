# invoke.py sends store=False to every agent

**Author:** Dallas | **Date:** 2026-10-09 | **Status:** proposed, untested live

Run invoke-01b1fd795e4f failed with HTTP 500: host persistence hit "Public access is
disabled" on the Foundry account. `invoke.py` now sends `store=False` (a native
`responses.create` parameter in the installed openai client) via one constant,
`STORE_RESPONSE`, identically to every agent. A test asserts audit and enforced calls
have identical kwargs.

SDK reading (azure-ai-agentserver-responses 2.2.0, `hosting/_orchestrator.py`):
every persistence call is guarded by store: bg create :686, bg non-stream finalization
(the failing site, error text :900) :853-858, terminal persist :1914 and :2022, sync
path :3846. So store=false skips them all. Caveats: `_validation.py:102` rejects
background=true with store=false, so if the platform forces background mode the request
will 400 rather than persist; store=false responses cannot be fetched later (404,
`_endpoint_handler.py:1172`). The host's FoundryStorageProvider is still constructed at
startup (`_routing.py:368-380`); only the calls are skipped.

Not a containment control and not evidence of anything. Also: the earlier NotFoundError
on the model call is a separate, unresolved problem. The docstring no longer repeats the
protocol version string.
