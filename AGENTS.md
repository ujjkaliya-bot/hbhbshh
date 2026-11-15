# AGENTS.md — kilo-host-agent

Repository-specific knowledge for future sessions.

## What this is
A single Telegram agent that runs 24/7 on Render.com (free web service) and
manages remote Linux VPS boxes over SSH. Users describe a bot in chat, the AI
writes the files, `security_scanner` checks them, and the cluster deploys.

Flat repo layout — all app files live at the repo root (no subdirectory).

## Deploy target
- Repo: `ujjkaliya-bot/hbhbshh`, branch `main`
- Render service: `kilo-host-agent` (`srv-dbsac00ae00c73d1dhug`), plan free,
  region singapore, owner `tea-d3ibmh0dl3ps73d3a970`
- Build: `pip install -r requirements.txt` · Start: `python main.py`
- Health: `GET /` → `200 OK` (also `/health` → JSON). Keep-alive via UptimeRobot.
- Live URL: https://kilo-host-agent.onrender.com

## AI configuration (important)
`ai_coder_agent.py` talks to **any OpenAI-compatible endpoint** via `AI_BASE_URL`
+ `AI_MODEL` + `AI_API_KEY`, with an optional second model for speed:

- **`AI_MODEL`** — builds and fixes whole projects (quality matters).
- **`AI_FAST_MODEL`** — clarifying questions + help chat (latency matters).
  Falls back to `AI_MODEL` when unset, and `_chat()` auto-falls back to
  `AI_MODEL` at runtime if the fast model errors out (free models disappear).

- **Kilo (default):** `AI_BASE_URL=https://api.kilo.ai/api/openrouter/v1`,
  `AI_MODEL=kilo-auto/free`, `AI_FAST_MODEL=reflection/beam-free`. Key is a long
  JWT (`eyJ...`).
  - `kilocode.ai` redirects (308) and does NOT serve the API — use `api.kilo.ai`.
  - Kilo **rejects `response_format: json_object`** with `400 "This model does not
    support structured output."` The code handles this: `_chat()` detects it,
    permanently disables JSON mode for the process, and retries prompt-only.
    A single `400` followed by `200` in the logs is expected, not a bug.
  - **Reasoning models are the big trap.** `kilo-auto/free` routes to
    `stealth/glyph-cluster`, which spends tokens "thinking" before emitting any
    `content`. With a small `max_tokens` it returns an **empty string** with
    `finish_reason: length` and `reasoning_tokens` ≈ the whole budget. `_chat()`
    now detects this (`_empty_reasoning_reply`) and retries with double the
    budget. Fast free models that are NOT reasoning models: `reflection/beam-free`,
    `cohere/north-mini-code:free`, `openrouter/free`, `baidu/ernie-5.5-flash-preview:free`
    (~1.3–2.0s vs ~7s).
- **Gemini (alternative):** keys start with `AQ.` and only work against
  `https://generativelanguage.googleapis.com/v1beta/openai`.
  Free tier is only **20 requests/day** — easy to exhaust while testing.
- Key prefix tells you the provider: `AQ.` = Gemini, `eyJ...` = Kilo JWT,
  `sk-...` = OpenAI. A mismatch gives `401` → "invalid or expired key" message.

## 24/7 resilience (deploy overlap + deaf-poller bug)
`python-telegram-bot` aborts its polling retry loop on a *fatal* error and logs
`No error handlers are registered, logging exception.` The process (and the HTTP
health port) stay up, so the bot looks alive but is **deaf** — a silent 24/7
outage. Two guards are in place:

- `_on_error` is registered via `app.add_error_handler`, so handler exceptions
  are logged instead of killing the run.
- `_check_poller()` runs every watchdog tick: if `app.updater.running` is False
  it calls `updater.start_polling()` again (self-heal) and flips
  `health_server.set_liveness()`.
- `run_polling(bootstrap_retries=5)` lets a new instance survive the short
  `Conflict: terminated by other getUpdates request` window while Render is
  still shutting the old instance down during a deploy. Every deploy logs a few
  of these lines — that is normal, not a bug.
- **Never call Telegram `getUpdates` by hand to "check if the bot is alive".**
  Your own request becomes the "other getUpdates" and kills the bot's poller.
  Use `/health` (`telegram_polling: true/false`) instead.

## Language handling (English / Hindi / Hinglish)
The bot mirrors whatever language the user writes in.

- `ai_coder_agent.detect_language()` → `"en"`, `"hi"` (Devanagari regex) or
  `"hinglish"` (≥2 common romanised-Hindi words, or 1 in a ≤3-word message).
- `reply_language_instruction(lang)` is appended to every system prompt; code,
  identifiers and file names stay English.
- `i18n.py` holds every button/message in all three languages
  (`t("key", lang, **fmt)`). Add a key to all three languages or the table
  check in the tests will flag it. `t()` falls back to English for unknown
  languages, so a missing key never crashes the UI.
- `main.py` keeps the per-user language in the session (`session(uid)["lang"]`)
  and updates it on **every** incoming message via `note_user_lang()`, so users
  can switch mid-conversation.
- Build/clarify/chat calls all take a `lang` argument.

## AI pipeline gotchas (all already handled in code)
1. Multi-file projects need a large output budget — `PROJECT_MAX_TOKENS`
   defaults to 16000 (`AI_MAX_TOKENS` overrides). Small budgets truncate the
   JSON mid-file.
2. `json.loads(..., strict=False)` — models embed literal newlines inside string
   values (file contents), which strict JSON rejects.
3. `extract_json()` tries the raw text FIRST, then a fence, then the outermost
   `{...}`. A naive fence regex matches a code block *inside* a generated README
   and destroys the payload.
4. `_chat()` retries transient errors (429/500/502/503/504) with backoff
   (`AI_RETRIES`, `AI_RETRY_BACKOFF`).
5. `_chat_json()` retries once on unparseable JSON, feeding the partial reply
   back and asking for a more concise complete object.

## Manual packages + live logs (added for "AI ke bharose nahi" requests)
Two features exist so a user never has to rely on the AI to fix a missing
dependency or to guess what a bot is doing:

* **📦 Packages** (`cluster_manager.install_packages`): user types package names
  and we run `pip install` into the bot's `../.venv` (or `npm install` inside
  `src/` for Node) then restart. This is the *manual* path — **no AI call at all**.
  * `_validate_packages()` in `cluster_manager.py` accepts only PEP-508-ish
    specifiers (`name`, `name[extra]`, `name>=1.2`, `@scope/pkg@1.2.3`). Shell
    metacharacters are rejected *before* the command is built, so a typo cannot
    inject a command. `MAX_PACKAGES_PER_REQUEST = 20`.
  * Returns `{"ok", "installed", "rejected", "output", "restart"}`.
* **📡 Live Logs** (`cluster_manager.get_logs_since` + `main._run_live_logs`):
  `get_logs_since(bot_id, offset)` does `stat -c %s` + `tail -c +N` so each poll
  returns only *new* bytes (offset==0 seeds from `size - max_bytes`). The viewer
  edits one Telegram message in place, bounded by `LIVE_LOG_TICKS` (default 24)
  at `LIVE_LOG_INTERVAL` (default 5s) so a forgotten window can never spam SSH.
  🔄 Refresh restarts the window; ⏹ Stop Live falls back to the static 📊 view.

State: `S_AWAITING_PKGS` + `session()["pkg_bot"]`; `_clear_transient_state()`
drops it when the user taps ⬅️ Back so a stray message is not eaten by the flow.

## Bot flow ("Build a New Bot with AI")
`main.py` session state machine: `awaiting_ai_prompt` → `clarifying` (one
question per turn via `ai_coder_agent.clarify_bot()`) → `confirm_build` →
`_do_ai_build()`. Everything user-facing is English.

## Render API notes (learned the hard way)
- `PUT /v1/services/{id}/env-vars` **replaces the entire env-var set**. Always
  send the FULL list (including `TELEGRAM_BOT_TOKEN`, `ADMIN_USER_ID`,
  `AI_API_KEY`) or you will silently wipe secrets and the service will crash-loop
  with "TELEGRAM_BOT_TOKEN missing".
- Trigger a deploy: `POST /v1/services/{id}/deploys` with
  `{"clearCache":"do_not_clear"}` → `202` with an empty body (normal).
- Logs: `GET /v1/logs?ownerId=<owner>&resource=<serviceId>&limit=N`; sort by
  `timestamp` client-side.

## Environment
- `PORT` (default 10000) for the aiohttp health server.
- `CLUSTER_PRIVATE_KEY` (raw or base64) bootstraps the SSH key from env so
  Render can reach Selfhost servers without a local laptop.
