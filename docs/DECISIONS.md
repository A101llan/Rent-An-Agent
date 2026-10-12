# AgentHub decisions log

Format: decision, why, alternatives considered. Newest first.

## 2026-10-12 Â· local-runtime job safety (branch `local-mvp-hardening`)

Context: real .docx jobs could freeze the renter's PC. The reference PC is a 2-core i7-7600U with 7.9 GB RAM, about 1 GB free, and no GPU, running llama3.2:1b on the CPU. Model and prompt content are owned by the Ollama Integrator. Only request options and guards were changed.

### D1. Cap generation through Ollama request options
- **Choice:** every `/api/chat` request sends `options.num_predict = 512` (`LOCAL_RUNTIME_NUM_PREDICT`) and `options.num_ctx = 4096` (`LOCAL_RUNTIME_NUM_CTX`), and keeps `format` set (`"json"`, or the prompt file's JSON schema). Options from the prompt file (e.g. `temperature: 0`) are merged in. The sidecar caps win, and a lower `num_predict` from the prompt file is kept.
- **Why:**
  - A complete notes JSON is about 150â€“250 tokens, so 512 leaves headroom while stopping runaway generation, which caused the CPU and RAM pinning.
  - An explicit `num_ctx` stops Ollama from silently dropping the start of the prompt (the system prompt) when the input is long. It also bounds the KV-cache memory: for a 1B model, 4096 tokens is roughly 130 MB.
- **Alternatives:**
  - Rely on Ollama's defaults (unbounded, and they vary by Ollama version).
  - Set limits in a Modelfile or globally in Ollama. That changes shared Ollama settings, which belong to the Integrator.
  - Stream and cut client-side (more code, and same effect).

### D2. Request timeout 180 s (was 300 s)
- **Choice:** `OLLAMA_TIMEOUT` defaults to 180 s and stays configurable. A timeout fails the job with a clear message and reports no usage.
- **Why:** observed runs took 18â€“60 s, including cold loads. 180 s is 3Ã— the worst observed run, and the shorter timeout limits how long a stuck run holds the machine.
- **Alternatives:**
  - 300 s (too long for a renter waiting on a frozen PC).
  - 60â€“90 s (would fail cold starts on 2-core CPUs).

### D3. Input cap of 8,000 characters, truncated with a visible note
- **Choice:** joined document text over `LOCAL_RUNTIME_MAX_INPUT_CHARS` (8000) is cut at the last line break before the limit, and a `[... document truncated ...]` marker is added. The output JSON gets an `input_truncated` block `{truncated, original_chars, kept_chars, limit_chars, message}`. Under the limit, it's `null`.
- **Why:**
  - 8,000 characters is about 2,000 tokens.
  - With the decisions-v2 prompt and its example (~600 tokens) plus 512 output tokens, that fits inside the 4,096-token context with margin.
  - Prompt evaluation time and RAM stay bounded on a 2-core CPU, roughly 30â€“60 s.
- **Alternatives:**
  - Map-reduce chunking: summarise each chunk, then merge. Better coverage of long documents, but it costs N+1 model calls, which means minutes and repeated RAM pressure on the target PCs. Deferred: revisit with the Integrator if long meetings matter.
  - Reject long documents outright (a worse user experience).
  - A token-exact cap (needs a tokenizer in the bundle).

### D4. Free-RAM guard via psutil before calling Ollama
- **Choice:** before each run, `psutil.virtual_memory().available` is checked.
  - Need â‰¥ 1,500 MB free if the model is not yet resident (checked via Ollama `/api/ps`). llama3.2:1b loads at about 1.3 GB.
  - Need â‰¥ 400 MB free if it's already loaded.
  - Both are configurable: `LOCAL_RUNTIME_MIN_FREE_MB` and `LOCAL_RUNTIME_MIN_FREE_MB_LOADED`.
  - Below the threshold, a `LowMemoryError` is raised (job `error_code: "low_memory"`, CLI exit 5) with a "Close other apps â€¦ and try again. Nothing was processed and no usage was reported" message. Ollama is not called, no output file is written, and no usage is reported.
  - If psutil can't be imported, the guard is skipped (fail-open) so a packaging slip can't brick the sidecar.
- **Why:**
  - Loading the model with too little free RAM makes Windows page heavily, which is the "freeze".
  - Separate cold and warm thresholds avoid blocking repeat runs while the model is already in memory.
  - The reference PC usually has about 1 GB free, so a cold run there will be refused until apps are closed. That is intended.
- **Alternatives:**
  - A single fixed threshold (either too strict for warm runs or too loose for cold ones).
  - Win32 `GlobalMemoryStatusEx` via ctypes (no dependency, but Windows-only and harder to test).
  - Lowering Ollama's priority or setting `OLLAMA_MAX_LOADED_MODELS` (global Ollama settings, which belong to the Integrator).

### D5. Setup and Ollama-down console stays open
- **Choice:** `agenthub-local-runtime.exe setup` waits for a keypress (`msvcrt.getch`) when it ends with a problem (Ollama down or missing, model not pulled, pull failed), or always when `--pause` is passed. The Start-menu "Setup - check Ollama and model" shortcut now passes `--pause`. The installer's post-install run pauses only on problems, so a successful install doesn't hang. `--no-pause` disables pausing for scripts, and pausing is a no-op when there is no console or tty.
- **Why:** the warning flashed for about 3 s and the window closed, so renters never saw "install Ollama".
- **Alternatives:**
  - A tkinter or MessageBox dialog. It would need GUI code in the setup path; the /ui page (step 2) will cover the GUI.
  - `timeout /t 30` in a .cmd wrapper (still closes by itself).

## 2026-10-12 Ã‚Â· local-runtime /ui page and the settled job-safety defaults (branch `local-mvp-hardening`)

### D6. Claim-and-run UI is a static page served by the sidecar at `127.0.0.1:8765/ui`
- **Choice:** one static `ui/index.html` (plain HTML and JS, no framework, no CDN) plus JSON endpoints under `/ui/api` (`state`, `claim`, `upload`, `run`, `jobs/{id}`, `jobs/{id}/json`). These reuse `session.claim_session` and `jobs.start_meeting_notes_job`.
  - The .docx is uploaded as a raw request body, so `python-multipart` isn't needed.
  - It is saved under `<data dir>\uploads\<id>\`, and the output goes to `<data dir>\out\meeting-notes-<id>.json`.
  - The file sits in `ui\` next to the exe; `build.ps1` copies it.
- **Why:**
  - No new heavy dependencies, and no GUI toolkit inside the PyInstaller bundle.
  - Fully testable headless with TestClient.
  - Works in any browser.
  - Same code path and contract handling as the API and CLI.
- **Alternatives:**
  - tkinter window: an extra GUI thread in the sidecar, harder to test, and the dated look puts renters off.
  - pywebview or Electron: heavy, more to bundle and sign.
  - A separate GUI exe: two binaries to keep in sync.

### D7. Local-only protection for the sidecar HTTP surface
- **Choice:** `LocalOnlyGuard` middleware.
  - **Host check:** `/ui*` requires `Host` to be `127.0.0.1:<port>` or `localhost:<port>`, which blocks DNS rebinding.
  - **Origin check:** every non-GET request (including the existing `/session/*` and `/jobs/*` routes) is rejected if `Origin` is present and not the sidecar's own origin.
  - **Custom header:** `/ui/api` POSTs also need `X-AgentHub-UI: 1`, which forces a CORS preflight that the app never approves.
  - **Page headers:** the page sends `X-Frame-Options: DENY` and a CSP with `frame-ancestors 'none'`.
  - **Binding:** the sidecar still binds only to 127.0.0.1.
- **Why:** any website the renter visits could otherwise POST to `localhost:8765` (CSRF) to claim with someone else's token or run jobs.
- **Alternatives:**
  - A random per-launch secret in the URL (stronger, but it breaks bookmarks and the Start-menu shortcut; possible later).
  - CORS settings alone (they don't stop "simple" cross-site POSTs).

### D8. Session token handling in the UI
- **Choice:** the token is typed into a password field and POSTed once to `/ui/api/claim`. The field is cleared right after the POST. It is never written to `localStorage` or `sessionStorage` or into the page, and `/ui/api/*` responses never include it. The sidecar keeps it in `<data dir>\.session.json`, the same as the existing claim path.
- **Why:** the token is the renter's credential, and the brief requires it to stay out of the browser.
- **Alternatives:** keeping it in browser storage to survive reloads (rejected; the sidecar already persists the binding).

### D9. Onboarding answers are recorded, not prompted (MVP)
- **Choice:** the 3 questions come from the claimed manifest (`manifest.onboarding.questions`). The answers go into the job as an `onboarding` dict and are saved in the output JSON. They are NOT added to the Ollama prompt.
- **Why:** prompt content is owned by the Ollama Integrator; Project Manager confirmed this for the MVP.
- **Alternatives:** inject the answers into the system or user prompt (deferred to the Integrator).

### D10. Long input: keep truncation, make it loud
- **Choice:** keep the cap from D3. When it triggers, the output JSON gets a top-level `warnings` entry ("WARNING: INPUT TRUNCATED - Ã¢â‚¬Â¦") in addition to `input_truncated`, and `/ui` shows a high-contrast banner above the notes ("Document truncated Ã¢â‚¬Â¦ split the document to process the rest").
- **Why:** chunking (map-reduce) means several model calls, which takes minutes and repeats the RAM pressure on the target 2-core, roughly 1 GB-free PCs. Silent truncation would mislead renters.
- **Alternatives:** chunk and merge (rejected for the MVP on cost), refuse long documents.

### D11. Job-safety defaults settled (decided by Project Manager; values owned by the Ollama Integrator)
- **Choice:** the values live in `apps/local-runtime/config.defaults.json`, which the Ollama Integrator owns:
  - `num_ctx` 2048
  - `num_predict` 384
  - `timeout_s` 120
  - input cap 6,000 characters
  - free RAM Ã¢â€°Â¥ 1,300 MB before a cold run (model not loaded)
  - free RAM Ã¢â€°Â¥ 300 MB when the model is already loaded
- **Code change:** `config.py` reads these keys through the Ollama Integrator's `_limit()` helper. It was their uncommitted work-in-progress, finished and committed here with credit. Order: env var (e.g. `LOCAL_RUNTIME_MIN_FREE_MB`, `LOCAL_RUNTIME_TIMEOUT_S` / `OLLAMA_TIMEOUT`) > `config.json` (same key) > `config.defaults.json` key (`num_predict`, `num_ctx`, `timeout_s`, `max_input_chars`, `min_free_mb`, `min_free_mb_loaded`, `format`) > hardcoded fallback. Values are validated as positive ints and clamped to sane bounds. The hardcoded fallbacks (D1Ã¢â‚¬â€œD4: 4096 / 512 / 180 s / 8,000 / 1,500 / 400) only apply if the file is missing a key. Tests read the active config rather than fixed numbers.
- **Low-RAM message:** says "X MB of RAM free, Y MB needed, close other apps Ã¢â‚¬Â¦ then retry". It appears in the job error and on `/ui`.
- **Why 1,300 over 1,500 (cold):**
  - llama3.2:1b loads at about 1.3 GB. The target PC usually has about 1 GB free, so 1,500 MB refused almost every cold run.
  - With the smaller context and output caps (2048 / 384), the KV cache and working set are smaller, so 1,300 MB gives enough headroom.
  - Rejected alternative: 1,500 MB (the earlier sidecar default; safer against paging but too strict for the target hardware).
- **Value in `config.defaults.json` at the time of this commit:** `min_free_mb` = 1300 MB (cold) and `min_free_mb_loaded` = 300 MB (loaded), as resolved by `config.py`.

### D12. Temperature default and Ollama-status notices (Ollama Integrator's work-in-progress, kept)
- **Choice:**
  - `temperature: 0` is sent by default, but a prompt file's own `options.temperature` wins. This was softened from their unconditional override.
  - Clearer timeout and "unreachable" messages are kept.
  - `runtime_notices()` (Ollama not running, model missing, low memory) is shown on `/health`, in `check`, and logged at `serve`.
  - Their full uncommitted diff was saved to `%TEMP%\integrator-uncommitted-20261012-181633.patch` before merging.
- **Why:** these are small, correct, and don't change prompt content. Deterministic output suits structured JSON.
- **Alternatives:** drop their work-in-progress (it would be lost), or keep the unconditional temperature override (it would override the prompt owner's choice).


## 2026-10-12 · AgentHub Local Runtime 0.2.0 (branch `local-mvp-hardening`)

### D13. Bump the runtime from 0.1.0 to 0.2.0
- **Choice:** the version is `0.2.0`. It is used in `config.VERSION` (and so `/health` and the `version` command), the installer's `.iss` `AppVersion` (which sets the output name `AgentHubLocalRuntimeSetup-0.2.0.exe`, `AppVerName` and the uninstall display name), the zip name (built from `config.VERSION` in `build.ps1`), the README, the root `.env.example` comment, and the web download fallback URL. A test checks that the sidecar, `/health` and the `.iss` agree.
- **Why a minor bump:** 0.2.0 adds user-visible features:
  - Job safety (D1–D5, D10).
  - The `/ui` claim-and-run page with its local-only guard (D6–D9).
  - Settings read from `config.defaults.json` (D11, D12).
  - New `/health` fields: `notices`. The job status endpoint also gains `error_code`.
- **Alternatives:**
  - 0.1.1: wrong, because this is new features, not only fixes.
  - Stay at 0.1.0: a renter couldn't tell the old build from the new one, and the installer would overwrite it with the same version.
- **`min_sidecar_version` is unchanged at 0.1.0** in the manifests and seeds. 0.2.0 still satisfies `>=0.1.0`, and the cloud contract doesn't need any 0.2.0-only feature. Raise it only once the cloud depends on something new, for example `/ui`.

## 2026-10-12 Â· real test-pass fixes (branch `local-mvp-hardening`)

### D14. Friendly Ollama errors, unload on timeout or abort, per-model RAM guard with fallback
Bugs found by the Ollama Integrator in real runs:
1. A run with Ollama down showed a raw "[WinError 10061]".
2. A missing model showed a raw "ollama HTTP 404".
3. After a timeout or abort, the model stayed in RAM for 5 minutes.

- **Choice:**
  - **Error codes:** extraction failures now carry a code: `ollama_down` (connection refused, or Ollama not answering), `model_missing` (HTTP 404 from `/api/chat`), or `timeout`. They raise `OllamaDownError`, `ModelMissingError` or `ExtractionTimeoutError`.
  - **Messages:** the text is the same OLLAMA NOT RUNNING / MODEL MISSING (`ollama pull <model>`) notice used by `check` and `/health`. It is shown in the CLI (exit 4, without the "EXTRACTION FAILED" prefix), in the job `error` / `error_code`, and on `/ui`.
  - **Unloading:** on a timeout the sidecar sends `POST /api/generate {"model": m, "keep_alive": 0}`, best effort, to unload the model. Cancelling a running job does the same, because the blocking HTTP call can't be interrupted.
  - **Per-model guard values:** an optional `models` map in `config.json` or `config.defaults.json`, e.g. `{"qwen2.5:3b": {"timeout_s": 180, "min_free_mb": 3000, "min_free_mb_loaded": 300}}`, plus an optional `fallback_model` (env `LOCAL_RUNTIME_FALLBACK_MODEL`).
  - **Precedence:** an env var set for the run > the model's map entry > the global value (D11).
  - **Fallback:** if free RAM is below the chosen model's cold threshold, the fallback model is used when it is pulled and its own threshold is met. Otherwise the job is refused as before, with the primary model's numbers.
  - **Reporting:** the output JSON gets `model_used` and `model_fallback` (`{from, to, reason, free_mb, primary_required_mb, message}`), and `/ui` shows a note.
- **Code defaults are unchanged:** no `models` map and no fallback, so behaviour is identical until the Ollama Integrator sets them in `config.defaults.json` (planned: qwen2.5:3b 180 s / 3000 / 300, fallback llama3.2:1b 1300 / 300).
- **Why:**
  - Raw socket and HTTP errors meant nothing to renters.
  - A model left loaded after a timeout keeps about 2 GB of RAM pinned on a PC with about 1 GB free.
  - A 3B model only fits when RAM allows, and degrading to 1B beats refusing.
- **Alternatives:**
  - Pre-flight `/api/tags` on every run (an extra call, and still racy).
  - Streaming with client-side abort (more code).
  - A global `OLLAMA_KEEP_ALIVE` (a shared Ollama setting, owned by the Integrator).
  - Always use the 1B model (worse decisions, per the Integrator's numbers).


### D15. Installer removes a stale login shortcut on upgrade
- **Choice:** an `[InstallDelete]` entry removes `{userstartup}\AgentHub Local Runtime.lnk` when the `autostart` task is not selected.
- **Why:** during the real test pass, a silent 0.1.0 → 0.2.0 upgrade without `autostart` kept the old login shortcut, because Inno never deletes icons from tasks that are no longer selected.
- **Alternatives:** delete it in `[Code]` (more code), or document a manual cleanup step.
- **Follow-up from the real test pass:** `fallback_model` is now also read from `config.json` (env > `config.json` > `config.defaults.json`), the same as `models`. The first real fallback run found that only the defaults file was being read.


### D16. Default model qwen2.5:3b with llama3.2:1b fallback (2026-10-12)
- **Choice:** `config.defaults.json` now defaults to `qwen2.5:3b`, with `fallback_model: llama3.2:1b` and per-model `models` limits: qwen 180 s / min_free_mb 3000 / loaded 300, and 1b 120 s / 1300 / 300.
- **Why (real tests on the 8 GB dev PC, sample-meeting.docx):** qwen2.5:3b took 89.3 s and got 2 decisions / 3 actions / 2 questions, all correct. Lowest free RAM was 1307 MB, from a 3478 MB start. llama3.2:1b took 44.5 s but got only 1/3/1.
- **Alternatives:** keep 1b as the default (faster, but it misses decisions and questions), or use qwen with no fallback (the job fails outright when RAM is low).
### D17. Unload the model after every run (`keep_alive_s`, default 0)
- **Choice:**
  - Every `/api/chat` request now sends `keep_alive` = `keep_alive_s`. It is resolved env `LOCAL_RUNTIME_KEEP_ALIVE_S` > `config.json` (`LOCAL_RUNTIME_KEEP_ALIVE_S` or `keep_alive_s`) > `config.defaults.json` `keep_alive_s` > hardcoded **0**.
  - Values below -1 become -1 (Ollama's "keep loaded forever"), and an invalid value falls back to 0.
  - The `keep_alive:0` unload after a timeout or abort (D14) is unchanged.
- **Why:** after a successful run, Ollama kept qwen2.5:3b resident for its default of about 5 minutes (roughly 2 GB). On the target PCs that pushed the next job's free-RAM check onto the fallback model, or refused it. Unloading right away gives each job the full RAM budget.
- **Cost:** every job pays a cold load (seconds on the reference PC). The Ollama Integrator can raise `keep_alive_s` in `config.defaults.json` if back-to-back speed matters more.
- **Alternatives:**
  - Ollama's global `OLLAMA_KEEP_ALIVE` (a shared setting, which the Integrator owns, and it would affect other apps).
  - A separate unload call after each run (an extra request; the per-request field does the same thing).
  - Keep Ollama's default (the problem above).
