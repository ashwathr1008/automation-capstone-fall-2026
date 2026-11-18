$ErrorActionPreference = 'Stop'
$pidPath = Join-Path $PSScriptRoot 'server.pid'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Output 'No recorded Qwen server.'; exit 0 }
$recordedId = [int](Get-Content -LiteralPath $pidPath)
$serverProcess = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $recordedId)
if (-not $serverProcess) { Write-Output 'Qwen server is already stopped.'; exit 0 }
$expectedPath = Join-Path $PSScriptRoot 'llama-b12323\llama-server.exe'
$aliasPattern = '(?:^|\s)--alias\s+(?:"qwen3\.5-4b"|qwen3\.5-4b)(?=\s|$)'
if ($serverProcess.ExecutablePath -ne $expectedPath -or $serverProcess.CommandLine -notmatch $aliasPattern) { throw 'Recorded PID identity differs from the base 4B server; refusing to stop it.' }
& "$env:SystemRoot\System32\taskkill.exe" /PID $recordedId /T /F
if ($LASTEXITCODE -ne 0) { throw ('Could not stop verified base server PID ' + $recordedId) }
Write-Output ('Stopped local Qwen server PID ' + $recordedId)
