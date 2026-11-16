param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [string]$PythonPath = 'D:\QMT\Python39\python.exe'
)

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Broker Node config does not exist: $ConfigPath"
}

# The backend sends the real GM token to the Broker Node API. The agent reads
# the private runtime token file when it starts; no Windows environment
# variable is required.

$env:BROKER_NODE_CONFIG = $ConfigPath
$env:PYTHONPATH = 'D:\QMT\workspace'
Set-Location 'D:\QMT\workspace\broker_node\gm_agent'
& $PythonPath -u -m broker_node.gm_agent.main
