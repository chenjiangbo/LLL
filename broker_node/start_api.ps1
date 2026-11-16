param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [Parameter(Mandatory = $true)]
    [string]$LogPath,
    [string]$PythonPath = 'D:\QMT\Python39\python.exe'
)

$ErrorActionPreference = 'Stop'

if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    exit 0
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Broker Node config does not exist: $ConfigPath"
}
$token = [Environment]::GetEnvironmentVariable('BROKER_NODE_API_TOKEN', 'User')
if (-not $token) {
    throw 'BROKER_NODE_API_TOKEN is not configured in the Windows user environment'
}

$env:BROKER_NODE_CONFIG = $ConfigPath
$env:BROKER_NODE_API_TOKEN = $token
$env:PYTHONPATH = 'D:\QMT\workspace'
$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Set-Location 'D:\QMT\workspace'
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $nodeConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    if (-not $nodeConfig.ipc_v2) { throw 'Node config must be initialized with setup_terminal_agent.py for the shared SIM/LIVE HTTP IPC runtime' }
    $credentialName = $nodeConfig.ipc_v2.credential_env
    $credential = [Environment]::GetEnvironmentVariable($credentialName, 'User')
    if (-not $credential) { throw "IPC credential is not configured: $credentialName" }
    [Environment]::SetEnvironmentVariable($credentialName, $credential, 'Process')
    & $PythonPath -u -m broker_node.api_service.v2_server *>> $LogPath
    $nativeExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
exit $nativeExitCode
