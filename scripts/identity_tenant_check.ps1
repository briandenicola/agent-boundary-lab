#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
    [string] $TenantId,
    [switch] $ApproveRead
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RequiredGraphVersion = '2.36.1'
$disconnect = $false
$exitCode = 2
$stage = 'explicit_read_approval_required'
$report = [ordered]@{
    tenant_check = 'inconclusive'
    tenant_verified = $false
    active_relevant_roles = @()
    role_metadata_complete = $false
    pim_eligibility = 'not_evaluated'
    agent_id_availability = 'not_evaluated'
    directory_lifecycle = 'not_evaluated'
    foundry_delegation = 'not_evaluated'
    i0_complete = $false
    powershell_version = $PSVersionTable.PSVersion.ToString()
    graph_module_required_version = $RequiredGraphVersion
    graph_module_version = $null
}

try {
    if (-not $ApproveRead) {
        throw 'Approval required.'
    }
    $stage = 'graph_module_missing_run_identity_graph_init'
    $module = Get-Module -ListAvailable -Name Microsoft.Graph.Authentication |
        Where-Object { $_.Version -eq [version]$RequiredGraphVersion } |
        Select-Object -First 1
    if ($null -eq $module) {
        throw 'Pinned Graph module required.'
    }
    Import-Module Microsoft.Graph.Authentication -RequiredVersion $RequiredGraphVersion
    $report.graph_module_version = $module.Version.ToString()
    $stage = 'interactive_graph_signin_failed'
    $scopes = @('User.Read', 'RoleManagement.Read.Directory')
    Connect-MgGraph -TenantId $TenantId -Scopes $scopes `
        -ContextScope Process -Environment Global -UseDeviceCode `
        -ClientTimeout 30 -NoWelcome | Out-Null

    $context = Get-MgContext
    $stage = 'graph_context_must_be_process_scoped'
    if ($null -eq $context -or [string]$context.ContextScope -ne 'Process') {
        throw 'Process-scoped context required.'
    }
    $disconnect = $true
    $stage = 'graph_context_tenant_mismatch'
    if ($context.TenantId -cne $TenantId) {
        throw 'Selected tenant required.'
    }
    $stage = 'graph_context_must_be_delegated'
    if ([string]$context.AuthType -ne 'Delegated' -or
        'User.Read' -notin $context.Scopes -or
        'RoleManagement.Read.Directory' -notin $context.Scopes) {
        throw 'Delegated user context required.'
    }
    $report.tenant_verified = $true
    $stage = 'directory_role_read_failed'
    $uri = 'https://graph.microsoft.com/v1.0/me/transitiveMemberOf/microsoft.graph.directoryRole?$count=true&$select=displayName&$top=100'
    $response = Invoke-MgGraphRequest -Method GET -Uri $uri `
        -Headers @{ ConsistencyLevel = 'eventual' } -OutputType Hashtable
    $stage = 'directory_role_response_invalid'
    if ($response -isnot [System.Collections.IDictionary] -or
        -not $response.Contains('value') -or
        $response['value'] -isnot [System.Collections.IList]) {
        throw 'Role membership collection required.'
    }

    $knownRoles = @(
        'Global Administrator',
        'Privileged Role Administrator',
        'Application Administrator',
        'Cloud Application Administrator',
        'Agent ID Administrator',
        'Agent ID Developer'
    )
    $roles = @()
    $limited = $false
    foreach ($row in $response['value']) {
        if ($row -isnot [System.Collections.IDictionary]) {
            throw 'Role membership object required.'
        }
        $name = $row['displayName']
        if ($name -isnot [string] -or [string]::IsNullOrWhiteSpace($name)) {
            $limited = $true
        } elseif ($name -cin $knownRoles) {
            $roles += $name
        }
    }
    $report.active_relevant_roles = @($roles | Sort-Object -Unique)
    if (-not [string]::IsNullOrEmpty([string]$response['@odata.nextLink'])) {
        $report.detail = 'directory_role_pagination_not_collected'
    } elseif ($limited) {
        $report.detail = 'directory_role_metadata_limited'
    } else {
        $report.role_metadata_complete = $true
        $report.tenant_check = 'pass'
        $exitCode = 0
    }
} catch {
    # SDK errors can contain claims or response bodies; expose only our fixed stage.
    $report.detail = $stage
} finally {
    if ($disconnect) {
        try {
            Disconnect-MgGraph | Out-Null
        } catch {
            $report.tenant_check = 'inconclusive'
            $report.disconnect_detail = 'process_graph_disconnect_failed'
            $exitCode = 2
        }
    }
}

$report | ConvertTo-Json -Depth 4
exit $exitCode
