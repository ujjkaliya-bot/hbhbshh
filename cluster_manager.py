"""
cluster_manager.py — SSH/SFTP orchestrator and smart load balancer.

Responsibilities
----------------
* Hold the ED25519 private key and open Paramiko SSH/SFTP connections to any
  server registered in servers.json / the SQLite ``servers`` table.
* Collect live RAM / CPU / disk / load statistics per server.
* Choose the healthiest server (most free RAM) for a new user bot.
* Deploy a user's ZIP: upload via SFTP, unpack, build an isolated virtualenv,
  install dependencies and launch the process under ``ulimit`` caps so one
  tenant cannot exhaust a 2 GB box.
* Watchdog: detect crashes, auto-restart up to ``MAX_RESTARTS`` times, and
  surface the tail of ``bot.log`` for AI diagnosis.
* Zero-downtime migration of every bot off an expiring server onto a fresh one.

Everything here is blocking (Paramiko is synchronous). Async callers should
wrap these methods with ``asyncio.to_thread``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import posixpath
import re
import shlex
import stat
import zipfile
from dataclasses import dataclass, field
from typing import Optional

import paramiko

import database as db
import security_scanner
from security_scanner import SecurityError

log = logging.getLogger("kilo-host-agent.cluster")

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEY_PATH = os.path.join(BASE_DIR, "private_key.pem")

# Server-side dedicated cluster key. When the Master Bot runs on the main
# Selfhost server it generates this key itself and uses it to reach the rest
# of the pool (server2, server3, ...). Only the .pub half is shared.
#
# On Render (ephemeral, read-only root fs) there is no /root/.ssh, so we fall
# back to /tmp. Set CLUSTER_KEY_PATH explicitly to override.
def _default_cluster_key_path() -> str:
    env = os.environ.get("CLUSTER_KEY_PATH")
    if env:
        return env
    if os.access("/root/.ssh", os.W_OK) or os.geteuid() == 0:
        try:
            os.makedirs("/root/.ssh", mode=0o700, exist_ok=True)
            if os.access("/root/.ssh", os.W_OK):
                return "/root/.ssh/cluster_key"
        except OSError:
            pass
    return "/tmp/cluster_key"


CLUSTER_KEY_PATH = _default_cluster_key_path()
CLUSTER_KEY_PUB_PATH = f"{CLUSTER_KEY_PATH}.pub"

REMOTE_ROOT = "/root/hosted_bots"
SSH_TIMEOUT = 20
MAX_RESTARTS = 3

# Per-tenant resource caps applied through `ulimit` before exec.
MEM_LIMIT_MB = 400          # address-space cap per bot process
CPU_SECONDS_LIMIT = 300     # soft CPU seconds before SIGXCPU
FILE_SIZE_LIMIT_MB = 200    # max single file the bot may write
NOFILE_LIMIT = 1024


class ClusterError(Exception):
    """Raised for recoverable cluster/deploy problems."""


@dataclass
class ServerStats:
    server_id: str
    online: bool
    ram_total_mb: int = 0
    ram_used_mb: int = 0
    ram_free_mb: int = 0
    cpu_percent: float = 0.0
    disk_used_pct: float = 0.0
    load1: float = 0.0
    active_bots: int = 0
    error: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ram_free_pct(self) -> float:
        if self.ram_total_mb <= 0:
            return 0.0
        return 100.0 * self.ram_free_mb / self.ram_total_mb


# --------------------------------------------------------------------------- #
# Key handling
# --------------------------------------------------------------------------- #
def _load_key_from(path: str):
    """Parse an OpenSSH private key file, with a generic-key fallback."""
    try:
        return paramiko.Ed25519Key.from_private_key_file(path)
    except paramiko.PasswordRequiredException:
        raise ClusterError("Private key is passphrase-protected; decrypt it first.")
    except paramiko.SSHException as exc:
        # Fall back to generic key detection (covers RSA/ECDSA pasted by mistake).
        try:
            return paramiko.SSHClient()._key_from_filepath(path)  # type: ignore[attr-defined]
        except Exception:
            raise ClusterError(f"Could not parse private key at {path}: {exc}") from exc


def load_private_key():
    """
    Load the SSH key used to reach the server pool.

    Preference order:
      1. The dedicated server-side cluster key (/root/.ssh/cluster_key) — this
         is the key the Master Bot generates for itself on startup.
      2. The operator-supplied private_key.pem next to this file.
    """
    if os.path.exists(CLUSTER_KEY_PATH):
        return _load_key_from(CLUSTER_KEY_PATH)
    if os.path.exists(PRIVATE_KEY_PATH):
        return _load_key_from(PRIVATE_KEY_PATH)
    raise ClusterError(
        "No usable SSH key found. Expected the auto-generated cluster key at "
        f"{CLUSTER_KEY_PATH} or a private_key.pem next to this file."
    )


def ensure_cluster_key(comment: str = "kilo-host-agent-cluster") -> str:
    """
    Ensure /root/.ssh/cluster_key(.pub) exists, generating an ED25519 pair on
    first run. Returns the public key text. Safe to call repeatedly.
    """
    ssh_dir = os.path.dirname(CLUSTER_KEY_PATH) or "/root/.ssh"
    try:
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
        _chmod(ssh_dir, 0o700)
    except OSError:
        pass

    if not os.path.exists(CLUSTER_KEY_PATH):
        # Generate via ssh-keygen when available (most portable), else Paramiko.
        if not _generate_with_ssh_keygen(comment):
            _generate_with_paramiko(comment)

    _chmod(CLUSTER_KEY_PATH, 0o600)
    if os.path.exists(CLUSTER_KEY_PUB_PATH):
        _chmod(CLUSTER_KEY_PUB_PATH, 0o644)
    return read_cluster_pubkey()


def _generate_with_ssh_keygen(comment: str) -> bool:
    import shutil
    import subprocess

    if not shutil.which("ssh-keygen"):
        return False
    try:
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-C", comment,
             "-f", CLUSTER_KEY_PATH],
            check=True, capture_output=True, timeout=60,
        )
        return os.path.exists(CLUSTER_KEY_PATH)
    except (subprocess.SubprocessError, OSError):
        return False


def _generate_with_paramiko(comment: str) -> None:
    """
    Fallback generator using the ``cryptography`` backend (a Paramiko
    dependency). Writes a standard OpenSSH-format key pair, which Paramiko
    can then read back with Ed25519Key.from_private_key_file.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    priv_bytes = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(CLUSTER_KEY_PATH, "wb") as fh:
        fh.write(priv_bytes)

    pub_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("utf-8")
    with open(CLUSTER_KEY_PUB_PATH, "w", encoding="utf-8") as fh:
        fh.write(f"{pub_bytes} {comment}\n")


def read_cluster_pubkey() -> str:
    """Return the cluster public key text, or a helpful message if missing."""
    if os.path.exists(CLUSTER_KEY_PUB_PATH):
        try:
            with open(CLUSTER_KEY_PUB_PATH, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            return f"(could not read {CLUSTER_KEY_PUB_PATH}: {exc})"
    return (
        f"(cluster public key not found at {CLUSTER_KEY_PUB_PATH} — "
        "run ensure_cluster_key() first)"
    )


def ensure_private_key_file() -> str:
    """
    Prepare a usable SSH key.

    Preferred: an operator-supplied ``CLUSTER_PRIVATE_KEY`` env var (written to
    CLUSTER_KEY_PATH, mode 600) — this is how the bot runs on Render.
    Then: the server-side cluster key (auto-generated if missing).
    Fallback: copy ~/.ssh/id_ed25519 (or the Windows path) to private_key.pem.
    Last resort: write a placeholder the operator must replace.
    """
    bootstrapped = bootstrap_key_from_env()
    if bootstrapped:
        return f"cluster key loaded from CLUSTER_PRIVATE_KEY -> {bootstrapped}"

    try:
        ensure_cluster_key()
        return f"cluster key ready at {CLUSTER_KEY_PATH}"
    except Exception:  # noqa: BLE001 - fall back to legacy behaviour
        pass

    if os.path.exists(PRIVATE_KEY_PATH):
        _chmod(PRIVATE_KEY_PATH, 0o600)
        return "exists"

    candidates = [
        os.path.expanduser("~/.ssh/id_ed25519"),
        "/root/.ssh/id_ed25519",
        "/mnt/c/Users/dell/.ssh/id_ed25519",
        r"C:\Users\dell\.ssh\id_ed25519",
        os.path.expanduser("~/.ssh/id_ed25519.pub").replace(".pub", ""),
    ]
    for cand in candidates:
        if cand and os.path.exists(cand) and not cand.endswith(".pub"):
            try:
                with open(cand, "rb") as src, open(PRIVATE_KEY_PATH, "wb") as dst:
                    dst.write(src.read())
                _chmod(PRIVATE_KEY_PATH, 0o600)
                return f"copied from {cand}"
            except OSError:
                continue

    placeholder = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "-----PASTE YOUR OPENSSH PRIVATE KEY HERE-----\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
    )
    with open(PRIVATE_KEY_PATH, "w", encoding="utf-8") as fh:
        fh.write(placeholder)
    _chmod(PRIVATE_KEY_PATH, 0o600)
    return "placeholder created"


def _chmod(path: str, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _chmod_600(path: str) -> None:
    _chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _normalize_private_key(text: str) -> str:
    """Accept a raw key or a base64-encoded one; return OpenSSH PEM text."""
    text = text.strip()
    if "BEGIN OPENSSH PRIVATE KEY" in text or "BEGIN RSA PRIVATE KEY" in text \
            or "BEGIN EC PRIVATE KEY" in text or "BEGIN PRIVATE KEY" in text:
        return text if text.endswith("\n") else text + "\n"
    import base64
    try:
        decoded = base64.b64decode(text, validate=False).decode("utf-8")
    except Exception:  # noqa: BLE001
        return text if text.endswith("\n") else text + "\n"
    return decoded if decoded.endswith("\n") else decoded + "\n"


def bootstrap_key_from_env() -> str | None:
    """
    If ``CLUSTER_PRIVATE_KEY`` (raw or base64) is set, write it to
    ``CLUSTER_KEY_PATH`` with mode 600 and return that path. This lets the
    Master Bot run on Render with an operator-supplied key that survives the
    ephemeral filesystem. Also accepts ``CLUSTER_PRIVATE_KEY_B64``.

    Returns None when no key is provided in the environment.
    """
    raw = os.environ.get("CLUSTER_PRIVATE_KEY", "").strip()
    if not raw:
        raw = os.environ.get("CLUSTER_PRIVATE_KEY_B64", "").strip()
    if not raw:
        return None

    key_text = _normalize_private_key(raw)
    try:
        os.makedirs(os.path.dirname(CLUSTER_KEY_PATH) or "/tmp", mode=0o700, exist_ok=True)
    except OSError:
        pass
    with open(CLUSTER_KEY_PATH, "w", encoding="utf-8") as fh:
        fh.write(key_text)
    _chmod(CLUSTER_KEY_PATH, 0o600)

    # Derive the matching public key so /pubkey and the cluster banner work.
    try:
        pub = _derive_pubkey(key_text)
        with open(CLUSTER_KEY_PUB_PATH, "w", encoding="utf-8") as fh:
            fh.write(pub + "\n")
        _chmod(CLUSTER_KEY_PUB_PATH, 0o644)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not derive public key from CLUSTER_PRIVATE_KEY: %s", exc)
    return CLUSTER_KEY_PATH


def _derive_pubkey(key_text: str) -> str:
    """Derive an OpenSSH ``authorized_keys`` line from a private key's text."""
    import io
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(key_text))
    b64 = key.get_base64()
    return f"ssh-ed25519 {b64} kilo-host-agent-cluster"


def is_ephemeral_key() -> bool:
    """True when the cluster key lives on a throwaway filesystem (e.g. Render).

    The key is regenerated on each deploy, so the operator must re-paste the
    fresh ``/pubkey`` into their Selfhost servers, or pin a durable key via
    ``CLUSTER_PRIVATE_KEY``.
    """
    return CLUSTER_KEY_PATH.startswith("/tmp/") and not os.environ.get(
        "CLUSTER_PRIVATE_KEY", ""
    ).strip() and not os.environ.get("CLUSTER_PRIVATE_KEY_B64", "").strip()


# --------------------------------------------------------------------------- #
# SSH plumbing
# --------------------------------------------------------------------------- #
def _connect(server: dict, timeout: int = SSH_TIMEOUT) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=server["ip"],
        port=int(server.get("port", 22)),
        username=server.get("ssh_user", "root"),
        pkey=load_private_key(),
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def run_command(client: paramiko.SSHClient, command: str, timeout: int = 120) -> tuple[int, str, str]:
    """Execute a remote command and return (exit_code, stdout, stderr)."""
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


# Package specifiers we accept: a PEP 508-ish name plus optional extras and an
# optional version comparator, e.g. "python-telegram-bot", "aiohttp>=3.9",
# "requests[socks]==2.31.0", "@scope/pkg@1.2.3" (npm). Anything with a shell
# metacharacter is rejected outright.
_PKG_RE = re.compile(r"^@?[A-Za-z0-9][A-Za-z0-9._+/-]{0,63}"
                     r"(?:\[[A-Za-z0-9._,+-]{1,64}\])?"
                     r"(?:(?:==|>=|<=|~=|!=|>|<|@)[A-Za-z0-9._+*!,<>=-]{1,40})?$")
MAX_PACKAGES_PER_REQUEST = 20


def _validate_packages(packages: list[str]) -> tuple[list[str], list[str]]:
    """Split user input into (accepted, rejected) package specifiers."""
    cleaned: list[str] = []
    rejected: list[str] = []
    for raw in packages:
        name = (raw or "").strip().strip(",")
        if not name:
            continue
        if len(name) > 128 or not _PKG_RE.match(name):
            rejected.append(name)
            continue
        if name not in cleaned:
            cleaned.append(name)
        if len(cleaned) >= MAX_PACKAGES_PER_REQUEST:
            break
    return cleaned, rejected


# --------------------------------------------------------------------------- #
# ClusterManager
# --------------------------------------------------------------------------- #
class ClusterManager:
    """High-level orchestrator over the server pool."""

    def __init__(self, servers_json_path: Optional[str] = None):
        self.servers_json_path = servers_json_path or os.path.join(BASE_DIR, "servers.json")

    # -- server discovery -------------------------------------------------- #
    def _server(self, server_id: str) -> dict:
        srv = db.get_server(server_id)
        if not srv:
            raise ClusterError(f"Unknown server '{server_id}'")
        return srv

    def reload_from_json(self) -> int:
        return db.seed_servers_from_json(self.servers_json_path)

    # -- stats ------------------------------------------------------------- #
    def get_server_stats(self, server_id: str) -> ServerStats:
        try:
            srv = self._server(server_id)
        except ClusterError as exc:
            return ServerStats(server_id=server_id, online=False, error=str(exc))

        try:
            client = _connect(srv, timeout=12)
        except Exception as exc:  # noqa: BLE001 - network errors are varied
            return ServerStats(
                server_id=server_id, online=False,
                ram_total_mb=int(srv.get("ram_total_mb", 2048)), error=str(exc),
            )

        try:
            cmd = (
                "echo '---MEM---'; free -m | awk '/Mem:/{print $2\" \"$3\" \"$7}'; "
                "echo '---CPU---'; grep 'cpu ' /proc/stat | awk '{print $2\" \"$3\" \"$4\" \"$5\" \"$6\" \"$7\" \"$8}'; "
                "echo '---LOAD---'; cat /proc/loadavg; "
                "echo '---DISK---'; df -P / | awk 'NR==2{print $5}' | tr -d '%'; "
                "echo '---UPTIME---'; uptime -p 2>/dev/null || uptime"
            )
            _, out, _ = run_command(client, cmd, timeout=20)
            stats = self._parse_stats(server_id, out, srv)
            stats.active_bots = db.count_bots_on_server(server_id)
            return stats
        except Exception as exc:  # noqa: BLE001
            return ServerStats(server_id=server_id, online=False, error=str(exc))
        finally:
            client.close()

    @staticmethod
    def _parse_stats(server_id: str, raw: str, srv: dict) -> ServerStats:
        stats = ServerStats(server_id=server_id, online=True,
                            ram_total_mb=int(srv.get("ram_total_mb", 2048)))
        section = None
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("---") and line.endswith("---"):
                section = line.strip("-")
                continue
            if not line or section is None:
                continue
            try:
                if section == "MEM":
                    parts = line.split()
                    total, used, avail = int(parts[0]), int(parts[1]), int(parts[2])
                    stats.ram_total_mb, stats.ram_used_mb, stats.ram_free_mb = total, used, avail
                elif section == "CPU":
                    vals = [int(x) for x in line.split()]
                    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                    total = sum(vals)
                    stats.cpu_percent = round(100.0 * (total - idle) / total, 1) if total else 0.0
                elif section == "LOAD":
                    stats.load1 = float(line.split()[0])
                elif section == "DISK":
                    stats.disk_used_pct = float(line)
                elif section == "UPTIME":
                    stats.extra["uptime"] = line
            except (ValueError, IndexError):
                continue
        return stats

    def get_cluster_stats(self) -> list[ServerStats]:
        return [self.get_server_stats(s["server_id"]) for s in db.list_servers()]

    # -- load balancing ---------------------------------------------------- #
    def pick_server(self, need_mb: int = MEM_LIMIT_MB, exclude: Optional[set[str]] = None) -> dict:
        """
        Return the active server with the most free RAM that can still fit
        another bot. Raises ClusterError if nothing is available.
        """
        exclude = exclude or set()
        candidates: list[tuple[int, dict, ServerStats]] = []
        errors: list[str] = []
        for srv in db.list_servers(active_only=True):
            if srv["server_id"] in exclude:
                continue
            stats = self.get_server_stats(srv["server_id"])
            if not stats.online:
                errors.append(f"{srv['server_id']}: {stats.error}")
                continue
            if stats.ram_free_mb < need_mb:
                errors.append(f"{srv['server_id']}: only {stats.ram_free_mb}MB free")
                continue
            candidates.append((stats.ram_free_mb, srv, stats))

        if not candidates:
            detail = "; ".join(errors) if errors else "no servers configured"
            raise ClusterError(f"No healthy server with >= {need_mb}MB free RAM ({detail})")

        candidates.sort(key=lambda t: (-t[0], t[1]["server_id"]))
        return candidates[0][1]

    # -- ZIP validation ---------------------------------------------------- #
    @staticmethod
    def validate_zip(zip_path: str) -> tuple[bool, str]:
        """Static scan for zip-bombs, fork-bombs and destructive payloads."""
        return security_scanner.validate_zip(zip_path)

    # -- deployment -------------------------------------------------------- #
    def deploy_bot(self, owner_id: int, bot_id: str, zip_path: str, language: str,
                   name: str = "bot") -> dict:
        """
        Upload and start a user bot. Returns a result dict with status details.
        On failure the bot row is marked 'failed'.
        """
        ok, reason = self.validate_zip(zip_path)
        if not ok:
            return {"ok": False, "error": reason}

        return self._deploy_from_zip(owner_id, bot_id, zip_path, language, name)

    def deploy_files(self, owner_id: int, bot_id: str, files: dict[str, str],
                     language: str, name: str = "ai-bot") -> dict:
        """
        Deploy an AI-generated project given as ``{relative_path: contents}``.

        Files are scanned by ``security_scanner`` BEFORE anything reaches a
        server, then packed into a ZIP and deployed through the normal path.
        """
        if not files:
            return {"ok": False, "error": "Koi file nahi mili deploy karne ke liye."}

        ok, reason = security_scanner.scan_files(files)
        if not ok:
            return {"ok": False, "error": reason}

        import tempfile
        tmp_zip = os.path.join(tempfile.gettempdir(), f"{bot_id}.zip")
        try:
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for path, contents in files.items():
                    zf.writestr(path, contents)
            return self._deploy_from_zip(owner_id, bot_id, tmp_zip, language, name)
        finally:
            try:
                os.remove(tmp_zip)
            except OSError:
                pass

    def _deploy_from_zip(self, owner_id: int, bot_id: str, zip_path: str,
                         language: str, name: str) -> dict:
        """Shared upload + build + start path used by both deploy entrypoints."""

        server = self.pick_server()
        server_id = server["server_id"]
        remote_path = posixpath.join(REMOTE_ROOT, str(owner_id), bot_id)

        db.add_bot(bot_id, owner_id, server_id, name, language, remote_path, status="deploying")

        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            db.update_bot_status(bot_id, "failed")
            return {"ok": False, "error": f"SSH connect failed: {exc}", "server_id": server_id}

        try:
            run_command(client, f"mkdir -p {shlex.quote(remote_path)}", timeout=30)
            sftp = client.open_sftp()
            try:
                remote_zip = posixpath.join(remote_path, "bot.zip")
                sftp.put(zip_path, remote_zip)
            finally:
                sftp.close()

            setup_cmd = self._build_setup_command(remote_path, language)
            code, out, err = run_command(client, setup_cmd, timeout=600)
            if code != 0:
                db.update_bot_status(bot_id, "failed")
                return {"ok": False, "error": f"Dependency install failed: {err[-800:]}",
                        "server_id": server_id, "remote_path": remote_path}

            start_code, start_out, start_err = self._start_process(client, remote_path, language)
            if start_code != 0:
                db.update_bot_status(bot_id, "failed")
                return {"ok": False, "error": f"Start failed: {start_err[-800:]}",
                        "server_id": server_id, "remote_path": remote_path}

            db.update_bot_status(bot_id, "running", restart_count=0)
            return {"ok": True, "server_id": server_id, "remote_path": remote_path,
                    "log": (out + start_out)[-500:]}
        except Exception as exc:  # noqa: BLE001
            db.update_bot_status(bot_id, "failed")
            return {"ok": False, "error": str(exc), "server_id": server_id}
        finally:
            client.close()

    def _build_setup_command(self, remote_path: str, language: str) -> str:
        """Unpack the ZIP and prepare an isolated runtime."""
        q = shlex.quote(remote_path)
        base = (
            f"set -e; cd {q}; "
            "command -v unzip >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq unzip) ; "
            "rm -rf src && mkdir -p src && unzip -o -q bot.zip -d src && rm -f bot.zip; "
            "cd src; "
            "# flatten a single top-level directory if present\n"
            "if [ \"$(ls -1 | wc -l)\" -eq 1 ] && [ -d \"$(ls -1)\" ]; then "
            "  inner=\"$(ls -1)\"; mv \"$inner\"/* . 2>/dev/null || true; rmdir \"$inner\" 2>/dev/null || true; fi; "
        )
        if language == "python":
            # Create the venv at the bot root (../.venv) so run.sh finds it.
            base += (
                "command -v python3 >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip); "
                "python3 -m venv ../.venv; "
                ". ../.venv/bin/activate; "
                "python -m pip install --upgrade pip -q; "
                "[ -f requirements.txt ] && pip install -r requirements.txt -q || true; "
            )
        else:  # node
            base += (
                "command -v node >/dev/null 2>&1 || (apt-get update -qq && "
                "curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && "
                "apt-get install -y -qq nodejs); "
                "[ -f package.json ] && npm install --omit=dev --no-audit --no-fund || true; "
            )
        return base

    # -- process lifecycle ------------------------------------------------- #
    @staticmethod
    def _bot_marker(remote_path: str) -> str:
        """A unique, shell-safe marker embedded in the bot's command line."""
        digest = hashlib.sha1(remote_path.encode("utf-8")).hexdigest()[:12]
        return f"KILOBOT{os.path.basename(remote_path)}{digest}"

    @staticmethod
    def _marker_search_pattern(marker: str) -> str:
        """
        Bracket the first character so the search pattern does not match our
        own shell command line (the classic `ps | grep [p]attern` trick).
        """
        if not marker:
            return marker
        return f"[{marker[0]}]{marker[1:]}"

    def _write_runner(self, sftp, remote_path: str, language: str) -> str:
        """Create run.sh (ulimit caps + entry detection + exec) on the server."""
        marker = self._bot_marker(remote_path)
        ulimits = (
            f"ulimit -v $(( {MEM_LIMIT_MB} * 1024 )) 2>/dev/null || true\n"
            f"ulimit -t {CPU_SECONDS_LIMIT} 2>/dev/null || true\n"
            f"ulimit -f $(( {FILE_SIZE_LIMIT_MB} * 1024 )) 2>/dev/null || true\n"
            f"ulimit -n {NOFILE_LIMIT} 2>/dev/null || true\n"
        )
        if language == "python":
            entry = (
                'if [ -f main.py ]; then ENTRY=main.py; '
                'elif [ -f bot.py ]; then ENTRY=bot.py; '
                'elif [ -f src/main.py ]; then cd src && ENTRY=main.py; '
                'elif [ -f src/bot.py ]; then cd src && ENTRY=bot.py; '
                'else echo "NO_ENTRY" >&2; exit 3; fi\n'
                '[ -f "$VENV/bin/activate" ] && . "$VENV/bin/activate" 2>/dev/null || true\n'
                'exec -a "$MARKER" python -u "$ENTRY"\n'
            )
        else:
            entry = (
                'if [ -f index.js ]; then ENTRY=index.js; '
                'elif [ -f src/index.js ]; then cd src && ENTRY=index.js; '
                'else echo "NO_ENTRY" >&2; exit 3; fi\n'
                'exec -a "$MARKER" node "$ENTRY"\n'
            )
        script = (
            "#!/usr/bin/env bash\n"
            f"MARKER='{marker}'\n"
            'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'VENV="$DIR/.venv"\n'
            'cd "$DIR"\n'
            'echo $$ > "$DIR/bot.pid"\n'
            f"{ulimits}"
            f"{entry}"
        )
        with sftp.file(posixpath.join(remote_path, "run.sh"), "w") as fh:
            fh.write(script)
        return marker

    def _start_process(self, client: paramiko.SSHClient, remote_path: str,
                       language: str) -> tuple[int, str, str]:
        """(Re)launch the bot under ulimit caps via a setsid'd runner script."""
        q = shlex.quote(remote_path)
        sftp = client.open_sftp()
        try:
            marker = self._write_runner(sftp, remote_path, language)
        finally:
            sftp.close()

        pat = self._marker_search_pattern(marker)
        cmd = (
            f"cd {q}; "
            # stop any previous instance of THIS bot (marker-based, self-safe)
            f"pkill -f -- '{pat}' 2>/dev/null || true; "
            "[ -f bot.pid ] && { kill -0 $(cat bot.pid) 2>/dev/null && "
            "kill -- -$(cat bot.pid) 2>/dev/null; rm -f bot.pid; } ; "
            "sleep 1; "
            "setsid bash run.sh > bot.log 2>&1 < /dev/null & "
            "sleep 4; "
            f"if [ -f bot.pid ] && kill -0 $(cat bot.pid) 2>/dev/null; then echo STARTED; exit 0; "
            "else echo 'FAILED TO START'; tail -n 40 bot.log 2>/dev/null; exit 4; fi"
        )
        return run_command(client, cmd, timeout=120)

    def _is_running(self, client: paramiko.SSHClient, remote_path: str) -> bool:
        q = shlex.quote(remote_path)
        _, out, _ = run_command(
            client,
            f"cd {q} 2>/dev/null && [ -f bot.pid ] && "
            "kill -0 $(cat bot.pid) 2>/dev/null && echo RUNNING || echo STOPPED",
            timeout=20,
        )
        return "RUNNING" in out

    def _kill_bot(self, client: paramiko.SSHClient, remote_path: str) -> None:
        q = shlex.quote(remote_path)
        marker = self._bot_marker(remote_path)
        pat = self._marker_search_pattern(marker)
        run_command(
            client,
            f"cd {q} 2>/dev/null; "
            "[ -f bot.pid ] && kill -- -$(cat bot.pid) 2>/dev/null; "
            f"pkill -f -- '{pat}' 2>/dev/null; "
            "rm -f bot.pid; true",
            timeout=30,
        )

    # -- status / logs / control ------------------------------------------ #
    def bot_status(self, bot_id: str) -> dict:
        bot = db.get_bot(bot_id)
        if not bot:
            return {"ok": False, "error": "bot not found"}
        server = db.get_server(bot["server_id"]) if bot.get("server_id") else None
        if not server:
            return {"ok": False, "error": "server not found", "bot": bot}
        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ssh: {exc}", "bot": bot}
        try:
            running = self._is_running(client, bot["remote_path"])
            q = shlex.quote(posixpath.join(bot["remote_path"], "bot.pid"))
            _, rss, _ = run_command(
                client,
                f"[ -f {q} ] && ps -o rss= -p $(cat {q}) 2>/dev/null | awk '{{print $1}}' || echo 0",
                timeout=20,
            )
            return {"ok": True, "running": running, "bot": bot,
                    "rss_kb": (rss.strip() or "0")}
        finally:
            client.close()

    def get_logs(self, bot_id: str, lines: int = 60) -> str:
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return "bot/server not found"
        server = db.get_server(bot["server_id"])
        if not server:
            return "server not found"
        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return f"ssh error: {exc}"
        try:
            q = shlex.quote(posixpath.join(bot["remote_path"], "bot.log"))
            _, out, err = run_command(client, f"tail -n {int(lines)} {q} 2>&1", timeout=30)
            return out or err or "(log empty)"
        finally:
            client.close()

    def get_logs_since(self, bot_id: str, offset: int, max_bytes: int = 3500) -> dict:
        """
        Incremental read for the live-log viewer.

        Returns ``{"text": <new bytes>, "offset": <new byte offset>}``. The first
        call (``offset == 0``) seeds the cursor at the end minus ``max_bytes`` so
        the user sees recent history, then every later call returns only what was
        appended since — cheap enough to poll a few times per second.
        """
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return {"text": "", "offset": offset, "error": "bot/server not found"}
        server = db.get_server(bot["server_id"])
        if not server:
            return {"text": "", "offset": offset, "error": "server not found"}
        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return {"text": "", "offset": offset, "error": f"ssh error: {exc}"}
        log_path = posixpath.join(bot["remote_path"], "bot.log")
        try:
            q = shlex.quote(log_path)
            # Size of the log right now (0 if it does not exist yet).
            _, size_out, _ = run_command(
                client, f"stat -c %s {q} 2>/dev/null || echo 0", timeout=20)
            try:
                size = int((size_out or "0").strip() or 0)
            except ValueError:
                size = 0
            start = int(offset)
            if start <= 0 or start > size:
                start = max(0, size - int(max_bytes))
            if size <= start:
                return {"text": "", "offset": start, "size": size}
            _, out, err = run_command(
                client,
                f"tail -c +{start + 1} {q} | head -c {int(max_bytes)} 2>&1",
                timeout=30)
            text = out or err or ""
            return {"text": text, "offset": start + len(text.encode("utf-8")), "size": size}
        finally:
            client.close()

    def get_source(self, bot_id: str, max_bytes: int = 40000) -> str:
        """Return the primary source file of a bot (for the AI code doctor)."""
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return ""
        server = db.get_server(bot["server_id"])
        if not server:
            return ""
        candidates = ["src/main.py", "src/bot.py", "main.py", "bot.py",
                      "src/index.js", "index.js"]
        try:
            client = _connect(server)
        except Exception:  # noqa: BLE001
            return ""
        try:
            q = shlex.quote(bot["remote_path"])
            for rel in candidates:
                _, out, _ = run_command(
                    client, f"head -c {max_bytes} {q}/{rel} 2>/dev/null", timeout=20
                )
                if out.strip():
                    return f"# === {rel} ===\n{out}"
            return ""
        finally:
            client.close()

    def install_packages(self, bot_id: str, packages: list[str],
                         restart: bool = True) -> dict:
        """
        Install extra packages into an already-deployed bot, on demand.

        This is the *manual* counterpart to the AI auto-fix: the user names the
        exact packages and we install them straight away — no AI involvement.

        Python bots: ``pip install`` into the bot's existing ``../.venv``.
        Node bots:   ``npm install`` inside the bot's ``src`` directory.

        Packages are validated (name + optional version specifier) so a typo
        cannot smuggle shell metacharacters into the remote command. The bot is
        restarted afterwards so the new dependency is actually loaded.
        """
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return {"ok": False, "error": "bot/server not found"}

        cleaned, rejected = _validate_packages(packages)
        if not cleaned:
            return {"ok": False, "error": "Koi valid package name nahi mila.",
                    "rejected": rejected}

        server = db.get_server(bot["server_id"])
        if not server:
            return {"ok": False, "error": "server not found"}

        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ssh: {exc}"}

        remote_path = bot["remote_path"]
        q = shlex.quote(remote_path)
        args = " ".join(shlex.quote(p) for p in cleaned)
        language = (bot.get("language") or "python").lower()
        try:
            if language == "node":
                cmd = (
                    f"set -e; cd {q}; "
                    "[ -d src ] && cd src; "
                    "command -v npm >/dev/null 2>&1 || "
                    "(apt-get update -qq && apt-get install -y -qq nodejs npm); "
                    f"npm install --omit=dev --no-audit --no-fund {args} 2>&1 | tail -n 60"
                )
            else:
                cmd = (
                    f"set -e; cd {q}; "
                    "if [ ! -x .venv/bin/pip ]; then "
                    "command -v python3 >/dev/null 2>&1 || "
                    "(apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip); "
                    "python3 -m venv .venv; fi; "
                    ". .venv/bin/activate; "
                    "python -m pip install --upgrade pip -q; "
                    f"pip install {args} 2>&1 | tail -n 60"
                )
            code, out, err = run_command(client, cmd, timeout=600)
            output = (out or err or "").strip()
            if code != 0:
                return {"ok": False, "error": output[-900:] or f"exit {code}",
                        "installed": cleaned, "rejected": rejected}
            restart_info = ""
            if restart:
                rc, rout, rerr = self._start_process(client, remote_path, language)
                if rc == 0:
                    db.update_bot_status(bot_id, "running")
                    restart_info = "restarted"
                else:
                    restart_info = (rerr or rout or "")[-300:]
            return {"ok": True, "installed": cleaned, "rejected": rejected,
                    "output": output[-900:], "restart": restart_info}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "installed": cleaned}
        finally:
            client.close()

    def restart_bot(self, bot_id: str) -> dict:
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return {"ok": False, "error": "bot/server not found"}
        server = db.get_server(bot["server_id"])
        if not server:
            return {"ok": False, "error": "server not found"}
        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ssh: {exc}"}
        try:
            code, out, err = self._start_process(client, bot["remote_path"], bot["language"])
            if code == 0:
                db.update_bot_status(bot_id, "running")
                return {"ok": True}
            return {"ok": False, "error": (err or out)[-500:]}
        finally:
            client.close()

    def stop_bot(self, bot_id: str) -> dict:
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return {"ok": False, "error": "bot/server not found"}
        server = db.get_server(bot["server_id"])
        if not server:
            return {"ok": False, "error": "server not found"}
        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ssh: {exc}"}
        try:
            self._kill_bot(client, bot["remote_path"])
            db.update_bot_status(bot_id, "stopped")
            return {"ok": True}
        finally:
            client.close()

    def delete_bot(self, bot_id: str) -> dict:
        bot = db.get_bot(bot_id)
        if not bot:
            return {"ok": False, "error": "bot not found"}
        if bot.get("server_id"):
            server = db.get_server(bot["server_id"])
            if server:
                try:
                    client = _connect(server)
                    self._kill_bot(client, bot["remote_path"])
                    q = shlex.quote(bot["remote_path"])
                    run_command(client, f"rm -rf {q}", timeout=30)
                    client.close()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass
        db.delete_bot(bot_id)
        return {"ok": True}

    # -- auto-patch -------------------------------------------------------- #
    def read_sources(self, bot_id: str, max_bytes_per_file: int = 30000,
                     max_files: int = 20) -> dict[str, str]:
        """
        Return the bot's source files as ``{relative_path: contents}`` so the
        AI agent can reason about the whole project, not just one file.
        """
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return {}
        server = db.get_server(bot["server_id"])
        if not server:
            return {}
        try:
            client = _connect(server)
        except Exception:  # noqa: BLE001
            return {}
        files: dict[str, str] = {}
        try:
            q = shlex.quote(bot["remote_path"] + "/src")
            code, out, _ = run_command(
                client,
                f"find {q} -maxdepth 3 -type f "
                r"\( -name '*.py' -o -name '*.js' -o -name '*.json' -o -name '*.txt' \) "
                f"-printf '%P\\n' 2>/dev/null | head -n {int(max_files)}",
                timeout=30,
            )
            if code != 0 or not out.strip():
                return {}
            for rel in out.split():
                if not rel or ".." in rel.split("/"):
                    continue
                _, body, _ = run_command(
                    client,
                    f"head -c {int(max_bytes_per_file)} {shlex.quote(bot['remote_path'] + '/src/' + rel)}",
                    timeout=20,
                )
                if body:
                    files[rel] = body
        finally:
            client.close()
        return files

    def apply_patches(self, bot_id: str, files: dict[str, str]) -> dict:
        """
        Write multiple patched files into the bot's ``src/`` dir (each backed
        up to ``.bak``) and restart the bot. Every file is scanned by
        ``security_scanner`` first.
        """
        if not files:
            return {"ok": False, "error": "no files to patch"}

        ok, reason = security_scanner.scan_files(files)
        if not ok:
            return {"ok": False, "error": reason}

        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return {"ok": False, "error": "bot/server not found"}
        server = db.get_server(bot["server_id"])
        if not server:
            return {"ok": False, "error": "server not found"}
        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ssh: {exc}"}
        try:
            src_dir = posixpath.join(bot["remote_path"], "src")
            run_command(client, f"mkdir -p {shlex.quote(src_dir)}", timeout=20)
            sftp = client.open_sftp()
            try:
                written = []
                for rel, contents in files.items():
                    if not rel or ".." in rel.split("/"):
                        continue
                    remote_file = posixpath.join(src_dir, rel)
                    run_command(client, f"mkdir -p {shlex.quote(posixpath.dirname(remote_file))}",
                                timeout=20)
                    run_command(client, f"cp -f {shlex.quote(remote_file)} "
                                        f"{shlex.quote(remote_file + '.bak')} 2>/dev/null || true",
                                timeout=15)
                    with sftp.file(remote_file, "w") as fh:
                        fh.write(contents)
                    written.append(rel)
            finally:
                sftp.close()

            if not written:
                return {"ok": False, "error": "no valid file paths to patch"}

            # Reinstall deps in case requirements/package.json changed.
            setup = self._build_setup_command(bot["remote_path"], bot["language"])
            run_command(client, setup, timeout=600)
            result = self.restart_bot(bot_id)
            return {"ok": result.get("ok", False), "files": written,
                    "error": result.get("error", "")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        finally:
            client.close()

    def apply_patch(self, bot_id: str, new_source: str) -> dict:
        """
        Overwrite a bot's primary source file with AI-suggested code, then
        restart it. The previous file is backed up to ``<file>.bak``.
        """
        bot = db.get_bot(bot_id)
        if not bot or not bot.get("server_id"):
            return {"ok": False, "error": "bot/server not found"}
        server = db.get_server(bot["server_id"])
        if not server:
            return {"ok": False, "error": "server not found"}
        candidates = ["src/main.py", "src/bot.py", "main.py", "bot.py",
                      "src/index.js", "index.js"]
        try:
            client = _connect(server)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ssh: {exc}"}
        try:
            q = shlex.quote(bot["remote_path"])
            target = None
            for rel in candidates:
                _, out, _ = run_command(client, f"test -f {q}/{rel} && echo OK", timeout=15)
                if "OK" in out:
                    target = rel
                    break
            if not target:
                return {"ok": False, "error": "no known source file found to patch"}

            sftp = client.open_sftp()
            try:
                remote_file = posixpath.join(bot["remote_path"], target)
                run_command(client, f"cp -f {shlex.quote(remote_file)} {shlex.quote(remote_file)}.bak",
                            timeout=15)
                with sftp.file(remote_file, "w") as fh:
                    fh.write(new_source)
            finally:
                sftp.close()

            result = self.restart_bot(bot_id)
            return {"ok": result.get("ok", False), "file": target,
                    "error": result.get("error", "")}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        finally:
            client.close()

    # -- watchdog ---------------------------------------------------------- #
    def watchdog_scan(self) -> list[dict]:
        """
        Check every bot; auto-restart crashed ones (up to MAX_RESTARTS).
        Returns a list of events: {bot_id, owner_id, status, restarts, log_tail}.
        """
        events: list[dict] = []
        for bot in db.list_all_bots():
            if not bot.get("server_id"):
                continue
            try:
                status = self.bot_status(bot["bot_id"])
            except Exception as exc:  # noqa: BLE001
                events.append({"bot_id": bot["bot_id"], "owner_id": bot["owner_id"],
                               "status": "error", "error": str(exc)})
                continue
            if status.get("running"):
                db.update_bot_status(bot["bot_id"], "running")
                continue

            restarts = int(bot.get("restart_count") or 0)
            if restarts >= MAX_RESTARTS:
                db.update_bot_status(bot["bot_id"], "crashed")
                events.append({
                    "bot_id": bot["bot_id"], "owner_id": bot["owner_id"],
                    "status": "crashed", "restarts": restarts,
                    "log_tail": self.get_logs(bot["bot_id"], lines=40),
                })
                continue

            result = self.restart_bot(bot["bot_id"])
            restarts += 1
            if result.get("ok"):
                db.update_bot_status(bot["bot_id"], "running", restart_count=restarts)
                events.append({"bot_id": bot["bot_id"], "owner_id": bot["owner_id"],
                               "status": "restarted", "restarts": restarts,
                               "log_tail": self.get_logs(bot["bot_id"], lines=40)})
            else:
                db.update_bot_status(bot["bot_id"], "crashed", restart_count=restarts)
                events.append({"bot_id": bot["bot_id"], "owner_id": bot["owner_id"],
                               "status": "crashed", "restarts": restarts,
                               "log_tail": self.get_logs(bot["bot_id"], lines=40),
                               "error": result.get("error")})
        return events

    # -- migration --------------------------------------------------------- #
    def migrate_server(self, from_server: str, to_server: str,
                       progress=None) -> dict:
        """
        Move every bot off ``from_server`` onto ``to_server`` with minimal
        downtime: pack on source -> transfer -> unpack+install -> restart ->
        update DB. ``progress`` is an optional callable(str) for live updates.
        """
        def emit(msg: str) -> None:
            if progress:
                try:
                    progress(msg)
                except Exception:  # noqa: BLE001
                    pass

        src = self._server(from_server)
        dst = self._server(to_server)
        bots = db.list_bots_by_server(from_server)
        if not bots:
            return {"ok": True, "moved": 0, "failed": 0, "message": "No bots to migrate."}

        results = {"ok": True, "moved": 0, "failed": 0, "details": []}
        emit(f"Starting migration of {len(bots)} bot(s): {from_server} -> {to_server}")

        for bot in bots:
            try:
                emit(f"Migrating bot {bot['bot_id']} ({bot.get('name')})…")
                archive = self._pack_bot(src, bot)
                if not archive:
                    raise ClusterError("packing failed")
                new_path = posixpath.join(REMOTE_ROOT, str(bot["owner_id"]), bot["bot_id"])
                self._unpack_and_start(dst, archive, new_path, bot["language"])
                self._cleanup_source(src, bot)
                db.move_bot_to_server(bot["bot_id"], to_server, new_path, status="running")
                results["moved"] += 1
                results["details"].append({"bot_id": bot["bot_id"], "ok": True})
                emit(f"✅ {bot['bot_id']} migrated")
            except Exception as exc:  # noqa: BLE001
                results["failed"] += 1
                results["ok"] = False
                results["details"].append({"bot_id": bot["bot_id"], "ok": False, "error": str(exc)})
                emit(f"❌ {bot['bot_id']} failed: {exc}")

        if results["failed"] == 0:
            db.set_server_status(from_server, "draining")
        emit(f"Migration finished: {results['moved']} moved, {results['failed']} failed.")
        return results

    def _pack_bot(self, src: dict, bot: dict) -> Optional[str]:
        """tar.gz the bot's src directory into a local temp archive."""
        try:
            client = _connect(src)
        except Exception as exc:  # noqa: BLE001
            raise ClusterError(f"cannot connect to source: {exc}")
        try:
            q = shlex.quote(bot["remote_path"])
            tmp = f"/tmp/{bot['bot_id']}.tar.gz"
            cmd = f"cd {q} && tar czf {shlex.quote(tmp)} src"
            code, _, err = run_command(client, cmd, timeout=300)
            if code != 0:
                raise ClusterError(f"tar failed: {err[-300:]}")
            local = os.path.join(BASE_DIR, f".migrate_{bot['bot_id']}.tar.gz")
            sftp = client.open_sftp()
            try:
                sftp.get(tmp, local)
            finally:
                sftp.close()
            run_command(client, f"rm -f {shlex.quote(tmp)}", timeout=20)
            return local
        finally:
            client.close()

    def _unpack_and_start(self, dst: dict, archive_path: str, new_path: str,
                          language: str) -> None:
        try:
            client = _connect(dst)
        except Exception as exc:  # noqa: BLE001
            raise ClusterError(f"cannot connect to destination: {exc}")
        try:
            q = shlex.quote(new_path)
            run_command(client, f"mkdir -p {q}", timeout=30)
            sftp = client.open_sftp()
            try:
                remote_tar = posixpath.join(new_path, "bundle.tar.gz")
                sftp.put(archive_path, remote_tar)
            finally:
                sftp.close()

            install = (
                f"set -e; cd {q}; tar xzf bundle.tar.gz && rm -f bundle.tar.gz; "
            )
            if language == "python":
                install += (
                    "python3 -m venv .venv; . .venv/bin/activate; "
                    "python -m pip install --upgrade pip -q; "
                    "cd src && { [ -f requirements.txt ] && pip install -r requirements.txt -q || true; } "
                )
            else:
                install += (
                    "cd src && { [ -f package.json ] && npm install --omit=dev --no-audit --no-fund || true; } "
                )
            code, _, err = run_command(client, install, timeout=600)
            if code != 0:
                raise ClusterError(f"install failed: {err[-300:]}")

            code, out, err = self._start_process(client, new_path, language)
            if code != 0:
                raise ClusterError(f"start failed: {(err or out)[-300:]}")
        finally:
            client.close()
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
            except OSError:
                pass

    def _cleanup_source(self, src: dict, bot: dict) -> None:
        try:
            client = _connect(src)
        except Exception:  # noqa: BLE001
            return
        try:
            self._kill_bot(client, bot["remote_path"])
            q = shlex.quote(bot["remote_path"])
            run_command(client, f"rm -rf {q}", timeout=60)
        finally:
            client.close()


if __name__ == "__main__":
    db.init_db()
    cm = ClusterManager()
    print("[cluster] private key:", ensure_private_key_file())
    print("[cluster] servers loaded from json:", cm.reload_from_json())
    for st in cm.get_cluster_stats():
        state = "ONLINE" if st.online else f"OFFLINE ({st.error})"
        print(f"  {st.server_id}: {state} RAM free {st.ram_free_mb}MB "
              f"CPU {st.cpu_percent}% bots {st.active_bots}")
