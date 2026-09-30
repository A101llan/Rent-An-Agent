<#
  Zip-based install (fallback when the Inno Setup installer isn't used).
  Run from the unzipped folder:  powershell -ExecutionPolicy Bypass -File install.ps1 [-AutoStart] [-NoSetup]
#>
param([switch]$AutoStart, [switch]$NoSetup)
$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$dest = Join-Path $env:LOCALAPPDATA 'Programs\AgentHub Local Runtime'
Get-Process agenthub-local-runtime -ErrorAction SilentlyContinue | Stop-Process -Force
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item (Join-Path $src '*') $dest -Recurse -Force -Exclude 'install.ps1'
$exe = Join-Path $dest 'agenthub-local-runtime.exe'
$vbs = Join-Path $dest 'start-hidden.vbs'
if ($AutoStart) {
  $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'AgentHub Local Runtime.lnk'
  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
  $s.TargetPath = "$env:WINDIR\System32\wscript.exe"; $s.Arguments = "`"$vbs`""; $s.WorkingDirectory = $dest; $s.Save()
  Write-Output "login shortcut: $lnk"
}
if (-not $NoSetup) { & $exe setup --open-browser }
& "$env:WINDIR\System32\wscript.exe" $vbs
Start-Sleep 5
try { Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 10 | ConvertTo-Json -Compress } catch { Write-Warning "sidecar not answering yet: $_" }
Write-Output "installed to $dest"
