#Requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
    [string] $TenantId,
    [switch] $ApproveRead,
    [ValidateSet('Check', 'Run', 'Cleanup')]
    [string] $Action = 'Check',
    [string] $StatePath = '.identity-probe/interactive-directory.json',
    [switch] $ApproveMutation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RequiredGraphVersion = '2.36.1'

function Invoke-DirectoryLifecycle {
    param([string] $Operation, [string] $State, [string] $Tenant, $Context)
    Set-MgRequestContext -MaxRetry 0 -ClientTimeout 30
    $profile = Invoke-MgGraphRequest -Method GET `
        -Uri 'https://graph.microsoft.com/v1.0/me?$select=id' -OutputType Hashtable
    $sponsor = ([guid]$profile['id']).ToString()
    $clientId = ([guid]$Context.ClientId).ToString()
    $root = Split-Path -Parent $PSScriptRoot
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = Join-Path $root '.venv/bin/python'
    $start.WorkingDirectory = $root
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in @('-m', 'containment_demo.identity_directory',
            $Operation.ToLowerInvariant(), '--state', $State, '--approve', '--graph-stdio')) {
        $start.ArgumentList.Add($argument)
    }
    $start.Environment['PYTHONPATH'] = Join-Path $root 'src'
    $start.Environment['IDENTITY_TENANT_ID'] = $Tenant
    $start.Environment['IDENTITY_GRAPH_CLIENT_ID'] = $clientId
    $start.Environment['IDENTITY_SPONSOR_USER_ID'] = $sponsor
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    $final = $null
    $sequence = 0
    $started = $false
    try {
        $started = $process.Start()
        if (-not $started) { throw 'Directory engine did not start.' }
        while ($null -ne ($line = $process.StandardOutput.ReadLine())) {
            if ($line.Length -gt 1048576) { throw 'Directory engine frame too large.' }
            $frame = ConvertFrom-Json -AsHashtable -InputObject $line
            if (-not $frame.Contains('graph_request')) {
                if (-not $frame.Contains('directory_lifecycle')) {
                    throw 'Directory engine result invalid.'
                }
                $final = $frame
                continue
            }
            $sequence += 1
            if ($frame['graph_request'] -ne $sequence -or
                $frame['method'] -cnotin @('GET', 'POST', 'PATCH', 'DELETE') -or
                $frame['path'] -cnotmatch '^(applications|servicePrincipals)/(?:[0-9a-f-]{36}/)?microsoft\.graph\.(agentIdentityBlueprint|agentIdentityBlueprintPrincipal|agentIdentity)(?:\?\$select=[A-Za-z,]+)?$') {
                throw 'Directory engine request invalid.'
            }
            $reply = @{ graph_request = $sequence }
            try {
                $arguments = @{
                    Method = $frame['method']
                    Uri = 'https://graph.microsoft.com/v1.0/' + $frame['path']
                    Headers = @{ 'OData-Version' = '4.0' }
                    OutputType = 'HttpResponseMessage'
                    SkipHttpErrorCheck = $true
                }
                if ($null -ne $frame['body']) {
                    $arguments.Body = ConvertTo-Json -InputObject $frame['body'] -Depth 8 -Compress
                    $arguments.ContentType = 'application/json'
                }
                $response = Invoke-MgGraphRequest @arguments
                try {
                    $reply.status = [int]$response.StatusCode
                    $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                    $reply.body = if ([string]::IsNullOrEmpty($text)) { @{} } else {
                        ConvertFrom-Json -AsHashtable -InputObject $text
                    }
                } finally {
                    $response.Dispose()
                }
            } catch {
                $reply.transport_error = $true
            }
            $process.StandardInput.WriteLine(
                (ConvertTo-Json -InputObject $reply -Depth 12 -Compress))
            $process.StandardInput.Flush()
        }
        if (-not $process.WaitForExit(5000) -or $null -eq $final) {
            throw 'Directory engine stopped without a result.'
        }
        return @{ Report = $final; ExitCode = $process.ExitCode }
    } finally {
        if ($started -and -not $process.HasExited) {
            $process.Kill()
            $process.WaitForExit()
        }
        $process.Dispose()
    }
}

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
    $stage = 'explicit_mutation_approval_required'
    if ($Action -ne 'Check' -and -not $ApproveMutation) {
        throw 'Mutation approval required.'
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
    $scopes = if ($Action -eq 'Check') {
        @('User.Read', 'RoleManagement.Read.Directory')
    } else {
        @('User.Read', 'AgentIdentityBlueprint.ReadWrite.All',
            'AgentIdentityBlueprintPrincipal.ReadWrite.All',
            'AgentIdentity.Create.All', 'AgentIdentity.Read.All', 'AgentIdentity.DeleteRestore.All')
    }
    Connect-MgGraph -TenantId $TenantId -Scopes $scopes `
        -ContextScope Process -Environment Global -UseDeviceCode `
        -ClientTimeout 30 -NoWelcome | Out-Host

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
        @($scopes | Where-Object { $_ -notin $context.Scopes }).Count -ne 0) {
        throw 'Delegated user context required.'
    }
    $report.tenant_verified = $true
    if ($Action -ne 'Check') {
        $stage = 'interactive_directory_engine_failed'
        $outcome = Invoke-DirectoryLifecycle -Operation $Action -State $StatePath `
            -Tenant $TenantId -Context $context
        $report.tenant_check = 'pass'
        $report.directory_lifecycle = $outcome.Report['directory_lifecycle']
        if ($outcome.Report.Contains('detail')) {
            $report.detail = $outcome.Report['detail']
        }
        $exitCode = $outcome.ExitCode
    } else {
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
    }
} catch {
    # Show useful error identifiers without logging exception messages or claims.
    $report.detail = $stage
    $report.error_type = $_.Exception.GetType().FullName
    $report.aadsts_codes = @(
        [regex]::Matches($_.Exception.ToString(), 'AADSTS[0-9]{4,9}(?![0-9])') |
            ForEach-Object { $_.Value } | Sort-Object -Unique
    )
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
