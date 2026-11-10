"""Tamper-test the new boundaries in disposable copies, never in the working tree."""

from pathlib import Path

from scripts.verify_governance_guards import run_mutations

MUTATIONS = (
    (
        "trusted user context",
        Path("src/containment_demo/toolbox.py"),
        "if not context.call_id or not context.user_id:",
        "if False:",
        "tests/unit/test_toolbox.py::test_missing_caller_context_never_uses_an_app_only_fallback",
    ),
    (
        "tool approval fails closed",
        Path("src/containment_demo/toolbox.py"),
        'configuration.get("require_approval") != "never"',
        "False",
        "tests/unit/test_toolbox.py::test_toolbox_failures_never_fall_back_to_direct_http[approval]",
    ),
    (
        "consent reaches only the final reply",
        Path("src/containment_demo/protocol_adapter.py"),
        "authorization = stack.enter_context(capture_consent())",
        "stack.enter_context(capture_consent())",
        "tests/unit/test_protocol_adapter.py::test_toolbox_consent_reaches_only_final_reply",
    ),
    (
        "MCP requires delegated authorization",
        Path("src/services/policy_api/main.py"),
        "if guard is None or actor_store is not None:",
        "if False:",
        "tests/unit/test_policy_identity.py::test_mcp_cannot_start_without_delegated_authentication",
    ),
    (
        "separate project",
        Path("src/containment_demo/copilot_toolbox.py"),
        "self.project_name == baseline.foundry_project_name",
        "False",
        "tests/unit/test_copilot_toolbox.py::test_configuration_rejects_baseline_and_cross_project_targets[same-project]",
    ),
    (
        "destructive plan rejection",
        Path("scripts/copilot_toolbox_plan.py"),
        'change["change"]["actions"] not in allowed',
        "False",
        "tests/unit/test_copilot_toolbox.py::test_plan_guard_rejects_shared_or_destructive_changes[azapi_resource.policy-actions2]",
    ),
    (
        "ACS before toolbox dispatch",
        Path("src/containment_demo/agent.py"),
        "before_tool_callback=before_tool_callback,",
        "before_tool_callback=None,",
        "tests/unit/test_toolbox.py::test_real_adk_runs_acs_before_toolbox_or_receiver[False]",
    ),
)


if __name__ == "__main__":
    raise SystemExit(run_mutations(MUTATIONS))
