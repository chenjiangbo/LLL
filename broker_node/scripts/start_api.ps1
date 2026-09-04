param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [string]$PythonPath
)

$env:BROKER_NODE_CONFIG = $ConfigPath
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$hostAddress = [string]$config.api.host
$port = [int]$config.api.port
if ([string]::IsNullOrWhiteSpace($hostAddress) -or $port -lt 1 -or $port -gt 65535) {
    throw 'api.host and api.port must be valid in Broker Node config'
}
& $PythonPath -m uvicorn broker_node.api_service.app:create_app --factory --host $hostAddress --port $port
