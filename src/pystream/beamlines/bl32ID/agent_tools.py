"""
Tool catalog for the AI Agent plugin.

All tools are read-only — they observe beamline state (PVs, detector image,
recent scan files) but never move motors or change settings. Write tools
will live in a separate module behind a user-confirmation dialog.

Each entry exposes a name, a human description, a JSON-schema input shape,
and a callable returning a JSON-serializable dict. The callable runs from
the chat worker QThread, so anything it touches must be thread-safe:
  - pyepics caget — thread-safe
  - pvaccess Channel.get — thread-safe (cache the channel)
  - h5py / numpy / glob — fine

Tools must NEVER raise — wrap exceptions and return {"error": "..."} so the
model can recover gracefully and the conversation continues.
"""

import glob
import json
import os
import re
import time
from typing import Any, Callable

import numpy as np

# Importing plugin_settings runs the one-time legacy-paths migration before
# any of the path constants below are referenced.
from .plugin_settings import PYSTREAM_HOME, SETTINGS_FILE as PYSTREAM_SETTINGS_FILE


# ── PVA channel cache (shared between tools that grab detector frames) ──

_PVA_CH = {}

def _pva_channel(det_pv: str):
    ch = _PVA_CH.get(det_pv)
    if ch is None:
        import pvaccess as pva
        ch = pva.Channel(det_pv)
        _PVA_CH[det_pv] = ch
    return ch


def _ndarray_from_pva(st) -> np.ndarray:
    """Decode an NTNDArray pvaccess struct into a 2-D ndarray."""
    val = st['value'][0]
    flat = None
    for key in ('ushortValue', 'shortValue', 'intValue', 'floatValue',
                'doubleValue', 'ubyteValue', 'byteValue'):
        if key in val:
            flat = np.asarray(val[key])
            break
    if flat is None:
        raise RuntimeError("Unsupported NTNDArray numeric type")
    dims = []
    try:
        dims = st['dimension']
    except Exception:
        pass
    if len(dims) >= 2:
        h, w = int(dims[0]['size']), int(dims[1]['size'])
        if h * w == flat.size:
            return flat.reshape(h, w)
    n = flat.size
    side = int(np.sqrt(n))
    return flat.reshape(side, n // side) if side * (n // side) == n else flat


# ── tool implementations ────────────────────────────────────────────────

def tool_read_pv(pv_name: str, timeout: float = 2.0) -> dict:
    """Read a single EPICS PV."""
    if not pv_name:
        return {"error": "pv_name is required"}
    try:
        import epics
        v = epics.caget(pv_name, timeout=timeout)
        if v is None:
            return {"error": f"caget timed out or PV not found: {pv_name}"}
        if hasattr(v, "tolist"):  # numpy array → list
            v = v.tolist()
        return {"pv_name": pv_name, "value": v, "ts": time.time()}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_read_motor(motor_pv: str, timeout: float = 2.0) -> dict:
    """Read motor position. Tries `<pv>.RBV` first, then the base PV."""
    if not motor_pv:
        return {"error": "motor_pv is required"}
    try:
        import epics
        rbv = epics.caget(f"{motor_pv}.RBV", timeout=timeout)
        if rbv is None:
            rbv = epics.caget(motor_pv, timeout=timeout)
        if rbv is None:
            return {"error": f"caget timed out: {motor_pv}"}
        return {"motor_pv": motor_pv, "rbv": float(rbv)}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_view_detector_image(detector_pv: str = "32idbSP1:Pva1:Image",
                              max_dim: int = 1024) -> dict:
    """Grab the current detector frame and return it as a *viewable* image
    (downsampled to max_dim on the long edge, percentile-stretched to 8-bit
    PNG) so the model can SEE the image. Use this for visual analysis:
    'is the beam centered', 'is there a shadow', 'how's the alignment',
    'are there hot pixels', 'do you see the sample'. The image is
    contrast-normalized so even raw 16-bit detector frames are visible."""
    try:
        ch = _pva_channel(detector_pv)
        st = ch.get()
        img = np.asarray(_ndarray_from_pva(st))
        h, w = img.shape[-2:]
        # Block-mean downsample to keep token cost bounded.
        scale = max(h, w) / float(max_dim)
        if scale > 1:
            new_h = max(1, int(h / scale))
            new_w = max(1, int(w / scale))
            sh = max(1, h // new_h)
            sw = max(1, w // new_w)
            img_ds = (img[:sh * new_h, :sw * new_w]
                      .reshape(new_h, sh, new_w, sw)
                      .mean(axis=(1, 3)))
        else:
            img_ds = img
        # Percentile stretch to 8-bit (handles 16-bit detector frames).
        f = img_ds.astype(np.float32)
        lo, hi = np.percentile(f, [1, 99])
        if hi <= lo:
            hi = lo + 1.0
        u8 = np.clip((f - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        # Encode PNG.
        from PIL import Image
        import base64
        import io
        buf = io.BytesIO()
        Image.fromarray(u8, mode="L").save(buf, format="PNG", optimize=True)
        b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return {
            "image_base64": b64,                  # consumed by chat loop
            "media_type": "image/png",
            "original_shape": list(img.shape),
            "displayed_shape": list(u8.shape),
            "dtype": str(img.dtype),
            "stretch_low_percentile1": float(lo),
            "stretch_high_percentile99": float(hi),
            "png_kb": round(len(buf.getvalue()) / 1024, 1),
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_get_detector_image_stats(detector_pv: str = "32idbSP1:Pva1:Image") -> dict:
    """Grab the current detector frame via PVA and return summary statistics.
    Does NOT trigger an acquisition — returns whatever the detector is
    currently publishing."""
    try:
        ch = _pva_channel(detector_pv)
        st = ch.get()
        img = _ndarray_from_pva(st)
        img = np.asarray(img)
        flat = img.ravel()
        # Use numpy.float32 for percentiles to avoid overflow on uint16 inputs
        f = flat.astype(np.float32, copy=False)
        return {
            "detector_pv": detector_pv,
            "shape": list(img.shape),
            "dtype": str(img.dtype),
            "min": float(f.min()),
            "max": float(f.max()),
            "mean": float(f.mean()),
            "std": float(f.std()),
            "p1": float(np.percentile(f, 1)),
            "p50": float(np.percentile(f, 50)),
            "p99": float(np.percentile(f, 99)),
            "saturated_fraction": float((f >= np.iinfo(img.dtype).max
                                          if np.issubdtype(img.dtype, np.integer)
                                          else f.max()).mean()),
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_list_recent_scans(save_dir: str = "~/scans",
                           pattern: str = "*.h5",
                           limit: int = 10) -> dict:
    """List the most recent HDF5 master files in a directory, newest first."""
    try:
        d = os.path.expanduser(save_dir)
        if not os.path.isdir(d):
            return {"error": f"directory does not exist: {d}"}
        paths = glob.glob(os.path.join(d, pattern))
        paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        out = []
        for p in paths[:max(1, int(limit))]:
            st = os.stat(p)
            out.append({
                "path": p,
                "size_mb": round(st.st_size / (1024 * 1024), 2),
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                       time.localtime(st.st_mtime)),
            })
        return {"directory": d, "files": out}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


DOCS_DIR_DEFAULT  = os.path.join(PYSTREAM_HOME, "docs")
PV_ALIASES_FILE   = os.path.join(PYSTREAM_HOME, "pv_aliases.json")
DOC_URLS_FILE     = os.path.join(PYSTREAM_HOME, "doc_urls.json")
STATUS_PAGES_FILE = os.path.join(PYSTREAM_HOME, "status_pages.json")


# Tools that mutate state — the dispatcher in agent.py wraps these in a
# user-confirmation dialog before running them.
#
# `bash` is conditionally gated: read-only commands run without confirmation,
# destructive ones trigger the dialog (see _bash_is_destructive below).
# Tools that pop the Yes/No dialog. IOC start/stop/restart (ioc_action)
# is deliberately NOT here: the user wants it to run without asking, and
# the tool verifies the end state itself.
WRITE_TOOLS = {"caput", "tomoscan_start"}


# Patterns that should pop a confirmation dialog when seen in a bash command.
# Read-only stuff (ls, cat, ps, ping, curl, etc.) sails through; anything
# that could mutate the filesystem, kill processes, or hit the network with
# a write needs the user to click Yes. Compiled at module load.
_DESTRUCTIVE_BASH_RE = None
# Running an iocs_monitor wrapper script with an IOC action. These open
# terminal windows and return on *launch*, not when the IOC is up, which
# is how the agent ended up reporting "started" without evidence.
# tool_bash refuses them and points to ioc_action instead.
_IOC_WRAPPER_RE = re.compile(
    r"iocs_monitor.*\.sh\b\s+(?:start|stop|restart|status)\b",
    re.IGNORECASE | re.DOTALL)


def _bash_is_destructive(command: str) -> bool:
    """Heuristic: True if this bash command should pop the confirmation
    dialog. Conservative — when in doubt, returns True. Two parts:
    (1) destructive command words at command-position (after start, ; & | `)
    (2) certain patterns ANYWHERE in the line (.sh invocations, > redirects)."""
    if _IOC_WRAPPER_RE.search(command or ""):
        return False  # refused by tool_bash; don't ask the user first
    global _DESTRUCTIVE_BASH_RE
    if _DESTRUCTIVE_BASH_RE is None:
        import re
        cmd_pos = (
            r"rm\b", r"rmdir\b", r"dd\b", r"kill\b", r"pkill\b", r"killall\b",
            r"chmod\b", r"chown\b", r"chgrp\b", r"mv\b", r"cp\s+-[a-zA-Z]*r\b",
            r"truncate\b", r"shutdown\b", r"reboot\b", r"halt\b", r"poweroff\b",
            r"systemctl\b", r"service\b", r"sudo\b", r"su\s",
            r"caput\b",
            r"git\s+(?:push|reset\s+--hard|clean\s+-)",
        )
        anywhere = (
            r"\.sh\b",                                   # any *.sh invocation
            # > / >> redirect to a real file. EXCLUDES:
            #  - stderr fd-redirects (2>, 2>&1, 2>&2, &>) — leading char is
            #    a digit or & so the `\s>` lookahead fails them naturally
            #  - redirects whose target is /dev/null|zero (purely informational)
            r"\s>{1,2}\s*(?!/dev/(?:null|zero)\b)\S",
            r"\|\s*tee\b",                               # tee
        )
        pattern = (
            r"(?:^|[\s;&|`(])(?:" + "|".join(cmd_pos) + ")"
            + "|(?:" + "|".join(anywhere) + ")"
        )
        _DESTRUCTIVE_BASH_RE = re.compile(pattern, re.IGNORECASE)
    return bool(_DESTRUCTIVE_BASH_RE.search(command or ""))


def tool_list_url_docs() -> dict:
    """Return the user-maintained dict of friendly_name → URL stored in
    ~/.pystream_doc_urls.json. Format:
        {"links": {"areadetector": "https://areadetector.github.io/...",
                   "synapps_motor": "https://github.com/epics-modules/motor",
                   "txm_wiki": "https://confluence.aps.anl.gov/.../TXM"}}"""
    try:
        if not os.path.isfile(DOC_URLS_FILE):
            return {"error": f"URL list not found: {DOC_URLS_FILE}",
                    "hint": "create the file with a 'links' dict to expose "
                            "documentation URLs to the agent."}
        import json as _json
        with open(DOC_URLS_FILE) as f:
            data = _json.load(f)
        return {"path": DOC_URLS_FILE, **data}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_fetch_url(url: str, max_chars: int = 30000) -> dict:
    """Fetch a URL and return its text content (HTML stripped to plain
    text). Use for reading documentation pages — beamline wiki, synApps
    docs, areaDetector docs, etc. Truncates after `max_chars`."""
    if not url:
        return {"error": "url is required"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"error": "url must start with http:// or https://"}
    try:
        import httpx
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={
                "User-Agent": "pystream-agent/1.0 (beamline assistant)",
            })
        status = resp.status_code
        ctype = resp.headers.get("content-type", "")
        body = resp.text
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}", "url": url}

    # Best-effort HTML → text. Strip <script>/<style> blocks and tags.
    import re
    if "html" in ctype.lower():
        body = re.sub(r"<script[\s\S]*?</script>", " ", body, flags=re.I)
        body = re.sub(r"<style[\s\S]*?</style>", " ", body, flags=re.I)
        body = re.sub(r"<!--[\s\S]*?-->", " ", body)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"&nbsp;", " ", body)
        body = re.sub(r"&amp;", "&", body)
        body = re.sub(r"&lt;", "<", body)
        body = re.sub(r"&gt;", ">", body)
        body = re.sub(r"&quot;", '"', body)
        body = re.sub(r"\s+", " ", body).strip()

    truncated = len(body) > max_chars
    return {
        "url": url,
        "status": status,
        "content_type": ctype,
        "content": body[:max_chars],
        "truncated": truncated,
        "char_count": len(body) if not truncated else max_chars,
    }


def tool_list_docs(directory: str = DOCS_DIR_DEFAULT,
                   pattern: str = "*.md") -> dict:
    """List user-maintained reference docs (markdown files) the agent can read."""
    try:
        d = os.path.expanduser(directory)
        if not os.path.isdir(d):
            return {"error": f"docs directory does not exist: {d}",
                    "hint": f"create {d} and put .md files in it"}
        # Recursive: the procedures tree nests by beamline/category
        # (e.g. bl32ID/motors/zone_plate.md). `name` is the path relative
        # to `directory`, which read_doc accepts as-is.
        paths = sorted(glob.glob(os.path.join(d, "**", pattern), recursive=True))
        out = []
        for p in paths:
            st = os.stat(p)
            out.append({
                "name": os.path.relpath(p, d),
                "path": p,
                "size_kb": round(st.st_size / 1024, 1),
            })
        return {"directory": d, "docs": out, "count": len(out)}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_read_doc(name: str, directory: str = DOCS_DIR_DEFAULT,
                  max_chars: int = 20000) -> dict:
    """Read one reference doc. `name` may be a path relative to
    `directory` (as returned by list_docs, e.g. 'bl32ID/motors/zp.md')
    or an absolute path inside `directory`. Truncates after `max_chars`
    to keep the response bounded."""
    try:
        d = os.path.expanduser(directory)
        if not name:
            return {"error": "name is required"}
        candidate = name if os.path.isabs(name) else os.path.join(d, name)
        # Refuse path traversal — must end up inside `directory`.
        real_d = os.path.realpath(d)
        real_p = os.path.realpath(candidate)
        if not real_p.startswith(real_d + os.sep) and real_p != real_d:
            return {"error": f"path is outside docs directory: {candidate}"}
        if not os.path.isfile(real_p):
            return {"error": f"doc not found: {real_p}"}
        with open(real_p, encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
        truncated = len(text) > max_chars
        return {
            "path": real_p,
            "content": text[:max_chars],
            "truncated": truncated,
            "char_count": len(text) if not truncated else max_chars,
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_search_docs(query: str, directory: str = DOCS_DIR_DEFAULT,
                     max_hits: int = 30) -> dict:
    """Case-insensitive substring search across all .md files in the docs
    directory. Returns matching lines with their file + line number."""
    try:
        if not query:
            return {"error": "query is required"}
        d = os.path.expanduser(directory)
        if not os.path.isdir(d):
            return {"error": f"docs directory does not exist: {d}"}
        q = query.lower()
        hits = []
        for p in sorted(glob.glob(os.path.join(d, "**", "*.md"), recursive=True)):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, start=1):
                        if q in line.lower():
                            hits.append({
                                "file": os.path.relpath(p, d),
                                "line": i,
                                "text": line.rstrip("\n")[:240],
                            })
                            if len(hits) >= max_hits:
                                break
            except Exception:
                continue
            if len(hits) >= max_hits:
                break
        return {"query": query, "hits": hits, "truncated": len(hits) >= max_hits}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_list_pv_aliases() -> dict:
    """Read the user-maintained PV alias / macro-substitution file, a JSON
    mapping friendly names → full PV strings. Format:
        {"aliases": {"zp_z": "32idbTXM:mcs2:c1:m15", "energy_rbv": "32id:TXMOptics:Energy_RBV"},
         "macros": {"P": "32id:", "M": "m1"}}"""
    try:
        if not os.path.isfile(PV_ALIASES_FILE):
            return {"error": f"alias file does not exist: {PV_ALIASES_FILE}",
                    "hint": "create this file with an 'aliases' or 'macros' "
                            "dict to teach me your local PV naming."}
        import json as _json
        with open(PV_ALIASES_FILE) as f:
            data = _json.load(f)
        return {"path": PV_ALIASES_FILE, **data}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_resolve_pv(template: str, macros: dict | None = None) -> dict:
    """Apply EPICS-style $(MACRO) substitutions to a PV template. Macros
    default to whatever is stored in ~/.pystream_pv_aliases.json under
    'macros'; pass `macros` to override."""
    try:
        import re
        if not template:
            return {"error": "template is required"}
        if macros is None:
            base = tool_list_pv_aliases()
            macros = base.get("macros", {}) if "error" not in base else {}
        if not isinstance(macros, dict):
            return {"error": "macros must be a dict of {name: value}"}
        unresolved = []

        def _sub(match):
            key = match.group(1)
            if key in macros:
                return str(macros[key])
            unresolved.append(key)
            return match.group(0)

        result = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", _sub, template)
        return {"template": template, "resolved": result,
                "macros_used": macros, "unresolved": unresolved}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_list_plugins(settings_file: str = PYSTREAM_SETTINGS_FILE) -> dict:
    """List the names of pystream plugins that have persisted settings (i.e.
    have been opened at least once). Useful for the agent to know which
    plugins exist before asking for their settings."""
    try:
        import json as _json
        if not os.path.isfile(settings_file):
            return {"error": f"settings file not found: {settings_file}"}
        with open(settings_file) as f:
            data = _json.load(f)
        return {"settings_file": settings_file,
                "plugins": sorted(list(data.keys()))}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_get_plugin_settings(plugin_name: str,
                             settings_file: str = PYSTREAM_SETTINGS_FILE) -> dict:
    """Return the persisted settings for one plugin (e.g. 'QGMaxDialog',
    'AgentDialog'). Sensitive fields are redacted."""
    try:
        import json as _json
        if not os.path.isfile(settings_file):
            return {"error": f"settings file not found: {settings_file}"}
        with open(settings_file) as f:
            data = _json.load(f)
        block = data.get(plugin_name)
        if block is None:
            return {"error": f"no settings stored for plugin {plugin_name!r}",
                    "available": sorted(list(data.keys()))}
        # Redact obvious secrets so we don't echo them through the model.
        redacted = {}
        for k, v in (block.items() if isinstance(block, dict) else []):
            if any(s in k.lower() for s in ("api_key", "password", "secret",
                                             "token")):
                redacted[k] = "<redacted>"
            else:
                redacted[k] = v
        return {"plugin": plugin_name, "settings": redacted}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


# ── general-purpose: shell, file IO, EPICS write ──────────────────────

def tool_bash(command: str, timeout: float = 30.0) -> dict:
    """Run a shell command via `bash -c`. Captures stdout + stderr + exit
    code. Read-only commands run without confirmation; commands matching
    the destructive-pattern set (rm, kill, chmod, sudo, *.sh, redirects,
    git push, etc.) trigger the user's Yes/No dialog before executing.
    Always run as the current user (no privilege escalation).

    `timeout` clamped to [1, 3600] seconds. Default 30 s is right for
    `ls` / `caget` / `ping`; anything doing real work (ssh + conda run
    + tomogui-cli batch, tomocupy recon, big rsync) MUST override to a
    minutes-scale value or you'll get spurious timeouts."""
    if not command or not command.strip():
        return {"error": "command is required"}
    if _IOC_WRAPPER_RE.search(command):
        return {"error": "refused: don't run the iocs_monitor wrapper scripts "
                         "(they open terminal windows and report only that "
                         "the IOC was launched). Use ioc_status / ioc_action, "
                         "which go through the IOC control panel and confirm "
                         "the IOC is actually up or down.",
                "command": command}
    try:
        timeout = max(1.0, min(3600.0, float(timeout)))
    except (TypeError, ValueError):
        timeout = 30.0
    import subprocess
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True, text=True,
            timeout=timeout, shell=False,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "success": result.returncode == 0,
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"command timed out after {timeout}s",
                "command": command}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}", "command": command}


def tool_read_file(path: str, max_chars: int = 50000) -> dict:
    """Read a text file (any path the user has access to). Truncates after
    `max_chars` to keep responses bounded."""
    if not path:
        return {"error": "path is required"}
    try:
        p = os.path.expanduser(path)
        if not os.path.isfile(p):
            return {"error": f"file does not exist: {p}"}
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
        return {
            "path": p,
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
            "char_count": len(text) if len(text) <= max_chars else max_chars,
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_caput(pv_name: str, value, timeout: float = 30.0) -> dict:
    """Write a value to an EPICS PV, then read it back. WRITE action —
    gated by user confirmation.

    `success` is true only when the write actually completed: pyepics
    returns None (not connected) or a negative code (put-callback timed
    out) — the old `bool(ok)` treated the timeout code as success, so a
    motor move longer than the timeout was reported done while still
    moving. Motor .VAL writes additionally check DMOV and limit flags.
    """
    if not pv_name:
        return {"error": "pv_name is required"}
    try:
        import epics
    except Exception as ex:
        return {"error": f"pyepics unavailable: {ex}", "success": False}

    base, _, field = pv_name.partition(".")
    field = (field or "VAL").upper()
    try:
        rtyp = epics.caget(f"{base}.RTYP", timeout=1.0)
    except Exception:
        rtyp = None
    is_motor_move = (rtyp == "motor" and field == "VAL")

    try:
        ret = epics.caput(pv_name, value, wait=True, timeout=float(timeout))
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}", "success": False}

    out: dict[str, Any] = {"pv_name": pv_name, "requested": value}
    if ret is None:
        out.update(success=False,
                   reason="could not connect to the PV — nothing was written")
        return out
    completed = ret > 0
    out["completed"] = completed

    if is_motor_move:
        rb = {f: epics.caget(f"{base}.{f}", timeout=1.0)
              for f in ("RBV", "DMOV", "LVIO", "HLS", "LLS")}
        flags = [label for f, label in (("LVIO", "soft-limit violation"),
                                        ("HLS", "high limit switch"),
                                        ("LLS", "low limit switch"))
                 if rb.get(f)]
        out["readback"] = rb.get("RBV")
        out["done_moving"] = rb.get("DMOV") == 1
        out["limit_flags"] = flags
        out["success"] = completed and out["done_moving"] and not flags
        if not completed:
            out["reason"] = (f"move did not finish within {timeout}s — the "
                             "motor may still be moving")
        elif flags:
            out["reason"] = "motor stopped on " + ", ".join(flags)
        return out

    # Non-motor PV: prefer the areaDetector-style `<pv>_RBV` readback,
    # falling back to the PV itself.
    readback_pv = pv_name
    readback = None
    if "." not in pv_name:
        readback = epics.caget(f"{pv_name}_RBV", timeout=0.5)
        if readback is not None:
            readback_pv = f"{pv_name}_RBV"
    if readback is None:
        readback = epics.caget(pv_name, timeout=1.0)
    out["readback"] = readback
    out["readback_pv"] = readback_pv
    out["success"] = completed
    if not completed:
        out["reason"] = f"put-callback did not complete within {timeout}s"
    return out


# ── network diagnostics (no sudo, read-only) ───────────────────────────

def _validate_host(host: str) -> str | None:
    """Reject hostnames with shell metacharacters. Returns error message or None."""
    if not host:
        return "host is required"
    if any(c in host for c in " \t\n;|&`$<>(){}\\\"'"):
        return f"host contains invalid characters: {host!r}"
    if len(host) > 255:
        return "host name too long"
    return None


def tool_ping(host: str, count: int = 4, timeout: float = 5.0) -> dict:
    """Send ICMP echo requests via the system `ping` (no sudo needed —
    standard ping is setuid on most Linux distros). Returns reachability,
    packet loss percentage, and RTT averages. Use to diagnose whether an
    IOC host or detector server is reachable on the network."""
    err = _validate_host(host)
    if err:
        return {"error": err}
    try:
        count = max(1, min(int(count), 20))
    except (TypeError, ValueError):
        count = 4
    import subprocess
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-w", str(int(timeout) + 5), host],
            capture_output=True, text=True,
            timeout=float(timeout) + 10.0, shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"host": host, "reachable": False,
                "diagnosis": f"ping timed out after {timeout}s — host is "
                             f"down, blocking ICMP, or DNS-failing."}
    except FileNotFoundError:
        return {"error": "`ping` not found on this system"}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}

    out = result.stdout or ""
    # Parse "X packets transmitted, Y received, Z% packet loss" line + rtt summary.
    import re
    loss_pct = None
    m = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    if m:
        loss_pct = float(m.group(1))
    rtt_avg_ms = None
    m = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/", out)
    if m:
        rtt_avg_ms = float(m.group(1))
    reachable = (loss_pct is not None and loss_pct < 100.0)
    return {
        "host": host,
        "reachable": reachable,
        "packet_loss_pct": loss_pct,
        "rtt_avg_ms": rtt_avg_ms,
        "returncode": result.returncode,
        "raw_output": out[-1000:],
        "diagnosis": (
            f"reachable, avg RTT {rtt_avg_ms:.2f} ms" if reachable and rtt_avg_ms
            else "reachable" if reachable
            else "unreachable (100% packet loss)" if loss_pct == 100.0
            else "ping failed — check host/DNS"
        ),
    }


def tool_tcp_check(host: str, port: int, timeout: float = 3.0) -> dict:
    """Try a TCP connect to host:port. Use to verify whether a service is
    accepting connections — areaDetector pvAccess server, procServ telnet
    port, web status page, etc. Distinguishes 'host down', 'firewall blocked',
    and 'port not listening' through the connection error type."""
    err = _validate_host(host)
    if err:
        return {"error": err}
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"error": "port must be an integer"}
    if not (0 < port < 65536):
        return {"error": "port out of range (1–65535)"}
    import socket
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=float(timeout)):
            pass
        elapsed_ms = (time.time() - t0) * 1000.0
        return {"host": host, "port": port, "open": True,
                "elapsed_ms": round(elapsed_ms, 2),
                "diagnosis": f"port {port} open on {host}"}
    except socket.timeout:
        return {"host": host, "port": port, "open": False,
                "diagnosis": "timed out — likely firewalled or host down"}
    except ConnectionRefusedError:
        return {"host": host, "port": port, "open": False,
                "diagnosis": "connection refused — host is up but nothing "
                             "listening on this port"}
    except socket.gaierror as ex:
        return {"host": host, "port": port, "open": False,
                "diagnosis": f"DNS lookup failed: {ex}"}
    except Exception as ex:
        return {"host": host, "port": port, "open": False,
                "diagnosis": f"{type(ex).__name__}: {ex}"}


def tool_traceroute(host: str, max_hops: int = 15,
                    timeout: float = 30.0) -> dict:
    """Show the network path (hops) to a host. Use to diagnose where
    packets are being dropped or routed unexpectedly — especially when
    `ping` says unreachable and you need to know if the problem is the
    target host or somewhere on the way."""
    err = _validate_host(host)
    if err:
        return {"error": err}
    try:
        max_hops = max(1, min(int(max_hops), 30))
    except (TypeError, ValueError):
        max_hops = 15
    import subprocess
    try:
        result = subprocess.run(
            ["traceroute", "-n", "-m", str(max_hops), "-w", "2", host],
            capture_output=True, text=True,
            timeout=float(timeout), shell=False,
        )
    except FileNotFoundError:
        return {"error": "`traceroute` not installed on this host"}
    except subprocess.TimeoutExpired:
        return {"error": f"traceroute timed out after {timeout}s",
                "host": host}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}", "host": host}
    return {
        "host": host,
        "returncode": result.returncode,
        "output": (result.stdout or "")[-2000:],
        "stderr": (result.stderr or "")[-200:],
    }


def tool_dns_lookup(host: str) -> dict:
    """Resolve a hostname to its IP, and (if possible) reverse-resolve.
    Use to verify DNS is working before blaming the network."""
    err = _validate_host(host)
    if err:
        return {"error": err}
    import socket
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror as ex:
        return {"host": host, "resolved": False,
                "diagnosis": f"DNS lookup failed: {ex}"}
    try:
        rdns = socket.gethostbyaddr(ip)[0]
    except Exception:
        rdns = None
    return {"host": host, "resolved": True, "ip": ip, "reverse_dns": rdns,
            "diagnosis": f"{host} → {ip}" + (f" ({rdns})" if rdns else "")}


# ── status-page registry ────────────────────────────────────────────────

def tool_list_status_pages() -> dict:
    """List user-registered web status pages (areaDetector status, IOC
    procServ web view, motor controller status, etc.) from
    ~/.pystream_status_pages.json. These are LIVE pages — fetch with
    fetch_url(url) to read their current content. Distinct from
    list_url_docs which is for static reference material."""
    try:
        if not os.path.isfile(STATUS_PAGES_FILE):
            return {"error": f"status page list not found: {STATUS_PAGES_FILE}",
                    "hint": "create the file with a 'pages' dict mapping "
                            "name → {url, description} to expose live status "
                            "endpoints to the agent."}
        import json as _json
        with open(STATUS_PAGES_FILE) as f:
            data = _json.load(f)
        return {"path": STATUS_PAGES_FILE, **data}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


# ── IOC control (via the beamline IOC Control Panel REST API) ──────────
#
# The panel owns the IOC startup procedure (screen sessions, env). The
# iocs_monitor wrapper scripts it replaces open terminal windows and
# return as soon as they *launch*, so the agent reported "started" with
# no evidence the IOC came up. These tools ask the panel and, for
# actions, poll /status until the requested state is actually observed.

IOC_PANEL_URL = "http://164.54.102.6:5100"

# Names the panel manages. Not enforced (the panel is the authority);
# used for list_iocs and error hints.
CONTROL_PANEL_IOCS = (
    "ioc32idbSP1", "ioc32idbSP2", "ioc32idbBPM", "ioc32idbTEMP",
    "ioc32idbTXM", "ioc32idbShaker", "ioc32idbSoft", "ioc32idaSoft",
    "ioc32idcSoft", "ioc32idAERO", "ioc32idLM", "ioc32idQG",
    "ioc32idTomoScan", "ioc32Kinetix", "iocEnergyServer",
    "32idMZ1", "32idMZ2", "TXMbackend",
)


def _panel_post(endpoint: str, ioc_name: str, timeout: float = 10.0) -> dict:
    import urllib.request
    req = urllib.request.Request(
        f"{IOC_PANEL_URL}/{endpoint}/{ioc_name}", data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


def _panel_resolve(ioc_name: str) -> tuple:
    """Return (panel_name, status_json). Accepts the script-registry form
    ('32idbSP1') as well as the panel form ('ioc32idbSP1')."""
    status = _panel_post("status", ioc_name)
    if status.get("status") == "not found" and not ioc_name.startswith("ioc"):
        alt = _panel_post("status", "ioc" + ioc_name)
        if alt.get("status") != "not found":
            return "ioc" + ioc_name, alt
    return ioc_name, status


# One PV each IOC serves, to confirm the IOC process itself answers. The
# panel's "up" reflects its own session bookkeeping and can say "up" for
# an IOC that serves no PVs at all.
IOC_PROBE_PVS = {
    "ioc32idbSP1":     "32idbSP1:cam1:Acquire",
    "ioc32idbSP2":     "32idbSP2:cam1:Acquire",
    "ioc32idTomoScan": "32id:TomoScan:StartScan",
}


def _probe_ioc(ioc_name: str):
    """Return (probe_pv, reachable) — (None, None) when no probe is known."""
    pv = IOC_PROBE_PVS.get(ioc_name)
    if not pv:
        return None, None
    try:
        import epics
        return pv, epics.caget(pv, timeout=2.0) is not None
    except Exception:
        return pv, False


def _ioc_wait(ioc_name: str, want: str, timeout: float) -> tuple:
    """Poll until the panel reports `want` and, for "up", the probe PV
    answers. Returns (panel_status, probe_reachable, seconds_waited)."""
    start = time.monotonic()
    while True:
        try:
            panel = _panel_post("status", ioc_name).get("status")
        except Exception as ex:
            panel = f"unreachable ({ex})"
        probe_ok = _probe_ioc(ioc_name)[1] if want == "up" else None
        waited = round(time.monotonic() - start, 1)
        if (panel == want and probe_ok is not False) or waited >= timeout:
            return panel, probe_ok, waited
        time.sleep(2.0)


def tool_list_iocs() -> dict:
    """IOC names the control panel manages (for ioc_status / ioc_action)."""
    return {"iocs": list(CONTROL_PANEL_IOCS), "panel": IOC_PANEL_URL}


def tool_ioc_status(ioc_name: str) -> dict:
    """Ask the IOC control panel whether an IOC is up. READ-ONLY."""
    if not ioc_name:
        return {"error": "ioc_name is required"}
    try:
        name, status = _panel_resolve(ioc_name)
    except Exception as ex:
        return {"error": f"IOC control panel unreachable at {IOC_PANEL_URL}: {ex}"}
    if status.get("status") == "not found":
        return {"error": f"IOC {ioc_name!r} is not known to the control panel",
                "known_iocs": list(CONTROL_PANEL_IOCS)}
    out = {"ioc_name": name, "status": status.get("status"),
           "address": status.get("address")}
    probe_pv, reachable = _probe_ioc(name)
    if probe_pv:
        out["probe_pv"] = probe_pv
        out["pvs_reachable"] = reachable
        if status.get("status") == "up" and not reachable:
            out["warning"] = (f"control panel says 'up' but {probe_pv} is not "
                              "reachable — the IOC is not serving PVs. "
                              "ioc_action(..., 'restart') may fix it.")
    return out


def tool_ioc_action(ioc_name: str, action: str, timeout: float = 60.0) -> dict:
    """Start, stop or restart an IOC through the control panel, then poll
    /status until the requested state is observed. Runs without a
    confirmation dialog (user preference). `success` is true only when
    the end state was actually seen, not when the request was merely
    accepted."""
    if action not in ("start", "stop", "restart"):
        return {"error": f"action must be start, stop or restart (got {action!r})"}
    if not ioc_name:
        return {"error": "ioc_name is required"}
    try:
        name, status = _panel_resolve(ioc_name)
    except Exception as ex:
        return {"error": f"IOC control panel unreachable at {IOC_PANEL_URL}: {ex}",
                "success": False}
    before = status.get("status")
    if before == "not found":
        return {"error": f"IOC {ioc_name!r} is not known to the control panel",
                "known_iocs": list(CONTROL_PANEL_IOCS), "success": False}
    want = "down" if action == "stop" else "up"
    probe_pv, probe_before = _probe_ioc(name)
    if action == "stop" and before == "down":
        return {"ioc_name": name, "action": action, "status": before,
                "success": True, "note": "already down — nothing was done"}
    if action == "start" and before == "up":
        if probe_before is False:
            return {"ioc_name": name, "action": action, "status": before,
                    "success": False,
                    "reason": f"control panel says 'up' but {probe_pv} is not "
                              "reachable, so start would do nothing — use "
                              "action='restart'"}
        return {"ioc_name": name, "action": action, "status": before,
                "success": True, "note": "already up — nothing was done"}
    try:
        if action == "restart":
            _panel_post("stop", name, timeout=30.0)
            _ioc_wait(name, "down", timeout=min(30.0, float(timeout)))
            _panel_post("start", name, timeout=30.0)
        else:
            _panel_post(action, name, timeout=30.0)
    except Exception as ex:
        return {"error": f"control panel {action} request failed: {ex}",
                "ioc_name": name, "success": False}
    final, probe_ok, waited = _ioc_wait(name, want, timeout=float(timeout))
    success = final == want and probe_ok is not False
    out = {"ioc_name": name, "action": action, "status_before": before,
           "status": final, "waited_s": waited, "success": success}
    if probe_pv and want == "up":
        out["probe_pv"], out["pvs_reachable"] = probe_pv, probe_ok
    if not success:
        why = (f"control panel reports '{final}'" if final != want
               else f"panel says 'up' but {probe_pv} is not reachable")
        out["reason"] = (f"{why} after {waited}s — the {action} is NOT "
                         "confirmed")
    return out


# ── bl_gui display buttons (MEDM screens, launchers) ────────────────────
#
# The TomoScan / TomoStep / TomoStream screens, XANES, DCM Motors, IOC
# Setup, … are buttons in bl_gui's Displays / Launchers panels. Reading
# them from bl_gui's own saved layout keeps bl_gui the source of truth:
# a button the user edits there is what the agent opens.

def _norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _bl_gui_shell_buttons() -> dict:
    """label → shell command for every saved bl_gui shell button."""
    from bl_gui import headless as blh
    out = {}
    for a in blh.list_actions(blh.load_layout()):
        if a.get("type") == "shell" and a.get("label") and a.get("action"):
            out.setdefault(a["label"], a["action"])
    return out


def tool_open_bl_gui_display(name: str) -> dict:
    """Open a bl_gui display/launcher button by its label (e.g. 'TomoScan',
    'XANES', 'DCM Motors'). Runs the button's own command."""
    try:
        buttons = _bl_gui_shell_buttons()
    except Exception as ex:
        return {"error": f"cannot read bl_gui layout: {type(ex).__name__}: {ex}"}
    if not name:
        return {"available": sorted(buttons)}
    match = next((lbl for lbl in buttons if _norm_label(lbl) == _norm_label(name)), None)
    if match is None:
        return {"error": f"no bl_gui button named {name!r}",
                "available": sorted(buttons)}
    cmd = buttons[match].strip()
    if cmd.endswith("&"):
        cmd = cmd[:-1].rstrip()  # track the program itself, not a backgrounding shell
    import subprocess
    import tempfile
    log = tempfile.NamedTemporaryFile(prefix="bl_gui_display_", suffix=".log",
                                      delete=False)
    try:
        proc = subprocess.Popen(cmd, shell=True, start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    except Exception as ex:
        return {"error": f"launch failed: {type(ex).__name__}: {ex}",
                "command": cmd}
    # A window program that fails (no DISPLAY, missing .adl, bad macro)
    # exits within a second; one that stays up is very likely showing.
    time.sleep(1.5)
    code = proc.poll()
    if code is None:
        return {"button": match, "command": cmd, "pid": proc.pid,
                "success": True, "note": "process is running; window should be open"}
    log.close()
    try:
        with open(log.name, errors="replace") as f:
            output = f.read()[-1500:]
    except OSError:
        output = ""
    return {"button": match, "command": cmd, "success": code == 0,
            "exit_code": code, "output": output,
            "reason": None if code == 0 else "program exited immediately — the window did not open"}


def tool_list_bl_gui_displays() -> dict:
    """Labels of the bl_gui display/launcher buttons open_bl_gui_display accepts."""
    try:
        return {"buttons": sorted(_bl_gui_shell_buttons())}
    except Exception as ex:
        return {"error": f"cannot read bl_gui layout: {type(ex).__name__}: {ex}"}


# ── TomoScan ────────────────────────────────────────────────────────────
#
# ioc32idTomoScan serves three scan types, each its own PV prefix. A scan
# starts by writing StartScan=1 (a busy record that stays "Acquire" until
# the scan ends); ScanStatus is a text line the python server updates as
# it goes. ServerRunning=Running means the tomoscan python server is up.

TOMOSCAN_PREFIXES = {
    "TomoScan":       "32id:TomoScan:",
    "TomoScanStep":   "32id:TomoScanStep:",
    "TomoScanStream": "32id:TomoScanStream:",
}

_TOMOSCAN_STATUS_PVS = (
    "ServerRunning", "ScanStatus", "StartScan", "ScanType",
    "RotationStart", "RotationStep", "RotationStop", "NumAngles",
    "ExposureTime", "NumDarkFields", "NumFlatFields", "FlatFieldMode",
    "FlatFieldAxis", "SampleInX", "SampleOutX", "SampleInY", "SampleOutY",
    "FilePath", "FileName", "ImagesCollected", "ImagesSaved",
    "ElapsedTime", "RemainingTime",
)


def _tomoscan_get(epics, prefix: str, field: str):
    return epics.caget(prefix + field, as_string=True, timeout=1.0)


def _tomoscan_prefix(scan: str):
    prefix = TOMOSCAN_PREFIXES.get(scan or "TomoScan")
    if prefix is None:
        return None, {"error": f"scan must be one of {sorted(TOMOSCAN_PREFIXES)}, "
                               f"got {scan!r}"}
    return prefix, None


def tool_tomoscan_status(scan: str = "TomoScan") -> dict:
    """Read a TomoScan's state and scan parameters. READ-ONLY."""
    prefix, err = _tomoscan_prefix(scan)
    if err:
        return err
    try:
        import epics
    except Exception as ex:
        return {"error": f"pyepics unavailable: {ex}"}
    server = _tomoscan_get(epics, prefix, "ServerRunning")
    if server is None:
        return {"error": f"TomoScan PVs not reachable at {prefix} — the "
                         "TomoScan IOC is not serving them (the control panel "
                         "may still say 'up'). Tell the user; "
                         "ioc_action('ioc32idTomoScan', 'restart') may fix it. "
                         "Don't retry this call."}
    pvs = {f: _tomoscan_get(epics, prefix, f) for f in _TOMOSCAN_STATUS_PVS}
    return {"scan": scan, "prefix": prefix, "pvs": pvs,
            "server_running": server == "Running",
            "scan_in_progress": pvs.get("StartScan") == "Acquire"}


def tool_tomoscan_start(scan: str = "TomoScan", timeout: float = 20.0) -> dict:
    """Start a TomoScan with its current parameters, then confirm it really
    began (StartScan busy and ScanStatus or ImagesCollected changing).
    WRITE action — gated by user confirmation."""
    prefix, err = _tomoscan_prefix(scan)
    if err:
        return err
    try:
        import epics
    except Exception as ex:
        return {"error": f"pyepics unavailable: {ex}", "success": False}
    server = _tomoscan_get(epics, prefix, "ServerRunning")
    if server is None:
        return {"success": False,
                "reason": f"TomoScan PVs not reachable at {prefix} — the "
                          "TomoScan IOC is not serving them; nothing was started"}
    if server != "Running":
        return {"success": False,
                "reason": f"tomoscan python server is not running "
                          f"(ServerRunning={server}) — nothing was started"}
    if _tomoscan_get(epics, prefix, "StartScan") == "Acquire":
        return {"success": False, "reason": "a scan is already in progress"}
    status0 = _tomoscan_get(epics, prefix, "ScanStatus")
    images0 = _tomoscan_get(epics, prefix, "ImagesCollected")
    # wait=False: the busy record stays "Acquire" for the whole scan.
    if not epics.caput(prefix + "StartScan", 1, wait=False):
        return {"success": False, "reason": "write to StartScan failed"}

    deadline = time.monotonic() + float(timeout)
    busy = status = images = None
    while time.monotonic() < deadline:
        time.sleep(0.5)
        busy = _tomoscan_get(epics, prefix, "StartScan")
        status = _tomoscan_get(epics, prefix, "ScanStatus")
        images = _tomoscan_get(epics, prefix, "ImagesCollected")
        if busy == "Acquire" and (status != status0 or images != images0):
            return {"scan": scan, "success": True, "scan_status": status,
                    "images_collected": images}
        if busy == "Done" and status != status0:
            break  # ended already — almost always an error
    return {"scan": scan, "success": False, "start_scan": busy,
            "scan_status": status, "images_collected": images,
            "reason": (f"no scan progress seen within {timeout}s "
                       f"(StartScan={busy}, ScanStatus={status!r}) — the scan "
                       "is NOT confirmed as running")}


def tool_tomoscan_abort(scan: str = "TomoScan", timeout: float = 30.0) -> dict:
    """Abort a running TomoScan and wait for StartScan to return to Done.
    Not gated — stopping a scan must be immediate."""
    prefix, err = _tomoscan_prefix(scan)
    if err:
        return err
    try:
        import epics
    except Exception as ex:
        return {"error": f"pyepics unavailable: {ex}", "success": False}
    if not epics.caput(prefix + "AbortScan", 1, wait=True, timeout=5.0):
        return {"success": False, "reason": "write to AbortScan failed"}
    deadline = time.monotonic() + float(timeout)
    busy = None
    while time.monotonic() < deadline:
        busy = _tomoscan_get(epics, prefix, "StartScan")
        if busy == "Done":
            break
        time.sleep(0.5)
    out = {"scan": scan, "success": busy == "Done", "start_scan": busy,
           "scan_status": _tomoscan_get(epics, prefix, "ScanStatus")}
    if busy != "Done":
        out["reason"] = f"scan still reports StartScan={busy} after {timeout}s"
    return out


# ── device-health diagnostics ───────────────────────────────────────────

# CA alarm severity codes
_SEVR = {0: "NO_ALARM", 1: "MINOR", 2: "MAJOR", 3: "INVALID"}

# Motor record .MSTA bit names (subset of what's actually useful)
_MSTA_BITS = {
    0:  "DIRECTION",      # 0=neg, 1=pos last move
    1:  "DONE",
    2:  "PLUS_LS",        # at + limit
    3:  "HOME_LS",
    5:  "POSITION",
    6:  "SLIP_STALL",     # stalled / slipping
    7:  "AT_HOME",
    8:  "ENCODER_PRESENT",
    9:  "PROBLEM",        # general fault
    10: "MOVING",
    11: "GAIN_SUPPORT",
    12: "COMM_ERR",       # comm error
    13: "MINUS_LS",       # at - limit
    14: "HOMED",
}


def tool_check_pv_health(pv_name: str, connect_timeout: float = 2.0) -> dict:
    """Connect to a PV briefly and report whether it's alive: connected,
    last update time, alarm severity, age of last value. Use this when the
    user suspects a device has stopped communicating."""
    if not pv_name:
        return {"error": "pv_name is required"}
    try:
        import epics
        pv = epics.PV(pv_name, auto_monitor=False)
        connected = pv.wait_for_connection(timeout=connect_timeout)
        if not connected:
            return {
                "pv_name": pv_name,
                "connected": False,
                "diagnosis": "PV did not connect — IOC down, network issue, "
                             "or PV name typo.",
            }
        v = pv.get(timeout=connect_timeout)
        sevr = pv.severity if pv.severity is not None else -1
        stat = pv.status if pv.status is not None else -1
        ts = pv.timestamp or 0
        age = time.time() - ts if ts else None
        diag = []
        if v is None:
            diag.append("connected but get() returned None")
        if sevr in (2, 3):
            diag.append(f"alarm severity {_SEVR.get(sevr, sevr)}")
        if age is not None and age > 60:
            diag.append(f"value is {age:.0f}s old (no recent updates)")
        return {
            "pv_name": pv_name,
            "connected": True,
            "value": v.tolist() if hasattr(v, "tolist") else v,
            "severity": _SEVR.get(sevr, str(sevr)),
            "status_code": stat,
            "last_update_age_s": round(age, 1) if age is not None else None,
            "host": pv.host,
            "diagnosis": "; ".join(diag) if diag else "ok",
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_check_motor_health(motor_pv: str) -> dict:
    """Check a motor's health. Reads .RBV, .MSTA (status bits), .DMOV
    (done-moving), and decodes flags like at-limit / comm-error / problem.
    Use when the user reports a motor not moving, hitting a limit, or
    the IOC reporting an error."""
    if not motor_pv:
        return {"error": "motor_pv is required"}
    try:
        import epics
        rbv = epics.caget(f"{motor_pv}.RBV", timeout=2.0)
        dmov = epics.caget(f"{motor_pv}.DMOV", timeout=2.0)
        msta = epics.caget(f"{motor_pv}.MSTA", timeout=2.0)
        sevr = epics.caget(f"{motor_pv}.SEVR", timeout=2.0)
        if rbv is None and msta is None:
            return {
                "motor_pv": motor_pv,
                "connected": False,
                "diagnosis": "Motor PV did not respond — IOC down or name typo.",
            }
        bits = []
        if msta is not None:
            try:
                msta_int = int(msta)
                for bit, name in _MSTA_BITS.items():
                    if msta_int & (1 << bit):
                        bits.append(name)
            except (TypeError, ValueError):
                msta_int = None
        else:
            msta_int = None
        problems = []
        if "PROBLEM" in bits:
            problems.append("MSTA reports PROBLEM (general fault)")
        if "COMM_ERR" in bits:
            problems.append("MSTA reports COMM_ERR (lost contact with controller)")
        if "PLUS_LS" in bits:
            problems.append("at + limit switch")
        if "MINUS_LS" in bits:
            problems.append("at − limit switch")
        if "SLIP_STALL" in bits:
            problems.append("encoder slip/stall detected")
        sevr_int = int(sevr) if sevr is not None else -1
        if sevr_int in (2, 3):
            problems.append(f"alarm severity {_SEVR.get(sevr_int, sevr_int)}")
        return {
            "motor_pv": motor_pv,
            "connected": True,
            "rbv": float(rbv) if rbv is not None else None,
            "done_moving": bool(int(dmov)) if dmov is not None else None,
            "msta_int": msta_int,
            "msta_bits": bits,
            "severity": _SEVR.get(sevr_int, str(sevr_int)),
            "diagnosis": "; ".join(problems) if problems else "ok",
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_check_detector_stream(detector_pv: str = "32idbSP1:Pva1:Image",
                               settle_s: float = 0.5) -> dict:
    """Check whether the detector's PVA stream is alive. Grabs the current
    uniqueId, waits, grabs again — if it advanced, frames are arriving;
    otherwise the camera is idle, stuck, or disconnected."""
    try:
        ch = _pva_channel(detector_pv)
        st1 = ch.get()
        try:
            uid1 = int(st1["uniqueId"])
        except Exception:
            uid1 = None
        time.sleep(max(0.05, settle_s))
        st2 = ch.get()
        try:
            uid2 = int(st2["uniqueId"])
        except Exception:
            uid2 = None
        if uid1 is None or uid2 is None:
            return {
                "detector_pv": detector_pv,
                "alive": False,
                "diagnosis": "PVA channel responded but uniqueId field missing — "
                             "non-standard NTNDArray.",
            }
        advanced = uid2 != uid1
        return {
            "detector_pv": detector_pv,
            "alive": advanced,
            "uid_first": uid1,
            "uid_second": uid2,
            "delta_id": uid2 - uid1,
            "diagnosis": (
                f"frames are arriving (Δuid={uid2 - uid1} over {settle_s}s)"
                if advanced
                else "uniqueId did not advance — camera is idle, paused, or "
                     "detector server is wedged. Check Acquire_RBV and the "
                     "detector IOC."
            ),
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}",
                "diagnosis": "PVA channel could not be reached — detector "
                             "server (e.g. AD plugin) likely down."}


def tool_read_scan_metadata(path: str) -> dict:
    """Read the scan_config JSON attribute from an XANES2D master HDF5 file
    (and basic counts of /exchange datasets)."""
    try:
        import h5py
        import json as _json
        if not os.path.isfile(path):
            return {"error": f"file does not exist: {path}"}
        with h5py.File(path, "r") as f:
            cfg_raw = f.attrs.get("scan_config")
            cfg = None
            if cfg_raw is not None:
                try:
                    cfg = _json.loads(cfg_raw)
                except Exception:
                    cfg = str(cfg_raw)
            shape_data = (f["/exchange/data"].shape
                          if "/exchange/data" in f else None)
            shape_flat = (f["/exchange/data_flat"].shape
                          if "/exchange/data_flat" in f else None)
            n_e = (f["/exchange/energy"].shape[0]
                   if "/exchange/energy" in f else None)
        return {
            "path": path,
            "scan_config": cfg,
            "shape_data": list(shape_data) if shape_data else None,
            "shape_data_flat": list(shape_flat) if shape_flat else None,
            "n_energies_recorded": int(n_e) if n_e is not None else None,
        }
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


# ── catalog ─────────────────────────────────────────────────────────────
# Note: list_task_recordings / read_task_recording are now core tools
# provided by pystream/agent_core_tools.py — they work on every beamline
# (and even with no beamline). They are NOT registered here.

# Each entry: name, description (visible to the model), JSON-schema for
# inputs, the Python callable. Keep descriptions concrete — that's how the
# model decides when to use the tool.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "bash",
        "description": (
            "Run any shell command. The agent's general-purpose Swiss-army "
            "knife — use for listing files, grep, or anything else that's "
            "a regular shell operation without a dedicated tool. Never "
            "start/stop IOCs here — use ioc_status / ioc_action (the "
            "iocs_monitor .sh scripts are refused). Read-only commands run freely; "
            "destructive ones (rm, mv, kill, chmod, sudo, *.sh executions, "
            "redirects to files, git push) trigger a Yes/No confirmation. "
            "\n\n"
            "**Timeout is critical**: default 30 s is fine for `ls` / "
            "`ping` / `caget`; but any real work (SSH into another host, "
            "conda run, tomogui-cli batch, tomocupy recon, big rsync, "
            "long file scans) will run for MINUTES and must set `timeout` "
            "explicitly. Common values: `120` for a quick remote check, "
            "`600` (10 min) for a Try reconstruction, `1800` (30 min) for "
            "a Full reconstruction batch, `3600` max. A timed-out command "
            "is REPORTED as timeout — do NOT retry, ask the user; the "
            "child may still be running. Returns {returncode, success, "
            "stdout, stderr}."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string",
                            "description": "Shell command to run."},
                "timeout": {"type": "number",
                            "description": "Seconds to wait before killing "
                            "the command. Default 30. Bump for SSH+conda+"
                            "recon-batch or any minutes-long operation. "
                            "Ceiling 3600 (1 hour)."},
            },
            "required": ["command"],
        },
        "func": tool_bash,
    },
    {
        "name": "read_file",
        "description": (
            "Read a text file from disk (any path you have access to). "
            "Truncated at 50K characters. Use for config files, log files, "
            "local docs, scan parameter files, etc."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Absolute or ~/-relative path."},
            },
            "required": ["path"],
        },
        "func": tool_read_file,
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch an HTTP/HTTPS URL and return its body (HTML auto-stripped "
            "to plain text). Use for live status pages, vendor docs, wikis, "
            "or anything web. Truncated at 30K characters."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "Full URL."},
            },
            "required": ["url"],
        },
        "func": tool_fetch_url,
    },
    {
        "name": "read_pv",
        "description": (
            "Read the current value of an EPICS PV. Returns {value, ts} or "
            "{error}. Faster and cleaner than calling caget via bash."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "pv_name": {"type": "string",
                            "description": "Full PV name."},
            },
            "required": ["pv_name"],
        },
        "func": tool_read_pv,
    },
    {
        "name": "caput",
        "description": (
            "Write a value to an EPICS PV and read it back. WRITE action — "
            "Yes/No dialog before executing. Use for setpoints, mode "
            "changes, motor moves (set the .VAL field). Always explain WHY "
            "before calling.\n\n"
            "Returns {success, completed, readback, reason?}; motor moves "
            "also return done_moving and limit_flags. Report the READBACK, "
            "not the requested value. Only say the action succeeded when "
            "success is true; otherwise quote `reason` to the user."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "pv_name": {"type": "string"},
                "value":   {"description": "Number, string, or list."},
                "timeout": {"type": "number",
                            "description": "Seconds to wait for the write "
                            "(or motor move) to complete. Default 30; raise "
                            "for long moves."},
            },
            "required": ["pv_name", "value"],
        },
        "func": tool_caput,
    },
    {
        "name": "get_detector_image_stats",
        "description": (
            "Sample the current detector frame from PVA and return summary "
            "stats: shape, dtype, min/max/mean/std, percentiles, saturation "
            "fraction. Does NOT trigger a new acquisition."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "detector_pv": {
                    "type": "string",
                    "description": "PVA NTNDArray PV. Defaults to "
                                   "'32idbSP1:Pva1:Image'.",
                },
            },
            "required": [],
        },
        "func": tool_get_detector_image_stats,
    },
    {
        "name": "view_detector_image",
        "description": (
            "Capture the current detector frame and return it as a viewable "
            "image (downsampled to ≤1024 px on the long edge, contrast "
            "stretched to 8-bit PNG). USE THIS — not get_detector_image_stats — "
            "when the user asks anything that requires SEEING the image: "
            "'is the beam centered', 'is the sample in view', 'do you see "
            "a shadow', 'how does the alignment look', 'are there hot "
            "pixels', 'what does the detector see right now'. The image is "
            "embedded in the tool result so you can analyse the pixels "
            "directly. For pure numeric stats (mean, std, saturation %), "
            "use get_detector_image_stats — cheaper, no image."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "detector_pv": {
                    "type": "string",
                    "description": "PVA NTNDArray PV. Defaults to "
                                   "'32idbSP1:Pva1:Image'.",
                },
                "max_dim": {
                    "type": "integer",
                    "description": "Max long-edge size in pixels. "
                                   "Defaults to 1024.",
                },
            },
            "required": [],
        },
        "func": tool_view_detector_image,
    },
    {
        "name": "list_status_pages",
        "description": (
            "Return the user's registered live web status URLs (IOC monitor, "
            "machine status, etc.) from ~/.pystream/status_pages.json. "
            "PRIMARY tool for 'list IOCs', 'IOC status', 'machine status', "
            "'is the beam up' — use this FIRST, then fetch_url(url) on the "
            "right entry, BEFORE going hunting with bash."
        ),
        "schema": {"type": "object", "properties": {}, "required": []},
        "func": tool_list_status_pages,
    },
]


def _spec(name, description, func, properties=None, required=()):
    return {"name": name, "description": description, "func": func,
            "schema": {"type": "object", "properties": properties or {},
                       "required": list(required)}}


_STR = {"type": "string"}
_TOMOSCAN_SCAN = {"type": "string", "enum": sorted(TOMOSCAN_PREFIXES),
                  "description": "Which TomoScan: TomoScan (fly scan, "
                                 "default), TomoScanStep, TomoScanStream."}
_DOCS_DIR_HELP = {
    "type": "string",
    "description": "Defaults to ~/.pystream/docs (reference docs). Use "
                   "~/.pystream/procedures for the beamline procedures.",
}

# Tools that were implemented above but never offered to the model. The
# system-prompt addendum already told the model to call list_docs /
# read_doc, which failed as "unknown tool" until these were registered.
TOOLS += [
    _spec("read_motor",
          "Read a motor's position (tries <pv>.RBV, then the base PV). "
          "Prefer this over read_pv for motors.",
          tool_read_motor, {"motor_pv": _STR}, ["motor_pv"]),
    _spec("check_motor_health",
          "Diagnose a motor: RBV, DMOV, MSTA bits decoded (at limit, comm "
          "error, problem). Use when a motor won't move or reports errors.",
          tool_check_motor_health, {"motor_pv": _STR}, ["motor_pv"]),
    _spec("check_pv_health",
          "Report whether a PV is alive: connected, alarm severity, age of "
          "last update. Use when a device seems to have stopped talking.",
          tool_check_pv_health, {"pv_name": _STR}, ["pv_name"]),
    _spec("check_detector_stream",
          "Check whether detector frames are arriving (uniqueId advancing). "
          "Distinguishes a live stream from an idle/stuck camera.",
          tool_check_detector_stream,
          {"detector_pv": {"type": "string",
                           "description": "Defaults to 32idbSP1:Pva1:Image."}}),
    _spec("list_recent_scans",
          "List the most recent HDF5 files in a directory, newest first.",
          tool_list_recent_scans,
          {"save_dir": {"type": "string", "description": "Default ~/scans."},
           "pattern": {"type": "string", "description": "Default *.h5."},
           "limit": {"type": "integer", "description": "Default 10."}}),
    _spec("read_scan_metadata",
          "Read the scan_config attribute and /exchange dataset shapes from "
          "an XANES2D master HDF5 file.",
          tool_read_scan_metadata, {"path": _STR}, ["path"]),
    _spec("list_docs",
          "List markdown docs the agent can read (recursive). Returns names "
          "usable with read_doc.",
          tool_list_docs, {"directory": _DOCS_DIR_HELP}),
    _spec("read_doc",
          "Read one markdown doc by the name list_docs returned (relative "
          "path, e.g. 'bl32ID/motors/zone_plate.md').",
          tool_read_doc, {"name": _STR, "directory": _DOCS_DIR_HELP}, ["name"]),
    _spec("search_docs",
          "Case-insensitive text search across all markdown docs "
          "(recursive). Returns file, line number and line text. Use this "
          "to find the right procedure before acting.",
          tool_search_docs, {"query": _STR, "directory": _DOCS_DIR_HELP},
          ["query"]),
    _spec("list_url_docs",
          "Return the user's saved name → URL map of reference websites.",
          tool_list_url_docs),
    _spec("list_pv_aliases",
          "Return the user's friendly-name → PV alias map and macro values.",
          tool_list_pv_aliases),
    _spec("resolve_pv",
          "Expand $(MACRO) placeholders in a PV template using the saved "
          "macros (or the ones passed).",
          tool_resolve_pv,
          {"template": _STR,
           "macros": {"type": "object", "description": "Optional overrides."}},
          ["template"]),
    _spec("list_plugins",
          "List pystream plugins that have saved settings.",
          tool_list_plugins),
    _spec("get_plugin_settings",
          "Return one plugin's saved settings (e.g. 'QGMaxDialog'). "
          "Sensitive fields are redacted.",
          tool_get_plugin_settings, {"plugin_name": _STR}, ["plugin_name"]),
    _spec("ping",
          "Ping a host: reachability, packet loss, RTT.",
          tool_ping,
          {"host": _STR, "count": {"type": "integer", "description": "Default 4."}},
          ["host"]),
    _spec("tcp_check",
          "Try a TCP connect to host:port; distinguishes host down, "
          "firewalled, and port not listening.",
          tool_tcp_check, {"host": _STR, "port": {"type": "integer"}},
          ["host", "port"]),
    _spec("traceroute",
          "Show the network hops to a host.",
          tool_traceroute, {"host": _STR}, ["host"]),
    _spec("dns_lookup",
          "Resolve a hostname to IP (and reverse).",
          tool_dns_lookup, {"host": _STR}, ["host"]),
    _spec("list_iocs",
          "List the IOC names the beamline IOC control panel manages.",
          tool_list_iocs),
    _spec("ioc_status",
          "Ask the IOC control panel whether an IOC is up (read-only). "
          "Accepts 'ioc32idbSP1' or '32idbSP1'.",
          tool_ioc_status, {"ioc_name": _STR}, ["ioc_name"]),
    _spec("ioc_action",
          "Start, stop or restart an IOC through the control panel, then "
          "wait until the panel reports it up (or down). Runs without a "
          "confirmation dialog. This is the ONLY way to start/"
          "stop IOCs; never use the iocs_monitor .sh scripts. Report the "
          "returned `status`; if success is false, quote `reason`. For the "
          "camera IOC also confirm frames with check_detector_stream.",
          tool_ioc_action,
          {"ioc_name": _STR,
           "action": {"type": "string", "enum": ["start", "stop", "restart"]},
           "timeout": {"type": "number",
                       "description": "Seconds to wait for the end state. "
                       "Default 60."}},
          ["ioc_name", "action"]),
    _spec("list_bl_gui_displays",
          "List the bl_gui display/launcher buttons (TomoScan, TomoStep, "
          "TomoStream, XANES, DCM Motors, IOC Setup, ImageJ, …).",
          tool_list_bl_gui_displays),
    _spec("open_bl_gui_display",
          "Open a bl_gui display/launcher by its button label, exactly as "
          "clicking it in bl_gui — e.g. 'TomoScan' opens the TomoScan MEDM "
          "screen. Use this for 'open tomoscan', 'open the XANES screen', "
          "'open DCM motors'.",
          tool_open_bl_gui_display, {"name": _STR}, ["name"]),
    _spec("tomoscan_status",
          "Read a TomoScan's state (server running, scan in progress, "
          "status text, images collected) and its scan parameters (angles, "
          "exposure, flats/darks, sample in/out, file path/name).",
          tool_tomoscan_status, {"scan": _TOMOSCAN_SCAN}),
    _spec("tomoscan_start",
          "Start a tomography scan with the TomoScan's CURRENT parameters "
          "and confirm it actually began. WRITE action — Yes/No dialog. "
          "Call tomoscan_status first and show the user the parameters. "
          "Say the scan is running only if success is true.",
          tool_tomoscan_start,
          {"scan": _TOMOSCAN_SCAN,
           "timeout": {"type": "number",
                       "description": "Seconds to wait for scan progress. "
                       "Default 20."}}),
    _spec("tomoscan_abort",
          "Abort a running TomoScan and wait until it has stopped. Runs "
          "immediately, no dialog.",
          tool_tomoscan_abort, {"scan": _TOMOSCAN_SCAN}),
]


def get_tool(name: str) -> Callable | None:
    for t in TOOLS:
        if t["name"] == name:
            return t["func"]
    return None


def anthropic_tool_specs() -> list[dict]:
    """Return TOOLS in the shape the Anthropic Messages API expects."""
    return [{
        "name": t["name"],
        "description": t["description"],
        "input_schema": t["schema"],
    } for t in TOOLS]


def openai_tool_specs() -> list[dict]:
    """Return TOOLS in the shape the OpenAI Chat Completions API expects."""
    return [{
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["schema"],
        },
    } for t in TOOLS]


# ═══════════════════════════════════════════════════════════════════════
# System-prompt addendum — inserted at `{beamline_addendum}` in the core
# pystream/agent.py prompt when this beamline is active. Contains 32-ID-
# specific tools, PVs, IOC control panel, and workflow rules that only
# make sense on this beamline.
# ═══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_ADDENDUM = """
# 32-ID BEAMLINE MAP — where things live

| Thing                         | Where / how                                         |
|-------------------------------|-----------------------------------------------------|
| TomoScan / TomoStep / TomoStream screens, XANES, DCM Motors, IOC Setup, Furnace, ImageJ | buttons in **bl_gui** (Displays / Launchers panels) → `open_bl_gui_display(name)` |
| Tomography scans              | TomoScan IOC (`ioc32idTomoScan`), PVs `32id:TomoScan:*` → tomoscan_* tools |
| Camera (Oryx)                 | `ioc32idbSP1`, PVs `32idbSP1:cam1:*`, stream `32idbSP1:Pva1:Image` |
| Motors, shutters, energy      | bl_gui layout (`bl-cli layout motors`), moves via `bl-cli` |
| Zone plate X/Y/Z              | `32idbTXM:mcs2:c1:m13/m14/m15` (Z = focal); table ~/.bl_gui/bl32id_zp_calibration.json |
| IOC start/stop                | IOC Control Panel → ioc_status / ioc_action          |
| Procedures (how-to)           | ~/.pystream/procedures → search_docs / read_doc       |
| Project docs                  | ~/.pystream/docs (AGENTS.md / README of each project) |
| Source code                   | ~/Software/<project> (bl_gui, pystream, beamline-agent, xanes_gui, …); EPICS support under /home/beams19/USERTXM/epics/synApps/support |

If the user names something you don't recognise, LOOK IT UP before
asking: search_docs (both doc dirs), `bl-cli layout actions`,
list_bl_gui_displays, or `grep -rn` in ~/Software/<project>.

# 32-ID TOOLS (beyond the core ones)

| Need                               | Tool                                      |
|------------------------------------|-------------------------------------------|
| PV / motor read                    | read_pv, read_motor, check_pv_health, check_motor_health |
| PV write                           | caput (dialog, except camera Acquire)     |
| Detector                           | view_detector_image, get_detector_image_stats, check_detector_stream |
| IOCs                               | list_iocs, ioc_status, ioc_action (no dialog) |
| bl_gui screens / launchers         | list_bl_gui_displays, open_bl_gui_display |
| Tomography                         | tomoscan_status, tomoscan_start (dialog), tomoscan_abort |
| Docs / procedures                  | list_docs, search_docs, read_doc          |
| Status pages, web                  | list_status_pages, fetch_url              |
| Scans on disk                      | list_recent_scans, read_scan_metadata     |
| Network                            | ping, tcp_check, traceroute, dns_lookup   |
| Anything else                      | bash, read_file                           |

Task-recording tools (`list_task_recordings`, `read_task_recording`)
are core, not 32-ID-specific — they're always in your catalog. See
the "Task recordings" section of the core prompt for the general
workflow, and the 32-ID specifics below for the alignment task order
this beamline uses.

# 32-ID WORKFLOW RULES

A. ANY status / availability / load question — *always* start with
   list_status_pages, even when the user hasn't named a URL.
   Examples: "is X IOC running", "GPU load", "beam status", "disk space
   on tomo3", "is gauss reachable".
   Workflow:
       1. list_status_pages()  — read each entry's description.
       2. If the entry has a `metrics_endpoint`, prefer that for
          structured queries (needs JSON, not rendered HTML).
       3. fetch_url(<right URL>) — pull the live page.
       4. Summarize the answer in one paragraph or short table.
   NEVER `find /`, NEVER `ls ~/` to discover hosts/IOCs. The user has
   pre-registered the right URLs in ~/.pystream/status_pages.json.

B. Per-IOC actions — "is X running", "start/stop/restart X":
   ioc_status(name)            → {"status": "up"|"down"}       (read-only)
   ioc_action(name, action)    → start | stop | restart; waits until the
                                 IOC control panel reports the new state
                                 and returns success + status.
   list_iocs()                 → names the panel manages.
   Names: ioc32idbSP1 (Oryx camera), ioc32idbSP2, ioc32idbBPM,
   ioc32idbTEMP, ioc32idbTXM, ioc32idbShaker, ioc32idbSoft, ioc32idaSoft,
   ioc32idcSoft, ioc32idAERO, ioc32idLM, ioc32idQG, ioc32idTomoScan,
   ioc32Kinetix, iocEnergyServer, 32idMZ1, 32idMZ2, TXMbackend.
   NEVER run the iocs_monitor/scripts/*.sh wrappers (bash refuses them)
   and never ssh to the IOC host — the control panel owns startup.
   Say an IOC is started/stopped ONLY if ioc_action returned
   success: true; otherwise quote its `reason`. "Start the camera" may
   mean start acquisition (caput 32idbSP1:cam1:Acquire 1) rather than
   the IOC — check ioc_status first, and ask if it's already up.

C. PV / motor reads — use read_pv(), not bash with caget. Faster, cleaner.
       read_motor("32idbTXM:mcs2:c1:m15")  # ZP Z (focal axis)
       read_pv("32id:TXMOptics:Energy_RBV") # mono energy in keV
       read_pv("32idbSP1:cam1:Acquire_RBV") # camera state

D. PV writes — use `caput(pv_name, value)`. Motor moves, valve
   toggles, any write. The dialog pops for user confirmation.
   Motor units are MILLIMETRES (32-ID convention). Never use
   bash("caput …") for what `caput()` covers.

   For a coordinated ENERGY move on 32-ID (moves ZP X/Y/Z + QG V/H
   via the calibration table), use `bash("bl-cli energy set <keV>")`
   — that is the ONLY thing bl-cli is needed for; a single-motor
   move goes through `caput()` like anything else.

   Common motor PVs (mm):
     32idbTXM:mcs2:c1:m13 = ZP X    m14 = ZP Y    m15 = ZP Z (focus)
     32idQG:m1 = QG V     32idQG:m2 = QG H
     32idbTXM:mcs:c2:m1 = Sample TopX   m2 = Sample TopZ

E. Detector image checks — two complementary tools:
   * `get_detector_image_stats(pv)` for NUMERIC questions (saturation,
     mean intensity, "is acquisition working"). Cheap, no image on wire.
   * `view_detector_image(pv)` for VISUAL questions ("is beam centered",
     "do you see the sample", "hot pixels"). Image embedded in the
     result; you can inspect pixels directly.
   Default detector PV: `32idbSP1:Pva1:Image`.

F. PROJECT QUESTIONS — when the user mentions a project name (bl_gui,
   pystream, iocs_monitor, txm_calc, xanes_gui, mosalign, holotomo,
   tomocupy, tomopyui, lamn, …), the FIRST step is ALWAYS:
       list_docs()                        — see what's auto-linked
       read_doc("<project>_AGENTS.md")    — preferred
       read_doc("<project>_README.md")    — fallback
   The ~/.pystream/docs/ directory contains symlinks to AGENTS.md /
   README.md from EVERY project under ~/Software/.

   Other on-disk references:
       ~/.pystream/docs/<topic>.md           — user notes (condensers etc.)
       ~/.pystream/status_pages.json         — registered status URLs
       ~/.pystream/procedures/               — beamline procedures; use
                                              search_docs / read_doc with
                                              directory="~/.pystream/procedures"
       ~/.bl_gui/bl32id_zp_calibration.json  — ZP energy/X/Y/Z table
       ~/.pystream/agent_settings.json       — pystream agent settings
                                              (api_key is sensitive, DO NOT echo)

G. Network diagnostics — ping, tcp_check, traceroute, dns_lookup.
   Common IOC hosts: gauss, txmthree (+.aps.anl.gov suffix forms).

H. TOMOGRAPHY — "open tomoscan", "run a tomo scan", "is the scan done":
   - "open tomoscan" / "open the TomoScan screen" →
     open_bl_gui_display("TomoScan") (also TomoStep, TomoStream).
   - "run / start a scan" →
       1. tomoscan_status() — check server_running and that no scan is
          in progress; show the user angles, exposure, flats/darks,
          file name.
       2. If the user wants different parameters, set them with caput
          on 32id:TomoScan:<Field> (NumAngles, RotationStart,
          RotationStep, ExposureTime, NumFlatFields, NumDarkFields,
          FileName, …) and read them back.
       3. tomoscan_start() — the user confirms in the dialog. Report it
          running ONLY if it returned success: true.
   - Progress → tomoscan_status (ScanStatus, ImagesCollected,
     RemainingTime). Stop → tomoscan_abort (immediate, no dialog).
   - If server_running is false, the tomoscan python server is down —
     tell the user; don't try to start a scan.
   Three scan types: TomoScan (fly, default), TomoScanStep, TomoScanStream.

# 32-ID DOMAIN CHEAT SHEET

- TXM = transmission X-ray microscope. Beamline 32-ID-C runs hard X-ray TXM.
- Common modes/scans: XANES2D (energy series + flat), tomo, focus calib.
- Detector chain: SP1 areaDetector cam1 + PVA plugin → frames on
  `32idbSP1:Pva1:Image` (NTNDArray).
- Mono: `32id:TXMOptics:{Energy, EnergySet, Energy_RBV}` (keV).
  EnergySet is rising-edge-triggered (toggle 0→1 to commit a move).
- Zone plate: X/Y/Z = `32idbTXM:mcs2:c1:m13/m14/m15`, Z is the focal
  axis. Calibration table: ~/.bl_gui/bl32id_zp_calibration.json (the
  authority — `32id:m1` is NOT the zone plate).
- QGMax: image-mean optimization plugin. Status PV: `32id:pystream:qgmax`.
- TomoScan: prefix `32id:TomoScan:`; StartScan (busy: Done/Acquire),
  AbortScan, ScanStatus (text), ServerRunning (Stopped/Running),
  ImagesCollected, NumAngles, RotationStart/Step/Stop, ExposureTime,
  FilePath, FileName.

# 32-ID ANTI-PATTERNS (in addition to the core ones)

- ❌ Wrapper scripts (they spawn gnome-terminal). Use the Control Panel.
- ❌ Direct ssh to IOC hosts. Use the Control Panel.
- ❌ Inventing IOC / PV names. Verify with a tool or ask.
- ❌ Echoing ~/.pystream/agent_settings.json (contains api_key).
- ❌ **Raw `caput <MOTOR_PV>.VAL <VAL>` to move a motor.** Use
  `bash("bl-cli motor set <PV> <VAL>")` — the beamline's motor moves
  go through bl_gui / bl-cli, not raw caput. If bl-cli isn't
  available on this host, ASK the user; don't fall back to caput.
- ❌ Confusing units. All 32-ID motor RBVs are in **millimetres**,
  not micrometres. "1 µm move" = 0.001 in the caput value.
- ❌ "1e-6 = 4499" or any other magic-number rescaling of an RBV.
  The RBV IS the position. If the read looks tiny (~1e-6), the
  motor is near zero — that's real, not "raw units".

# 32-ID ALIGNMENT WORKFLOW (element order + slugs)

Six elements are aligned individually, in this order, then one final
joint refinement pass over all of them:

    1. Detector                — focus & rotation      (slug: detector)
    2. Zone Plate              — position & focus      (slug: zone_plate)
    3. Phase Ring              — position              (slug: phase_ring)
    4. Condenser               — position & angles     (slug: condenser)
    5. Pinhole                 — position              (slug: pinhole)
    6. Beam Stop               — position              (slug: beam_stop)
    7. Final Joint Refinement  — all 15 axes together  (slug: final_joint_refinement)

Use these slugs when calling `read_task_recording(task_slug)`.
The general workflow (always list first, load latest session, follow
the exact motor sequence) is in the core prompt above — no need to
restate it. If the user names a task that isn't in this list,
still call `list_task_recordings()` first — the free-text mode of
the recorder means anything might be there (Sample alignment, custom
elements, one-off diagnostics, …).
"""


# ═══════════════════════════════════════════════════════════════════════
# Knowledge-base bootstrap — the 32-ID-flavored helper the old
# AgentDialog ran on construction. Called by bl32ID.__init__:
# start_background_services(pystream_main) at launch, so the user-editable
# knowledge base is populated once when pystream starts against this
# beamline.
# ═══════════════════════════════════════════════════════════════════════

def _discover_ioc_scripts() -> dict:
    """Look for an iocs_monitor scripts directory under common APS
    conventions. Returns a populated `scripts` dict ready to drop into
    ioc_scripts.json, or {} if nothing is found."""
    import glob, os
    candidates = [
        os.path.expanduser("~/Software/iocs_monitor/iocs_monitor/scripts"),
        os.path.expanduser("~/iocs_monitor/scripts"),
    ]
    for d in candidates:
        if not os.path.isdir(d):
            continue
        shs = sorted(glob.glob(os.path.join(d, "*.sh")))
        if not shs:
            continue
        return {
            os.path.splitext(os.path.basename(p))[0]: {
                "path": p,
                "description": f"Restart {os.path.basename(p)} "
                               f"(auto-discovered in {d})",
            } for p in shs
        }
    return {}


def _link_known_reference_docs(docs_dir: str):
    """Auto-symlink AGENTS.md / README.md from every project under
    ~/Software/ into the agent's docs directory so list_docs /
    read_doc find them. Idempotent."""
    import glob, os
    try:
        os.makedirs(docs_dir, exist_ok=True)
    except Exception:
        return
    software_root = os.path.expanduser("~/Software")
    if not os.path.isdir(software_root):
        return
    for project_dir in sorted(glob.glob(os.path.join(software_root, "*"))):
        if not os.path.isdir(project_dir):
            continue
        project_name = os.path.basename(project_dir)
        for filename in ("AGENTS.md", "README.md"):
            src_abs = os.path.join(project_dir, filename)
            if not os.path.isfile(src_abs):
                continue
            tag = filename.rsplit(".", 1)[0]
            dst = os.path.join(docs_dir, f"{project_name}_{tag}.md")
            try:
                if os.path.islink(dst) and os.readlink(dst) == src_abs:
                    break
                if os.path.lexists(dst):
                    break
                os.symlink(src_abs, dst)
            except Exception:
                pass
            break  # prefer AGENTS over README


def bootstrap_knowledge_base():
    """Create empty starter files for the user-editable knowledge base
    the first time bl32ID is active. Never overwrites existing files.
    Called by bl32ID.start_background_services at pystream launch."""
    import json as _json, os
    from .plugin_settings import PYSTREAM_HOME as _HOME
    docs_dir     = os.path.join(_HOME, "docs")
    aliases_file = os.path.join(_HOME, "pv_aliases.json")
    urls_file    = os.path.join(_HOME, "doc_urls.json")
    ioc_file     = os.path.join(_HOME, "ioc_scripts.json")
    status_file  = os.path.join(_HOME, "status_pages.json")
    try:
        if not os.path.isdir(docs_dir):
            os.makedirs(docs_dir, exist_ok=True)
            readme = os.path.join(docs_dir, "README.md")
            if not os.path.isfile(readme):
                with open(readme, "w") as f:
                    f.write(
                        "# pystream agent — local docs\n\n"
                        "Drop markdown files in this directory and the AI "
                        "agent reads them on demand via list_docs / "
                        "search_docs / read_doc. One topic per file works "
                        "best — short titles, concrete facts.\n"
                    )
        _link_known_reference_docs(docs_dir)
        if not os.path.isfile(aliases_file):
            with open(aliases_file, "w") as f:
                _json.dump({"_comment": "friendly_name → PV",
                            "aliases": {}, "macros": {}}, f, indent=2)
        if not os.path.isfile(urls_file):
            with open(urls_file, "w") as f:
                _json.dump({"_comment": "friendly_name → URL",
                            "links": {}}, f, indent=2)
        if not os.path.isfile(ioc_file):
            with open(ioc_file, "w") as f:
                _json.dump({"_comment": "IOC control allowlist",
                            "scripts": _discover_ioc_scripts()}, f, indent=2)
        if not os.path.isfile(status_file):
            with open(status_file, "w") as f:
                _json.dump({"_comment": "Friendly_name → status page URL",
                            "pages": {}}, f, indent=2)
    except Exception:
        pass  # best-effort; user can create the files themselves
