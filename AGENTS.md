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
+ `AI_MODEL` + `AI_API_KEY`.

- **Kilo (default):** `AI_BASE_URL=https://api.kilo.ai/api/openrouter/v1`,
  `AI_MODEL=kilo-auto/free`. Key is a long JWT (`eyJ...`).
  - `kilocode.ai` redirects (308) and does NOT serve the API — use `api.kilo.ai`.
  - Kilo **rejects `response_format: json_object`** with `400 "This model does not
    support structured output."` The code handles this: `_chat()` detects it,
    permanently disables JSON mode for the process, and retries prompt-only.
    A single `400` followed by `200` in the logs is expected, not a bug.
- **Gemini (alternative):** keys start with `AQ.` and only work against
  `https://generativelanguage.googleapis.com/v1beta/openai`.
  Free tier is only **20 requests/day** — easy to exhaust while testing.
- Key prefix tells you the provider: `AQ.` = Gemini, `eyJ...` = Kilo JWT,
  `sk-...` = OpenAI. A mismatch gives `401` → "invalid or expired key" message.

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
