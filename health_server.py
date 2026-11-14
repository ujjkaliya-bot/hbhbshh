"""
health_server.py — tiny aiohttp HTTP server for Render / UptimeRobot keep-alive.

The Master Bot normally talks *out* to Telegram (long polling), so on a Render
"web service" we also need to listen on ``$PORT`` and answer HTTP probes. This
module exposes:

    GET /                    -> 200 "Kilo Host Agent is running"
    GET /health              -> 200 {"status": "ok"}
    GET /healthz             -> same as /health
    GET /install_247.sh      -> the self-extracting installer (if present)
    GET /kilo-host-agent.zip -> the ZIP bundle (if present)
    GET /kilo-host-agent-deploy.zip -> repo-root ZIP for Render Blueprint

The last three give a *stable* download URL (e.g.
``https://<service>.onrender.com/install_247.sh``) so you never need a temporary
tunnel again. Port comes from ``PORT`` (Render sets it; default 10000).
Import-safe and a no-op if aiohttp is unavailable.
"""

from __future__ import annotations

import logging
import os

try:  # aiohttp is optional at import time so the bot can still start without it.
    from aiohttp import web
except Exception:  # noqa: BLE001
    web = None  # type: ignore[assignment]

log = logging.getLogger("kilo-host-agent.health")

DEFAULT_PORT = 10000
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(_APP_DIR)
_STATIC = ("install_247.sh", "kilo-host-agent.zip", "kilo-host-agent-deploy.zip")

# Shared with the bot: False once Telegram polling has died for good.
_LIVENESS: dict[str, bool] = {"alive": True}


def _port() -> int:
    try:
        return int(os.environ.get("PORT", str(DEFAULT_PORT)))
    except (TypeError, ValueError):
        return DEFAULT_PORT


def _find_static(name: str) -> str | None:
    for base in (_REPO_DIR, _APP_DIR, "/tmp"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    return None


async def _root(_request):
    # Render's healthCheckPath is "/". Report process liveness here; a wedged
    # event loop simply fails to answer, which Render already treats as down.
    return web.Response(text="Kilo Host Agent is running ✅\n", status=200)


async def _health(_request):
    # Observability only: always 200 so a brief deploy-time overlap (two
    # instances polling for a moment) never triggers a restart loop.
    return web.json_response({
        "status": "ok",
        "service": "kilo-host-agent",
        "telegram_polling": bool(_LIVENESS.get("alive", True)),
    })


def set_liveness(alive: bool) -> None:
    """Called by the bot to advertise whether Telegram polling is healthy."""
    _LIVENESS["alive"] = bool(alive)


def _make_static(name: str):
    async def _handler(_request):
        path = _find_static(name)
        if not path:
            return web.Response(text=f"{name} not found on this instance.\n", status=404)
        return web.FileResponse(path)
    return _handler


async def start_health_server(host: str = "0.0.0.0", port: int | None = None):
    """Start the HTTP server; returns the AppRunner (or None if disabled)."""
    if web is None:
        log.warning("aiohttp not installed — HTTP health server disabled")
        return None
    port = port or _port()
    app = web.Application()
    app.router.add_get("/", _root)
    app.router.add_get("/health", _health)
    app.router.add_get("/healthz", _health)
    for name in _STATIC:
        app.router.add_get(f"/{name}", _make_static(name))
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("HTTP health server listening on %s:%s (GET /)", host, port)
    return runner


async def stop_health_server(runner) -> None:
    if runner is not None:
        try:
            await runner.cleanup()
        except Exception as exc:  # noqa: BLE001
            log.warning("health server cleanup failed: %s", exc)
