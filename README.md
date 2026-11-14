# 🤖 Kilo-Style AI Coding, Auto-Building & 24/7 Bot Hosting Agent

A single Telegram agent that runs **24/7 on your main cloud server** (`server1`)
and manages a cluster of remote Linux VPS boxes (`server2`, `server3`, …) over
SSH. Users chat in plain Hindi/English to:

- ✨ **Build brand-new Python/Node.js bots from scratch using AI** (Kilo-style).
- 📦 **Upload existing `.zip` bots** and host them 24/7.
- 🩺 **Auto-diagnose, edit and fix crashed bots** with AI (multi-file patches).
- 💬 **Get 24/7 AI coding & hosting help** in clear English.

Admins can inspect the cluster, add servers, show the cluster SSH public key,
migrate all bots between servers with **zero downtime**, and manage quotas.

Runs anywhere: **Render.com** (free web service + UptimeRobot keep-alive) or a
**Selfhost.dev** Linux server (systemd 24/7). Your laptop is never needed.

---

## ☁️ Option A — Render.com (free, 24/7 with UptimeRobot)

1. Push this repo to GitHub.
2. Render Dashboard → **New → Blueprint** → pick the repo (uses `render.yaml`),
   **or** New → **Web Service** with:
   - Build: `pip install -r requirements.txt`
   - Start: `python main.py`
   - Health check path: `/`
3. Add env vars in the Render dashboard: `TELEGRAM_BOT_TOKEN`, `ADMIN_USER_ID`,
   `AI_API_KEY` (and optionally `CLUSTER_PRIVATE_KEY` — see below).
   `AI_BASE_URL` / `AI_MODEL` are set in `render.yaml` (Gemini by default; switch
   to Kilo/OpenAI by editing those two values).
4. Deploy. Open `https://<your-service>.onrender.com/` → you should see
   `Kilo Host Agent is running ✅` (that's the health endpoint).
5. Create a free **UptimeRobot** HTTP(s) monitor hitting that URL every 5 min so
   the free instance never sleeps.
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

**Clone the repo onto the server, then run the installer:**

```bash
git clone <your-repo-url> kilo-host-agent && cd kilo-host-agent
bash install_from_zip.sh        # installs deps + systemd unit
```

This writes `/opt/kilo-host-agent/.env`, generates `/root/.ssh/cluster_key`, and
enables the `kilo-host-agent.service` unit (24/7 + reboot autostart).

---

## 📁 Project Structure (flat repo — all files at the root)

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
| `.env` | Secrets: `TELEGRAM_BOT_TOKEN`, `ADMIN_USER_ID`, `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`. |
| `requirements.txt` | Dependencies. |

Deploy files: `render.yaml` (Render blueprint) and `Procfile`.
`install_from_zip.sh` installs the agent on a Selfhost box as a systemd service.

---

## 🎛 Telegram Commands & Buttons

### User dashboard (`/start`)
- **✨ Build a New Bot with AI** — describe your idea in any language → the AI
  restates it in English, asks a few quick questions, then writes all files →
  `security_scanner` verifies them → auto-deploys 24/7 on the cluster.
- **📦 Host a ZIP Upload** — send a `.zip` → auto-extract, install deps, run 24/7.
- **📂 My Bots & Live Logs** — start, stop, restart, view logs, delete.
- **🩺 AI Auto-Fix (Repair Errors)** — reads crash logs + code, patches the bug
  automatically, restarts the bot.
- **💬 24/7 AI Coding Help** — chat with the agent for code edits or help.

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
| `AI is not configured yet` | Set `AI_API_KEY` (and `AI_BASE_URL`) and redeploy the service. |
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
