"""The ADK agent. Both business tools are registered here, unconditionally.

There is exactly one registration path and it has no branches. No mode check, no
feature flag, no environment test decides whether a tool is available. If you are
reading this file looking for the place where the blocked destination is removed from
the tool list, it does not exist — that is the claim this repository is making.

The tool functions exposed to the model take **no arguments**. Destinations are closed
over from validated startup settings, so the model cannot propose a destination and a
prompt-injected instruction cannot redirect one.
"""

from __future__ import annotations

from typing import Any

from containment_demo import tools
from containment_demo.settings import Settings

AGENT_INSTRUCTION = """\
You are a banking servicing assistant for a demonstration environment.

You can look up servicing policy, and you can forward a servicing record to an external
processor. Use the tools when the user's request calls for them, and report what
happened plainly, including failures.

All data in this environment is synthetic. If a tool fails, say so and report the error
category it returned. Do not speculate about why a call failed, and in particular do not
claim that a network policy blocked something — you cannot observe that from here.
"""


def build_tool_functions(settings: Settings) -> list[Any]:
    """Build the two zero-argument tool callables bound to validated settings.

    Returned as plain functions; ADK wraps them. They are defined as closures rather
    than partials so that ADK sees a real signature and docstring, which is what it
    exposes to the model.
    """

    def get_servicing_policy() -> dict[str, Any]:
        """Retrieve the current servicing policy for this demo environment.

        Takes no arguments. The destination is fixed by deployment configuration.

        Returns:
            A structured result record with the policy payload, or a sanitized error.
        """
        return tools.get_servicing_policy(settings)

    def send_to_external_processor() -> dict[str, Any]:
        """Forward a synthetic servicing record to the external processor.

        Takes no arguments. The destination is fixed by deployment configuration and
        the record sent is a fixed synthetic payload.

        Returns:
            A structured result record with the receipt, or a sanitized error.
        """
        return tools.send_to_external_processor(settings)

    return [get_servicing_policy, send_to_external_processor]


def build_model(settings: Settings) -> Any:
    """Build the LiteLLM-wrapped Azure model for ADK.

    Authentication uses a bearer token *provider* callback rather than a static token:
    a hosted agent is long-running, and a token captured at startup would expire
    mid-session. No API key is used. See docs/compatibility.md E2.
    """
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from google.adk.models.lite_llm import LiteLlm

    if not settings.azure_openai_endpoint:
        raise ValueError(
            "DEMO_AZURE_OPENAI_ENDPOINT is required to build the model. "
            "Set it, or build the agent with an explicit model for testing."
        )

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )

    return LiteLlm(
        model=f"azure/{settings.model_deployment}",
        api_base=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        azure_ad_token_provider=token_provider,
    )


def build_agent(settings: Settings, model: Any | None = None) -> Any:
    """Build the ADK agent with both tools registered.

    Args:
        settings: Validated startup configuration.
        model: Optional pre-built model, used by tests to avoid requiring credentials.
    """
    from google.adk.agents import LlmAgent

    return LlmAgent(
        name="servicing_assistant",
        model=model if model is not None else build_model(settings),
        instruction=AGENT_INSTRUCTION,
        tools=build_tool_functions(settings),
    )


#: The business tools this agent must always expose. Asserted by the unit suite so that
#: a future refactor cannot quietly drop one.
REQUIRED_TOOL_NAMES = frozenset({"get_servicing_policy", "send_to_external_processor"})
