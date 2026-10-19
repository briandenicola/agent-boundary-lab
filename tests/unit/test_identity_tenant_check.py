"""Execute the real PowerShell script against a local fake Graph SDK; no sign-in."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/identity_tenant_check.ps1"
TENANT = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
SDK = "2.36.1"
POWERSHELL = shutil.which("pwsh")

FAKE_SDK = r"""
function Record([string] $Event) {
    Add-Content -LiteralPath $env:MOCK_LOG -Value $Event
}
function Connect-MgGraph {
    [CmdletBinding()]
    param(
        [string] $TenantId, [string[]] $Scopes, [string] $ContextScope,
        [string] $Environment, [switch] $UseDeviceCode, [double] $ClientTimeout,
        [switch] $NoWelcome
    )
    $script:Scopes = $Scopes
    if ($TenantId -cne $env:MOCK_TENANT -or $ContextScope -cne 'Process' -or
        $Environment -cne 'Global' -or -not $UseDeviceCode -or
        $ClientTimeout -ne 30 -or -not $NoWelcome -or
        (($Scopes -join ',') -cne 'User.Read,RoleManagement.Read.Directory' -and
         ($Scopes -join ',') -cne (
            'User.Read,AgentIdentityBlueprint.ReadWrite.All,' +
            'AgentIdentityBlueprintPrincipal.ReadWrite.All,' +
            'AgentIdentity.Create.All,AgentIdentity.Read.All,AgentIdentity.DeleteRestore.All'))) {
        throw 'Unexpected sign-in request.'
    }
    Record 'connect'
    if ($env:MOCK_CASE -eq 'device_code') {
        'synthetic-device-code-instructions'
    }
    if ($env:MOCK_CASE -eq 'signin_error') {
        throw 'AADSTS65001 synthetic-private-bearer-do-not-log'
    }
}
function Get-MgContext {
    Record 'context'
    $context = @{
        TenantId = $env:MOCK_TENANT
        ContextScope = 'Process'
        AuthType = 'Delegated'
        Scopes = $script:Scopes
        ClientId = '00000000-0000-4000-8000-000000000003'
    }
    switch ($env:MOCK_CASE) {
        'wrong_tenant' { $context.TenantId = $env:MOCK_OTHER }
        'wrong_scope' { $context.ContextScope = 'CurrentUser' }
        'app_only' { $context.AuthType = 'AppOnly' }
        'missing_permission' { $context.Scopes = @('User.Read') }
    }
    return [pscustomobject]$context
}
function Set-MgRequestContext {
    param([int] $MaxRetry, [double] $ClientTimeout)
    if ($MaxRetry -ne 0 -or $ClientTimeout -ne 30) { throw 'Unsafe lifecycle retry settings.' }
    Record 'configure_transport'
    [pscustomobject]@{ MaxRetry = $MaxRetry; ClientTimeout = $ClientTimeout }
}
function Invoke-MgGraphRequest {
    [CmdletBinding()]
    param([string] $Method, [uri] $Uri, [hashtable] $Headers, [string] $OutputType,
        [string] $Body, [string] $ContentType, [switch] $SkipHttpErrorCheck)
    if ($env:MOCK_ACTION -ne 'Check') {
        if ($Uri.OriginalString -ceq 'https://graph.microsoft.com/v1.0/me?$select=id') {
            Record 'get_operator'
            if ($env:MOCK_CASE -eq 'operator_mismatch') { return @{ id = $env:MOCK_OTHER } }
            return @{ id = '00000000-0000-4000-8000-000000000004' }
        }
        if ($Uri.Host -cne 'graph.microsoft.com' -or $Uri.Scheme -cne 'https' -or
            $Headers['OData-Version'] -cne '4.0' -or
            $OutputType -cne 'HttpResponseMessage' -or -not $SkipHttpErrorCheck) {
            throw 'Unexpected lifecycle transport.'
        }
        Record ("graph:" + $Method + ":" + $Uri.AbsolutePath)
        if (-not (Test-Path variable:script:Objects)) { $script:Objects = @{} }
        $kind = ($Uri.AbsolutePath -split '/')[-1]
        $status = 200
        $payload = @{}
        if ($Method -eq 'POST') {
            if ($env:MOCK_CASE -eq 'uncertain_creation') {
                throw 'synthetic-private-bearer-do-not-log'
            }
            $payload = ConvertFrom-Json -AsHashtable -InputObject $Body
            $number = switch ($kind) {
                'microsoft.graph.agentIdentityBlueprint' { 5 }
                'microsoft.graph.agentIdentityBlueprintPrincipal' { 6 }
                'microsoft.graph.agentIdentity' { 7 }
                default { throw 'Unknown object kind.' }
            }
            $payload.id = '00000000-0000-4000-8000-00000000000' + $number
            if ($number -ne 7) { $payload.appId = '00000000-0000-4000-8000-000000000008' }
            $script:Objects[$kind] = $payload
            $status = 201
        } elseif (-not $script:Objects.Contains($kind)) {
            $status = 404
        } elseif ($Method -eq 'GET') {
            $payload = $script:Objects[$kind]
        } elseif ($Method -eq 'PATCH') {
            $patch = ConvertFrom-Json -AsHashtable -InputObject $Body
            $script:Objects[$kind].description = $patch.description
            $status = 204
        } elseif ($Method -eq 'DELETE') {
            $script:Objects.Remove($kind)
            $status = 204
        } else {
            throw 'Unexpected lifecycle method.'
        }
        $response = [System.Net.Http.HttpResponseMessage]::new(
            [System.Net.HttpStatusCode]$status)
        $response.Content = [System.Net.Http.StringContent]::new(
            (ConvertTo-Json -InputObject $payload -Depth 8 -Compress))
        return $response
    }
    if ($Method -cne 'GET' -or $OutputType -cne 'Hashtable' -or
        $Headers.ConsistencyLevel -cne 'eventual' -or
        $Uri.OriginalString -cne (
            'https://graph.microsoft.com/v1.0/me/transitiveMemberOf/' +
            'microsoft.graph.directoryRole?$count=true&$select=displayName&$top=100'
        )) {
        throw 'Unexpected Graph request.'
    }
    Record 'get_roles'
    switch ($env:MOCK_CASE) {
        'read_error' { throw 'synthetic-private-bearer-do-not-log' }
        'malformed' { return @{ different = @() } }
        'malformed_row' { return @{ value = @('synthetic-private-profile') } }
        'limited' { return @{ value = @(@{ displayName = $null; id = 'private-id' }) } }
        'pagination' {
            return @{
                value = @(@{ displayName = 'Global Administrator' })
                '@odata.nextLink' = 'https://unrelated.invalid/private'
            }
        }
        'no_roles' { return @{ value = @() } }
        default {
            return @{
                value = @(
                    @{ displayName = 'Global Administrator'; id = 'private-id' },
                    @{ displayName = 'Global Administrator' },
                    @{ displayName = 'synthetic-private-customer-role' }
                )
            }
        }
    }
}
function Disconnect-MgGraph {
    Record 'disconnect'
    if ($env:MOCK_CASE -eq 'disconnect_error') {
        throw 'synthetic-private-bearer-do-not-log'
    }
}
Export-ModuleMember -Function Connect-MgGraph,Get-MgContext,Set-MgRequestContext,`
    Invoke-MgGraphRequest,Disconnect-MgGraph
"""


@pytest.fixture
def sdk(tmp_path: Path) -> tuple[dict[str, str], Path]:
    if POWERSHELL is None:
        pytest.skip("PowerShell 7.4+ is required for offline script execution")
    module_root = tmp_path / "modules"
    module = module_root / "Microsoft.Graph.Authentication" / SDK
    module.mkdir(parents=True)
    (module / "Microsoft.Graph.Authentication.psm1").write_text(FAKE_SDK)
    (module / "Microsoft.Graph.Authentication.psd1").write_text(
        "@{ RootModule='Microsoft.Graph.Authentication.psm1';"
        f"ModuleVersion='{SDK}'; GUID='{OTHER}';"
        "FunctionsToExport=@('Connect-MgGraph','Get-MgContext',"
        "'Set-MgRequestContext','Invoke-MgGraphRequest','Disconnect-MgGraph') }"
    )
    log = tmp_path / "calls.txt"
    environment = {
        **os.environ,
        "PSModulePath": str(module_root),
        "MOCK_MODULE_ROOT": str(module_root),
        "MOCK_SCRIPT": str(SCRIPT),
        "MOCK_TENANT": TENANT,
        "MOCK_OTHER": OTHER,
        "MOCK_LOG": str(log),
        "POWERSHELL_TELEMETRY_OPTOUT": "1",
    }
    return environment, log


def execute(
    sdk: tuple[dict[str, str], Path],
    case: str = "success",
    *,
    approved: bool = True,
    action: str = "Check",
    mutation_approved: bool = False,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    environment, log = sdk
    command = [
        str(POWERSHELL),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$env:PSModulePath = $env:MOCK_MODULE_ROOT + "
        "[IO.Path]::PathSeparator + (Join-Path $PSHOME 'Modules'); "
        "& $env:MOCK_SCRIPT -TenantId $env:MOCK_TENANT "
        "-Action $env:MOCK_ACTION -StatePath $env:MOCK_STATE "
        "-ApproveRead:($env:MOCK_APPROVED -eq 'true') "
        "-ApproveMutation:($env:MOCK_MUTATION_APPROVED -eq 'true'); exit $LASTEXITCODE",
    ]
    result = subprocess.run(  # noqa: S603 - fixed executable and repository script, no shell
        command,
        env={
            **environment,
            "MOCK_CASE": case,
            "MOCK_APPROVED": str(approved).lower(),
            "MOCK_ACTION": action,
            "MOCK_MUTATION_APPROVED": str(mutation_approved).lower(),
            "MOCK_STATE": str(log.parent / "directory.json"),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result, log.read_text().splitlines() if log.exists() else []


def test_isolated_interactive_check(sdk: tuple[dict[str, str], Path]) -> None:
    result, calls = execute(sdk)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["tenant_check"] == "pass"
    assert report["tenant_verified"] is True
    assert report["active_relevant_roles"] == ["Global Administrator"]
    assert report["role_metadata_complete"] is True
    assert report["graph_module_version"] == SDK
    assert report["agent_id_availability"] == "not_evaluated"
    assert report["directory_lifecycle"] == "not_evaluated"
    assert report["foundry_delegation"] == "not_evaluated"
    assert report["i0_complete"] is False
    assert "MaxRetry" not in result.stdout + result.stderr
    assert calls == ["connect", "context", "get_roles", "disconnect"]
    for private in ("private-id", "synthetic-private", TENANT, OTHER):
        assert private not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("case", "detail", "calls"),
    [
        ("wrong_tenant", "graph_context_tenant_mismatch", ["connect", "context", "disconnect"]),
        ("wrong_scope", "graph_context_must_be_process_scoped", ["connect", "context"]),
        ("app_only", "graph_context_must_be_delegated", ["connect", "context", "disconnect"]),
        (
            "missing_permission",
            "graph_context_must_be_delegated",
            ["connect", "context", "disconnect"],
        ),
        ("signin_error", "interactive_graph_signin_failed", ["connect"]),
        (
            "read_error",
            "directory_role_read_failed",
            ["connect", "context", "get_roles", "disconnect"],
        ),
        (
            "malformed",
            "directory_role_response_invalid",
            ["connect", "context", "get_roles", "disconnect"],
        ),
        (
            "malformed_row",
            "directory_role_response_invalid",
            ["connect", "context", "get_roles", "disconnect"],
        ),
        (
            "limited",
            "directory_role_metadata_limited",
            ["connect", "context", "get_roles", "disconnect"],
        ),
        (
            "pagination",
            "directory_role_pagination_not_collected",
            ["connect", "context", "get_roles", "disconnect"],
        ),
    ],
)
def test_incomplete_or_wrong_context_never_passes(
    sdk: tuple[dict[str, str], Path], case: str, detail: str, calls: list[str]
) -> None:
    result, observed = execute(sdk, case)
    assert result.returncode == 2, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["tenant_check"] == "inconclusive"
    assert report["detail"] == detail
    assert observed == calls
    assert "synthetic-private" not in result.stdout + result.stderr
    assert "private-id" not in result.stdout + result.stderr
    if case == "signin_error":
        assert report["aadsts_codes"] == ["AADSTS65001"]


def test_explicit_approval_before_signin(sdk: tuple[dict[str, str], Path]) -> None:
    result, calls = execute(sdk, approved=False)
    assert result.returncode == 2
    assert json.loads(result.stdout)["detail"] == "explicit_read_approval_required"
    assert calls == []


def test_device_code_instructions_are_visible(sdk: tuple[dict[str, str], Path]) -> None:
    result, calls = execute(sdk, "device_code")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "synthetic-device-code-instructions" in result.stdout
    report = json.loads(result.stdout.split("synthetic-device-code-instructions", 1)[1].strip())
    assert report["tenant_check"] == "pass"
    assert calls == ["connect", "context", "get_roles", "disconnect"]


@pytest.mark.parametrize("action", ["Run", "Cleanup"])
def test_lifecycle_requires_separate_mutation_approval(
    sdk: tuple[dict[str, str], Path], action: str
) -> None:
    result, calls = execute(sdk, action=action)
    assert result.returncode == 2
    assert json.loads(result.stdout)["detail"] == "explicit_mutation_approval_required"
    assert calls == []


def test_interactive_lifecycle_reuses_python_engine(
    sdk: tuple[dict[str, str], Path],
) -> None:
    result, calls = execute(sdk, action="Run", mutation_approved=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["directory_lifecycle"] == "pass"
    assert report["foundry_delegation"] == "not_evaluated"
    assert report["i0_complete"] is False
    assert len([call for call in calls if call.startswith("graph:POST:")]) == 3
    assert len([call for call in calls if call.startswith("graph:DELETE:")]) == 3
    assert len([call for call in calls if call.startswith("graph:PATCH:")]) == 1
    assert calls[:4] == ["connect", "context", "configure_transport", "get_operator"]
    assert calls[-1] == "disconnect"
    for private in ("synthetic-private", TENANT, OTHER, "00000000-0000-4000-8000-000000000004"):
        assert private not in result.stdout + result.stderr
    journal = json.loads((sdk[1].parent / "directory.json").read_text())
    assert all(resource["deleted"] for resource in journal["resources"].values())


def test_interactive_cleanup_accepts_completed_journal(
    sdk: tuple[dict[str, str], Path],
) -> None:
    initial, calls = execute(sdk, action="Run", mutation_approved=True)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    result, observed = execute(sdk, action="Cleanup", mutation_approved=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["detail"] == "directory_recorded_objects_cleaned_up"
    assert report["directory_lifecycle"] == "not_evaluated"
    assert report["i0_complete"] is False
    assert observed[len(calls) :] == [
        "connect",
        "context",
        "configure_transport",
        "get_operator",
        "disconnect",
    ]


def test_uncertain_interactive_post_stops_without_retry(
    sdk: tuple[dict[str, str], Path],
) -> None:
    result, calls = execute(sdk, "uncertain_creation", action="Run", mutation_approved=True)
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["directory_lifecycle"] == "inconclusive"
    assert report["detail"] == "directory_graph_transport_failed"
    assert len([call for call in calls if call.startswith("graph:POST:")]) == 1
    journal = json.loads((sdk[1].parent / "directory.json").read_text())
    assert journal["pending"] == "blueprint"
    assert "synthetic-private" not in result.stdout + result.stderr


def test_cleanup_rejects_a_different_signed_in_operator(
    sdk: tuple[dict[str, str], Path],
) -> None:
    initial, calls = execute(sdk, action="Run", mutation_approved=True)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    result, observed = execute(sdk, "operator_mismatch", action="Cleanup", mutation_approved=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["detail"] == "directory_interactive_operator_mismatch"
    assert observed[len(calls) :] == [
        "connect",
        "context",
        "configure_transport",
        "get_operator",
        "disconnect",
    ]


def test_no_active_roles_is_not_agent_id_proof(sdk: tuple[dict[str, str], Path]) -> None:
    result, _ = execute(sdk, "no_roles")
    report = json.loads(result.stdout)
    assert result.returncode == 0, result.stderr + result.stdout
    assert report["active_relevant_roles"] == []
    assert report["role_metadata_complete"] is True
    assert report["agent_id_availability"] == "not_evaluated"


def test_disconnect_errors_are_explicit(sdk: tuple[dict[str, str], Path]) -> None:
    result, calls = execute(sdk, "disconnect_error")
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["tenant_check"] == "inconclusive"
    assert report["disconnect_detail"] == "process_graph_disconnect_failed"
    assert calls[-1] == "disconnect"
    assert "synthetic-private" not in result.stdout + result.stderr


def test_task_and_module_version_wiring() -> None:
    taskfile = (ROOT / "tasks/Taskfile.identity.yml").read_text()
    script = SCRIPT.read_text()
    assert f"$RequiredGraphVersion = '{SDK}'" in script
    assert f"Install-Module Microsoft.Graph.Authentication -RequiredVersion {SDK}" in taskfile
    block = taskfile.split("  tenant-check:", 1)[1].split("\n\n  ", 1)[0]
    assert "vars: [TENANT_ID]" in block
    assert "prompt:" in block and "-ApproveRead" in block
    assert "RoleManagement.Read.Directory" in block
    assert "identity_tenant_check.ps1" in block
    assert not re.search(r"\baz\s+(login|account\s+set)\b", script)
    assert "AZURE_CONFIG_DIR" not in script
    assert "-ContextScope Process" in script
