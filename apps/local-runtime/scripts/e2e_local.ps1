# E2E: hire (local agent) -> claim/bind -> .docx -> notes JSON -> usage rows in cloud,
# plus fail-closed negatives and the offline queue -> sync path. Log: out\e2e-log.txt
$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')
$log = Join-Path (Get-Location) 'out\e2e-log.txt'
Set-Content $log ''
function Log($m) { $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') EAT] $m"; Add-Content $log $line; Write-Output $line }
$docx = (Resolve-Path 'fixtures\sample-meeting.docx').Path

Log '== 0. NEGATIVE: claim on a non-local (mock runtime) hire must fail closed'
if (Test-Path .dev-hire.json) {
  $env:LOCAL_RUNTIME_SESSION_FILE = 'out\.session-neg.json'
  $o = python -m app.cli $docx --hire-file .dev-hire.json -o out\should-not-exist.json 2>&1 | Out-String
  Log "cli exit=$LASTEXITCODE output_written=$(Test-Path out\should-not-exist.json)`n$o"
  Remove-Item Env:LOCAL_RUNTIME_SESSION_FILE
}

Log '== 1. seed meeting-notes-agent-local (apps/api additive insert-if-missing script)'
Push-Location ..\api
$o = python -m app.scripts.seed_meeting_notes_agent 2>&1 | Out-String
Pop-Location
Log $o

Log '== 2. HIRE meeting-notes-agent-local (real API, seeded dev customer)'
$o = python scripts\dev_hire.py --agent meeting-notes-agent-local --out .dev-hire-local.json 2>&1 | Out-String
Log "exit=$LASTEXITCODE`n$o"
if (-not (Test-Path .dev-hire-local.json)) { Log 'no local hire; abort'; exit 1 }
$h = Get-Content .dev-hire-local.json -Raw | ConvertFrom-Json
$sid = $h.session_id

Log '== 3. NEGATIVE: bad token must fail closed (401)'
$env:LOCAL_RUNTIME_SESSION_FILE = 'out\.session-neg.json'
$env:AGENTHUB_SESSION_TOKEN = 'bogus-token-for-negative-test'
$o = python -m app.cli $docx --session-id $sid -o out\should-not-exist-2.json 2>&1 | Out-String
Log "cli exit=$LASTEXITCODE output_written=$(Test-Path out\should-not-exist-2.json)`n$o"
Remove-Item Env:AGENTHUB_SESSION_TOKEN; Remove-Item Env:LOCAL_RUNTIME_SESSION_FILE

Log '== 4. restart sidecar on 127.0.0.1:8765 with new code'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'app\.main:app --host 127\.0\.0\.1 --port 8765' } | ForEach-Object { Log "stopping old sidecar pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2
$p = Start-Process python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765' -WorkingDirectory (Get-Location) -WindowStyle Hidden -RedirectStandardOutput 'out\sidecar-8765.out.log' -RedirectStandardError 'out\sidecar-8765.err.log' -PassThru
Log "sidecar pid $($p.Id)"
$ok = $false
for ($i = 0; $i -lt 30; $i++) { try { $hl = Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 5; $ok = $true; break } catch { Start-Sleep 2 } }
Log ("health: " + ($hl | ConvertTo-Json -Compress -Depth 5))

Log '== 5. BIND: POST sidecar /session/claim -> cloud /api/v1/sessions/{id}/local/claim'
$body = @{ session_id = $sid; session_token = $h.session_token } | ConvertTo-Json
try {
  $r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/session/claim -ContentType 'application/json' -Body $body -TimeoutSec 30
  $rt = $r.manifest.runtime | ConvertTo-Json -Compress
  Log ("claim OK: " + (($r | Select-Object bound, mode, session_id, validated, claimed, expires_at) | ConvertTo-Json -Compress) + " manifest.runtime=$rt")
} catch { Log "claim FAILED: $($_.ErrorDetails.Message)"; exit 1 }

Log '== 6. JOB: POST /jobs/meeting-notes with the .docx'
$jb = @{ input_paths = @($docx); output_path = (Join-Path (Get-Location) 'out\e2e-local-notes.json') } | ConvertTo-Json
$j = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/jobs/meeting-notes -ContentType 'application/json' -Body $jb
Log "job queued: $($j.job_id)"
for ($i = 0; $i -lt 150; $i++) { $s = Invoke-RestMethod "http://127.0.0.1:8765/jobs/$($j.job_id)"; if ($s.status -notin 'queued','running') { break }; Start-Sleep 2 }
Log "job status=$($s.status) source=$($s.result.source) result_path=$($s.result_path) error=$($s.error)"
Log ("usage_report: " + ($s.result.usage_report | ConvertTo-Json -Compress -Depth 6))

Log '== 7. CLOUD: usage_records rows for the session (read-only DB query)'
$o = python scripts\check_cloud_usage.py $sid 2>&1 | Out-String; Log $o

Log '== 8. CLOUD: execute on a local session must return 400 RUNTIME_LOCAL'
try { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/sessions/$sid/execute" -Headers @{ 'X-Session-Token' = $h.session_token } -ContentType 'application/json' -Body '{"input":"x"}' | Out-Null; Log 'execute unexpectedly succeeded' } catch { Log "execute -> HTTP $($_.Exception.Response.StatusCode.value__): $($_.ErrorDetails.Message)" }

Log '== 9. OFFLINE path: API unreachable + --offline-stub -> extraction + usage QUEUED locally'
$env:LOCAL_RUNTIME_SESSION_FILE = 'out\.session-offline.json'
$env:AGENTHUB_API_BASE = 'http://127.0.0.1:8999'
$o = python -m app.cli $docx --hire-file .dev-hire-local.json --offline-stub -o out\e2e-offline-notes.json 2>&1 | Out-String
Log "cli exit=$LASTEXITCODE`n$o"
Remove-Item Env:AGENTHUB_API_BASE; Remove-Item Env:LOCAL_RUNTIME_SESSION_FILE
if (Test-Path usage-pending.jsonl) { Log ("queue:`n" + (Get-Content usage-pending.jsonl -Raw)) }

Log '== 10. SYNC queued rows to the live API'
$o = python -m app.usage_sync --hire-file .dev-hire-local.json 2>&1 | Out-String; Log $o
$o = python scripts\check_cloud_usage.py $sid 2>&1 | Out-String; Log $o
Log '== done'
