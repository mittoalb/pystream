"""
AI Agent plugin for bl32ID.

Chat panel that talks to a Gateway speaking either the Anthropic Messages
API protocol or the OpenAI Chat Completions protocol. The user picks the
protocol in the dialog; the plugin lists models from the Gateway and routes
the call through the matching SDK.

The agent has access to a small read-only tool catalog (read_pv, read_motor,
get_detector_image_stats, list_recent_scans, read_scan_metadata — see
`agent_tools.py`). The chat loop is agentic: when the model decides to
call a tool, the worker executes it, surfaces it in the transcript, and
feeds the result back to the model until it produces a final answer.

Network calls run on a QThread worker so the GUI thread stays responsive.
"""

import json
import logging
import os
from typing import Optional

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import pyqtSignal

from .plugin_settings import PYSTREAM_HOME, load_settings, save_settings
from .agent_tools import (
    anthropic_tool_specs,
    openai_tool_specs,
    get_tool,
    WRITE_TOOLS,
)


# ── confirmation bridge (worker thread → GUI thread) ────────────────────

class _ConfirmHelper(QtCore.QObject):
    """Lives on the GUI thread. Worker threads call its `ask` slot via
    BlockingQueuedConnection to pop a Yes/No QMessageBox and get the
    user's answer back. Used to gate write-class tools."""

    @QtCore.pyqtSlot(str, str, result=bool)
    def ask(self, title: str, message: str) -> bool:
        reply = QtWidgets.QMessageBox.question(
            None, title, message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return reply == QtWidgets.QMessageBox.Yes


def _confirmation_message(name: str, args: dict) -> str:
    """Format a clear, scannable confirmation message per write tool."""
    if name == "restart_ioc":
        ioc = args.get("ioc_name", "?")
        return (
            f"The agent wants to RESTART an IOC.\n\n"
            f"  IOC: {ioc}\n\n"
            f"This will run the script registered for '{ioc}' in "
            f"~/.pystream_ioc_scripts.json. Continue?"
        )
    return (
        f"The agent wants to call:\n\n"
        f"  {name}({json.dumps(args, default=str)})\n\n"
        f"Allow this?"
    )


PROTOCOL_ANTHROPIC = "anthropic"
PROTOCOL_OPENAI = "openai"

# Cap on agentic iterations per turn — protects against runaway tool loops.
MAX_AGENT_ITERATIONS = 10


SYSTEM_PROMPT_DEFAULT = """You are an AI assistant embedded in pystream, the
live-image GUI for APS beamline 32-ID (TXM, transmission X-ray microscopy).
You help the on-shift scientist operate the beamline. Be concise — a couple
of sentences unless asked for detail. Prefer concrete answers (PV names,
file paths, motor positions) over generalities.

You have a set of read-only tools. Use them rather than guessing:

LIVE STATE
- read_pv(pv_name) — current value of any EPICS PV
- read_motor(motor_pv) — motor .RBV
- get_detector_image_stats() — current detector frame stats (no new acquire)

DEVICE HEALTH (use when something seems stuck, frozen, or unresponsive)
- check_pv_health(pv_name) — connected? alarm? how stale is the value?
- check_motor_health(motor_pv) — decodes .MSTA: comm error, at limit,
  slip/stall, fault. Returns a one-sentence diagnosis.
- check_detector_stream(detector_pv) — checks if frames are still flowing
  (uniqueId advancing). Use when the live image looks frozen.

NETWORK DIAGNOSTICS (no sudo)
- ping(host) — is the host reachable? packet loss + RTT
- tcp_check(host, port) — is a specific service listening?
- dns_lookup(host) — resolve a hostname / verify DNS works
- list_status_pages() / fetch_url(url) — registered live status URLs
  (areaDetector status, IOC web view, etc.) — fetch the URL after looking
  it up.

IOC RECOVERY (write actions — user gets a Yes/No dialog before they run)
- list_ioc_scripts() — RESTART AUTHORIZATION list, NOT a status source.
  Only call this when about to call restart_ioc.
- restart_ioc(ioc_name) — runs the user's local restart script for that
  IOC. Only suggest this if a tool result clearly indicates the IOC is
  down/wedged. Always call list_ioc_scripts FIRST and confirm the IOC is
  on the allowlist; never guess names.

IMPORTANT — DISAMBIGUATION:
- "Are my IOCs running?" / "What IOCs are up?" / "IOC status" →
  list_status_pages then fetch_url for an ioc_monitor page if registered,
  OR ping/tcp_check the IOC hosts. NOT list_ioc_scripts.
- "Restart this IOC" / "the IOC is wedged, fix it" → list_ioc_scripts
  then restart_ioc.
- list_ioc_scripts only tells you what you're permitted to RESTART; it
  says nothing about which IOCs exist or whether they're up.

LOCAL KNOWLEDGE BASE
- list_docs() / read_doc(name) / search_docs(query) — markdown reference
  docs the user maintains in ~/.pystream_docs/ (procedures, troubleshooting,
  IOC notes, etc.). ALWAYS check here before saying you don't know
  something beamline-specific.
- list_pv_aliases() — user-maintained PV alias / macro file at
  ~/.pystream_pv_aliases.json. Call this BEFORE guessing PV names — the
  user has a local naming convention.
- resolve_pv(template) — expand $(MACRO) substitutions using the alias file.

WEB DOCS
- list_url_docs() — registered documentation URLs (beamline wiki, synApps,
  areaDetector). Check here before fetching arbitrary URLs.
- fetch_url(url) — read a specific page. Prefer pages from list_url_docs.

GUI / PLUGIN STATE
- list_plugins() — pystream plugins the user has configured
- get_plugin_settings(plugin_name) — what's configured in that plugin
  (motor PVs, scan parameters, save dirs). Sensitive fields (api_key,
  password) are redacted.

DATA
- list_recent_scans() / read_scan_metadata(path) — recent XANES2D HDF5
  master files and their scan_config

WORKFLOW
- For "what's happening right now" → live-state tools.
- For "how do I do X" → search_docs / read_doc first.
- For "what PV is …" → list_pv_aliases first.
- For "what's plugin X set to" → get_plugin_settings.
- Don't invent PV names, file paths, or settings. If a tool returns
  {"error": ...}, say so plainly and suggest the fix the error hints at.
"""


# ── tool dispatch helper ────────────────────────────────────────────────

def _execute_tool(name: str, arguments: dict, confirm=None) -> dict:
    """Run a tool by name with the model-provided arguments. Always returns
    a JSON-serializable dict — tools wrap their own exceptions.

    If `name` is in WRITE_TOOLS, `confirm(title, message) -> bool` is
    called BEFORE the tool runs. If the user clicks No (or no confirm
    callback was provided), the call is rejected with an error result the
    model can read."""
    func = get_tool(name)
    if func is None:
        return {"error": f"unknown tool: {name}"}
    if not isinstance(arguments, dict):
        return {"error": f"arguments must be an object, got {type(arguments).__name__}"}

    if name in WRITE_TOOLS:
        if confirm is None:
            return {"error": f"{name} is a write tool but no confirmation "
                             f"channel is available — refusing."}
        approved = False
        try:
            approved = bool(confirm("Confirm action", _confirmation_message(name, arguments)))
        except Exception as ex:
            return {"error": f"confirmation prompt failed: {ex}"}
        if not approved:
            return {"error": "user denied the action",
                    "denied": True, "tool": name, "arguments": arguments}

    try:
        result = func(**arguments)
    except TypeError as ex:
        return {"error": f"bad arguments to {name}: {ex}"}
    except Exception as ex:
        return {"error": f"{type(ex).__name__} in {name}: {ex}"}
    return result if isinstance(result, dict) else {"value": result}


# ── chat: Anthropic protocol ────────────────────────────────────────────

def _chat_anthropic(base_url, api_key, model, system_prompt,
                    history, user_text, emit_tool, confirm):
    """Agentic loop on the Anthropic Messages API. `emit_tool` is a callback
    `(name, arguments, result_or_None) -> None` invoked once at call-start
    (result=None) and once at completion."""
    import anthropic
    client = anthropic.Anthropic(base_url=base_url, api_key=api_key,
                                 timeout=60.0, max_retries=2)
    tools = anthropic_tool_specs()
    messages = [*history, {"role": "user", "content": user_text}]

    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    for _ in range(MAX_AGENT_ITERATIONS):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=tools,
            messages=messages,
        )
        u = response.usage
        totals["input"] += getattr(u, "input_tokens", 0) or 0
        totals["output"] += getattr(u, "output_tokens", 0) or 0
        totals["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        totals["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0

        if response.stop_reason != "tool_use":
            text = "".join(
                b.text for b in response.content
                if getattr(b, "type", None) == "text"
            ).strip()
            return text, totals

        # Append the assistant's content (text + tool_use blocks) verbatim,
        # then run each tool and feed results back as a user turn.
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for b in response.content:
            if getattr(b, "type", None) == "tool_use":
                emit_tool(b.name, b.input, None)
                result = _execute_tool(b.name, b.input, confirm=confirm)
                emit_tool(b.name, b.input, result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": json.dumps(result, default=str),
                })
        messages.append({"role": "user", "content": tool_results})

    return "(stopped: hit MAX_AGENT_ITERATIONS — too many tool calls)", totals


# ── chat: OpenAI protocol ───────────────────────────────────────────────

def _chat_openai(base_url, api_key, model, system_prompt,
                 history, user_text, emit_tool, confirm):
    """Agentic loop on OpenAI Chat Completions."""
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key,
                    timeout=60.0, max_retries=2)
    tools = openai_tool_specs()
    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_text},
    ]
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    for _ in range(MAX_AGENT_ITERATIONS):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=tools, max_tokens=4096,
        )
        u = response.usage
        totals["input"] += getattr(u, "prompt_tokens", 0) or 0
        totals["output"] += getattr(u, "completion_tokens", 0) or 0
        cd = getattr(u, "prompt_tokens_details", None)
        totals["cache_read"] += (getattr(cd, "cached_tokens", 0) or 0) if cd else 0

        msg = response.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip(), totals

        # Re-attach the assistant turn including its tool_calls, then send
        # one tool message per call.
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [{
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            } for tc in msg.tool_calls],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            emit_tool(tc.function.name, args, None)
            result = _execute_tool(tc.function.name, args, confirm=confirm)
            emit_tool(tc.function.name, args, result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    return "(stopped: hit MAX_AGENT_ITERATIONS — too many tool calls)", totals


# ── worker thread ───────────────────────────────────────────────────────

class _ChatWorker(QtCore.QThread):
    """Throwaway worker — one chat turn per instance. Emits tool_event for
    every tool call so the dialog can render it live."""

    done = pyqtSignal(str, dict)            # (assistant_text, usage_dict)
    error = pyqtSignal(str)
    tool_event = pyqtSignal(str, dict, object)  # (name, args, result-or-None)

    def __init__(self, protocol, base_url, api_key, model,
                 system_prompt, history, user_text, confirm_helper=None):
        super().__init__()
        self.protocol = protocol
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.history = history
        self.user_text = user_text
        self.confirm_helper = confirm_helper

    def _emit_tool(self, name, args, result):
        self.tool_event.emit(name, dict(args), result)

    def _confirm(self, title, message) -> bool:
        """Block this worker thread, ask the GUI thread for Yes/No."""
        if self.confirm_helper is None:
            return False
        result = QtCore.QMetaObject.invokeMethod(
            self.confirm_helper, "ask",
            QtCore.Qt.BlockingQueuedConnection,
            QtCore.Q_RETURN_ARG(bool),
            QtCore.Q_ARG(str, title),
            QtCore.Q_ARG(str, message),
        )
        return bool(result)

    def run(self):
        try:
            if self.protocol == PROTOCOL_ANTHROPIC:
                text, usage = _chat_anthropic(
                    self.base_url, self.api_key, self.model,
                    self.system_prompt, self.history, self.user_text,
                    self._emit_tool, self._confirm,
                )
            elif self.protocol == PROTOCOL_OPENAI:
                text, usage = _chat_openai(
                    self.base_url, self.api_key, self.model,
                    self.system_prompt, self.history, self.user_text,
                    self._emit_tool, self._confirm,
                )
            else:
                self.error.emit(f"unknown protocol: {self.protocol!r}")
                return
            self.done.emit(text, usage)
        except ImportError as ex:
            self.error.emit(f"SDK not installed: {ex}")
        except Exception as ex:
            self.error.emit(f"{type(ex).__name__}: {ex}")


# ── helpers for listing models ──────────────────────────────────────────

def _list_models(protocol, base_url, api_key, *, timeout=10.0):
    if protocol == PROTOCOL_ANTHROPIC:
        import anthropic
        client = anthropic.Anthropic(base_url=base_url, api_key=api_key,
                                     timeout=timeout, max_retries=0)
        return [m.id for m in client.models.list()]
    elif protocol == PROTOCOL_OPENAI:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key,
                        timeout=timeout, max_retries=0)
        return [m.id for m in client.models.list().data]
    raise ValueError(f"unknown protocol: {protocol!r}")


# ── dialog ──────────────────────────────────────────────────────────────

class AgentDialog(QtWidgets.QDialog):
    """Chat panel with read-only beamline tools. Singleton — open once in
    pystream and leave it; settings persist across sessions."""

    BUTTON_TEXT = "AI"
    HANDLER_TYPE = "singleton"

    def __init__(self, parent=None, logger: Optional[logging.Logger] = None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("AI Agent")
        self.resize(720, 640)

        self._history: list[dict] = []
        self._worker: Optional[_ChatWorker] = None
        self._pending_user_text: str = ""
        # Lives on the GUI thread; workers route confirmation prompts through it.
        self._confirm_helper = _ConfirmHelper(self)

        self._build_ui()
        self._restore_settings()
        self._bootstrap_knowledge_base()

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)

        setup = QtWidgets.QGroupBox("Gateway")
        sl = QtWidgets.QFormLayout()

        self.protocol_combo = QtWidgets.QComboBox()
        self.protocol_combo.addItem("Anthropic Messages API", PROTOCOL_ANTHROPIC)
        self.protocol_combo.addItem("OpenAI Chat Completions", PROTOCOL_OPENAI)
        self.protocol_combo.currentIndexChanged.connect(self._on_protocol_changed)
        sl.addRow("Protocol:", self.protocol_combo)

        self.url_edit = QtWidgets.QLineEdit()
        sl.addRow("Base URL:", self.url_edit)

        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.setToolTip(
            "Saved locally in ~/.pystream_bl32ID_settings.json "
            "(user-only file; not in any git repo)."
        )
        sl.addRow("API key:", self.key_edit)

        row = QtWidgets.QHBoxLayout()
        self.connect_btn = QtWidgets.QPushButton("Connect / refresh models")
        self.connect_btn.clicked.connect(self._refresh_models)
        row.addWidget(self.connect_btn)
        self.conn_status = QtWidgets.QLabel("not connected")
        self.conn_status.setStyleSheet("color: #888;")
        row.addWidget(self.conn_status)
        row.addStretch()
        rw = QtWidgets.QWidget()
        rw.setLayout(row)
        sl.addRow("", rw)

        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setEditable(True)
        sl.addRow("Model:", self.model_combo)
        setup.setLayout(sl)
        lay.addWidget(setup)

        # System prompt (collapsible)
        sys_box = QtWidgets.QGroupBox("System prompt (click to expand)")
        sys_box.setCheckable(True)
        sys_box.setChecked(False)
        svl = QtWidgets.QVBoxLayout()
        self.system_edit = QtWidgets.QTextEdit()
        self.system_edit.setPlainText(SYSTEM_PROMPT_DEFAULT)
        self.system_edit.setMaximumHeight(160)
        svl.addWidget(self.system_edit)
        reset_row = QtWidgets.QHBoxLayout()
        reset_row.addStretch()
        self.reset_prompt_btn = QtWidgets.QPushButton("Reset to default")
        self.reset_prompt_btn.setToolTip(
            "Replace the saved system prompt with the current built-in "
            "default. Use this after a code update changes the default "
            "guidance.")
        self.reset_prompt_btn.clicked.connect(
            lambda: self.system_edit.setPlainText(SYSTEM_PROMPT_DEFAULT))
        reset_row.addWidget(self.reset_prompt_btn)
        svl.addLayout(reset_row)
        sys_box.setLayout(svl)
        self.system_edit.setVisible(False)
        self.reset_prompt_btn.setVisible(False)
        sys_box.toggled.connect(self.system_edit.setVisible)
        sys_box.toggled.connect(self.reset_prompt_btn.setVisible)
        lay.addWidget(sys_box)

        # Chat transcript
        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        self.transcript.setStyleSheet(
            "QTextBrowser { background-color: #1e1e1e; color: #e0e0e0; "
            "font-family: 'DejaVu Sans Mono', monospace; font-size: 10pt; }"
        )
        lay.addWidget(self.transcript, stretch=1)

        # Input row
        irow = QtWidgets.QHBoxLayout()
        self.input_edit = QtWidgets.QLineEdit()
        self.input_edit.setPlaceholderText("Type a question and press Enter…")
        self.input_edit.returnPressed.connect(self._on_send)
        irow.addWidget(self.input_edit)
        self.send_btn = QtWidgets.QPushButton("Send")
        self.send_btn.clicked.connect(self._on_send)
        irow.addWidget(self.send_btn)
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.setToolTip("Clear conversation history")
        self.clear_btn.clicked.connect(self._on_clear)
        irow.addWidget(self.clear_btn)
        lay.addLayout(irow)

        # Status bar
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color: #888; font-size: 9pt;")
        lay.addWidget(self.status_label)

        self._on_protocol_changed()

    def _on_protocol_changed(self):
        proto = self._current_protocol()
        if proto == PROTOCOL_ANTHROPIC:
            self.url_edit.setPlaceholderText(
                "https://gateway.example.com (Anthropic Messages — no /v1)"
            )
        else:
            self.url_edit.setPlaceholderText(
                "https://gateway.example.com/v1 (OpenAI)"
            )

    def _current_protocol(self) -> str:
        return self.protocol_combo.currentData() or PROTOCOL_ANTHROPIC

    # ── connection / models ─────────────────────────────────────────────
    def _refresh_models(self):
        url = self.url_edit.text().strip()
        key = self.key_edit.text().strip()
        if not url or not key:
            self._set_conn_status("set URL and API key first", error=True)
            return
        proto = self._current_protocol()
        self._set_conn_status("connecting…", error=False)
        QtWidgets.QApplication.processEvents()
        try:
            ids = _list_models(proto, url, key)
        except ImportError as ex:
            self._set_conn_status(f"SDK missing: {ex}", error=True)
            return
        except Exception as ex:
            self._set_conn_status(f"{type(ex).__name__}: {ex}", error=True)
            return
        if not ids:
            self._set_conn_status("connected, but no models exposed", error=True)
            return
        prev = self.model_combo.currentText().strip()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for mid in sorted(ids):
            self.model_combo.addItem(mid)
        if prev and prev in ids:
            self.model_combo.setCurrentText(prev)
        self.model_combo.blockSignals(False)
        self._set_conn_status(f"connected — {len(ids)} models", error=False)
        self._persist_settings()

    def _set_conn_status(self, text, *, error):
        self.conn_status.setText(text)
        self.conn_status.setStyleSheet(
            "color: #c66;" if error else "color: #6a6;"
        )

    # ── chat flow ───────────────────────────────────────────────────────
    def _on_send(self):
        if self._worker is not None and self._worker.isRunning():
            return
        text = self.input_edit.text().strip()
        if not text:
            return
        url = self.url_edit.text().strip()
        key = self.key_edit.text().strip()
        model = self.model_combo.currentText().strip()
        if not (url and key and model):
            self.status_label.setText("Set URL, API key, and model first.")
            return

        self._append_transcript("user", text)
        self.input_edit.clear()
        self.send_btn.setEnabled(False)
        self.status_label.setText("…thinking")
        self._pending_user_text = text

        self._worker = _ChatWorker(
            protocol=self._current_protocol(),
            base_url=url, api_key=key, model=model,
            system_prompt=self.system_edit.toPlainText(),
            history=list(self._history),
            user_text=text,
            confirm_helper=self._confirm_helper,
        )
        self._worker.tool_event.connect(self._on_tool_event)
        self._worker.done.connect(self._on_worker_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_tool_event(self, name, args, result):
        if result is None:
            self._append_tool_call(name, args)
        else:
            self._append_tool_result(name, result)

    def _on_worker_done(self, assistant_text, usage):
        self._history.append({"role": "user", "content": self._pending_user_text})
        self._history.append({"role": "assistant", "content": assistant_text})
        self._append_transcript("assistant", assistant_text)
        cr = usage.get("cache_read", 0)
        cw = usage.get("cache_write", 0)
        cache_str = ""
        if cr:
            cache_str = f", cache hit {cr}"
        elif cw:
            cache_str = f", cache write {cw}"
        self.status_label.setText(
            f"in {usage.get('input', 0)}{cache_str}, "
            f"out {usage.get('output', 0)} tokens"
        )

    def _on_worker_error(self, msg):
        self._append_transcript("error", msg)
        self.status_label.setText("error")

    def _on_worker_finished(self):
        self.send_btn.setEnabled(True)

    def _on_clear(self):
        self._history = []
        self.transcript.clear()
        self.status_label.setText("history cleared")

    # ── transcript rendering ────────────────────────────────────────────
    def _append_transcript(self, role, text):
        text_html = self._escape(text).replace("\n", "<br>")
        if role == "user":
            html = f"<p><b style='color:#7fbf7f;'>You:</b> {text_html}</p>"
        elif role == "assistant":
            html = f"<p><b style='color:#88aaee;'>TXMBot:</b> {text_html}</p>"
        else:
            html = f"<p><b style='color:#e07070;'>Error:</b> {text_html}</p>"
        self.transcript.append(html)

    def _append_tool_call(self, name, args):
        try:
            args_str = json.dumps(args, default=str)
        except Exception:
            args_str = repr(args)
        self.transcript.append(
            f"<p style='color:#aaa; margin-left: 12px;'>"
            f"⏵ <b>{self._escape(name)}</b>({self._escape(args_str)})</p>"
        )

    def _append_tool_result(self, name, result):
        try:
            res_str = json.dumps(result, default=str)
        except Exception:
            res_str = repr(result)
        if len(res_str) > 600:
            res_str = res_str[:600] + " …"
        is_error = isinstance(result, dict) and "error" in result
        color = "#e07070" if is_error else "#777"
        self.transcript.append(
            f"<p style='color:{color}; margin-left: 24px;'>"
            f"  ↳ {self._escape(res_str)}</p>"
        )

    @staticmethod
    def _escape(text):
        return (str(text).replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;"))

    # ── settings ────────────────────────────────────────────────────────
    def _restore_settings(self):
        s = load_settings("AgentDialog")
        if not s:
            return
        proto = s.get("protocol", PROTOCOL_ANTHROPIC)
        idx = self.protocol_combo.findData(proto)
        if idx >= 0:
            self.protocol_combo.setCurrentIndex(idx)
        self.url_edit.setText(s.get("base_url", ""))
        self.key_edit.setText(s.get("api_key", ""))
        sp = s.get("system_prompt")
        if sp:
            self.system_edit.setPlainText(sp)
        last_model = s.get("model")
        if last_model:
            self.model_combo.addItem(last_model)
            self.model_combo.setCurrentText(last_model)

    def _persist_settings(self):
        save_settings("AgentDialog", {
            "protocol": self._current_protocol(),
            "base_url": self.url_edit.text(),
            "api_key": self.key_edit.text(),
            "system_prompt": self.system_edit.toPlainText(),
            "model": self.model_combo.currentText(),
        })

    # ── knowledge-base bootstrap ────────────────────────────────────────
    def _bootstrap_knowledge_base(self):
        """Create empty starter files for the user-editable knowledge base
        the first time the dialog opens. Never overwrites existing files."""
        docs_dir     = os.path.join(PYSTREAM_HOME, "docs")
        aliases_file = os.path.join(PYSTREAM_HOME, "pv_aliases.json")
        urls_file    = os.path.join(PYSTREAM_HOME, "doc_urls.json")
        ioc_file     = os.path.join(PYSTREAM_HOME, "ioc_scripts.json")
        status_file  = os.path.join(PYSTREAM_HOME, "status_pages.json")
        try:
            if not os.path.isdir(docs_dir):
                os.makedirs(docs_dir, exist_ok=True)
                readme = os.path.join(docs_dir, "README.md")
                if not os.path.isfile(readme):
                    with open(readme, "w") as f:
                        f.write(
                            "# pystream agent — local docs\n\n"
                            "Drop markdown files in this directory and the AI "
                            "plugin (TXMBot) reads them on demand via "
                            "list_docs / search_docs / read_doc. One topic per "
                            "file works best — short titles, concrete facts.\n"
                        )
            if not os.path.isfile(aliases_file):
                with open(aliases_file, "w") as f:
                    json.dump(
                        {"_comment": "friendly_name → PV ; "
                                     "EPICS macros expand $(NAME) substitutions",
                         "aliases": {},
                         "macros": {}},
                        f, indent=2,
                    )
            if not os.path.isfile(urls_file):
                with open(urls_file, "w") as f:
                    json.dump(
                        {"_comment": "friendly_name → URL ; "
                                     "agent fetches via fetch_url(url)",
                         "links": {}},
                        f, indent=2,
                    )
            if not os.path.isfile(ioc_file):
                with open(ioc_file, "w") as f:
                    json.dump(
                        {"_comment": "Allowlist of IOCs the agent may "
                                     "restart. Each entry: ioc_name → "
                                     "{path: <script>, description: <why>}. "
                                     "Empty by default — add entries to "
                                     "authorize.",
                         "scripts": {}},
                        f, indent=2,
                    )
            if not os.path.isfile(status_file):
                with open(status_file, "w") as f:
                    json.dump(
                        {"_comment": "Friendly_name → web status page "
                                     "(areaDetector status, IOC procServ "
                                     "web view, vendor status URLs). Agent "
                                     "fetches with fetch_url after looking "
                                     "the URL up via list_status_pages.",
                         "pages": {}},
                        f, indent=2,
                    )
        except Exception:
            pass  # best-effort; user can create the files themselves

    def closeEvent(self, event):
        self._persist_settings()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)
