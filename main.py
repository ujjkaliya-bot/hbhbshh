"""
main.py — Kilo: AI coding, auto-building & 24/7 bot hosting Telegram agent.

Users chat in plain English to:

1. Design and build brand-new Python/Node.js bots with AI, step by step.
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
import re
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
import i18n
from i18n import t
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
MAX_CLARIFY_QUESTIONS = int(os.environ.get("MAX_CLARIFY_QUESTIONS", "6"))


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
# user_id -> {"state": str|None, "language": str|None, ...}
SESSIONS: dict[int, dict] = {}

RATE: dict[int, list[float]] = {}
RATE_WINDOW = 10.0
RATE_MAX = 15  # messages per window

# States used by the AI design flow.
S_IDLE = None
S_AI_IDEA = "awaiting_ai_idea"
S_AI_CLARIFY = "clarifying"
S_AI_CONFIRM = "confirm_build"
S_AWAITING_ZIP = "awaiting_zip"
S_AI_CHAT = "ai_chat"


def session(user_id: int) -> dict:
    return SESSIONS.setdefault(
        user_id, {"state": None, "language": None, "lang": i18n.DEFAULT_LANG})


def user_lang(user_id: int) -> str:
    """The reply language for this user (auto-learned from their messages)."""
    return i18n.normalize(session(user_id).get("lang"))


def note_user_lang(user_id: int, text: str) -> str:
    """Detect the language of an incoming message and remember it for the user."""
    lang = ai_coder_agent.detect_language(text)
    session(user_id)["lang"] = lang
    return lang


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


_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_MD_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.S)


def plain_markdown(text: str) -> str:
    """Flatten common Markdown so it reads cleanly in a plain-text Telegram message."""
    text = _MD_BOLD_RE.sub(r"\1", text or "")
    text = _MD_ITALIC_RE.sub(r"\1", text)
    return text.replace("### ", "").replace("## ", "").replace("# ", "")


def _quota_left(user_id: int) -> tuple[int, int]:
    """Return (used, limit) for a user."""
    user = db.ensure_user(user_id)
    return db.count_user_bots(user_id), int(user.get("max_bots", 1) or 1)


# --------------------------------------------------------------------------- #
# Keyboards
# --------------------------------------------------------------------------- #
def main_menu_kb(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_build_ai", lang), callback_data="menu:aibuild")],
        [InlineKeyboardButton(t("btn_host_zip", lang), callback_data="menu:host")],
        [InlineKeyboardButton(t("btn_my_bots", lang), callback_data="menu:bots")],
        [InlineKeyboardButton(t("btn_autofix", lang), callback_data="menu:fixer")],
        [InlineKeyboardButton(t("btn_help", lang), callback_data="menu:help")],
    ])


def language_kb(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("lang_python", lang), callback_data="lang:python"),
         InlineKeyboardButton(t("lang_node", lang), callback_data="lang:node")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu:home")],
    ])


def ai_language_kb(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("lang_python", lang), callback_data="ailang:python"),
         InlineKeyboardButton(t("lang_node", lang), callback_data="ailang:node")],
        [InlineKeyboardButton(t("btn_ai_choose", lang), callback_data="ailang:auto")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu:home")],
    ])


def design_kb(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_build_now", lang), callback_data="aibuild:go")],
        [InlineKeyboardButton(t("btn_more_details", lang), callback_data="aibuild:more")],
        [InlineKeyboardButton(t("btn_cancel", lang), callback_data="aibuild:cancel")],
    ])


def back_kb(lang: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(t("btn_back", lang), callback_data="menu:home")]])


def bots_kb(owner_id: int, action: str, lang: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for bot in db.list_bots_by_owner(owner_id):
        label = f"{bot['name']} · {bot['language']} · {bot['status']}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"{action}:{bot['bot_id']}")])
    rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


# --------------------------------------------------------------------------- #
# Public commands
# --------------------------------------------------------------------------- #
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = user_lang(user.id)
    if rate_limited(user.id):
        await update.message.reply_text(t("rate_limit", lang))
        return
    db.ensure_user(user.id, user.username or user.full_name)
    if db.is_banned(user.id):
        await update.message.reply_text(t("banned", lang))
        return
    session(user.id)["state"] = None
    await update.message.reply_text(
        t("welcome", lang, name=esc(user.first_name)),
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = user_lang(update.effective_user.id)
    await update.message.reply_text(t("help", lang), parse_mode=ParseMode.HTML)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = user_lang(update.effective_user.id)
    session(update.effective_user.id)["state"] = None
    await update.message.reply_text(t("cancelled", lang), reply_markup=main_menu_kb(lang))


async def cmd_stop_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = user_lang(update.effective_user.id)
    session(update.effective_user.id)["state"] = None
    await update.message.reply_text(t("ai_off", lang), reply_markup=main_menu_kb(lang))


# --------------------------------------------------------------------------- #
# Callback router
# --------------------------------------------------------------------------- #
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user
    lang = user_lang(user.id)
    await query.answer()
    if rate_limited(user.id):
        await query.message.reply_text(t("rate_limit_short", lang))
        return
    data = query.data or ""
    db.ensure_user(user.id, user.username or user.full_name)
    if db.is_banned(user.id):
        await query.edit_message_text(t("banned", lang))
        return

    try:
        if data == "menu:home":
            await _show_home(query, lang)
        elif data == "menu:aibuild":
            await _show_ai_lang(query, lang)
        elif data == "menu:host":
            await _show_host_prompt(query, lang)
        elif data.startswith("lang:"):
            await _set_language(query, user.id, data.split(":", 1)[1])
        elif data.startswith("ailang:"):
            await _start_ai_design(query, user.id, data.split(":", 1)[1])
        elif data == "aibuild:go":
            await _do_ai_build(query, user.id, context)
        elif data == "aibuild:more":
            await _ask_for_more_details(query, user.id)
        elif data == "aibuild:cancel":
            session(user.id)["state"] = None
            await query.edit_message_text(t("cancelled", lang), reply_markup=main_menu_kb(lang))
        elif data == "menu:bots":
            await _show_bots(query, user.id)
        elif data == "menu:logs":
            await _show_pick_bot(query, user.id, "logs", t("choose_bot_logs", lang))
        elif data == "menu:fixer":
            await _show_pick_bot(query, user.id, "fix", t("choose_bot_fix", lang))
        elif data == "menu:help":
            session(user.id)["state"] = S_AI_CHAT
            await query.edit_message_text(
                t("ai_chat_on", lang), parse_mode=ParseMode.HTML)
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
            await query.message.reply_text(t("unknown_action", lang), reply_markup=main_menu_kb(lang))
    except TelegramError as exc:
        log.warning("callback telegram error: %s", exc)


async def _show_home(query, lang: str | None = None) -> None:
    await query.edit_message_text(
        t("dashboard", lang), parse_mode=ParseMode.HTML,
        reply_markup=main_menu_kb(lang),
    )


async def _show_ai_lang(query, lang: str | None = None) -> None:
    await query.edit_message_text(
        t("choose_lang", lang), parse_mode=ParseMode.HTML, reply_markup=ai_language_kb(lang),
    )


async def _show_host_prompt(query, lang: str | None = None) -> None:
    await query.edit_message_text(
        t("choose_zip_lang", lang), parse_mode=ParseMode.HTML, reply_markup=language_kb(lang),
    )


async def _set_language(query, user_id: int, language: str) -> None:
    lang = user_lang(user_id)
    if language not in ("python", "node"):
        await query.edit_message_text(t("unknown_action", lang))
        return
    sess = session(user_id)
    sess["state"] = S_AWAITING_ZIP
    sess["language"] = language
    db.ensure_user(user_id)
    used, limit = _quota_left(user_id)
    if used >= limit:
        await query.edit_message_text(
            t("bot_limit", lang, used=used, limit=limit), reply_markup=back_kb(lang))
        return
    pretty = t("lang_python" if language == "python" else "lang_node", lang)
    await query.edit_message_text(
        t("zip_send", lang, pretty=pretty),
        parse_mode=ParseMode.HTML, reply_markup=back_kb(lang),
    )


async def _start_ai_design(query, user_id: int, language: str) -> None:
    lang = user_lang(user_id)
    sess = session(user_id)
    sess["language"] = None if language == "auto" else language
    sess["idea"] = None
    sess["qa"] = []
    sess["pending_q"] = None
    sess["understood"] = None
    used, limit = _quota_left(user_id)
    if used >= limit:
        await query.edit_message_text(
            t("bot_limit", lang, used=used, limit=limit), reply_markup=back_kb(lang))
        return
    if not ai_coder_agent.is_configured():
        await query.edit_message_text(
            t("ai_not_configured", lang), parse_mode=ParseMode.HTML, reply_markup=back_kb(lang))
        return
    sess["state"] = S_AI_IDEA
    pretty = {"python": t("lang_python", lang), "node": t("lang_node", lang),
              None: t("lang_auto", lang)}[sess["language"]]
    await query.edit_message_text(
        t("describe_idea", lang, pretty=pretty),
        parse_mode=ParseMode.HTML, reply_markup=back_kb(lang),
    )


async def _ask_for_more_details(query, user_id: int) -> None:
    lang = user_lang(user_id)
    sess = session(user_id)
    sess["state"] = S_AI_CLARIFY
    sess["pending_q"] = None
    await query.edit_message_text(t("add_details", lang), reply_markup=back_kb(lang))


async def _show_bots(query, user_id: int) -> None:
    lang = user_lang(user_id)
    bots = db.list_bots_by_owner(user_id)
    if not bots:
        await query.edit_message_text(t("no_bots", lang), reply_markup=back_kb(lang))
        return
    lines = [t("my_bots", lang)]
    for b in bots:
        lines.append(
            f"• <code>{esc(b['bot_id'][:8])}</code> <b>{esc(b['name'])}</b> "
            f"({esc(b['language'])}) — <i>{esc(b['status'])}</i> @ {esc(b['server_id'] or '-')}"
        )
    kb_rows = []
    for b in bots:
        kb_rows.append([
            InlineKeyboardButton(f"📊 {b['name']}"[:28], callback_data=f"logs:{b['bot_id']}"),
            InlineKeyboardButton(t("btn_ai_autofix", lang)[:20], callback_data=f"fix:{b['bot_id']}"),
        ])
        kb_rows.append([
            InlineKeyboardButton(t("btn_restart", lang), callback_data=f"restart:{b['bot_id']}"),
            InlineKeyboardButton("⏹ Stop", callback_data=f"stopbot:{b['bot_id']}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"del:{b['bot_id']}"),
        ])
    kb_rows.append([InlineKeyboardButton(t("btn_back", lang), callback_data="menu:home")])
    await query.edit_message_text(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )


async def _show_pick_bot(query, user_id: int, action: str, prompt: str) -> None:
    lang = user_lang(user_id)
    bots = db.list_bots_by_owner(user_id)
    if not bots:
        await query.edit_message_text(t("no_bots_found", lang), reply_markup=back_kb(lang))
        return
    await query.edit_message_text(prompt, reply_markup=bots_kb(user_id, action, lang))


async def _show_logs(query, user_id: int, bot_id: str) -> None:
    lang = user_lang(user_id)
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text(t("not_yours", lang))
        return
    await query.edit_message_text(t("fetching_logs", lang))
    status = await asyncio.to_thread(cm.bot_status, bot_id)
    logs = await asyncio.to_thread(cm.get_logs, bot_id, 40)
    ram_line = ""
    if bot.get("server_id"):
        stats = await asyncio.to_thread(cm.get_server_stats, bot["server_id"])
        if stats.online:
            ram_line = (f"\n🖥 Server <b>{esc(bot['server_id'])}</b>: "
                        f"{stats.ram_free_mb}MB free / {stats.ram_total_mb}MB · "
                        f"CPU {stats.cpu_percent}% · {stats.active_bots} bots")
    state = f"🟢 {t('running', lang)}" if status.get("running") else f"🔴 {t('stopped', lang)}"
    text = (
        f"📊 <b>{esc(bot['name'])}</b> — {state}{ram_line}\n\n"
        f"<b>{t('last_logs', lang)}</b>\n<pre>{esc(logs[-3000:])}</pre>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_ai_autofix", lang), callback_data=f"fix:{bot_id}"),
         InlineKeyboardButton(t("btn_restart", lang), callback_data=f"restart:{bot_id}")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu:bots")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _ai_fix(query, user_id: int, bot_id: str) -> None:
    lang = user_lang(user_id)
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text(t("not_yours", lang))
        return
    await query.edit_message_text(t("ai_reading_logs", lang))
    logs, sources = await asyncio.gather(
        asyncio.to_thread(cm.get_logs, bot_id, 80),
        asyncio.to_thread(cm.read_sources, bot_id),
    )
    fix = await asyncio.to_thread(
        ai_coder_agent.fix_code, logs, sources or {}, bot.get("language", "python"), lang
    )
    if not fix.get("ok"):
        await query.edit_message_text(
            f"⚠️ {esc_trunc(fix.get('error', 'AI could not produce a fix.'), 800)}",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(lang),
        )
        return
    files_list = ", ".join(fix["files"].keys())
    text = (
        f"{t('ai_diagnosis', lang)}\n\n{esc_trunc(fix['explanation'], 2000)}\n\n"
        f"<b>{t('patched_files', lang)}</b> <code>{esc(files_list)}</code>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_apply", lang), callback_data=f"apply:{bot_id}")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu:bots")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _apply_fix(query, user_id: int, bot_id: str) -> None:
    lang = user_lang(user_id)
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text(t("not_yours", lang))
        return
    await query.edit_message_text(t("applying_fix", lang))
    logs, sources = await asyncio.gather(
        asyncio.to_thread(cm.get_logs, bot_id, 80),
        asyncio.to_thread(cm.read_sources, bot_id),
    )
    fix = await asyncio.to_thread(
        ai_coder_agent.fix_code, logs, sources or {}, bot.get("language", "python"), lang
    )
    if not fix.get("ok"):
        await query.edit_message_text(
            f"⚠️ {esc_trunc(fix.get('error', 'AI could not produce a fix.'), 800)}",
            parse_mode=ParseMode.HTML, reply_markup=back_kb(lang),
        )
        return
    result = await asyncio.to_thread(cm.apply_patches, bot_id, fix["files"])
    if result.get("ok"):
        files_list = ", ".join(result.get("files", []))
        await query.edit_message_text(
            t("fix_applied", lang, files=esc(files_list)),
            parse_mode=ParseMode.HTML, reply_markup=back_kb(lang),
        )
    else:
        await query.edit_message_text(
            t("apply_failed", lang, error=esc_trunc(result.get('error', 'unknown'), 500)),
            parse_mode=ParseMode.HTML, reply_markup=back_kb(lang),
        )


async def _bot_action(query, user_id: int, bot_id: str, action: str) -> None:
    lang = user_lang(user_id)
    bot = db.get_bot(bot_id)
    if not bot or bot["owner_id"] != user_id:
        await query.edit_message_text(t("not_yours", lang))
        return
    await query.edit_message_text(t("please_wait", lang))
    if action == "restart":
        res = await asyncio.to_thread(cm.restart_bot, bot_id)
        msg = t("restarted", lang) if res.get("ok") else f"❌ {esc_trunc(res.get('error', ''), 500)}"
    elif action == "stop":
        res = await asyncio.to_thread(cm.stop_bot, bot_id)
        msg = t("stopped_ok", lang) if res.get("ok") else f"❌ {esc_trunc(res.get('error', ''), 500)}"
    else:
        res = await asyncio.to_thread(cm.delete_bot, bot_id)
        msg = t("deleted_ok", lang) if res.get("ok") else f"❌ {esc_trunc(res.get('error', ''), 500)}"
    await query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=back_kb(lang))


# --------------------------------------------------------------------------- #
# ZIP upload handler
# --------------------------------------------------------------------------- #
async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = user_lang(user.id)
    if rate_limited(user.id):
        await update.message.reply_text(t("rate_limit_short", lang))
        return
    if db.is_banned(user.id):
        await update.message.reply_text(t("banned", lang))
        return
    doc = update.message.document
    name = doc.file_name or ""
    sess = session(user.id)
    if not name.lower().endswith(".zip"):
        await update.message.reply_text(t("send_zip", lang), parse_mode=ParseMode.HTML)
        return
    if sess.get("state") != S_AWAITING_ZIP or not sess.get("language"):
        await update.message.reply_text(t("choose_lang_first", lang))
        return

    language = sess["language"]
    sess["state"] = None
    status_msg = await update.message.reply_text(t("downloading_zip", lang))

    local_path = os.path.join(DOWNLOADS_DIR, f"{user.id}_{uuid.uuid4().hex}.zip")
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(local_path)
    except TelegramError as exc:
        await status_msg.edit_text(t("download_failed", lang, error=esc_trunc(str(exc), 500)),
                                   parse_mode=ParseMode.HTML)
        return

    ok, reason = await asyncio.to_thread(cm.validate_zip, local_path)
    if not ok:
        try:
            os.remove(local_path)
        except OSError:
            pass
        await status_msg.edit_text(t("zip_rejected", lang, reason=esc_trunc(reason, 300)),
                                   parse_mode=ParseMode.HTML)
        return

    bot_id = uuid.uuid4().hex[:12]
    bot_name = os.path.splitext(name)[0][:40] or "bot"
    await status_msg.edit_text(
        t("deploying_zip", lang, name=esc(bot_name), language=language),
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
            t("zip_live", lang, name=esc(bot_name), bot_id=bot_id,
              server=esc(result.get('server_id', '')),
              path=esc(result.get('remote_path', ''))),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang),
        )
    else:
        await status_msg.edit_text(
            t("deploy_failed", lang, error=esc_trunc(result.get('error', 'unknown'), 500)),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang),
        )


# --------------------------------------------------------------------------- #
# AI design flow (idea → clarifying questions → build)
# --------------------------------------------------------------------------- #
def _composed_prompt(sess: dict) -> str:
    """Turn the stored idea + Q&A into one rich build prompt."""
    parts = [(sess.get("idea") or "").strip()]
    qa = sess.get("qa") or []
    if qa:
        parts.append("Additional details gathered:")
        for turn in qa:
            parts.append(f"- Q: {turn.get('q', '').strip()}\n  A: {turn.get('a', '').strip()}")
    return "\n".join(p for p in parts if p)


async def _ai_design_turn(message, user_id: int) -> None:
    """Call the AI clarifier and render either the next question or the summary."""
    sess = session(user_id)
    lang = user_lang(user_id)
    idea = sess.get("idea") or ""
    qa = sess.get("qa") or []
    res = await asyncio.to_thread(
        ai_coder_agent.clarify_bot, idea, qa, MAX_CLARIFY_QUESTIONS, lang
    )
    if not res.get("ok"):
        await message.reply_text(
            f"⚠️ {esc_trunc(res.get('error', 'AI error'), 800)}",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang),
        )
        return

    sess["understood"] = res["understood"]
    if res["ready"]:
        sess["state"] = S_AI_CONFIRM
        text = t("plan_ready", lang, understood=esc_trunc(res['understood'], 2500))
    else:
        sess["state"] = S_AI_CLARIFY
        sess["pending_q"] = res["question"]
        text = t("plan_progress", lang, understood=esc_trunc(res['understood'], 2000),
                 n=len(qa) + 1, question=esc_trunc(res['question'], 500))
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=design_kb(lang))


async def _progress_ticker(status_msg, lang: str, base: str, stop: asyncio.Event) -> None:
    """Keep a long build from looking frozen by ticking the elapsed seconds."""
    start = time.time()
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=12)
                return
            except asyncio.TimeoutError:
                pass
            elapsed = int(time.time() - start)
            try:
                await status_msg.edit_text(
                    t("writing_bot_eta", lang, base=base, secs=elapsed),
                    parse_mode=ParseMode.HTML)
            except TelegramError:
                pass
    except asyncio.CancelledError:
        raise


async def _generate_and_deploy(status_msg, user_id: int, sess: dict) -> None:
    """Generate → scan → deploy, updating ``status_msg`` as we go."""
    lang = user_lang(user_id)
    idea = (sess.get("idea") or "").strip()
    language = sess.get("language")
    prompt = _composed_prompt(sess)
    sess["state"] = None

    base = t("writing_bot_short", lang)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_progress_ticker(status_msg, lang, base, stop))
    try:
        await status_msg.edit_text(base)
        gen = await asyncio.to_thread(
            ai_coder_agent.generate_project, prompt, language, lang)
    finally:
        stop.set()
        try:
            await ticker
        except (asyncio.CancelledError, TelegramError):
            pass

    if not gen.get("ok"):
        await status_msg.edit_text(
            t("ai_failed", lang, error=esc_trunc(gen.get('error', 'AI failed'), 800)),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang))
        return

    # Security-scan the AI output BEFORE anything reaches a server.
    from security_scanner import scan_files
    ok, reason = await asyncio.to_thread(scan_files, gen["files"])
    if not ok:
        await status_msg.edit_text(
            t("unsafe_code", lang, reason=esc_trunc(reason, 300)),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang))
        return

    files = gen["files"]
    gen_lang = gen["language"]
    bot_id = uuid.uuid4().hex[:12]
    bot_name = (idea[:30] or "ai-bot").strip().replace("\n", " ")
    await status_msg.edit_text(
        t("files_produced", lang, n=len(files), files=esc(', '.join(files.keys())),
          summary=esc_trunc(gen.get('summary', ''), 200)),
        parse_mode=ParseMode.HTML)
    try:
        result = await asyncio.to_thread(
            cm.deploy_files, user_id, bot_id, files, gen_lang, bot_name
        )
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc)}

    if result.get("ok"):
        await status_msg.edit_text(
            t("bot_live", lang, summary=esc_trunc(gen.get('summary', ''), 200),
              bot_id=bot_id, server=esc(result.get('server_id', '')),
              language=esc(gen_lang)),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang),
        )
    else:
        await status_msg.edit_text(
            t("deploy_failed", lang, error=esc_trunc(result.get('error', 'unknown'), 600)),
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb(lang),
        )


async def _do_ai_build(query, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate, scan and deploy the AI bot from the stored design."""
    lang = user_lang(user_id)
    sess = session(user_id)
    idea = (sess.get("idea") or "").strip()
    if not idea:
        await query.edit_message_text(t("no_idea_yet", lang), reply_markup=back_kb(lang))
        return

    used, limit = _quota_left(user_id)
    if used >= limit:
        await query.edit_message_text(
            t("bot_limit", lang, used=used, limit=limit), reply_markup=back_kb(lang))
        return

    status_msg = await query.edit_message_text(t("writing_bot_short", lang))
    await _generate_and_deploy(status_msg, user_id, sess)


# --------------------------------------------------------------------------- #
# Plain-text handler: AI design flow + AI helpdesk
# --------------------------------------------------------------------------- #
async def _stream_reply(message, user_id: int, question: str) -> None:
    """Stream the AI helpdesk answer into one Telegram message, editing as it grows."""
    lang = user_lang(user_id)
    history = await asyncio.to_thread(db.get_chat_history, user_id, 8)
    reply_msg = await message.reply_text("✍️ …")
    buf = ""
    last_sent = ""
    last_edit = 0.0
    try:
        async for piece in _aiter_stream(question, history, lang):
            buf += piece
            now = time.time()
            # Telegram rate-limits edits; refresh roughly twice a second.
            if now - last_edit < 0.7:
                continue
            text = plain_markdown(buf)[-3900:]
            if text == last_sent:
                continue
            try:
                await reply_msg.edit_text(text or "✍️ …")
                last_sent = text
                last_edit = now
            except TelegramError:
                pass
    finally:
        final = plain_markdown(buf or "(no reply)")[-3900:]
        if final != last_sent:
            try:
                await reply_msg.edit_text(final, reply_markup=main_menu_kb(lang))
            except TelegramError:
                pass
    await asyncio.to_thread(db.add_chat, user_id, "user", question)
    await asyncio.to_thread(db.add_chat, user_id, "assistant", buf or "(no reply)")


async def _aiter_stream(question: str, history, lang: str):
    """Bridge the synchronous stream generator onto the asyncio event loop."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def worker():
        try:
            for piece in ai_coder_agent.stream_answer(question, history, lang):
                loop.call_soon_threadsafe(queue.put_nowait, piece)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    task = loop.run_in_executor(None, worker)
    while True:
        item = await queue.get()
        if item is sentinel:
            break
        yield item
    await task


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lang = user_lang(user.id)
    if rate_limited(user.id):
        await update.message.reply_text(t("rate_limit_short", lang))
        return
    if db.is_banned(user.id):
        await update.message.reply_text(t("banned", lang))
        return
    db.ensure_user(user.id, user.username or user.full_name)
    sess = session(user.id)
    text = (update.message.text or "").strip()
    if not text:
        return

    # Mirror whatever language the user writes in from now on.
    lang = note_user_lang(user.id, text)

    state = sess.get("state")

    if state == S_AI_IDEA:
        sess["idea"] = text
        sess["qa"] = []
        sess["pending_q"] = None
        await update.message.chat.send_action("typing")
        await _ai_design_turn(update.message, user.id)
        return

    if state == S_AI_CLARIFY:
        pending = sess.get("pending_q")
        if pending:
            sess.setdefault("qa", []).append({"q": pending, "a": text})
        else:
            sess["idea"] = (sess.get("idea") or "") + "\n" + text
        await update.message.chat.send_action("typing")
        await _ai_design_turn(update.message, user.id)
        return

    if state == S_AI_CONFIRM:
        low = text.lower()
        if any(w in low for w in ("build", "go", "yes", "ok", "proceed", "start",
                                  "banao", "bana", "haan", "ha", "theek", "thik")):
            status_msg = await update.message.reply_text(t("building_now", lang))
            await _generate_and_deploy(status_msg, user.id, sess)
        else:
            sess["idea"] = (sess.get("idea") or "") + "\n" + text
            await update.message.chat.send_action("typing")
            await _ai_design_turn(update.message, user.id)
        return

    # Default: 24/7 AI coding help (DB-backed history), streamed for speed.
    await update.message.chat.send_action("typing")
    await _stream_reply(update.message, user.id, text)


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
    msg = await update.message.reply_text("📡 Fetching cluster stats…")
    stats = await asyncio.to_thread(cm.get_cluster_stats)
    if not stats:
        await msg.edit_text("No servers configured. Add one with /addserver.")
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
        await update.message.reply_text("No servers. Use /addserver <id> <ip>")
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
        f"✅ Server <b>{esc(server_id)}</b> ({esc(ip)}) added & active — no restart needed.",
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
                f"🚚 Your bot <b>{esc(bot['name'])}</b> was moved to server "
                f"<b>{esc(to_s)}</b> and restarted. ✅",
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
        await update.message.reply_text("user_id must be an integer.")
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
        await update.message.reply_text("user_id and bot_limit must be integers.")
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
        "Copy this into the <b>SSH Keys</b> settings of your other Selfhost "
        "servers (server2, server3, …).\n\n"
        f"<pre>{esc(pub)}</pre>\n"
        "💡 Tip: tap to copy."
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
                    text = (f"♻️ Your bot <b>{esc(bot_name)}</b> had crashed and was "
                            f"auto-restarted (attempt {ev.get('restarts')}/3).")
                else:
                    # AI-diagnose the final crash using the full source tree.
                    sources = await asyncio.to_thread(cm.read_sources, ev["bot_id"])
                    fix = await asyncio.to_thread(
                        ai_coder_agent.fix_code, ev.get("log_tail", ""),
                        sources or {}, (bot or {}).get("language", "python"),
                    )
                    diag = fix.get("explanation") if fix.get("ok") else fix.get("error", "")
                    text = (
                        f"🔴 Your bot <b>{esc(bot_name)}</b> is stopped after crashing "
                        f"3 times.\n\n<b>AI diagnosis:</b>\n{esc_trunc(diag or '', 2000)}\n\n"
                        "To fix it: 📂 My Bots → 🩺 AI Auto-Fix"
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
        "This bot runs on an ephemeral filesystem (Render), so the cluster key "
        "<b>can change on every restart/deploy</b>.\n\n"
        "If SSH to your Selfhost servers breaks:\n"
        "1. Copy the <b>new</b> key below into server2/server3's "
        "<code>Org Settings &gt; SSH Keys</code>, replacing the old one.\n"
        "2. Or set <code>CLUSTER_PRIVATE_KEY</code> in Render to make it permanent.\n\n"
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
            "❌ TELEGRAM_BOT_TOKEN missing. Set it in your environment (see .env.example)."
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
