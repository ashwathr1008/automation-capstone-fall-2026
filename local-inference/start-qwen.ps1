$ErrorActionPreference = 'Stop'
$inferenceRoot = $PSScriptRoot
$serverPath = Join-Path $inferenceRoot 'llama-b12323\llama-server.exe'
$modelPath = Join-Path $inferenceRoot 'Qwen3.5-4B-Q4_K_M.gguf'
if (-not (Test-Path -LiteralPath $serverPath)) { throw 'Run provision.py first.' }
if (-not (Test-Path -LiteralPath $modelPath)) { throw 'The verified Qwen model is missing.' }
$pidPath = Join-Path $inferenceRoot 'server.pid'
if (Test-Path -LiteralPath $pidPath) {
    $recordedProcess = Get-Process -Id ([int](Get-Content -LiteralPath $pidPath)) -ErrorAction SilentlyContinue
    if ($recordedProcess -and $recordedProcess.Path -eq $serverPath) {
        Write-Output ('Qwen server is already running with PID ' + $recordedProcess.Id)
        exit 0
    }
}
$serverArguments = @(
    '-m', ('"' + $modelPath + '"'),
    '--alias', 'qwen3.5-4b',
    '--host', '127.0.0.1', '--port', '18080',
    '--cors-origins', 'localhost', '--no-cors-credentials',
    '--ctx-size', '32768', '--parallel', '1',
    '--gpu-layers', 'all', '--flash-attn', 'on',
    '--jinja', '--reasoning', 'off',
    '--temp', '0.2', '--seed', '42', '--n-predict', '4096'
)
$serverProcess = Start-Process -FilePath $serverPath -ArgumentList $serverArguments -WorkingDirectory $inferenceRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $inferenceRoot 'server.stdout.log') -RedirectStandardError (Join-Path $inferenceRoot 'server.stderr.log') -PassThru
$serverProcess.Id | Set-Content -LiteralPath $pidPath
Write-Output ('Started Qwen server PID ' + $serverProcess.Id + ' at http://127.0.0.1:18080/v1')
