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
import os
import time
from typing import Any, Callable

import numpy as np


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


DOCS_DIR_DEFAULT = os.path.expanduser("~/.pystream_docs")
PV_ALIASES_FILE = os.path.expanduser("~/.pystream_pv_aliases.json")
PYSTREAM_SETTINGS_FILE = os.path.expanduser("~/.pystream_bl32ID_settings.json")
DOC_URLS_FILE = os.path.expanduser("~/.pystream_doc_urls.json")


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
        paths = sorted(glob.glob(os.path.join(d, pattern)))
        out = []
        for p in paths:
            st = os.stat(p)
            out.append({
                "name": os.path.basename(p),
                "path": p,
                "size_kb": round(st.st_size / 1024, 1),
            })
        return {"directory": d, "docs": out, "count": len(out)}
    except Exception as ex:
        return {"error": f"{type(ex).__name__}: {ex}"}


def tool_read_doc(name: str, directory: str = DOCS_DIR_DEFAULT,
                  max_chars: int = 20000) -> dict:
    """Read one reference doc by filename. `name` may be a bare filename
    (resolved against `directory`) or an absolute path inside `directory`.
    Truncates after `max_chars` to keep the response bounded."""
    try:
        d = os.path.expanduser(directory)
        if not name:
            return {"error": "name is required"}
        candidate = (name if os.path.isabs(name)
                     else os.path.join(d, os.path.basename(name)))
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
        for p in sorted(glob.glob(os.path.join(d, "*.md"))):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, start=1):
                        if q in line.lower():
                            hits.append({
                                "file": os.path.basename(p),
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
        {"aliases": {"zp_z": "32id:m1", "energy_rbv": "32id:TXMOptics:Energy_RBV"},
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

# Each entry: name, description (visible to the model), JSON-schema for
# inputs, the Python callable. Keep descriptions concrete — that's how the
# model decides when to use the tool.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "read_pv",
        "description": (
            "Read the current value of an EPICS Process Variable. "
            "Use this to inspect any PV the user mentions, or to verify the "
            "state of a device. Returns {pv_name, value, ts} or {error}."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "pv_name": {"type": "string",
                            "description": "Full PV name, e.g. '32id:m1.RBV'."},
            },
            "required": ["pv_name"],
        },
        "func": tool_read_pv,
    },
    {
        "name": "read_motor",
        "description": (
            "Read a motor's position (the .RBV field, falling back to the "
            "base PV). Use this to check where a motor currently is."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "motor_pv": {"type": "string",
                             "description": "Motor PV without .RBV suffix, "
                                            "e.g. '32id:m1'."},
            },
            "required": ["motor_pv"],
        },
        "func": tool_read_motor,
    },
    {
        "name": "get_detector_image_stats",
        "description": (
            "Sample the current detector frame from PVA and return summary "
            "stats: shape, dtype, min/max/mean/std and 1/50/99 percentiles. "
            "Does NOT trigger a new acquisition — returns the latest "
            "published frame. Use this when the user asks about beam "
            "intensity, saturation, alignment quality, or unusual image "
            "behaviour."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "detector_pv": {
                    "type": "string",
                    "description": "PVA NTNDArray PV name. Defaults to "
                                   "'32idbSP1:Pva1:Image' if omitted.",
                },
            },
            "required": [],
        },
        "func": tool_get_detector_image_stats,
    },
    {
        "name": "list_recent_scans",
        "description": (
            "List recent XANES2D master HDF5 files in a directory, newest "
            "first. Use this to find a recent scan to inspect, or to "
            "confirm a scan was actually saved."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "save_dir": {"type": "string",
                             "description": "Directory to search. Defaults "
                                            "to '~/scans'."},
                "pattern": {"type": "string",
                            "description": "Glob pattern. Defaults to '*.h5'."},
                "limit": {"type": "integer",
                          "description": "Max number of files to return. "
                                         "Defaults to 10."},
            },
            "required": [],
        },
        "func": tool_list_recent_scans,
    },
    {
        "name": "read_scan_metadata",
        "description": (
            "Read the scan_config metadata + dataset shapes from an XANES2D "
            "master HDF5 file. Use this after list_recent_scans to inspect "
            "what was actually scanned (energies, sample positions, ZP cal)."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Absolute path to the .h5 file."},
            },
            "required": ["path"],
        },
        "func": tool_read_scan_metadata,
    },
    {
        "name": "list_docs",
        "description": (
            "List user-maintained reference documents (markdown files in "
            "~/.pystream_docs/). Use this when the user asks about beamline "
            "procedures, troubleshooting, or anything that might be in the "
            "local documentation. ALWAYS check here before saying you don't "
            "know something domain-specific."
        ),
        "schema": {"type": "object", "properties": {}, "required": []},
        "func": tool_list_docs,
    },
    {
        "name": "read_doc",
        "description": (
            "Read one reference document by filename (from list_docs). "
            "Returns the markdown text. Truncates after 20K characters; if "
            "you need more, ask the user where to look or grep with "
            "search_docs."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Doc filename, e.g. 'xanes2d.md'."},
            },
            "required": ["name"],
        },
        "func": tool_read_doc,
    },
    {
        "name": "search_docs",
        "description": (
            "Case-insensitive substring search across all reference docs. "
            "Returns matching lines with file + line number. Use this to "
            "locate a topic before pulling the full doc with read_doc."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Substring to search for."},
            },
            "required": ["query"],
        },
        "func": tool_search_docs,
    },
    {
        "name": "list_pv_aliases",
        "description": (
            "Read the user-maintained PV alias / macro-substitution file at "
            "~/.pystream_pv_aliases.json. The 'aliases' dict maps friendly "
            "names to full PV strings (e.g. 'zp_z' → '32id:m1'). The "
            "'macros' dict maps EPICS-style macros (e.g. 'P' → '32id:'). "
            "Call this before guessing a PV name — the user often has a "
            "local convention."
        ),
        "schema": {"type": "object", "properties": {}, "required": []},
        "func": tool_list_pv_aliases,
    },
    {
        "name": "resolve_pv",
        "description": (
            "Expand EPICS-style $(MACRO) substitutions in a PV template. "
            "By default uses the macros from ~/.pystream_pv_aliases.json. "
            "Use this to convert a template like '$(P)$(M).RBV' into a "
            "real PV before calling read_pv."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "template": {"type": "string",
                             "description": "PV template, e.g. '$(P)$(M).RBV'."},
                "macros": {"type": "object",
                           "description": "Optional override macros dict."},
            },
            "required": ["template"],
        },
        "func": tool_resolve_pv,
    },
    {
        "name": "list_plugins",
        "description": (
            "List the names of pystream plugins that have persisted settings. "
            "Use this to discover which plugins the user has configured "
            "before asking for their settings."
        ),
        "schema": {"type": "object", "properties": {}, "required": []},
        "func": tool_list_plugins,
    },
    {
        "name": "get_plugin_settings",
        "description": (
            "Return the persisted settings for one pystream plugin (e.g. "
            "'QGMaxDialog', 'XANES2DGuiDialog'). Sensitive fields like "
            "'api_key' are redacted. Use this to learn what the user has "
            "configured (motor PVs, scan parameters, save directories, "
            "etc.) before answering questions about that plugin."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "plugin_name": {
                    "type": "string",
                    "description": "Plugin class name, e.g. 'QGMaxDialog'.",
                },
            },
            "required": ["plugin_name"],
        },
        "func": tool_get_plugin_settings,
    },
    {
        "name": "list_url_docs",
        "description": (
            "List documentation URLs the user has registered in "
            "~/.pystream_doc_urls.json (beamline wiki, synApps modules, "
            "areaDetector docs, etc.). Call this BEFORE fetching arbitrary "
            "URLs — it tells you what references the user wants you to use."
        ),
        "schema": {"type": "object", "properties": {}, "required": []},
        "func": tool_list_url_docs,
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch a documentation page over HTTPS and return its text "
            "content (HTML auto-stripped). Use for reading manuals, wikis, "
            "synApps / areaDetector docs that the user has registered via "
            "list_url_docs. Truncates at 30K characters; if you need more, "
            "fetch a specific subpage rather than the whole site."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "Full URL, http:// or https://."},
            },
            "required": ["url"],
        },
        "func": tool_fetch_url,
    },
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
