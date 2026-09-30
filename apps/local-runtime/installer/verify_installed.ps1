# Verify the INSTALLED sidecar: hire -> stop dev sidecar -> start installed exe (hidden, like the
# login shortcut) -> /health -> claim -> .docx job -> cloud usage rows -> prompt-override one-shot.
param([string]$InstallDir = "$env:LOCALAPPDATA\Programs\AgentHub Local Runtime")
$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')
$log = Join-Path (Get-Location) 'out\installed-verify-log.txt'
Set-Content $log ''
function Log($m) { $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') EAT] $m"; Add-Content $log $line; Write-Output $line }
$exe = Join-Path $InstallDir 'agenthub-local-runtime.exe'
$docx = (Resolve-Path 'fixtures\sample-meeting.docx').Path
Log "installed exe: $exe exists=$(Test-Path $exe) version=$(& $exe version)"

Log '== 1. HIRE meeting-notes-agent-local'
$o = python scripts\dev_hire.py --agent meeting-notes-agent-local --out .dev-hire-installed.json 2>&1 | Out-String; Log $o
$h = Get-Content .dev-hire-installed.json -Raw | ConvertFrom-Json

Log '== 2. stop any sidecar on :8765 (dev uvicorn or installed exe)'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'app\.main:app --host 127\.0\.0\.1 --port 8765' } | ForEach-Object { Log "stopping dev sidecar pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
Get-Process agenthub-local-runtime -ErrorAction SilentlyContinue | ForEach-Object { Log "stopping installed sidecar pid $($_.Id)"; Stop-Process -Id $_.Id -Force }
for ($i = 0; $i -lt 20; $i++) { if (-not (netstat -ano | Select-String 'TCP\s+127\.0\.0\.1:8765\s+.*LISTENING')) { break }; Start-Sleep 1 }
Log ("port 8765 listeners after stop: " + ((netstat -ano | Select-String ':8765\s+.*LISTENING') -join ' | '))

Log '== 3. start installed sidecar hidden (start-hidden.vbs, same as login shortcut)'
& "$env:WINDIR\System32\wscript.exe" (Join-Path $InstallDir 'start-hidden.vbs')
$hl = $null
for ($i = 0; $i -lt 60; $i++) { try { $hl = Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 5; break } catch { Start-Sleep 2 } }
Log ("health: " + ($hl | ConvertTo-Json -Compress -Depth 5))
Log ("listener: " + ((netstat -ano | Select-String ':8765\s+.*LISTENING') -join ' | '))
Get-Process agenthub-local-runtime -ErrorAction SilentlyContinue | ForEach-Object { Log "installed process pid $($_.Id) path $($_.Path)" }
$o = & $exe check 2>&1 | Out-String; Log "check:`n$o"

Log '== 4. second start must not fight over :8765'
$o = & $exe serve 2>&1 | Out-String; Log "second serve exit=$LASTEXITCODE`n$o"

Log '== 5. BIND via installed sidecar'
$body = @{ session_id = $h.session_id; session_token = $h.session_token } | ConvertTo-Json
try {
  $r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/session/claim -ContentType 'application/json' -Body $body -TimeoutSec 30
  Log ("claim OK: " + (($r | Select-Object bound, mode, session_id, validated, expires_at) | ConvertTo-Json -Compress) + " manifest.runtime=" + ($r.manifest.runtime | ConvertTo-Json -Compress))
} catch { Log "claim FAILED: $($_.ErrorDetails.Message)" }

Log '== 6. JOB via installed sidecar (.docx)'
$out = Join-Path (Get-Location) 'out\installed-notes.json'
$jb = @{ input_paths = @($docx); output_path = $out } | ConvertTo-Json
$j = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/jobs/meeting-notes -ContentType 'application/json' -Body $jb
for ($i = 0; $i -lt 200; $i++) { $s = Invoke-RestMethod "http://127.0.0.1:8765/jobs/$($j.job_id)"; if ($s.status -notin 'queued','running') { break }; Start-Sleep 2 }
Log "job $($j.job_id) status=$($s.status) error=$($s.error) result_path=$($s.result_path)"
Log ("model_meta: " + ($s.result.model_meta | ConvertTo-Json -Compress))
Log ("usage_report outcomes: " + (($s.result.usage_report | ForEach-Object { "$($_.metric_type)=$($_.quantity):$($_.outcome)/$($_.http_status)" }) -join ', '))

Log '== 7. CLOUD usage rows'
$o = python scripts\check_cloud_usage.py $h.session_id 2>&1 | Out-String; Log $o

Log '== 8. installed exe honours LOCAL_RUNTIME_PROMPT_FILE (opt-in prompt, one-shot)'
$env:LOCAL_RUNTIME_PROMPT_FILE = 'prompts\decisions-v2.json'
$env:LOCAL_RUNTIME_SESSION_FILE = (Join-Path (Get-Location) 'out\.session-installed-oneshot.json')
$o = & $exe notes $docx --hire-file .dev-hire-installed.json -o (Join-Path (Get-Location) 'out\installed-notes-promptfile.json') 2>&1 | Out-String
Log "one-shot exit=$LASTEXITCODE`n$o"
Remove-Item Env:LOCAL_RUNTIME_PROMPT_FILE, Env:LOCAL_RUNTIME_SESSION_FILE
Log '== done'
