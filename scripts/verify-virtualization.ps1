# verify-virtualization.ps1
# Checks whether Intel VT-x / firmware virtualization is enabled and related stack readiness.

$ErrorActionPreference = 'Continue'

function Write-Result {
    param(
        [string]$Label,
        [bool]$Pass,
        [string]$Detail = '',
        [string[]]$NextSteps = @()
    )
    $status = if ($Pass) { 'PASS' } else { 'FAIL' }
    $color = if ($Pass) { 'Green' } else { 'Red' }
    Write-Host "`n[$status] $Label" -ForegroundColor $color
    if ($Detail) { Write-Host "  $Detail" }
    foreach ($step in $NextSteps) {
        if ($step) { Write-Host "  -> $step" -ForegroundColor Yellow }
    }
}

Write-Host '=== Virtualization verification ===' -ForegroundColor Cyan
Write-Host "Computer: $env:COMPUTERNAME"
Write-Host "Date:     $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$overallPass = $true
$firmwareEnabled = $null

Write-Host "`n--- Firmware (BIOS) ---"
try {
    $proc = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $firmwareEnabled = [bool]$proc.VirtualizationFirmwareEnabled
    $pass = $firmwareEnabled -eq $true
    if (-not $pass) { $overallPass = $false }
    $fwSteps = @()
    if (-not $pass) {
        $fwSteps = @(
            'Enable Intel VT-x in BIOS: see docs/ENABLE_VTX.md',
            'Full shutdown, then F10 at HP logo -> Advanced -> System Options -> Virtualization Technology (VTx) -> Enabled'
        )
    }
    Write-Result -Label 'VirtualizationFirmwareEnabled (Win32_Processor)' -Pass $pass -Detail "Value: $($proc.VirtualizationFirmwareEnabled)" -NextSteps $fwSteps
} catch {
    $overallPass = $false
    Write-Result -Label 'VirtualizationFirmwareEnabled (Win32_Processor)' -Pass $false -Detail "Error: $_" -NextSteps @('Run PowerShell as Administrator and retry.')
}

Write-Host "`n--- systeminfo (Hyper-V) ---"
try {
    $si = systeminfo 2>&1 | Out-String
    $hyperLines = ($si -split "`r?`n") | Where-Object { $_ -match 'Hyper-V|Virtualization Enabled In Firmware' }
    foreach ($line in $hyperLines) {
        Write-Host "  $($line.TrimEnd())"
    }
    $firmwareLine = $hyperLines | Where-Object { $_ -match 'Virtualization Enabled In Firmware|Firmware Enabled' } | Select-Object -First 1
    $siFirmwarePass = $false
    if ($firmwareLine -match ':\s*Yes\b') { $siFirmwarePass = $true }
    if ($firmwareLine -and -not $siFirmwarePass) { $overallPass = $false }
    if ($firmwareLine) {
        $siSteps = @()
        if (-not $siFirmwarePass) { $siSteps = @('BIOS VT-x must be Enabled; reboot into BIOS (F10).') }
        Write-Result -Label 'systeminfo: Virtualization Enabled In Firmware' -Pass $siFirmwarePass -Detail ($firmwareLine.Trim() -replace '^\s+', '') -NextSteps $siSteps
    } else {
        Write-Host '  (No Hyper-V virtualization firmware line found in systeminfo output.)'
    }
} catch {
    Write-Host "  systeminfo failed: $_"
}

Write-Host "`n--- Docker ---"
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    Write-Result -Label 'Docker CLI' -Pass $false -Detail 'docker not found in PATH.' -NextSteps @(
        'Install Docker Desktop after VT-x is enabled.',
        'After BIOS change: enable Windows features (VM Platform, WSL), reboot, then start Docker Desktop.'
    )
    $overallPass = $false
} else {
    Write-Host "  docker: $($dockerCmd.Source)"
    $verOut = docker version 2>&1 | Out-String
    Write-Host $verOut
    $infoOut = docker info 2>&1 | Out-String
    $dockerRunning = ($LASTEXITCODE -eq 0) -and ($infoOut -match 'Server Version|Operating System')
    if (-not $dockerRunning) {
        $overallPass = $false
        Write-Result -Label 'Docker daemon' -Pass $false -Detail 'docker info did not succeed.' -NextSteps @(
            'Start Docker Desktop.',
            'If WSL2 backend: ensure WSL2 and VM Platform are enabled and VT-x is on in BIOS.'
        )
    } else {
        Write-Result -Label 'Docker daemon' -Pass $true -Detail 'docker info succeeded.'
    }
}

Write-Host "`n--- WSL ---"
$wslCmd = Get-Command wsl -ErrorAction SilentlyContinue
if (-not $wslCmd) {
    Write-Result -Label 'WSL' -Pass $false -Detail 'wsl.exe not available.' -NextSteps @(
        'Enable WSL: dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart',
        'Enable VM Platform: dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart'
    )
} else {
    $wslStatus = wsl --status 2>&1 | Out-String
    if ($wslStatus.Trim()) { Write-Host $wslStatus }
    $wslOk = $wslStatus -notmatch 'not installed|WSL optional component is not enabled'
    if (-not $wslOk) { $overallPass = $false }
    $wslSteps = @()
    if (-not $wslOk) { $wslSteps = @('Run post-BIOS Windows feature commands in docs/ENABLE_VTX.md (Admin PowerShell).') }
    $wslDetail = if ($wslOk) { 'wsl --status returned output.' } else { 'WSL may not be fully enabled.' }
    Write-Result -Label 'WSL status' -Pass $wslOk -Detail $wslDetail -NextSteps $wslSteps
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if ($firmwareEnabled -eq $true) {
    Write-Host 'Firmware VT-x: ENABLED' -ForegroundColor Green
} else {
    Write-Host 'Firmware VT-x: DISABLED or unknown — enable in BIOS before Docker/WSL2 will work reliably.' -ForegroundColor Red
    Write-Host 'Next: docs/ENABLE_VTX.md then re-run this script.' -ForegroundColor Yellow
}

if ($overallPass -and $firmwareEnabled -eq $true) {
    Write-Host 'Overall: PASS (firmware on; check Docker/WSL details above).' -ForegroundColor Green
    exit 0
} else {
    Write-Host 'Overall: FAIL or INCOMPLETE — follow FAIL items and next steps above.' -ForegroundColor Red
    exit 1
}
