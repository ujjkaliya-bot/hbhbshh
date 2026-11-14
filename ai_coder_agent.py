"""
ai_coder_agent.py — Autonomous AI coding, editing and bug-fixing agent.

Works with any OpenAI-compatible endpoint (OpenRouter, Kilo, OpenAI, Gemini
via its OpenAI-compatible shim, local llama.cpp servers, ...) configured
through:

    AI_API_KEY   = sk-...
    AI_BASE_URL  = https://openrouter.ai/api/v1   (or any compatible base)
    AI_MODEL     = openai/gpt-4o-mini              (or any tool-capable model)

The agent exposes three high-level capabilities used by the Telegram bot:

* ``generate_project(prompt, language)`` — turn a plain Hindi/English idea
  into a complete, multi-file, runnable bot project.
* ``fix_code(log_tail, files, language)`` — read a crash log + the current
  sources and return rewritten file(s) that fix the bug.
* ``answer(question, history)`` — general 24/7 coding/hosting help in
  simple Hinglish.

All generated/patch files are returned as a plain ``{path: contents}`` map so
the caller can run them through ``security_scanner`` before anything executes.
The module is import-safe with no network access at import time.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

try:  # The SDK is optional at import time so the bot can start without AI.
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1").strip()
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini").strip()

MAX_PROJECT_FILES = 25
MAX_FILE_CHARS = 20000
REQUEST_TIMEOUT = 120

# Some OpenAI-compatible gateways (e.g. Kilo/OpenRouter free routing) reject the
# `response_format` field. We try it once, then permanently fall back to prompt
# -only JSON for the rest of the process so we don't waste a call every time.
_json_mode_supported = True


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
PROJECT_SYSTEM_PROMPT = """\
You are "Kilo", a senior full-stack engineer that writes COMPLETE, runnable
Telegram/automation bots. You NEVER use placeholders or TODOs — every file is
production-ready.

When asked to build a bot, reply with ONLY a JSON object (no prose outside it):
{
  "language": "python" | "node",
  "summary": "<one line, in Hinglish, of what you built>",
  "entrypoint": "<the main file to run, e.g. main.py or index.js>",
  "files": { "<relative/path>": "<full file contents>", ... },
  "run_command": "<command to start it, e.g. python main.py>"
}

Rules:
- Python bots: include `requirements.txt`. The bot MUST read its token from the
  TELEGRAM_BOT_TOKEN environment variable (never hard-code secrets).
- Node bots: include `package.json` with a `start` script and correct deps.
- Keep dependencies minimal and widely available on PyPI/npm.
- The code must run unattended 24/7 and log errors to stdout/stderr.
- Never emit shell commands that delete files, format disks, or reboot hosts.
"""

FIX_SYSTEM_PROMPT = """\
You are "Kilo", an expert debugger. You are given a bot's crash log and its
source files. Identify the root cause and produce a MINIMAL fix.

Reply with ONLY a JSON object:
{
  "explanation": "<root cause + fix, in simple Hinglish, 1-3 sentences>",
  "files": { "<path to change>": "<full NEW contents of that file>" }
}

Rules:
- Only include files you actually changed.
- Return the COMPLETE new file contents, not a diff.
- If the fix is a dependency, update requirements.txt / package.json instead.
- Never introduce shell commands that delete files, format disks or reboot.
"""

HELP_SYSTEM_PROMPT = """\
You are "Kilo", a friendly 24/7 AI coding & bot-hosting assistant for Indian
users. Answer in simple Hinglish (Hindi in Roman script mixed with English
technical terms). Be concise, practical and friendly. When you show code, use
short fenced blocks. If the user asks to build or fix a bot, tell them to use
the dashboard buttons.
"""


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class AICoderError(Exception):
    """Raised for recoverable AI-agent problems."""


# --------------------------------------------------------------------------- #
# Client helpers
# --------------------------------------------------------------------------- #
def is_configured() -> bool:
    """True when an API key and SDK are available."""
    return bool(AI_API_KEY) and OpenAI is not None


def not_configured_message() -> str:
    return (
        "⚠️ *AI Support abhi configure nahi hai.*\n"
        "Server ke `/opt/kilo-host-agent/.env` me `AI_API_KEY` (aur zarurat ho to "
        "`AI_BASE_URL`) daalein, phir service restart karein:\n"
        "`systemctl restart kilo-host-agent`"
    )


def _client() -> "OpenAI":
    if OpenAI is None:
        raise AICoderError("openai SDK not installed (pip install openai).")
    if not AI_API_KEY:
        raise AICoderError("AI_API_KEY is not set.")
    return OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL, timeout=REQUEST_TIMEOUT)


def _chat(messages: list[dict], max_tokens: int = 4000, temperature: float = 0.2,
          json_mode: bool = True) -> str:
    """One chat completion round; returns the assistant text (may be '')."""
    global _json_mode_supported
    client = _client()
    kwargs: dict = {
        "model": AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    use_json = json_mode and _json_mode_supported
    if use_json:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        if use_json:
            # Gateway/model rejects structured output — disable it for good and
            # retry relying on the prompt's "reply with ONLY JSON" instruction.
            _json_mode_supported = False
            kwargs.pop("response_format", None)
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as exc2:  # noqa: BLE001
                raise AICoderError(_friendly_ai_error(exc2)) from exc2
        else:
            raise AICoderError(_friendly_ai_error(exc)) from exc
    if not resp.choices:
        return ""
    return (resp.choices[0].message.content or "").strip()


def _friendly_ai_error(exc: Exception) -> str:
    """Turn SDK/HTTP errors into an actionable Hinglish message."""
    text = str(exc)
    low = text.lower()
    if "credits required" in low or "paid model" in low or "402" in low:
        return ("AI account me credits nahi hain. Kilo par free model use karein "
                "(AI_MODEL=kilo-auto/free) ya https://app.kilo.ai/profile par "
                "credits add karein.")
    if "authentication" in low or "invalid_token" in low or "401" in low:
        return "AI_API_KEY galat/expired hai. .env me nayi key daal kar service restart karein."
    if "rate limit" in low or "429" in low:
        return "AI rate limit hit ho gaya — thodi der baad dobara try karein."
    return f"AI request failed: {text[:300]}"


# --------------------------------------------------------------------------- #
# JSON extraction (robust to fences / stray prose)
# --------------------------------------------------------------------------- #
def extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model reply."""
    if not text:
        return None
    text = text.strip()
    # Strip ```json ... ``` fences.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _sanitize_files(raw: object) -> dict[str, str]:
    """Validate/limit a ``{path: contents}`` map coming from the model."""
    files: dict[str, str] = {}
    if not isinstance(raw, dict):
        return files
    for path, contents in raw.items():
        if not isinstance(path, str) or not isinstance(contents, str):
            continue
        safe = path.strip().lstrip("/")
        if not safe or ".." in safe.split("/"):
            continue
        if len(files) >= MAX_PROJECT_FILES:
            break
        files[safe] = contents[:MAX_FILE_CHARS]
    return files


# --------------------------------------------------------------------------- #
# Public capabilities
# --------------------------------------------------------------------------- #
def generate_project(prompt: str, language: Optional[str] = None) -> dict:
    """
    Build a complete bot project from a natural-language prompt.

    Returns ``{"ok", "language", "summary", "entrypoint", "files", "run_command"}``
    or ``{"ok": False, "error": ...}``.
    """
    if not is_configured():
        return {"ok": False, "error": not_configured_message()}

    hint = f"\nPreferred language: {language}." if language in ("python", "node") else ""
    messages = [
        {"role": "system", "content": PROJECT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Build this bot:\n{prompt}{hint}"},
    ]
    text = _chat(messages, max_tokens=4000)
    data = extract_json(text)
    if not data:
        return {"ok": False, "error": "AI ne valid project JSON nahi diya. Dobara try karein."}

    files = _sanitize_files(data.get("files"))
    if not files:
        return {"ok": False, "error": "AI ne koi file generate nahi ki. Prompt thoda saaf likhein."}

    lang = data.get("language") if data.get("language") in ("python", "node") else (language or "python")
    entrypoint = data.get("entrypoint") or ("main.py" if lang == "python" else "index.js")
    if entrypoint not in files:
        entrypoint = next(iter(files))

    # Guarantee a dependency manifest exists.
    if lang == "python" and "requirements.txt" not in files:
        files["requirements.txt"] = "python-telegram-bot>=20.0\n"
    if lang == "node" and "package.json" not in files:
        files["package.json"] = json.dumps(
            {"name": "user-bot", "version": "1.0.0", "main": entrypoint,
             "scripts": {"start": f"node {entrypoint}"}}, indent=2)

    return {
        "ok": True,
        "language": lang,
        "summary": data.get("summary") or "Bot generate ho gaya.",
        "entrypoint": entrypoint,
        "files": files,
        "run_command": data.get("run_command") or (
            f"python {entrypoint}" if lang == "python" else f"node {entrypoint}"),
    }


def fix_code(log_tail: str, files: dict[str, str], language: str = "python") -> dict:
    """
    Diagnose a crash and return patched file(s).

    ``files`` is the current source map. Returns
    ``{"ok", "explanation", "files"}`` or ``{"ok": False, "error"}``.
    """
    if not is_configured():
        return {"ok": False, "error": not_configured_message()}

    bundle = []
    for path, contents in list(files.items())[:MAX_PROJECT_FILES]:
        bundle.append(f"===== {path} =====\n{contents[:MAX_FILE_CHARS]}")
    source_blob = "\n\n".join(bundle) or "(no source available)"

    messages = [
        {"role": "system", "content": FIX_SYSTEM_PROMPT},
        {"role": "user", "content":
            f"Language: {language}\n\nCrash log:\n```\n{log_tail[-6000:]}\n```\n\n"
            f"Source files:\n{source_blob}"},
    ]
    text = _chat(messages, max_tokens=4000)
    data = extract_json(text)
    if not data:
        return {"ok": False, "error": "AI ne valid fix JSON nahi diya."}

    patched = _sanitize_files(data.get("files"))
    if not patched:
        return {"ok": False, "error": "AI ne koi patched file nahi di."}
    return {
        "ok": True,
        "explanation": data.get("explanation") or "Bug fix apply kiya gaya.",
        "files": patched,
    }


def edit_file(filename: str, current: str, instruction: str,
              language: str = "python") -> dict:
    """Rewrite a single file per an instruction. Returns ``{"ok","contents"}``."""
    if not is_configured():
        return {"ok": False, "error": not_configured_message()}
    messages = [
        {"role": "system", "content":
            "You are Kilo. Rewrite the given file to satisfy the instruction. "
            "Reply with ONLY the complete new file contents (no fences, no prose)."},
        {"role": "user", "content":
            f"Language: {language}\nFile: {filename}\nInstruction: {instruction}\n\n"
            f"Current contents:\n{current[:MAX_FILE_CHARS]}"},
    ]
    text = _chat(messages, max_tokens=4000, json_mode=False)
    if not text:
        return {"ok": False, "error": "AI ne khaali reply diya."}
    fence = re.search(r"```(?:[\w]+)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    return {"ok": True, "contents": text}


def answer(question: str, history: Optional[list[dict]] = None) -> str:
    """General 24/7 coding/hosting help. Returns a plain-text reply."""
    if not is_configured():
        return not_configured_message()
    messages = [{"role": "system", "content": HELP_SYSTEM_PROMPT}]
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    try:
        return _chat(messages, max_tokens=1200, temperature=0.4, json_mode=False) or "(no reply)"
    except AICoderError as exc:
        return f"⚠️ AI error: {exc}"


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    print("configured:", is_configured())
    print("extract_json:", extract_json('```json\n{"a": 1}\n```'))
