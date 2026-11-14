"""
main.py — Kilo-Style AI Coding, Auto-Building & 24/7 Bot Hosting Telegram Agent.

Users chat in plain Hindi/English to:

1. Build brand-new Python/Node.js bots from scratch using AI (Kilo-style).
2. Upload existing ``.zip`` bots and host them 24/7 on a cluster of VPS boxes.
3. Auto-diagnose, edit and fix crashed bots with AI (multi-file patches).
4. Get 24/7 AI coding & hosting help.

Admins can inspect the cluster, add servers, show the cluster SSH public key,
migrate all bots between servers (zero-downtime) and manage user quotas.

Run:  python main.py
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import time
import uuid

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import ai_coder_agent
import database as db
import health_server
from cluster_manager import (
    ClusterManager,
    ensure_cluster_key,
    ensure_private_key_file,
    is_ephemeral_key,
    read_cluster_pubkey,
)

# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("kilo-host-agent")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0") or 0)
WATCHDOG_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL", "60"))


def _default_downloads_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    if os.access(here, os.W_OK):
        return os.path.join(here, "downloads")
    return "/tmp/downloads"


DOWNLOADS_DIR = _default_downloads_dir()
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

cm = ClusterManager()

# --------------------------------------------------------------------------- #
# Lightweight per-user state
# --------------------------------------------------------------------------- #
# user_id -> {"state": str|None, "language": str|None}
SESSIONS: dict[int, dict] = {}

RATE: dict[int, list[float]] = {}
RATE_WINDOW = 10.0
RATE_MAX = 15  # messages per window


def session(user_id: int) -> dict:
    return SESSIONS.setdefault(user_id, {"state": None, "language": None})


def rate_limited(user_id: int) -> bool:
    now = time.time()
    stamps = [t for t in RATE.get(user_id, []) if now - t < RATE_WINDOW]
    stamps.append(now)
    RATE[user_id] = stamps
    return len(stamps) > RATE_MAX


def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID


def esc(text: str) -> str:
    return html.escape(text or "")


def esc_trunc(text: str, limit: int) -> str:
    """Truncate the RAW text first, then escape — never split an HTML entity."""
    return html.escape((text or "")[:limit])


def _quota_left(user_id: int) -> tuple[int, int]:
    """Return (used, limit) for a user."""
    user = db.ensure_user(user_id)
    return db.count_user_bots(user_id), int(user.get("max_bots", 1) or 1)


# --------------------------------------------------------------------------- #
# Keyboards
# --------------------------------------------------------------------------- #
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ AI se Naya Bot Banwao", callback_data="menu:aibuild")],
        [InlineKeyboardButton("📦 ZIP Upload karke Host Karo", callback_data="menu:host")],
        [InlineKeyboardButton("📂 Mere Bots & Live Logs", callback_data="menu:bots")],
        [InlineKeyboardButton("🩺 AI Auto-Fix (Error Theek Karo)", callback_data="menu:fixer")],
        [InlineKeyboardButton("💬 24/7 AI Coding Help", callback_data="menu:help")],
    ])


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐍 Python", callback_data="lang:python"),
         InlineKeyboardButton("🟩 Node.js", callback_data="lang:node")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:home")],
    ])


def ai_language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐍 Python", callback_data="ailang:python"),
         InlineKeyboardButton("🟩 Node.js", callback_data="ailang:node")],
        [InlineKeyboardButton("🤖 AI Khud Chune (Auto)", callback_data="ailang:auto")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:home")],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu:home")]])


def bots_kb(owner_id: int, action: str) -> InlineKeyboardMarkup:
    rows = []
    for bot in db.list_bots_by_owner(owner_id):
        label = f"{bot['name']} · {bot['language']} · {bot['status']}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"{action}:{bot['bot_id']}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


# --------------------------------------------------------------------------- #
# Public commands
# --------------------------------------------------------------------------- #
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if rate_limited(user.id):
        await update.message.reply_text("⏳ Thoda slow! Rate limit hit — 10 sec baad try karein.")
        return
    db.ensure_user(user.id, user.username or user.full_name)
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 Aapko ban kiya gaya hai. / Banned.")
        return
    session(user.id)["state"] = None
    text = (
        f"👋 <b>Namaste {esc(user.first_name)}!</b>\n\n"
        "Main <b>Kilo</b> hoon — aapka 24/7 <b>AI Coding & Bot Hosting Agent</b>. 🤖\n\n"
        "Main aapke liye:\n"
        "• ✨ AI se naya Python/Node.js bot bana sakta hoon\n"
        "• 📦 aapki <code>.zip</code> bot ko 24/7 host kar sakta hoon\n"
        "• 🩺 crash hue bot ko AI se auto-fix kar sakta hoon\n\n"
        "Neeche se option chunein 👇"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>📖 Commands</b>\n"
        "/start – Dashboard\n"
        "/help – Yeh help\n"
        "/stop – AI chat mode band karein\n"
        "/cancel – Current flow cancel\n\n"
        "<b>✨ AI se bot banane ke liye:</b>\n"
        "1. <b>✨ AI se Naya Bot Banwao</b> dabayein\n"
        "2. Language chunein (ya Auto)\n"
        "3. Hindi/English me likhein kaisa bot chahiye\n"
        "4. AI code likhega, security scan hoga, aur 24/7 deploy ho jayega! 🎉\n\n"
        "<b>📦 ZIP host karne ke liye:</b>\n"
        "1. <b>📦 ZIP Upload karke Host Karo</b> dabayein\n"
        "2. Language chunein\n"
        "3. Apna <code>.zip</code> bhejein (Python: <code>main.py</code>/"
        "<code>bot.py</code> + <code>requirements.txt</code>; Node: "
        "<code>index.js</code> + <code>package.json</code>)"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session(update.effective_user.id)["state"] = None
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_kb())


async def cmd_stop_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session(update.effective_user.id)["state"] = None
    await update.message.reply_text("🤖 AI chat mode off. /start se menu kholein.",
                                    reply_markup=main_menu_kb())


# --------------------------------------------------------------------------- #
# Callback router
# --------------------------------------------------------------------------- #
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    await query.answer()
    if rate_limited(user.id):
        await query.message.reply_text("⏳ Rate limit — thoda ruk kar try karein.")
        return
    data = query.data or ""
    db.ensure_user(user.id, user.username or user.full_name)
    if db.is_banned(user.id):
        await query.edit_message_text("🚫 You are banned.")
        return

    try:
        if data == "menu:home":
            await _show_home(query)
        elif data == "menu:aibuild":
            await _show_ai_lang(query)
        elif data == "menu:host":
            await _show_host_prompt(query)
        elif data.startswith("lang:"):
            await _set_language(query, user.id, data.split(":", 1)[1])
        elif data.startswith("ailang:"):
            await _set_ai_language(query, user.id, data.split(":", 1)[1])
        elif data == "menu:bots":
            await _show_bots(query, user.id)
        elif data == "menu:logs":
            await _show_pick_bot(query, user.id, "logs", "📊 Logs dekhne ke liye bot chunein:")
        elif data == "menu:fixer":
            await _show_pick_bot(query, user.id, "fix", "🩺 AI se fix karane ke liye bot chunein:")
        elif data == "menu:help":
            session(user.id)["state"] = "ai_chat"
            await query.edit_message_text(
                "💬 <b>24/7 AI Coding Help</b> active!\n\n"
                "Apna coding/hosting sawaal likhein (Hindi/English dono chalega). "
                "Band karne ke liye /stop bhejein.",
                parse_mode=ParseMode.HTML,
            )
        elif data.startswith("logs:"):
            await _show_logs(query, user.id, data.split(":", 1)[1])
        elif data.startswith("fix:"):
            await _ai_fix(query, user.id, data.split(":", 1)[1])
        elif data.startswith("apply:"):
            await _apply_fix(query, user.id, data.split(":", 1)[1])
        elif data.startswith("restart:"):
            await _bot_action(query, user.id, data.split(":", 1)[1], "restart")
        elif data.startswith("stopbot:"):
            await _bot_action(query, user.id, data.split(":", 1)[1], "stop")
        elif data.startswith("del:"):
            await _bot_action(query, user.id, data.split(":", 1)[1], "delete")
        else:
            await query.message.reply_text("Unknown action.", reply_markup=main_menu_kb())
    except TelegramError as exc:
        log.warning("callback telegram error: %s", exc)


async def _show_home(query) -> None:
    await query.edit_message_text(
        "🏠 <b>Dashboard</b>\nOption chunein 👇", parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(),
    )


async def _show_ai_lang(query) -> None:
    await query.edit_message_text(
        "✨ <b>AI se Naya Bot Banwao</b>\n\nKaunsi language me banau?",
        parse_mode=ParseMode.HTML, reply_markup=ai_language_kb(),
    )


async def _show_host_prompt(query) -> None:
    await query.edit_message_text(
        "📦 <b>ZIP Upload karke Host Karo</b>\n\nPehle language chunein:",
        parse_mode=ParseMode.HTML, reply_markup=language_kb(),
    )


async def _set_language(query, user_id: int, language: str) -> None:
    if language not in ("python", "node"):
        await query.edit_message_text("Unknown language.")
        return
    sess = session(user_id)
    sess["state"] = "awaiting_zip"
    sess["language"] = language
    db.ensure_user(user_id)
    used, limit = _quota_left(user_id)
    if used >= limit:
        await query.edit_message_text(
            f"⚠️ Aapki bot limit poori ho gayi ({used}/{limit}).\n"
            "Admin se /grant karwa lein.",
            reply_markup=back_kb(),
        )
        return
    pretty = "🐍 Python" if language == "python" else "🟩 Node.js"
    await query.edit_message_text(
        f"{pretty} selected ✅\n\nAb apna <b>.zip</b> file bhejein "
        "(Telegram par document ke roop me).\nSize limit 25 MB.",
        parse_mode=ParseMode.HTML, reply_markup=back_kb(),
    )


async def _set_ai_language(query, user_id: int, language: str) -> None:
    sess = session(user_id)
    sess["state"] = "awaiting_ai_prompt"
    sess["language"] = None if language == "auto" else language
    used, limit = _quota_left(user_id)
    if used >= limit:
        await query.edit_message_text(
            f"⚠️ Aapki bot limit poori ho gayi ({used}/{limit}).\n"
            "Admin se /grant karwa lein.",
            reply_markup=back_kb(),
        )
        return
    if not ai_coder_agent.is_configured():
        await query.edit_message_text(
            "⚠️ AI abhi configure nahi hai. Server ke /opt/kilo-host-agent/.env me "
            "AI_API_KEY daalein, phir: systemctl restart kilo-host-agent",
            reply_markup=back_kb(),
        )
        return
    pretty = {"python": "🐍 Python", "node": "🟩 Node.js", None: "🤖 Auto"}[sess["language"]]
    await query.edit_message_text(
        f"{pretty} selected ✅\n\n"
        "Ab likhein aapko <b>kaisa bot</b> chahiye. Example:\n\n"
        "<i>“Ek Telegram bot banao jo har message ko reverse karke bheje aur "
        "/start par help dikhaye.”</i>\n\n"
        "AI code likhega → security scan hoga → 24/7 deploy ho jayega. 🚀",
        parse_mode=ParseMode.HTML, reply_markup=back_kb(),
    )


async def _show_bots(query, user_id: int) -> None:
    bots = db.list_bots_by_owner(user_id)
    if not bots:
        await query.edit_message_text("📂 Abhi koi bot nahi hai. Pehle bana/host karein!",
                                      reply_markup=back_kb())
        return
    lines = ["<b>📂 Mere Bots</b>\n"]
    for b in bots:
        lines.append(
            f"• <code>{esc(b['bot_id'][:8])}</code> <b>{esc(b['name'])}</b> "
            f"({esc(b['language'])}) — <i>{esc(b['status'])}</i> @ {esc(b['server_id'] or '-')}"
        )
    kb_rows = []
    for b in bots:
        kb_rows.append([
            InlineKeyboardButton(f"📊 {b['name']}"[:28], callback_data=f"logs:{b['bot_id']}"),
            InlineKeyboardButton("🩺 Fix", callback_data=f"fix:{b['bot_id']}"),
        ])
        kb_rows.append([
            InlineKeyboardButton("🔁 Restart", callback_data=f"restart:{b['bot_id']}"),
            InlineKeyboardButton("⏹ Stop", callback_data=f"stopbot:{b['bot_id']}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"del:{b['bot_id']}"),
        ])
    kb_rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:home")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )


async def _show_pick_bot(query, user_id: int, action: str, prompt: str) -> None:
    bots = db.list_bots_by_owner(user_id)
    if not bots:
        await query.edit_message_text("📂 Koi bot nahi mila. Pehle bana/host karein!",
                                      reply_markup=back_kb())
        return
    await query.edit_message_text(prompt, reply_markup=bots_kb(user_id, action))


async def _show_logs(query, user_id: int, bot_id: str) -> None:
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text("⛔ Yeh aapka bot nahi hai.")
        return
    await query.edit_message_text("⏳ Logs aur RAM fetch kar raha hoon…")
    status = await asyncio.to_thread(cm.bot_status, bot_id)
    logs = await asyncio.to_thread(cm.get_logs, bot_id, 40)
    ram_line = ""
    if bot.get("server_id"):
        stats = await asyncio.to_thread(cm.get_server_stats, bot["server_id"])
        if stats.online:
            ram_line = (f"\n🖥 Server <b>{esc(bot['server_id'])}</b>: "
                        f"{stats.ram_free_mb}MB free / {stats.ram_total_mb}MB · "
                        f"CPU {stats.cpu_percent}% · {stats.active_bots} bots")
    state = "🟢 RUNNING" if status.get("running") else "🔴 STOPPED"
    text = (
        f"📊 <b>{esc(bot['name'])}</b> — {state}{ram_line}\n\n"
        f"<b>Last 40 log lines:</b>\n<pre>{esc(logs[-3000:])}</pre>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🩺 AI Auto-Fix", callback_data=f"fix:{bot_id}"),
         InlineKeyboardButton("🔁 Restart", callback_data=f"restart:{bot_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:bots")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _ai_fix(query, user_id: int, bot_id: str) -> None:
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text("⛔ Yeh aapka bot nahi hai.")
        return
    await query.edit_message_text("🩺 AI aapke logs + poora code padh raha hai… thoda intezaar karein.")
    logs, sources = await asyncio.gather(
        asyncio.to_thread(cm.get_logs, bot_id, 80),
        asyncio.to_thread(cm.read_sources, bot_id),
    )
    fix = await asyncio.to_thread(
        ai_coder_agent.fix_code, logs, sources or {}, bot.get("language", "python")
    )
    if not fix.get("ok"):
        await query.edit_message_text(
            f"⚠️ {esc_trunc(fix.get('error', 'AI fix nahi de paya.'), 800)}",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return
    files_list = ", ".join(fix["files"].keys())
    text = (
        f"🩺 <b>AI Diagnosis</b>\n\n{esc_trunc(fix['explanation'], 2000)}\n\n"
        f"<b>Patched files:</b> <code>{esc(files_list)}</code>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠 Auto-Apply & Restart", callback_data=f"apply:{bot_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:bots")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _apply_fix(query, user_id: int, bot_id: str) -> None:
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text("⛔ Yeh aapka bot nahi hai.")
        return
    await query.edit_message_text("🛠 AI se fixed code nikaal kar apply kar raha hoon…")
    logs, sources = await asyncio.gather(
        asyncio.to_thread(cm.get_logs, bot_id, 80),
        asyncio.to_thread(cm.read_sources, bot_id),
    )
    fix = await asyncio.to_thread(
        ai_coder_agent.fix_code, logs, sources or {}, bot.get("language", "python")
    )
    if not fix.get("ok"):
        await query.edit_message_text(
            f"⚠️ {esc_trunc(fix.get('error', 'AI fix nahi de paya.'), 800)}",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
        return
    result = await asyncio.to_thread(cm.apply_patches, bot_id, fix["files"])
    if result.get("ok"):
        files_list = ", ".join(result.get("files", []))
        await query.edit_message_text(
            f"✅ Fix applied to <code>{esc(files_list)}</code> and bot restarted!\n"
            "(Purane files <code>.bak</code> me safe hain.)",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )
    else:
        await query.edit_message_text(
            f"❌ Auto-apply fail: {esc_trunc(result.get('error', 'unknown'), 500)}",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(),
        )


async def _bot_action(query, user_id: int, bot_id: str, action: str) -> None:
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text("⛔ Yeh aapka bot nahi hai.")
        return
    await query.edit_message_text("⏳ Please wait…")
    if action == "restart":
        res = await asyncio.to_thread(cm.restart_bot, bot_id)
        msg = "🔁 Restarted ✅" if res.get("ok") else f"❌ {esc_trunc(res.get('error', ''), 500)}"
    elif action == "stop":
        res = await asyncio.to_thread(cm.stop_bot, bot_id)
        msg = "⏹ Stopped ✅" if res.get("ok") else f"❌ {esc_trunc(res.get('error', ''), 500)}"
    else:
        res = await asyncio.to_thread(cm.delete_bot, bot_id)
        msg = "🗑 Deleted ✅" if res.get("ok") else f"❌ {esc_trunc(res.get('error', ''), 500)}"
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=back_kb())


# --------------------------------------------------------------------------- #
# ZIP upload handler
# --------------------------------------------------------------------------- #
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if rate_limited(user.id):
        await update.message.reply_text("⏳ Rate limit — thoda ruk kar try karein.")
        return
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 Banned.")
        return
    doc = update.message.document
    name = doc.file_name or ""
    sess = session(user.id)
    if not name.lower().endswith(".zip"):
        await update.message.reply_text("⚠️ Sirf <b>.zip</b> file bhejein.",
                                        parse_mode=ParseMode.HTML)
        return
    if sess.get("state") != "awaiting_zip" or not sess.get("language"):
        await update.message.reply_text(
            "Pehle language chunein: /start → 📦 ZIP Upload karke Host Karo")
        return

    language = sess["language"]
    sess["state"] = None
    status_msg = await update.message.reply_text("⬇️ ZIP download ho rahi hai…")

    local_path = os.path.join(DOWNLOADS_DIR, f"{user.id}_{uuid.uuid4().hex}.zip")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(local_path)
    except TelegramError as exc:
        await status_msg.edit_text(f"❌ Download fail: {esc_trunc(str(exc), 500)}",
                                   parse_mode=ParseMode.HTML)
        return

    ok, reason = await asyncio.to_thread(cm.validate_zip, local_path)
    if not ok:
        try:
            os.remove(local_path)
        except OSError:
            pass
        await status_msg.edit_text(f"🛑 ZIP reject: {esc_trunc(reason, 300)}",
                                   parse_mode=ParseMode.HTML)
        return

    bot_id = uuid.uuid4().hex[:12]
    bot_name = os.path.splitext(name)[0][:40] or "bot"
    await status_msg.edit_text(
        f"🚀 Deploying <b>{esc(bot_name)}</b> ({language})…\n"
        "Healthiest server chun kar install ho raha hai. 1-2 min lag sakte hain.",
        parse_mode=ParseMode.HTML,
    )
    try:
        result = await asyncio.to_thread(
            cm.deploy_bot, user.id, bot_id, local_path, language, bot_name
        )
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc)}
    finally:
        try:
            os.remove(local_path)
        except OSError:
            pass

    if result.get("ok"):
        await status_msg.edit_text(
            f"✅ <b>{esc(bot_name)}</b> live hai!\n"
            f"🆔 <code>{bot_id}</code>\n"
            f"🖥 Server: <b>{esc(result.get('server_id', ''))}</b>\n"
            f"📁 <code>{esc(result.get('remote_path', ''))}</code>\n\n"
            "Watchdog isko 24/7 monitor karega. 🎉",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(),
        )
    else:
        await status_msg.edit_text(
            f"❌ Deploy fail: {esc_trunc(result.get('error', 'unknown'), 500)}",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(),
        )


# --------------------------------------------------------------------------- #
# Plain-text handler: AI build flow + AI helpdesk
# --------------------------------------------------------------------------- #
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if rate_limited(user.id):
        await update.message.reply_text("⏳ Rate limit — thoda ruk kar try karein.")
        return
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 Banned.")
        return
    db.ensure_user(user.id, user.username or user.full_name)
    sess = session(user.id)
    text = (update.message.text or "").strip()
    if not text:
        return

    if sess.get("state") == "awaiting_ai_prompt":
        await _handle_ai_build(update, context, text)
        return

    # Default: 24/7 AI coding help (DB-backed history).
    await update.message.chat.send_action("typing")
    history = await asyncio.to_thread(db.get_chat_history, user.id, 8)
    reply = await asyncio.to_thread(ai_coder_agent.answer, text, history)
    await asyncio.to_thread(db.add_chat, user.id, "user", text)
    await asyncio.to_thread(db.add_chat, user.id, "assistant", reply)
    # AI replies contain markdown/code; send as plain text to avoid HTML parse errors.
    await update.message.reply_text(reply[:4000], reply_markup=main_menu_kb())


async def _handle_ai_build(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           prompt: str) -> None:
    user = update.effective_user
    sess = session(user.id)
    language = sess.get("language")
    sess["state"] = None

    used, limit = _quota_left(user.id)
    if used >= limit:
        await update.message.reply_text(
            f"⚠️ Aapki bot limit poori ho gayi ({used}/{limit}). Admin se /grant karwa lein.",
            reply_markup=main_menu_kb(),
        )
        return

    status = await update.message.reply_text(
        "🧠 Kilo aapka bot likh raha hai… (thoda intezaar karein)")
    gen = await asyncio.to_thread(ai_coder_agent.generate_project, prompt, language)
    if not gen.get("ok"):
        await status.edit_text(f"❌ {esc_trunc(gen.get('error', 'AI fail'), 800)}",
                               parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
        return

    # Security-scan the AI output BEFORE anything reaches a server.
    from security_scanner import scan_files
    ok, reason = await asyncio.to_thread(scan_files, gen["files"])
    if not ok:
        await status.edit_text(
            f"🛑 AI ke code me unsafe pattern mila, isliye deploy nahi kiya:\n{esc_trunc(reason, 300)}",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(),
        )
        return

    files = gen["files"]
    lang = gen["language"]
    bot_id = uuid.uuid4().hex[:12]
    bot_name = (prompt[:30] or "ai-bot").strip().replace("\n", " ")
    await status.edit_text(
        f"✨ AI ne <b>{len(files)}</b> file(s) banayi:\n"
        f"<code>{esc(', '.join(files.keys()))}</code>\n\n"
        f"📝 <i>{esc_trunc(gen.get('summary', ''), 200)}</i>\n\n"
        "🚀 Ab healthiest server par deploy kar raha hoon…",
        parse_mode=ParseMode.HTML,
    )
    try:
        result = await asyncio.to_thread(
            cm.deploy_files, user.id, bot_id, files, lang, bot_name
        )
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc)}

    if result.get("ok"):
        await status.edit_text(
            f"✅ <b>AI Bot live hai!</b> 🎉\n\n"
            f"📝 {esc_trunc(gen.get('summary', ''), 200)}\n"
            f"🆔 <code>{bot_id}</code>\n"
            f"🖥 Server: <b>{esc(result.get('server_id', ''))}</b>\n"
            f"🐍 Language: <b>{esc(lang)}</b>\n\n"
            "📂 Mere Bots se logs/restart/fix kar sakte hain.",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(),
        )
    else:
        await status.edit_text(
            f"❌ Deploy fail: {esc_trunc(result.get('error', 'unknown'), 600)}",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(),
        )


# --------------------------------------------------------------------------- #
# Admin commands
# --------------------------------------------------------------------------- #
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Admin only.")
            return
        return await func(update, context)
    return wrapper


@admin_only
async def cmd_cluster(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text("📡 Cluster stats fetch ho rahe hain…")
    stats = await asyncio.to_thread(cm.get_cluster_stats)
    if not stats:
        await msg.edit_text("Koi server configure nahi hai. /addserver se add karein.")
        return
    lines = ["<b>🖥 Cluster Overview</b>\n"]
    for st in stats:
        if st.online:
            lines.append(
                f"• <b>{esc(st.server_id)}</b> 🟢\n"
                f"  RAM free {st.ram_free_mb}/{st.ram_total_mb}MB ({st.ram_free_pct:.0f}%) · "
                f"CPU {st.cpu_percent}% · load {st.load1}\n"
                f"  disk {st.disk_used_pct:.0f}% · bots {st.active_bots}"
            )
        else:
            lines.append(f"• <b>{esc(st.server_id)}</b> 🔴 offline — {esc_trunc(st.error, 120)}")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.HTML)


@admin_only
async def cmd_servers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    servers = db.list_servers()
    if not servers:
        await update.message.reply_text("Koi server nahi. /addserver <id> <ip>")
        return
    lines = ["<b>📋 Servers</b>\n"]
    for s in servers:
        lines.append(
            f"• <code>{esc(s['server_id'])}</code> → {esc(s['ip'])}:{s['port']} "
            f"user={esc(s['ssh_user'])} ram={s['ram_total_mb']}MB "
            f"status=<i>{esc(s['status'])}</i> expiry={esc(s['credit_expiry'] or '-')}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


@admin_only
async def cmd_addserver(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /addserver <id> <ip> [port] [user] [ram_mb] [credit_expiry]")
        return
    server_id, ip = args[0], args[1]
    port = int(args[2]) if len(args) > 2 else 22
    ssh_user = args[3] if len(args) > 3 else "root"
    ram = int(args[4]) if len(args) > 4 else 2048
    expiry = args[5] if len(args) > 5 else None
    db.add_server(server_id, ip, port, ssh_user, ram, None, expiry)
    await update.message.reply_text(
        f"✅ Server <b>{esc(server_id)}</b> ({esc(ip)}) added & active — restart ki zarurat nahi.",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def cmd_migrate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /migrate <from_server> <to_server>")
        return
    from_s, to_s = args[0], args[1]
    if not db.get_server(from_s) or not db.get_server(to_s):
        await update.message.reply_text("⛔ Unknown server id.")
        return
    status = await update.message.reply_text(
        f"🚚 Migrating bots {esc(from_s)} → {esc(to_s)}…", parse_mode=ParseMode.HTML
    )
    loop = asyncio.get_running_loop()

    def progress(msg: str) -> None:
        asyncio.run_coroutine_threadsafe(_safe_edit(status, msg), loop)

    result = await asyncio.to_thread(cm.migrate_server, from_s, to_s, progress)

    for detail in result.get("details", []):
        if not detail.get("ok"):
            continue
        bot = db.get_bot(detail["bot_id"])
        if not bot:
            continue
        try:
            await context.bot.send_message(
                bot["owner_id"],
                f"🚚 Aapka bot <b>{esc(bot['name'])}</b> naye server "
                f"<b>{esc(to_s)}</b> par move kar diya gaya hai aur restart ho chuka hai. ✅",
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

    await status.edit_text(
        f"✅ Migration done: {result['moved']} moved, {result['failed']} failed.",
    )


async def _safe_edit(message, text: str) -> None:
    try:
        await message.edit_text(esc_trunc(text, 4000), parse_mode=ParseMode.HTML)
    except TelegramError:
        pass


@admin_only
async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /ban <user_id> [unban]")
        return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text("user_id integer hona chahiye.")
        return
    banned = not (len(args) > 1 and args[1].lower() == "unban")
    db.ensure_user(uid)
    db.set_ban(uid, banned)
    await update.message.reply_text(f"{'🚫 Banned' if banned else '✅ Unbanned'} user {uid}.")


@admin_only
async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /grant <user_id> <bot_limit> [plan] [expiry_days]")
        return
    try:
        uid, limit = int(args[0]), int(args[1])
    except ValueError:
        await update.message.reply_text("user_id aur bot_limit integer hone chahiye.")
        return
    plan = args[2] if len(args) > 2 else "custom"
    expiry = None
    if len(args) > 3:
        try:
            days = int(args[3])
            expiry = time.strftime("%Y-%m-%d", time.gmtime(time.time() + days * 86400))
        except ValueError:
            expiry = args[3]
    db.ensure_user(uid)
    db.set_plan(uid, plan, limit, expiry)
    await update.message.reply_text(
        f"✅ User {uid}: plan={esc(plan)}, max_bots={limit}, expiry={esc(expiry or '-')}",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def cmd_pubkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show this server's cluster public key so it can be pasted into other
    Selfhost accounts' SSH Keys settings."""
    await asyncio.to_thread(ensure_cluster_key)
    pub = await asyncio.to_thread(read_cluster_pubkey)
    text = (
        "🔑 <b>Cluster Public Key</b>\n\n"
        "Isko copy karke apne baaki Selfhost servers ke <b>SSH Keys</b> "
        "settings me paste kar dein (server2, server3, …).\n\n"
        f"<pre>{esc(pub)}</pre>\n"
        "💡 Tip: tap karke copy karein."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


@admin_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "<b>🛡 Admin Commands</b>\n"
        "/cluster – live RAM/CPU/disk + bot counts\n"
        "/servers – list servers\n"
        "/pubkey – show this server's cluster SSH public key\n"
        "/addserver &lt;id&gt; &lt;ip&gt; [port] [user] [ram_mb] [expiry] – add server live\n"
        "/migrate &lt;from&gt; &lt;to&gt; – move all bots (zero-downtime)\n"
        "/ban &lt;user_id&gt; [unban]\n"
        "/grant &lt;user_id&gt; &lt;bot_limit&gt; [plan] [expiry]",
        parse_mode=ParseMode.HTML,
    )


# --------------------------------------------------------------------------- #
# Watchdog background loop
# --------------------------------------------------------------------------- #
async def watchdog_loop(app: Application) -> None:
    log.info("watchdog started (interval=%ss)", WATCHDOG_INTERVAL)
    while True:
        try:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            events = await asyncio.to_thread(cm.watchdog_scan)
            for ev in events:
                if ev.get("status") not in ("restarted", "crashed"):
                    continue
                owner = ev.get("owner_id")
                if not owner:
                    continue
                bot = db.get_bot(ev["bot_id"])
                bot_name = bot["name"] if bot else ev["bot_id"][:8]
                if ev["status"] == "restarted":
                    text = (f"♻️ Aapka bot <b>{esc(bot_name)}</b> crash hua tha aur "
                            f"auto-restart ho gaya (attempt {ev.get('restarts')}/3).")
                else:
                    # AI-diagnose the final crash using the full source tree.
                    sources = await asyncio.to_thread(cm.read_sources, ev["bot_id"])
                    fix = await asyncio.to_thread(
                        ai_coder_agent.fix_code, ev.get("log_tail", ""),
                        sources or {}, (bot or {}).get("language", "python"),
                    )
                    diag = fix.get("explanation") if fix.get("ok") else fix.get("error", "")
                    text = (
                        f"🔴 Aapka bot <b>{esc(bot_name)}</b> 3 baar crash hone ke baad "
                        f"band hai.\n\n<b>AI diagnosis:</b>\n{esc_trunc(diag or '', 2000)}\n\n"
                        "Fix ke liye: 📂 Mere Bots → 🩺 AI Auto-Fix"
                    )
                try:
                    await app.bot.send_message(owner, text, parse_mode=ParseMode.HTML)
                except TelegramError:
                    pass
        except asyncio.CancelledError:
            log.info("watchdog stopped")
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("watchdog error: %s", exc)


async def _post_init(app: Application) -> None:
    app.bot_data["watchdog"] = asyncio.create_task(watchdog_loop(app))
    # Keep the Render web service (and UptimeRobot) happy with a live HTTP port.
    try:
        app.bot_data["health"] = await health_server.start_health_server()
    except Exception as exc:  # noqa: BLE001
        log.warning("health server failed to start: %s", exc)
    # Warm the cluster key + server pool so the first user action is fast.
    try:
        status = await asyncio.to_thread(ensure_private_key_file)
        log.info("ssh key: %s", status)
        pub = await asyncio.to_thread(read_cluster_pubkey)
        log.info("=" * 68)
        log.info("CLUSTER PUBLIC KEY (paste into other Selfhost servers' SSH Keys):")
        log.info("%s", pub)
        log.info("=" * 68)
        loaded = await asyncio.to_thread(cm.reload_from_json)
        log.info("servers loaded from servers.json: %s", loaded)
        log.info("AI configured: %s", ai_coder_agent.is_configured())
        if ADMIN_USER_ID and is_ephemeral_key():
            await _notify_ephemeral_key(app, pub)
    except Exception as exc:  # noqa: BLE001
        log.warning("post_init warmup issue: %s", exc)


async def _notify_ephemeral_key(app: Application, pub: str) -> None:
    """Warn the admin that the key lives in /tmp and will change on redeploy."""
    text = (
        "🔑 <b>Cluster key (temporary disk)</b>\n\n"
        "Ye bot ephemeral filesystem par chal raha hai (Render), isliye cluster "
        "key <b>har restart/deploy par badal sakti hai</b>.\n\n"
        "Agar Selfhost servers se SSH toot jaaye to:\n"
        "1. Neeche wali <b>nayi</b> key copy karke server2/server3 ke "
        "<code>Org Settings &gt; SSH Keys</code> me purani hataake paste karein.\n"
        "2. Ya isko permanent banane ke liye Render me "
        "<code>CLUSTER_PRIVATE_KEY</code> env set karein.\n\n"
        f"<pre>{esc(pub)}</pre>"
    )
    try:
        await app.bot.send_message(ADMIN_USER_ID, text, parse_mode=ParseMode.HTML)
    except TelegramError as exc:  # noqa: BLE001
        log.warning("could not notify admin about ephemeral key: %s", exc)


async def _post_shutdown(app: Application) -> None:
    task = app.bot_data.get("watchdog")
    if task:
        task.cancel()
    await health_server.stop_health_server(app.bot_data.get("health"))


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def build_app() -> Application:
    if not BOT_TOKEN:
        raise SystemExit(
            "❌ TELEGRAM_BOT_TOKEN missing. .env me daalein (see .env.example)."
        )
    db.init_db()
    db.seed_servers_from_json(cm.servers_json_path)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stop", cmd_stop_ai))
    app.add_handler(CommandHandler("cluster", cmd_cluster))
    app.add_handler(CommandHandler("servers", cmd_servers))
    app.add_handler(CommandHandler("pubkey", cmd_pubkey))
    app.add_handler(CommandHandler("addserver", cmd_addserver))
    app.add_handler(CommandHandler("migrate", cmd_migrate))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def main() -> None:
    app = build_app()
    log.info("🚀 Kilo Host Agent starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
