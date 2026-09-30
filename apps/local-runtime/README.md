# AgentHub local-runtime

Windows-first localhost sidecar so a rented Meeting Notes agent runs **on the renter's device**.

- Binds **127.0.0.1** only (default port **8765**).
- Extraction runs through local Ollama (`llama3.2:1b` by default). Documents never leave the device;
  only metering rows (`usage`) go to the cloud.
- Claims the rent session against the AgentHub API before any run and **fails closed** otherwise.
- **Never** calls runtime-manager.

## Setup

```powershell
cd C:\Users\wambua\Documents\AgentHub\apps\local-runtime
pip install -r requirements.txt          # fastapi, uvicorn, python-docx, httpx
python scripts\make_docx_fixture.py      # (re)creates fixtures\sample-meeting.docx
```

Config precedence: **environment variable > `config.json` in the data dir > default**.
Data dir (`LOCAL_RUNTIME_HOME`): this folder in dev; `%LOCALAPPDATA%\AgentHub\LocalRuntime` for the installed build
(holds `config.json`, `.session.json`, usage queue files, `out\`, `logs\`).

| Setting | Default | Notes |
|-----|---------|-------|
| `HOST` / `PORT` | `127.0.0.1` / `8765` | installed build always binds 127.0.0.1 |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | |
| `LOCAL_RUNTIME_MODEL` | `llama3.2:1b` | sidecar model; falls back to `OLLAMA_MODEL`, then `llama3.2:1b`. Owned by the Ollama Integrator |
| `LOCAL_RUNTIME_PROMPT_FILE` | unset (built-in prompt) | optional prompt override, `.txt` (system prompt) or `.json` (see below). Relative paths resolve against the data dir, then the install dir |
| `OLLAMA_TIMEOUT` | `300` | seconds per extraction |
| `LOCAL_RUNTIME_ALLOW_CANNED` | off | `1` = return labeled canned demo notes if Ollama fails (never metered). Off = job fails |
| `AGENTHUB_API_BASE` | `http://127.0.0.1:8000` | apps/api |
| `AGENTHUB_API_TIMEOUT` | `5` | seconds |
| `LOCAL_RUNTIME_OFFLINE_STUB` | off | `1` = allow a **labeled** stub bind only when the API is unreachable |
| `AGENTHUB_SESSION_TOKEN` | – | CLI/sync token (tokens are never taken on argv) |
| `LOCAL_RUNTIME_SESSION_FILE` | `<data dir>\.session.json` | persisted binding (contains the token; gitignored) |
| `LOCAL_RUNTIME_USAGE_QUEUE` / `_FAILED` | `<data dir>\usage-pending.jsonl` / `usage-failed.jsonl` | |

Prompt override JSON: `{ "name", "system", "user_template" (must contain {notes}), "examples": [{"input", "output"}],
"format": "json" | <JSON schema>, "options": {ollama options} }`. `prompts\decisions-v2.json` is an **opt-in**
experiment (explicit decisions instructions + one few-shot example + schema + temperature 0); it is not the default.
`/health` and every output JSON (`model_meta`) show the model and prompt that were used.

Inputs: **.docx** (paragraphs + tables, in document order, via python-docx), `.txt`, `.md`.

## Cloud contract (apps/api)

Full HTTP contract: [`docs/LOCAL_RUNTIME_API.md`](../../docs/LOCAL_RUNTIME_API.md).
Sidecar helpers: `app/api_contract.py`. Run contract tests: `python -m unittest discover -s tests`.

Auth header on both: `X-Session-Token: <session_token from hire>` (the API also accepts the owner JWT as Bearer; the sidecar uses the session token).

**Claim** `POST {API}/api/v1/sessions/{session_id}/local/claim` (empty JSON body)

- `200` → `{ session_id, expires_at, manifest, agent_slug, agent_version, runtime_provider: "local" }`
- `401/403` bad auth · `404` unknown session · `400/409` not a local session (`SESSION_NOT_LOCAL`) · `410` expired
- Sidecar stores `session_id`, `expires_at`, `manifest` on 200. **Any non-200 → fail closed**: the binding is
  cleared and jobs are refused (HTTP 403 `session_not_bound`).
- API unreachable (refused/timeout) → fail closed (`503 api_unreachable`) unless `LOCAL_RUNTIME_OFFLINE_STUB=1`,
  in which case the binding is stored with `mode: "offline_stub"` and a warning, and is written into every output JSON.

**Usage** `POST {API}/api/v1/sessions/{session_id}/usage`

- Body `{ metric_type, quantity (>0), unit, execution_id: null }` (API forbids extra fields) → `201` UsageRecord
  `{ id, session_id, execution_id, metric_type, quantity, unit, recorded_at }`
- After each successful job: `requests`/`1`/`count`, then `input_tokens` and `output_tokens` (`unit: tokens`) when > 0.
- Outcomes recorded per row in the output JSON `usage_report`:
  - `sent` (2xx; includes the cloud row)
  - `queued` (API unreachable → appended to `usage-pending.jsonl`, sync later)
  - `failed` (non-2xx → logged to `usage-failed.jsonl`; not retried automatically, not reported as success)
- Sync the queue: `python -m app.usage_sync [--hire-file .dev-hire-local.json]` or `POST /usage/sync`.
  Rows are removed only on 2xx; otherwise kept with `last_error`/`attempts`.

Execute on a local session returns `400 RUNTIME_LOCAL` from the API (the sidecar never calls execute or runtime-manager).

## Run server

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

- `GET /health` → `{ ok, ollama, version, api_base, offline_stub_enabled, session{bound,mode,session_id}, usage_pending }`
- `GET /session` → current binding (no token)
- `POST /session/claim` `{ session_id, session_token }` → cloud claim; errors: 401/403/404/409/410 mirrored, 503 unreachable
- `POST /session/bind` → alias of claim (`session_id` now required)
- `POST /jobs/meeting-notes` `{ input_paths?, pick_files?, output_path? }` → refused unless claimed and not expired.
  `pick_files: true` opens a Windows file dialog (tkinter) on the desktop running the sidecar.
- `GET /jobs/:id`, `POST /jobs/:id/cancel`
- `GET /usage/pending`, `POST /usage/sync` `{ session_token? }`

Output JSON: `{ status, output{summary, decisions, action_items, open_questions}, usage, source, job_id, input_paths, session, usage_report, written_at }`.

## Dev hire + end-to-end

With apps/api running on :8000 (and seeded):

```powershell
# additive, insert-if-missing (apps/api script) - adds meeting-notes-agent-local (manifest.runtime.type = "local")
cd ..\api; python -m app.scripts.seed_meeting_notes_agent; cd ..\local-runtime

# hire as the seeded dev customer; writes session_id + token to .dev-hire-local.json (token not printed)
python scripts\dev_hire.py --agent meeting-notes-agent-local --out .dev-hire-local.json

# one-shot: claim -> .docx -> notes JSON -> usage POSTs
python -m app.cli fixtures\sample-meeting.docx --hire-file .dev-hire-local.json -o out\notes.json

# check the cloud rows (read-only DB query using apps/api settings)
python scripts\check_cloud_usage.py <session_id>

# full scripted run incl. fail-closed negatives and offline queue -> sync (log: out\e2e-log.txt)
powershell -ExecutionPolicy Bypass -File scripts\e2e_local.ps1
```

Only `meeting-notes-agent-local` (runtime.type `local`) produces a claimable session; hiring
`meeting-notes-agent` gives a server (`mock`) session and claim fails closed with 409.

Other CLI modes:

```powershell
python -m app.cli notes.docx --session-id <uuid>     # token from $env:AGENTHUB_SESSION_TOKEN
python -m app.cli notes.docx                         # reuse claimed binding in .session.json
python -m app.cli notes.docx --hire-file .dev-hire-local.json --offline-stub   # labeled stub if API unreachable
python -m app.cli notes.docx --dev-unbound           # no session, no usage (labeled dev run)
```

Exit codes: `0` ok, `1` bad input, `2` no session given, `3` claim failed (fail closed; nothing extracted).

## Windows installer (renters: no Python needed)

Build (dev PC, from `apps\local-runtime`):

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

- creates `.build-venv` (requirements + PyInstaller), builds a PyInstaller **onedir** bundle in
  `build\dist\agenthub-local-runtime\` (console exe + `start-hidden.vbs`, `config.example.json`, `prompts\`)
- `build\AgentHubLocalRuntime-0.1.0-win64.zip`: the bundle + `install.ps1` (fallback)
- `build\installer\AgentHubLocalRuntimeSetup-0.1.0.exe`: single-file Inno Setup installer, if Inno Setup 6 is
  installed (`winget install JRSoftware.InnoSetup --scope user`)

Install (renter):

- Run `AgentHubLocalRuntimeSetup-0.1.0.exe`. Per-user, no admin. Installs to `%LOCALAPPDATA%\Programs\AgentHub Local Runtime`.
  Options: *Start when I sign in* (Startup-folder shortcut, hidden window) and *Check Ollama and download the AI model*
  (`agenthub-local-runtime.exe setup`: if Ollama is missing it says so and opens https://ollama.com/download/windows;
  if the configured model isn't pulled it pulls it through the Ollama API). It then starts the sidecar on 127.0.0.1:8765.
- Silent: `AgentHubLocalRuntimeSetup-0.1.0.exe /VERYSILENT /TASKS="autostart"` (add `,setupollama` to pull the model).
- Zip route: unzip, then `powershell -ExecutionPolicy Bypass -File install.ps1 [-AutoStart] [-NoSetup]`.
- Start menu: Start / Stop / Setup (check Ollama and model) / Uninstall. Uninstall stops the process but keeps the
  data dir (`%LOCALAPPDATA%\AgentHub\LocalRuntime`).

The installed exe honours the same settings (env vars or `%LOCALAPPDATA%\AgentHub\LocalRuntime\config.json`, see
`config.example.json`); restart it after changes. Commands:

```powershell
agenthub-local-runtime.exe            # serve (refuses to start a second copy if :8765 is taken)
agenthub-local-runtime.exe setup      # Ollama + model check / pull
agenthub-local-runtime.exe check      # diagnostics JSON
agenthub-local-runtime.exe notes <file.docx> --hire-file <hire.json> -o notes.json   # one-shot CLI
agenthub-local-runtime.exe version    # 0.1.0
```

Logs: `%LOCALAPPDATA%\AgentHub\LocalRuntime\logs\sidecar.log`.
