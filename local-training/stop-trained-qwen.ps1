param([Parameter(Mandatory=$true)][ValidateSet('4B','9B')][string]$Size)
$ErrorActionPreference = 'Stop'
$sizeTag = $Size.ToLowerInvariant()
$pidPath = Join-Path $PSScriptRoot ('runs\qwen-' + $sizeTag + '-lanm\server.pid')
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Output 'No recorded trained server.'; exit 0 }
$recordedId = [int](Get-Content -LiteralPath $pidPath)
$serverProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $recordedId)
if (-not $serverProcess) { Write-Output 'Trained server is already stopped.'; exit 0 }
$expectedPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'local-inference\llama-b12323\llama-server.exe'
$expectedAlias = 'qwen3.5-' + $sizeTag + '-lanm'
$aliasPattern = '(?:^|\s)--alias\s+(?:"' + [regex]::Escape($expectedAlias) + '"|' + [regex]::Escape($expectedAlias) + ')(?=\s|$)'
if ($serverProcess.ExecutablePath -ne $expectedPath -or $serverProcess.CommandLine -notmatch $aliasPattern) { throw 'PID identity does not match this trained server; refusing to stop it.' }
& "$env:SystemRoot\System32\taskkill.exe" /PID $recordedId /T /F
if ($LASTEXITCODE -ne 0) { throw ('Could not stop verified trained server PID ' + $recordedId) }
Write-Output ('Stopped trained ' + $Size + ' server PID ' + $recordedId)
