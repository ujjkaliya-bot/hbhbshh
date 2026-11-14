# 🤖 Kilo-Style AI Coding, Auto-Building & 24/7 Bot Hosting Agent

A single Telegram agent that runs **24/7 on your main cloud server** (`server1`)
and manages a cluster of remote Linux VPS boxes (`server2`, `server3`, …) over
SSH. Users chat in plain English, Hindi or Hinglish to:

- ✨ **Build brand-new Python/Node.js bots from scratch using AI** (Kilo-style).
- 📦 **Upload existing `.zip` bots** and host them 24/7.
- 🩺 **Auto-diagnose, edit and fix crashed bots** with AI (multi-file patches).
- 💬 **Get 24/7 AI coding & hosting help** in your own language.

**The bot mirrors your language.** Write in English and it answers in English;
write in Hindi (Devanagari) and it answers in Hindi; write in Hinglish
("mujhe ek bot chahiye") and it answers in Hinglish. Code, file names and
technical terms always stay in English. The language is detected per message, so
a user can switch mid-conversation.

Admins can inspect the cluster, add servers, show the cluster SSH public key,
migrate all bots between servers with **zero downtime**, and manage quotas.

Runs anywhere: **Render.com** (free web service + UptimeRobot keep-alive) or a
**Selfhost.dev** Linux server (systemd 24/7). Your laptop is never needed.

---

## ☁️ Option A — Render.com (free, 24/7 with UptimeRobot)

1. Push this repo to GitHub.
2. Render Dashboard → **New → Blueprint** → pick the repo (uses `render.yaml`),
   **or** New → **Web Service** with:
   - Build: `pip install -r kilo-host-agent/requirements.txt`
   - Start: `python kilo-host-agent/main.py`
   - Health check path: `/`
3. Add env vars in the Render dashboard: `TELEGRAM_BOT_TOKEN`, `ADMIN_USER_ID`,
   `AI_API_KEY` (and optionally `CLUSTER_PRIVATE_KEY` — see below).
   `AI_BASE_URL` / `AI_MODEL` / `AI_FAST_MODEL` already default to Kilo in
   `render.yaml`.
4. Deploy. Open `https://<your-service>.onrender.com/` → you should see
   `Kilo Host Agent is running ✅` (that's the health endpoint).
5. Create a free **UptimeRobot** HTTP(s) monitor hitting that URL every 5 min so
   the free instance never sleeps.

**Stable download URL (bonus):** the running service also serves the deploy
artifacts, so you get a permanent installer link with no tunnels:

```
https://<your-service>.onrender.com/install_247.sh            # Selfhost installer
https://<your-service>.onrender.com/kilo-host-agent.zip       # sources (kilo-host-agent/)
https://<your-service>.onrender.com/kilo-host-agent-deploy.zip  # repo-root ZIP for Render
```

**No-Render-account-free way (upload a ZIP instead of using git):**

1. Download `kilo-host-agent-deploy.zip` (it already contains `render.yaml`,
   `Procfile` and `kilo-host-agent/` at the repo root, with **no secrets**).
2. On GitHub: your repo → **Add file → Upload files** → drag the ZIP's contents
   in → **Commit**.
3. Render → **New → Blueprint** → pick that repo → it reads `render.yaml`
   automatically.
4. Add the three env vars and hit **Deploy**.

**SSH key on Render:** the filesystem is ephemeral, so either
- let the bot generate a key and read it from Telegram `/pubkey`, then paste that
  `.pub` into your Selfhost servers' SSH Keys, **or**
- paste your existing cluster **private** key into `CLUSTER_PRIVATE_KEY`
  (raw or base64) — it is written to `/tmp/cluster_key` (chmod 600) on boot.

---

## 🖥 Option B — Selfhost.dev server (systemd, 24/7)

Two ways, both one-command:

**B1. Self-extracting installer** (needs `curl`):

```bash
curl -fsSL https://work-1-jxdijlsskrlmafta.prod-runtime.all-hands.dev/install_247.sh | bash
```

**B2. ZIP** (if you prefer to upload the file yourself):

```bash
# upload kilo-host-agent.zip to the server, then:
unzip kilo-host-agent.zip && cd kilo-host-agent
bash install_from_zip.sh        # installs deps + systemd unit
```

Both write `/opt/kilo-host-agent/.env`, generate `/root/.ssh/cluster_key`, and
enable the `kilo-host-agent.service` unit (24/7 + reboot autostart).

---

## 📁 Project Structure (`kilo-host-agent/`)

| File | Role |
|------|------|
| `main.py` | Async Telegram bot (v20+) — inline menus, conversational AI agent loop, admin commands, health-server bootstrap. |
| `health_server.py` | Tiny aiohttp server on `$PORT` (default 10000); `GET /` → `200 OK` for Render + UptimeRobot. |
| `ai_coder_agent.py` | Autonomous AI coding & bug-fixing agent. OpenAI-compatible (OpenRouter/Kilo/OpenAI/Gemini). Generates multi-file projects, patches crashed bots, answers questions. |
| `cluster_manager.py` | SSH/SFTP + load-balancing engine (Paramiko). Auto-generates the server-side ED25519 cluster key, monitors live RAM/CPU, deploys bots into isolated venvs with `ulimit`, watchdog, zero-downtime migrate. |
| `security_scanner.py` | Static safety scanner — blocks fork-bombs, zip-bombs, path traversal and destructive shell commands before any code runs. |
| `database.py` | SQLite: `users`, `hosted_bots`, `servers`, `chat_history`. |
| `servers.json` | Cluster definition (`server1` local + `server2`, `server3`). |
| `kilo-host-agent.service` | systemd unit for 24/7 autostart (Selfhost). |
| `.env` | Secrets: `TELEGRAM_BOT_TOKEN`, `ADMIN_USER_ID`, `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`, `AI_FAST_MODEL`. |
| `requirements.txt` | Dependencies. |

Repo-root deploy files: `render.yaml` (Render blueprint), `Procfile`,
`install_247.sh` (self-extracting installer), `kilo-host-agent.zip` (ZIP bundle),
`build_install.py` (regenerates both artifacts).

---

## 🎛 Telegram Commands & Buttons

### User dashboard (`/start`)
- **✨ Build a New Bot with AI** — describe a bot in English/Hindi/Hinglish → the
  bot restates your idea and asks one question at a time → AI writes all files →
  `security_scanner` verifies → auto-deploys 24/7 on the cluster.
- **📦 Host a ZIP Upload** — send a `.zip` → auto-extract, install deps, run 24/7.
- **📂 My Bots & Live Logs** — start, stop, restart, view logs, delete.
- **🩺 AI Auto-Fix (Repair Errors)** — reads crash logs + code, patches the bug
  automatically, restarts the bot.
- **💬 24/7 AI Coding Help** — chat with the agent for code edits or help. Replies
  stream in live, in your language.

### Admin (`ADMIN_USER_ID` only)
- **`/pubkey`** — show `/root/.ssh/cluster_key.pub` to paste into other accounts.
- **`/cluster`** — live RAM, CPU and active-bot count across all servers.
- **`/addserver <id> <ip> <port> <user> <ram_mb>`** — add a Selfhost server live.
- **`/migrate <from> <to>`** — move all bots to a fresh server and notify owners.
- **`/ban <user_id>`**, **`/grant <user_id> <max_bots>`** — moderation & quotas.

---

## 🔐 Security model
- The AI writes code; `security_scanner` scans it **before** deployment — a
  malicious prompt cannot smuggle `rm -rf /`, a fork bomb or a reverse shell
  onto your servers.
- Uploaded ZIPs are statically scanned (path traversal, zip-bomb ratio, fork
  bombs, disk wipes, shutdown, `/etc/shadow` writes).
- Every bot runs isolated in its own `venv`/`npm` env under `ulimit` caps.
- Shell inputs are sanitized with `shlex.quote`.
- The cluster private key never leaves `server1`.

---

## 🛠 Troubleshooting
| Symptom | Fix |
|---------|-----|
| `AI Support abhi configure nahi hai` | Set `AI_API_KEY` in `.env`, `systemctl restart kilo-host-agent`. |
| `Permission denied (publickey)` on a server | Copy the output of `/pubkey` into that server's `SSH Keys` settings. |
| `No healthy server with >= 400MB free RAM` | Add/verify a server; check `/cluster`. |
| Bot deploys but `STOPPED` | Open 📊 Logs → 🩺 AI Auto-Fix. |
| Service not running | `journalctl -u kilo-host-agent -n 80 --no-pager` |


---

## 🧱 How deployment works

```
ZIP upload  → security_scanner (static safety scan)
AI prompt   → ai_coder_agent (multi-file project) → security_scanner
            → pick_server() by most free RAM
            → SFTP upload → unzip → venv/npm install
            → setsid + nohup + ulimit launch → bot.log
            → watchdog monitors & self-heals (AI auto-fix)
```

Per-tenant caps applied via `ulimit`: 400 MB address space, 300 CPU-seconds,
200 MB max file, 1024 file descriptors — so one tenant cannot crash a 2 GB box.
