"""
security_scanner.py — Static safety scanner for user-uploaded and AI-generated code.

Every piece of code that will be executed on a cluster server — whether it
arrived as a user ZIP upload or was written by the AI coding agent — passes
through this module first. It blocks:

* fork bombs and process bombs
* zip bombs / decompression bombs and oversized archives
* path traversal inside archives
* destructive shell commands (rm -rf /, disk wipes, shutdown, ...)
* credential theft (reading /etc/shadow, ~/.ssh private keys)
* reverse shells and obvious host-takeover payloads

The scanner is deliberately conservative: it prefers a false positive (which
the user can review) over letting a destructive payload run on a shared box.
"""

from __future__ import annotations

import os
import re
import zipfile

# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #
MAX_ZIP_BYTES = 25 * 1024 * 1024            # 25 MB upload cap
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB unpacked cap
MAX_ENTRIES = 2000
MAX_COMPRESSION_RATIO = 200                 # per-entry zip-bomb heuristic
MAX_SCAN_BYTES = 2 * 1024 * 1024            # only text-scan files up to 2 MB

TEXT_EXTS = (
    ".py", ".js", ".ts", ".mjs", ".cjs", ".sh", ".bash",
    ".json", ".txt", ".env", ".yaml", ".yml", ".toml", ".cfg", ".ini",
)

# --------------------------------------------------------------------------- #
# Destructive / malicious patterns
# --------------------------------------------------------------------------- #
# Each tuple is (compiled regex, human-readable reason).
FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    # --- fork bombs -------------------------------------------------------
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;?\s*:", re.S),
     "fork bomb"),
    (re.compile(r"while\s+True\s*:\s*\n\s*.*(fork|subprocess|Popen|os\.system)", re.S),
     "fork bomb loop"),
    (re.compile(r"\bfor\s*\(\s*;\s*;\s*\)\s*.*\bfork\b", re.S),
     "fork bomb loop"),
    # --- recursive deletion of root / home --------------------------------
    # Allow an optional trailing quote/bracket so `os.system('rm -rf /')` matches.
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(?=[\s'\"`)]|$|\*)"), "rm -rf /"),
    (re.compile(r"\brm\s+-[a-z]*f[a-z]*r[a-z]*\s+/(?=[\s'\"`)]|$|\*)"), "rm -fr /"),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(root|home|etc|var|usr|boot)\b"),
     "rm -rf critical directory"),
    # --- raw disk destruction --------------------------------------------
    (re.compile(r"\bdd\s+if=/dev/(zero|random|urandom)\s+of=/dev/(sd|nvme|hd|vd)"),
     "disk wipe via dd"),
    (re.compile(r"mkfs(\.\w+)?\s+/dev/"), "filesystem format"),
    (re.compile(r">\s*/dev/(sd|nvme|hd|vd)"), "raw write to block device"),
    # --- host power control ----------------------------------------------
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b"), "host power command"),
    (re.compile(r"\binit\s+0\b"), "host power command"),
    # --- credential / secret theft ---------------------------------------
    (re.compile(r"/etc/(passwd|shadow)\b.*(>>|>|\bcat\b)"), "credential file access"),
    (re.compile(r"\.ssh/id_(rsa|ed25519|ecdsa)\b"), "SSH private key access"),
    (re.compile(r"\bcat\s+[^\n]*/root/\.ssh/"), "SSH private key access"),
    # --- privilege / permission abuse ------------------------------------
    (re.compile(r"\bchmod\s+(-R\s+)?777\s+/\s"), "world-writable root"),
    (re.compile(r"\bchown\s+-R\s+[^\s]+\s+/\s"), "recursive chown of root"),
    # --- reverse shells ---------------------------------------------------
    (re.compile(r"/dev/tcp/\d{1,3}(\.\d{1,3}){3}/\d+"), "reverse shell"),
    (re.compile(r"\bnc\s+-e\s+/bin/(ba)?sh\b"), "reverse shell via netcat"),
    (re.compile(r"bash\s+-i\s+>&\s*/dev/tcp"), "reverse shell"),
    # --- disabling the watchdog / killing siblings ------------------------
    (re.compile(r"pkill\s+-9\s+(-f\s+)?python"), "mass process kill"),
    (re.compile(r"killall\s+-9\s+python"), "mass process kill"),
]


class SecurityError(Exception):
    """Raised when code fails the safety scan."""


def scan_code_text(code: str, label: str = "code") -> tuple[bool, str]:
    """
    Scan a single piece of source text.

    Returns ``(ok, reason)``. ``ok`` is False when a forbidden pattern matched.
    """
    if not code:
        return True, "ok"
    for pattern, reason in FORBIDDEN_PATTERNS:
        if pattern.search(code):
            return False, f"Blocked dangerous pattern ({reason}) in {label}."
    return True, "ok"


def scan_files(files: dict[str, str]) -> tuple[bool, str]:
    """
    Scan an in-memory project mapping ``{relative_path: contents}`` — this is
    how the AI coding agent hands over freshly generated files before they are
    written to disk or deployed.
    """
    for path, contents in files.items():
        ok, reason = scan_code_text(contents, os.path.basename(path))
        if not ok:
            return False, reason
    return True, "ok"


def validate_zip(zip_path: str) -> tuple[bool, str]:
    """
    Static scan for zip-bombs, fork-bombs, path traversal and destructive
    payloads in an uploaded archive. Returns ``(ok, reason)``.
    """
    if not os.path.exists(zip_path):
        return False, "ZIP file not found."
    if os.path.getsize(zip_path) > MAX_ZIP_BYTES:
        return False, f"ZIP too large (max {MAX_ZIP_BYTES // (1024 * 1024)} MB)."
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                return False, f"Too many files in ZIP (max {MAX_ENTRIES})."
            total = 0
            for info in infos:
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    return False, "ZIP would expand too large (possible zip-bomb)."
                name = info.filename
                if name.startswith("/") or ".." in name.split("/"):
                    return False, f"Unsafe path in ZIP: {name}"
                if info.compress_size > 0 and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                    return False, f"Suspicious compression ratio in {name} (possible zip-bomb)."
                if info.file_size <= MAX_SCAN_BYTES and name.endswith(TEXT_EXTS):
                    data = zf.read(info).decode("utf-8", "replace")
                    ok, reason = scan_code_text(data, name)
                    if not ok:
                        return False, reason
    except zipfile.BadZipFile:
        return False, "Not a valid ZIP file."
    except OSError as exc:
        return False, f"Could not read ZIP: {exc}"
    return True, "ok"


if __name__ == "__main__":  # pragma: no cover - tiny self-test
    samples = {
        "clean": "print('hello world')",
        "forkbomb": ":(){ :|:& };:",
        "rmrf": "import os; os.system('rm -rf /')",
        "shutdown": "subprocess.run(['shutdown', '-h', 'now'])",
    }
    for name, code in samples.items():
        print(f"{name:10} -> {scan_code_text(code)}")
