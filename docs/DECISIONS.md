# AgentHub decisions log

Format: decision, why, alternatives considered. Newest first.

## 2026-10-12 · local-runtime job safety (branch `local-mvp-hardening`)

Context: real .docx jobs could freeze the renter's PC. The reference PC is a 2-core i7-7600U with 7.9 GB RAM, about 1 GB free, and no GPU, running llama3.2:1b on the CPU. Model and prompt content are owned by the Ollama Integrator. Only request options and guards were changed.

### D1. Cap generation through Ollama request options
- **Choice:** every `/api/chat` request sends `options.num_predict = 512` (`LOCAL_RUNTIME_NUM_PREDICT`) and `options.num_ctx = 4096` (`LOCAL_RUNTIME_NUM_CTX`), and keeps `format` set (`"json"`, or the prompt file's JSON schema). Options from the prompt file (e.g. `temperature: 0`) are merged in. The sidecar caps win, and a lower `num_predict` from the prompt file is kept.
- **Why:**
  - A complete notes JSON is about 150–250 tokens, so 512 leaves headroom while stopping runaway generation, which caused the CPU and RAM pinning.
  - An explicit `num_ctx` stops Ollama from silently dropping the start of the prompt (the system prompt) when the input is long. It also bounds the KV-cache memory: for a 1B model, 4096 tokens is roughly 130 MB.
- **Alternatives:**
  - Rely on Ollama's defaults (unbounded, and they vary by Ollama version).
  - Set limits in a Modelfile or globally in Ollama. That changes shared Ollama settings, which belong to the Integrator.
  - Stream and cut client-side (more code, and same effect).

### D2. Request timeout 180 s (was 300 s)
- **Choice:** `OLLAMA_TIMEOUT` defaults to 180 s and stays configurable. A timeout fails the job with a clear message and reports no usage.
- **Why:** observed runs took 18–60 s, including cold loads. 180 s is 3× the worst observed run, and the shorter timeout limits how long a stuck run holds the machine.
- **Alternatives:**
  - 300 s (too long for a renter waiting on a frozen PC).
  - 60–90 s (would fail cold starts on 2-core CPUs).

### D3. Input cap of 8,000 characters, truncated with a visible note
- **Choice:** joined document text over `LOCAL_RUNTIME_MAX_INPUT_CHARS` (8000) is cut at the last line break before the limit, and a `[... document truncated ...]` marker is added. The output JSON gets an `input_truncated` block `{truncated, original_chars, kept_chars, limit_chars, message}`. Under the limit, it's `null`.
- **Why:**
  - 8,000 characters is about 2,000 tokens.
  - With the decisions-v2 prompt and its example (~600 tokens) plus 512 output tokens, that fits inside the 4,096-token context with margin.
  - Prompt evaluation time and RAM stay bounded on a 2-core CPU, roughly 30–60 s.
- **Alternatives:**
  - Map-reduce chunking: summarise each chunk, then merge. Better coverage of long documents, but it costs N+1 model calls, which means minutes and repeated RAM pressure on the target PCs. Deferred: revisit with the Integrator if long meetings matter.
  - Reject long documents outright (a worse user experience).
  - A token-exact cap (needs a tokenizer in the bundle).

### D4. Free-RAM guard via psutil before calling Ollama
- **Choice:** before each run, `psutil.virtual_memory().available` is checked.
  - Need ≥ 1,500 MB free if the model is not yet resident (checked via Ollama `/api/ps`). llama3.2:1b loads at about 1.3 GB.
  - Need ≥ 400 MB free if it's already loaded.
  - Both are configurable: `LOCAL_RUNTIME_MIN_FREE_MB` and `LOCAL_RUNTIME_MIN_FREE_MB_LOADED`.
  - Below the threshold, a `LowMemoryError` is raised (job `error_code: "low_memory"`, CLI exit 5) with a "Close other apps … and try again. Nothing was processed and no usage was reported" message. Ollama is not called, no output file is written, and no usage is reported.
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
