<#
  Build the Windows sidecar:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
  Output:
    build\dist\agenthub-local-runtime\           PyInstaller onedir bundle
    build\AgentHubLocalRuntime-0.1.0-win64.zip   zip + install.ps1 (fallback)
    build\installer\AgentHubLocalRuntimeSetup-0.1.0.exe   Inno Setup installer (if ISCC found)
#>
param([switch]$SkipInno)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$py = Join-Path $root '.build-venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
  python -m venv .build-venv
  & $py -m pip install --disable-pip-version-check -r requirements.txt pyinstaller
}
$version = (& $py -c "from app import config; print(config.VERSION)").Trim()
Write-Output "version $version"

& $py -m PyInstaller --noconfirm --clean --onedir --console `
  --name agenthub-local-runtime `
  --distpath (Join-Path $root 'build\dist') --workpath (Join-Path $root 'build\work') --specpath (Join-Path $root 'build') `
  --paths $root --collect-submodules uvicorn --collect-data docx `
  (Join-Path $root 'installer\entry.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$dist = Join-Path $root 'build\dist\agenthub-local-runtime'
Copy-Item installer\start-hidden.vbs, installer\config.example.json, config.defaults.json $dist -Force
New-Item -ItemType Directory -Force (Join-Path $dist 'prompts') | Out-Null
Copy-Item prompts\* (Join-Path $dist 'prompts') -Force
& (Join-Path $dist 'agenthub-local-runtime.exe') version

$zipStage = Join-Path $root 'build\zipstage'
Remove-Item $zipStage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $zipStage | Out-Null
Copy-Item "$dist\*" $zipStage -Recurse
Copy-Item installer\install.ps1 $zipStage
$zip = Join-Path $root "build\AgentHubLocalRuntime-$version-win64.zip"
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path "$zipStage\*" -DestinationPath $zip
Remove-Item $zipStage -Recurse -Force
Write-Output "zip: $zip"

if (-not $SkipInno) {
  $iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($iscc) {
    & $iscc (Join-Path $root 'installer\agenthub-local-runtime.iss')
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
  } else { Write-Warning "Inno Setup (ISCC.exe) not found - skipped setup.exe; use the zip" }
}
Get-ChildItem (Join-Path $root 'build') -File -Recurse -Include *.zip, *Setup*.exe | Select-Object FullName, Length
