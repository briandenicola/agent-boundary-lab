package containment

import rego.v1

default governance_deny := {"decision": "deny", "reason": "operation_not_authorized"}
default network_allow := {"decision": "deny", "reason": "operation_not_authorized"}

valid_call if {
    input.snapshot.tool_call.arguments_valid == true
    input.policy_target.value == {}
}

governance_deny := {"decision": "allow", "reason": "servicing_permitted"} if {
    valid_call
    input.tool.name == "get_servicing_policy"
}

governance_deny := {"decision": "deny", "reason": "external_processor_prohibited"} if {
    valid_call
    input.tool.name == "send_to_external_processor"
}

network_allow := {"decision": "allow", "reason": "operation_permitted"} if {
    valid_call
    input.tool.name in {"get_servicing_policy", "send_to_external_processor"}
}
