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
  clear, simple English.

All generated/patch files are returned as a plain ``{path: contents}`` map so
the caller can run them through ``security_scanner`` before anything executes.
The module is import-safe with no network access at import time.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

log = logging.getLogger("kilo-host-agent.ai")

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
# Optional second model for latency-sensitive turns (clarify + chat). Falls back
# to AI_MODEL when unset. Heavy builds/fixes always use AI_MODEL.
AI_FAST_MODEL = (os.environ.get("AI_FAST_MODEL", "").strip() or AI_MODEL)

MAX_PROJECT_FILES = 25
MAX_FILE_CHARS = 40000
REQUEST_TIMEOUT = 180
# Multi-file projects need a generous output budget or the JSON gets truncated
# mid-file and can no longer be parsed.
PROJECT_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "16000"))
# Reasoning models spend tokens "thinking" before they emit any content, so the
# budget must cover both or the reply comes back empty.
CLARIFY_MAX_TOKENS = int(os.environ.get("AI_CLARIFY_MAX_TOKENS", "2000"))
CHAT_MAX_TOKENS = int(os.environ.get("AI_CHAT_MAX_TOKENS", "2000"))
FIX_MAX_TOKENS = 16000

# Transient provider errors (rate limits, overload) are retried with backoff.
_RETRIES = int(os.environ.get("AI_RETRIES", "2"))
_RETRY_BACKOFF = float(os.environ.get("AI_RETRY_BACKOFF", "3"))


# Some OpenAI-compatible gateways (e.g. Kilo/OpenRouter free routing) reject the
# `response_format` field. We try it once, then permanently fall back to prompt
# -only JSON for the rest of the process so we don't waste a call every time.
_json_mode_supported = True


# --------------------------------------------------------------------------- #
# Language detection + reply-language instructions
# --------------------------------------------------------------------------- #
# Supported reply languages: "en" (English), "hi" (Hindi/Devanagari),
# "hinglish" (Hindi in Latin script, e.g. "mujhe ek bot chahiye").
LANG_EN, LANG_HI, LANG_HINGLISH = "en", "hi", "hinglish"

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
# Common romanised-Hindi function words. Two or more hits => Hinglish.
_HINGLISH_WORDS = {
    "mujhe", "chahiye", "karo", "karna", "kaise", "kya", "hai", "hain", "nahi",
    "nahin", "banao", "bana", "banana", "kar", "ki", "ka", "ke", "ko", "se",
    "mera", "meri", "apna", "ek", "aur", "bhi", "yeh", "ye", "wo", "wala",
    "wali", "matlab", "acha", "accha", "theek", "thik", "samajh", "batao",
    "dena", "dedo", "karvao", "banwao", "bhai", "yaar", "kaam", "sakta",
    "sakte", "hoga", "hogi", "kab", "kahan", "kaun", "kitna", "zyada",
    "thoda", "abhi", "phir", "lekin", "kyunki", "isliye", "jaise", "aisa",
}
# Devanagari digits are irrelevant here; script is enough to call it Hindi.

_REPLY_LANG_INSTRUCTION = {
    LANG_EN: "Reply in English.",
    LANG_HI: "Reply in Hindi using Devanagari script (हिन्दी). Keep code, "
              "commands, file names and technical terms in English.",
    LANG_HINGLISH: "Reply in Hinglish — Hindi written in Latin/English script, "
                   "the casual way Indian users text (e.g. \"Bilkul, main bana "
                   "deta hoon\"). Keep code, commands, file names and technical "
                   "terms in English.",
}


def detect_language(text: str) -> str:
    """Guess the user's language: 'hi', 'hinglish' or 'en'.

    Devanagari script wins outright. Otherwise two or more common romanised-Hindi
    words mark the text as Hinglish. Defaults to English.
    """
    if not text:
        return LANG_EN
    if _DEVANAGARI_RE.search(text):
        return LANG_HI
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return LANG_EN
    hits = sum(1 for w in words if w in _HINGLISH_WORDS)
    # One hit is too noisy on short English text; require two, or one when the
    # message is tiny and clearly romanised-Hindi.
    if hits >= 2 or (hits == 1 and len(words) <= 3):
        return LANG_HINGLISH
    return LANG_EN


def reply_language_instruction(lang: str) -> str:
    """Instruction line telling the model which language to answer in."""
    return _REPLY_LANG_INSTRUCTION.get(lang or LANG_EN, _REPLY_LANG_INSTRUCTION[LANG_EN])


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
PROJECT_SYSTEM_PROMPT = """\
You are "Kilo", a principal-level full-stack engineer who ships COMPLETE,
production-grade Telegram and automation bots. Your output is always runnable
as-is: no placeholders, no TODOs, no "your_token_here" stubs, no ellipses.

Reply with ONLY a single JSON object — no prose and no markdown fences around it:
{
  "language": "python" | "node",
  "summary": "<one clear sentence describing what you built>",
  "entrypoint": "<main file to run, e.g. main.py or index.js>",
  "files": { "<relative/path>": "<full file contents>", ... },
  "run_command": "<command that starts it, e.g. python main.py>"
}

Quality bar — aim for a polished, senior-engineer result:
- Complete, coherent multi-file projects. Split concerns into modules when it
  improves clarity instead of dumping everything into one giant file.
- Robust error handling: catch and log failures, never crash silently, and shut
  down gracefully. Retry transient network operations where it matters.
- Structured logging to stdout/stderr with timestamps.
- Clear, minimal comments that explain intent (not line-by-line narration).
- Modern async Python (python-telegram-bot v20+ style) or idiomatic Node.js.
- Read every secret from environment variables; never hard-code tokens.
- Python: always include requirements.txt (with >= version bounds).
  Node: always include package.json with a "start" script and correct deps.
- Always include a short README.md documenting setup, required env vars and how
  to run. Include a .env.example listing the env vars (with dummy values).
- Keep dependencies minimal and widely available on PyPI/npm.
- The bot must run unattended 24/7 and degrade gracefully on network errors.

Language:
- Write the "summary" in the same language the user used (English, Hindi or
  Hinglish). All CODE, comments, README and identifiers stay in English.

Safety:
- Never emit shell commands that delete files, format disks or reboot hosts.
- Never exfiltrate secrets or call unknown third-party endpoints.
"""

CLARIFY_SYSTEM_PROMPT = """\
You are "Kilo", a friendly senior engineer who helps the user design their bot
BEFORE any code is written. Your job is to (1) restate the whole idea back in
clear, simple language so you both agree on it, and (2) ask exactly ONE focused
follow-up question at a time until you have enough detail to build a great bot.

Reply with ONLY a JSON object:
{
  "understood": "<a clear restatement of everything agreed so far, 2-5 sentences>",
  "question": "<exactly ONE short, specific question to ask next, or null if ready>",
  "ready": true | false
}

Rules:
- Write "understood" and "question" in the SAME language the user writes in
  (English, Hindi/Devanagari, or Hinglish). If the user mixes languages, mirror
  their mix. Keep code names and technical terms in English.
- Restate the full picture every time, folding in the user's latest answer.
- Ask only ONE question per turn. Prioritise the most important unknowns first:
  what the bot does, its commands/features, storage or database needs, external
  APIs it talks to, admin controls, and any scheduling.
- Set "ready": true once you have enough to build a solid bot, or if the user
  says to go ahead / build now / no more questions. Then set "question": null.
- Never ask about programming language or secret tokens (the app handles those).
- Never ask more than 6 questions in total.
"""

FIX_SYSTEM_PROMPT = """\
You are "Kilo", an expert debugger. You are given a bot's crash log and its
source files. Identify the root cause and produce a MINIMAL, correct fix.

Reply with ONLY a JSON object:
{
  "explanation": "<root cause + fix, 1-3 sentences>",
  "files": { "<path to change>": "<full NEW contents of that file>" }
}

Rules:
- Write "explanation" in the same language the user writes in (English, Hindi
  or Hinglish). Code stays in English.
- Only include files you actually changed.
- Return the COMPLETE new file contents, never a diff.
- If the real fix is a dependency, update requirements.txt / package.json.
- Keep the surrounding style, logging and error handling intact.
- Never introduce shell commands that delete files, format disks or reboot.
"""

HELP_SYSTEM_PROMPT = """\
You are "Kilo", a friendly 24/7 AI coding & bot-hosting assistant. Be concise,
practical and friendly. Answer in the user's language — English, Hindi
(Devanagari) or Hinglish — mirroring however they write. When you show code, use
short fenced blocks and keep code in English. If the user wants to build or fix a
bot, point them to the dashboard buttons.
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
        "⚠️ *AI is not configured yet.*\n"
        "Set the `AI_API_KEY` environment variable (and `AI_BASE_URL` if you use a "
        "custom endpoint), then redeploy the service."
    )


def _client() -> "OpenAI":
    if OpenAI is None:
        raise AICoderError("openai SDK not installed (pip install openai).")
    if not AI_API_KEY:
        raise AICoderError("AI_API_KEY is not set.")
    return OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL, timeout=REQUEST_TIMEOUT)


def _chat(messages: list[dict], max_tokens: int = 4000, temperature: float = 0.2,
          json_mode: bool = True, model: Optional[str] = None) -> str:
    """One chat completion round; returns the assistant text (may be '')."""
    global _json_mode_supported
    client = _client()
    kwargs: dict = {
        "model": model or AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    use_json = json_mode and _json_mode_supported
    if use_json:
        kwargs["response_format"] = {"type": "json_object"}

    resp = None
    last_exc: Optional[Exception] = None
    active_model = model or AI_MODEL
    for attempt in range(_RETRIES + 1):
        try:
            kwargs["model"] = active_model
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if use_json and _is_json_unsupported(exc):
                # Gateway/model rejects structured output — disable it for good
                # and retry relying on the prompt's "reply with ONLY JSON" hint.
                _json_mode_supported = False
                use_json = False
                kwargs.pop("response_format", None)
                continue
            if _is_transient(exc) and attempt < _RETRIES:
                delay = _RETRY_BACKOFF * (attempt + 1)
                log.warning("transient AI error (%s); retrying in %.1fs",
                            type(exc).__name__, delay)
                time.sleep(delay)
                continue
            # A free/cheap fast model can vanish or run out of credit; fall back
            # to the main model once before giving up.
            if active_model != AI_MODEL:
                log.warning("model %s failed (%s); falling back to %s",
                            active_model, type(exc).__name__, AI_MODEL)
                active_model = AI_MODEL
                continue
            raise AICoderError(_friendly_ai_error(exc)) from exc

        # Reasoning models can burn the whole budget "thinking" and emit no
        # content. Retry once with double the budget instead of returning "".
        if _empty_reasoning_reply(resp) and attempt < _RETRIES:
            bumped = min(int(kwargs["max_tokens"]) * 2, 32000)
            log.warning("model returned no content (reasoning used the budget); "
                        "retrying with max_tokens=%s", bumped)
            kwargs["max_tokens"] = bumped
            continue
        break

    if resp is None:
        raise AICoderError(_friendly_ai_error(last_exc or RuntimeError("no response")))
    if not resp.choices:
        return ""
    choice = resp.choices[0]
    content = (choice.message.content or "").strip()
    if getattr(choice, "finish_reason", None) == "length":
        log.warning("AI response hit the token limit (max_tokens=%s); output truncated.",
                    max_tokens)
    return content


def _stream_chat(messages: list[dict], max_tokens: int = CHAT_MAX_TOKENS,
                 temperature: float = 0.4, model: Optional[str] = None):
    """Yield assistant text deltas as they arrive (for a snappy chat feel).

    Reasoning models emit their thinking first; only ``content`` deltas are
    yielded so the user never sees raw chain-of-thought.
    """
    client = _client()
    stream = client.chat.completions.create(
        model=model or AI_FAST_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            yield piece


def _empty_reasoning_reply(resp) -> bool:
    """True when the model spent its whole budget thinking and returned no text."""
    if resp is None or not getattr(resp, "choices", None):
        return False
    choice = resp.choices[0]
    content = (choice.message.content or "").strip()
    if content:
        return False
    usage = getattr(resp, "usage", None)
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    reasoning = getattr(details, "reasoning_tokens", 0) if details else 0
    return bool(reasoning) or getattr(choice, "finish_reason", None) == "length"


def _is_json_unsupported(exc: Exception) -> bool:
    low = str(exc).lower()
    return ("response_format" in low or "json_object" in low or "json mode" in low
            or "structured" in low) and not _is_transient(exc)


def _is_transient(exc: Exception) -> bool:
    """True for errors worth retrying (rate limits, overload, gateway hiccups)."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in (429, 500, 502, 503, 504):
        return True
    low = str(exc).lower()
    return any(s in low for s in (
        "rate limit", "429", "high demand", "unavailable", "503",
        "timeout", "timed out", "connection", "overloaded"))




def _friendly_ai_error(exc: Exception) -> str:
    """Turn SDK/HTTP errors into an actionable English message."""
    text = str(exc)
    low = text.lower()
    if "credits required" in low or "paid model" in low or "402" in low:
        return ("Your AI account has no credits. Use a free model "
                "(e.g. AI_MODEL=kilo-auto/free) or add credits to your provider.")
    if "authentication" in low or "invalid_token" in low or "invalid token" in low \
            or "401" in low:
        return ("The AI_API_KEY is invalid or expired, or it does not match the "
                "configured AI_BASE_URL. Set a valid key (with a matching "
                "AI_BASE_URL) and redeploy.")
    if "model" in low and ("not found" in low or "no longer available" in low
                           or "404" in low):
        return ("The configured AI_MODEL is not available on this endpoint. Pick a "
                "supported model and redeploy.")
    if "rate limit" in low or "429" in low:
        return "The AI provider is rate-limiting us — please try again in a moment."
    if "high demand" in low or "unavailable" in low or "503" in low:
        return "The AI model is temporarily overloaded — please try again shortly."
    return f"AI request failed: {text[:300]}"


# --------------------------------------------------------------------------- #
# JSON extraction (robust to fences / stray prose)
# --------------------------------------------------------------------------- #
def _loads(text: str) -> Optional[dict]:
    """json.loads that tolerates the control characters models leave in strings."""
    try:
        val = json.loads(text, strict=False)
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        return None


def extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model reply.

    Tries, in order: the whole reply, a leading/trailing ```json fence, then the
    outermost ``{...}`` block. Models often embed literal newlines inside string
    values (e.g. file contents), which strict JSON rejects — hence
    ``strict=False``. Order matters: a naive fence regex can match a code block
    *inside* a generated README, so the raw text is tried first.
    """
    if not text:
        return None
    text = text.strip()

    data = _loads(text)
    if data is not None:
        return data

    # ```json ... ``` fence wrapping the whole reply.
    fence = re.match(r"```(?:json)?\s*(.*?)```\s*$", text, re.S)
    if fence:
        data = _loads(fence.group(1).strip())
        if data is not None:
            return data

    # Outermost {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return _loads(text[start:end + 1])
    return None




def _chat_json(messages: list[dict], max_tokens: int = PROJECT_MAX_TOKENS,
               temperature: float = 0.2, retries: int = 1,
               model: Optional[str] = None) -> Optional[dict]:
    """Chat expecting a JSON object, retrying once if the reply is unusable.

    Multi-file generations can be cut off when the provider caps output length;
    on failure we feed the partial reply back and ask for a complete, more
    concise JSON object.
    """
    last = ""
    for attempt in range(retries + 1):
        last = _chat(messages, max_tokens=max_tokens, temperature=temperature,
                     model=model)
        data = extract_json(last)
        if data is not None:
            return data
        if attempt < retries:
            log.warning("AI reply was not valid JSON (len=%d); retrying.", len(last))
            messages = messages + [
                {"role": "assistant", "content": last},
                {"role": "user", "content":
                    "Your previous reply was cut off or was not valid JSON. Reply "
                    "again with ONLY one complete JSON object and no prose. Keep each "
                    "file concise so the whole object fits in the response."},
            ]
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
def clarify_bot(idea: str, answers: Optional[list[dict]] = None,
                max_questions: int = 6, lang: Optional[str] = None) -> dict:
    """
    Restate the user's idea and ask ONE follow-up question, in their language.

    ``answers`` is the running transcript: ``[{"q": ..., "a": ...}, ...]``.
    ``lang`` is "en", "hi" or "hinglish" (auto-detected from the idea when None).
    Returns ``{"ok", "understood", "question", "ready"}`` or ``{"ok": False,
    "error"}``. When ``ready`` is true, ``question`` is ``None``.
    """
    if not is_configured():
        return {"ok": False, "error": not_configured_message()}

    lang = lang or detect_language(idea)
    lines = [f"Original idea:\n{idea.strip()}"]
    if answers:
        lines.append("\nAnswers so far:")
        for i, turn in enumerate(answers, 1):
            lines.append(f"{i}. Q: {turn.get('q', '').strip()}\n   A: {turn.get('a', '').strip()}")
    lines.append(f"\nQuestions asked so far: {len(answers or [])} of {max_questions}.")
    if answers and len(answers) >= max_questions:
        lines.append("You have reached the maximum number of questions — set "
                     '"ready": true now and "question": null.')

    messages = [
        {"role": "system", "content": CLARIFY_SYSTEM_PROMPT
            + "\n" + reply_language_instruction(lang)},
        {"role": "user", "content": "\n".join(lines)},
    ]
    data = _chat_json(messages, max_tokens=CLARIFY_MAX_TOKENS, temperature=0.3,
                      model=AI_FAST_MODEL)
    if not data:
        return {"ok": False, "error": "AI did not return a valid response. Please try again."}

    ready = bool(data.get("ready"))
    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        question = None
        ready = True
    if answers and len(answers) >= max_questions:
        ready = True
        question = None
    understood = (data.get("understood") or "").strip() or "Got it."
    return {"ok": True, "understood": understood, "question": question, "ready": ready}


def generate_project(prompt: str, language: Optional[str] = None,
                     lang: Optional[str] = None) -> dict:
    """
    Build a complete bot project from a natural-language prompt.

    ``lang`` controls the language of the "summary" (English/Hindi/Hinglish).
    Returns ``{"ok", "language", "summary", "entrypoint", "files", "run_command"}``
    or ``{"ok": False, "error": ...}``.
    """
    if not is_configured():
        return {"ok": False, "error": not_configured_message()}

    lang = lang or detect_language(prompt)
    hint = f"\nPreferred language: {language}." if language in ("python", "node") else ""
    messages = [
        {"role": "system", "content": PROJECT_SYSTEM_PROMPT
            + "\n" + reply_language_instruction(lang)},
        {"role": "user", "content": f"Build this bot:\n{prompt}{hint}"},
    ]
    data = _chat_json(messages, max_tokens=PROJECT_MAX_TOKENS, model=AI_MODEL)
    if not data:
        return {"ok": False, "error": "The AI did not return a valid project. Please try again."}

    files = _sanitize_files(data.get("files"))
    if not files:
        return {"ok": False, "error": "The AI did not generate any files. Try describing the bot in more detail."}

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
        "summary": data.get("summary") or "Your bot is ready.",
        "entrypoint": entrypoint,
        "files": files,
        "run_command": data.get("run_command") or (
            f"python {entrypoint}" if lang == "python" else f"node {entrypoint}"),
    }


def fix_code(log_tail: str, files: dict[str, str], language: str = "python",
             lang: Optional[str] = None) -> dict:
    """
    Diagnose a crash and return patched file(s).

    ``files`` is the current source map. ``lang`` controls the explanation
    language. Returns ``{"ok", "explanation", "files"}`` or ``{"ok": False,
    "error"}``.
    """
    if not is_configured():
        return {"ok": False, "error": not_configured_message()}

    lang = lang or LANG_EN
    bundle = []
    for path, contents in list(files.items())[:MAX_PROJECT_FILES]:
        bundle.append(f"===== {path} =====\n{contents[:MAX_FILE_CHARS]}")
    source_blob = "\n\n".join(bundle) or "(no source available)"

    messages = [
        {"role": "system", "content": FIX_SYSTEM_PROMPT
            + "\n" + reply_language_instruction(lang)},
        {"role": "user", "content":
            f"Language: {language}\n\nCrash log:\n```\n{log_tail[-6000:]}\n```\n\n"
            f"Source files:\n{source_blob}"},
    ]
    data = _chat_json(messages, max_tokens=FIX_MAX_TOKENS, model=AI_MODEL)
    if not data:
        return {"ok": False, "error": "The AI did not return a valid fix. Please try again."}

    patched = _sanitize_files(data.get("files"))
    if not patched:
        return {"ok": False, "error": "The AI did not produce any patched files."}
    return {
        "ok": True,
        "explanation": data.get("explanation") or "Applied a bug fix.",
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
        return {"ok": False, "error": "The AI returned an empty reply."}
    fence = re.search(r"```(?:[\w]+)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    return {"ok": True, "contents": text}


def _answer_messages(question: str, history: Optional[list[dict]],
                     lang: Optional[str]) -> list[dict]:
    messages = [{"role": "system", "content": HELP_SYSTEM_PROMPT
                 + "\n" + reply_language_instruction(lang or LANG_EN)}]
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    return messages


def answer(question: str, history: Optional[list[dict]] = None,
           lang: Optional[str] = None) -> str:
    """General 24/7 coding/hosting help. Returns a plain-text reply."""
    if not is_configured():
        return not_configured_message()
    lang = lang or detect_language(question)
    messages = _answer_messages(question, history, lang)
    try:
        return _chat(messages, max_tokens=CHAT_MAX_TOKENS, temperature=0.4,
                     json_mode=False, model=AI_FAST_MODEL) or "(no reply)"
    except AICoderError as exc:
        return f"⚠️ AI error: {exc}"


def stream_answer(question: str, history: Optional[list[dict]] = None,
                  lang: Optional[str] = None):
    """Yield the reply text in pieces as the model streams it."""
    if not is_configured():
        yield not_configured_message()
        return
    lang = lang or detect_language(question)
    messages = _answer_messages(question, history, lang)
    try:
        for piece in _stream_chat(messages, model=AI_FAST_MODEL):
            yield piece
    except Exception as exc:  # noqa: BLE001
        log.warning("stream_answer failed: %s", exc)
        yield f"\n\n⚠️ AI error: {_friendly_ai_error(exc)}"


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    print("configured:", is_configured())
    print("extract_json:", extract_json('```json\n{"a": 1}\n```'))
