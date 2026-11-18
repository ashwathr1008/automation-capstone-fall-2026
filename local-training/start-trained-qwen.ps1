param([Parameter(Mandatory=$true)][ValidateSet('4B','9B')][string]$Size)
$ErrorActionPreference = 'Stop'
$trainingRoot = $PSScriptRoot
$inferenceRoot = Join-Path (Split-Path -Parent $trainingRoot) 'local-inference'
$sizeTag = $Size.ToLowerInvariant()
$aliasName = 'qwen3.5-' + $sizeTag + '-lanm'
$portNumber = if ($Size -eq '4B') { 18082 } else { 18083 }
$runRoot = Join-Path $trainingRoot ('runs\qwen-' + $sizeTag + '-lanm')
$serverPath = Join-Path $inferenceRoot 'llama-b12323\llama-server.exe'
$modelPath = Join-Path $inferenceRoot ('Qwen3.5-' + $Size + '-Q4_K_M.gguf')
$adapterPath = Join-Path $runRoot ('qwen-' + $sizeTag + '-lanm-lora-f16.gguf')
$exportManifest = Get-Content -LiteralPath (Join-Path $runRoot 'export-manifest.json') -Raw | ConvertFrom-Json
$runManifest = Get-Content -LiteralPath (Join-Path $runRoot 'run-manifest.json') -Raw | ConvertFrom-Json
if ($exportManifest.synthetic -or $runManifest.status -ne 'completed') { throw 'A completed real trained adapter is required.' }
if ((Get-FileHash -LiteralPath $adapterPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $exportManifest.gguf_sha256) { throw 'Exported adapter checksum mismatch.' }
$baseProvenanceName = if ($Size -eq '4B') { 'provenance.json' } else { 'provenance-9b.json' }
$baseProvenance = Get-Content -LiteralPath (Join-Path $inferenceRoot $baseProvenanceName) -Raw | ConvertFrom-Json
$baseAsset = @($baseProvenance.assets | Where-Object { $_.file -eq (Split-Path -Leaf $modelPath) })
if ($baseAsset.Count -ne 1 -or (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $baseAsset[0].sha256) { throw 'Frozen baseline model checksum mismatch.' }
$pidPath = Join-Path $runRoot 'server.pid'
if (Test-Path -LiteralPath $pidPath) {
    $recordedId = [int](Get-Content -LiteralPath $pidPath)
    $existing = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $recordedId)
    if ($existing) {
        if ($existing.ExecutablePath -eq $serverPath -and $existing.CommandLine.Contains($aliasName)) { Write-Output ('Already running PID ' + $recordedId); exit 0 }
        throw 'Recorded PID belongs to a different process; refusing to reuse it.'
    }
}
$serverArguments = @('-m', ('"' + $modelPath + '"'), '--lora', ('"' + $adapterPath + '"'),
    '--alias', $aliasName, '--host', '127.0.0.1', '--port', [string]$portNumber,
    '--cors-origins', 'localhost', '--no-cors-credentials', '--ctx-size', '32768', '--parallel', '1',
    '--gpu-layers', 'all', '--flash-attn', 'on', '--jinja', '--reasoning', 'off',
    '--temp', '0.2', '--seed', '42', '--n-predict', '4096')
$serverProcess = Start-Process -FilePath $serverPath -ArgumentList $serverArguments -WorkingDirectory $inferenceRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runRoot 'server.stdout.log') -RedirectStandardError (Join-Path $runRoot 'server.stderr.log') -PassThru
$serverProcess.Id | Set-Content -LiteralPath $pidPath
Write-Output ('Started trained ' + $Size + ' PID ' + $serverProcess.Id + ' at http://127.0.0.1:' + $portNumber + '/v1')
