param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$LogPath,
    [string]$PythonPath = 'D:\QMT\Python39\python.exe'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Broker Node config does not exist: $ConfigPath"
}
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (Get-Process essence -ErrorAction SilentlyContinue) {
        break
    }
    Start-Sleep -Seconds 5
}
if (-not (Get-Process essence -ErrorAction SilentlyContinue)) {
    throw 'QMT essence.exe is not running'
}

$env:BROKER_NODE_CONFIG = $ConfigPath
$env:PYTHONPATH = 'D:\QMT\workspace'
$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Set-Location 'D:\QMT\workspace'
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $nodeConfig = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
    if (-not $nodeConfig.ipc_v2) { throw 'Node config must be initialized with setup_terminal_agent.py for the shared SIM/LIVE HTTP IPC runtime' }
    if ($nodeConfig.account_mode -ne 'SIM') { throw 'LIVE strategies are started by the Broker Node manager' }
    $strategyPath = Join-Path $env:USERPROFILE ('.essence\projects\' + $nodeConfig.gm.strategy_id + '\main.py')
    if (-not (Test-Path -LiteralPath $strategyPath -PathType Leaf)) { throw 'GM strategy does not exist' }
    & $PythonPath -u $strategyPath *>> $LogPath
    $nativeExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorActionPreference
}
exit $nativeExitCode
