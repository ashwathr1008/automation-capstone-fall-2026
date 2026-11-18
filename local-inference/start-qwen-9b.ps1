$ErrorActionPreference = 'Stop'
$inferenceRoot = $PSScriptRoot
$serverPath = Join-Path $inferenceRoot 'llama-b12323\llama-server.exe'
$modelPath = Join-Path $inferenceRoot 'Qwen3.5-9B-Q4_K_M.gguf'
if (-not (Test-Path -LiteralPath $serverPath)) { throw 'Run provision.py first.' }
if (-not (Test-Path -LiteralPath $modelPath)) { throw 'Run provision-9b.py first.' }
$pidPath = Join-Path $inferenceRoot 'server-9b.pid'
if (Test-Path -LiteralPath $pidPath) {
    $recordedProcess = Get-Process -Id ([int](Get-Content -LiteralPath $pidPath)) -ErrorAction SilentlyContinue
    if ($recordedProcess -and $recordedProcess.Path -eq $serverPath) {
        Write-Output ('Qwen 9B server is already running with PID ' + $recordedProcess.Id)
        exit 0
    }
}
$serverArguments = @(
    '-m', ('"' + $modelPath + '"'),
    '--alias', 'qwen3.5-9b',
    '--host', '127.0.0.1', '--port', '18081',
    '--cors-origins', 'localhost', '--no-cors-credentials',
    '--ctx-size', '32768', '--parallel', '1',
    '--gpu-layers', 'all', '--flash-attn', 'on',
    '--jinja', '--reasoning', 'off',
    '--temp', '0.2', '--seed', '42', '--n-predict', '4096'
)
$serverProcess = Start-Process -FilePath $serverPath -ArgumentList $serverArguments -WorkingDirectory $inferenceRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $inferenceRoot 'server-9b.stdout.log') -RedirectStandardError (Join-Path $inferenceRoot 'server-9b.stderr.log') -PassThru
$serverProcess.Id | Set-Content -LiteralPath $pidPath
Write-Output ('Started Qwen 9B server PID ' + $serverProcess.Id + ' at http://127.0.0.1:18081/v1')
