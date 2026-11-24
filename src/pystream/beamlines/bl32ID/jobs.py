"""Jobs window: the scheduled beamline jobs (scheduler.py) — list, run
history, cancel, and a form to add a job without the AI agent."""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from . import scheduler as sch

_SCANS = ["XANES 2D", "XANES 1D", "2D Time Series", "DataMap", "energy scan"]

# label → (action dict, value field: None | "helium" | "wait")
_ACTIONS = {
    "B shutter open":  ({"type": "b_shutter", "state": "open"}, None),
    "B shutter close": ({"type": "b_shutter", "state": "close"}, None),
    "Helium (V)":      ({"type": "helium"}, "helium"),
    "Shaker start":    ({"type": "shaker", "state": "start"}, None),
    "Shaker stop":     ({"type": "shaker", "state": "stop"}, None),
    "Camera start":    ({"type": "camera", "state": "start"}, None),
    "Camera stop":     ({"type": "camera", "state": "stop"}, None),
    "TomoScan start":  ({"type": "tomoscan", "state": "start", "scan": "TomoScan"}, None),
    "TomoScan abort":  ({"type": "tomoscan", "state": "abort", "scan": "TomoScan"}, None),
    "Wait (s)":        ({"type": "wait"}, "wait"),
}


class NewJobDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New job")
        self.actions: list[dict] = []
        form = QtWidgets.QFormLayout(self)

        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("e.g. close B shutter after XANES")
        form.addRow("Name:", self.name)

        self.trig = QtWidgets.QComboBox()
        self.trig.addItems(["At a time", "Every …", "When a scan ends", "When a PV condition holds"])
        form.addRow("When:", self.trig)

        self.stack = QtWidgets.QStackedWidget()
        # at
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w); f.setContentsMargins(0, 0, 0, 0)
        self.at_time = QtWidgets.QLineEdit()
        self.at_time.setPlaceholderText("02:00  or  2026-11-24 02:00  or  +30m")
        f.addRow("Time:", self.at_time)
        self.stack.addWidget(w)
        # every
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w); f.setContentsMargins(0, 0, 0, 0)
        self.ev_interval = QtWidgets.QLineEdit("1h")
        self.ev_start = QtWidgets.QLineEdit(); self.ev_start.setPlaceholderText("now")
        self.ev_until = QtWidgets.QLineEdit(); self.ev_until.setPlaceholderText("(no end)")
        self.ev_count = QtWidgets.QSpinBox(); self.ev_count.setRange(0, 100000)
        self.ev_count.setSpecialValueText("unlimited")
        f.addRow("Interval:", self.ev_interval); f.addRow("First at:", self.ev_start)
        f.addRow("Until:", self.ev_until); f.addRow("Times:", self.ev_count)
        self.stack.addWidget(w)
        # scan end
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w); f.setContentsMargins(0, 0, 0, 0)
        self.scan = QtWidgets.QComboBox()
        self.scan.addItems(_SCANS + sorted(sch.TOMOSCAN_PREFIXES))
        self.scan.setEditable(True)
        self.scan_err = QtWidgets.QCheckBox("also when it ends with an error")
        self.scan_err.setChecked(True)
        f.addRow("Scan:", self.scan); f.addRow("", self.scan_err)
        self.stack.addWidget(w)
        # pv
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w); f.setContentsMargins(0, 0, 0, 0)
        self.pv = QtWidgets.QLineEdit(); self.pv.setPlaceholderText("S:SRcurrentAI")
        self.pv_op = QtWidgets.QComboBox(); self.pv_op.addItems([">", ">=", "<", "<=", "==", "!="])
        self.pv_val = QtWidgets.QLineEdit(); self.pv_val.setPlaceholderText("100")
        self.pv_hold = QtWidgets.QLineEdit("0"); self.pv_hold.setToolTip("seconds the condition must hold")
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.pv_op); row.addWidget(self.pv_val)
        f.addRow("PV:", self.pv); f.addRow("Condition:", row); f.addRow("Held for (s):", self.pv_hold)
        self.stack.addWidget(w)
        self.trig.currentIndexChanged.connect(self.stack.setCurrentIndex)
        form.addRow(self.stack)

        self.repeat = QtWidgets.QCheckBox("Repeat (scan end / PV: every time it happens)")
        form.addRow("", self.repeat)

        # actions
        self.act_list = QtWidgets.QListWidget()
        self.act_list.setMaximumHeight(130)
        form.addRow("Do:", self.act_list)
        row = QtWidgets.QHBoxLayout()
        self.act_kind = QtWidgets.QComboBox(); self.act_kind.addItems(list(_ACTIONS))
        self.act_val = QtWidgets.QDoubleSpinBox(); self.act_val.setRange(0, 86400)
        self.act_val.setDecimals(2)
        add = QtWidgets.QPushButton("Add"); rem = QtWidgets.QPushButton("Remove")
        row.addWidget(self.act_kind, 1); row.addWidget(self.act_val)
        row.addWidget(add); row.addWidget(rem)
        form.addRow("", row)
        self.act_kind.currentTextChanged.connect(self._kind_changed)
        self._kind_changed(self.act_kind.currentText())
        add.clicked.connect(self._add_action)
        rem.clicked.connect(self._remove_action)

        self.on_err = QtWidgets.QCheckBox("Continue with the next action if one fails")
        form.addRow("", self.on_err)

        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Schedule")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.job = None

    def _kind_changed(self, label):
        kind = _ACTIONS[label][1]
        self.act_val.setVisible(kind is not None)
        if kind == "helium":
            self.act_val.setRange(*sch.HELIUM_RANGE); self.act_val.setSuffix(" V")
        elif kind == "wait":
            self.act_val.setRange(0, 86400); self.act_val.setSuffix(" s")

    def _add_action(self):
        label = self.act_kind.currentText()
        a, kind = _ACTIONS[label]
        a = dict(a)
        if kind == "helium":
            a["value"] = self.act_val.value()
        elif kind == "wait":
            a["seconds"] = self.act_val.value()
        self.actions.append(a)
        self.act_list.addItem(sch.describe_action(sch._check_action(0, a)))

    def _remove_action(self):
        r = self.act_list.currentRow()
        if r >= 0:
            self.act_list.takeItem(r)
            del self.actions[r]

    def _trigger(self) -> dict:
        i = self.trig.currentIndex()
        if i == 0:
            t = {"type": "at", "time": self.at_time.text().strip()}
        elif i == 1:
            t = {"type": "every", "interval": self.ev_interval.text().strip()}
            if self.ev_start.text().strip():
                t["start"] = self.ev_start.text().strip()
            if self.ev_until.text().strip():
                t["until"] = self.ev_until.text().strip()
            if self.ev_count.value():
                t["count"] = self.ev_count.value()
        elif i == 2:
            name = self.scan.currentText().strip()
            t = ({"type": "scan_end", "tomoscan": name} if name in sch.TOMOSCAN_PREFIXES
                 else {"type": "scan_end", "scan": name,
                       "states": ["done", "error"] if self.scan_err.isChecked() else ["done"]})
        else:
            v = self.pv_val.text().strip()
            try:
                v = float(v)
            except ValueError:
                pass
            t = {"type": "pv", "pv": self.pv.text().strip(), "op": self.pv_op.currentText(),
                 "value": v, "hold_s": self.pv_hold.text().strip() or 0}
        if self.repeat.isChecked() and t["type"] in ("pv", "scan_end"):
            t["repeat"] = True
        return t

    def _ok(self):
        try:
            self.job = sch.new_job(self.name.text().strip() or "job", self._trigger(),
                                   self.actions,
                                   "continue" if self.on_err.isChecked() else "stop")
        except ValueError as ex:
            QtWidgets.QMessageBox.warning(self, "Cannot schedule", str(ex))
            return
        self.accept()


class JobsDialog(QtWidgets.QDialog):
    BUTTON_TEXT = "Jobs"
    GROUP = "Scans"
    HANDLER_TYPE = "singleton"

    COLS = ["ID", "Name", "State", "When", "Do", "Fired", "Last run"]

    def __init__(self, parent=None, logger=None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Scheduled jobs")
        self.resize(1000, 560)
        v = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.start_btn = QtWidgets.QPushButton("Start scheduler")
        self.start_btn.setToolTip("Start the scheduler process on this computer "
                                  "(it keeps running after pystream closes)")
        self.start_btn.clicked.connect(self._start_runner)
        self.show_finished = QtWidgets.QCheckBox("Show finished")
        self.show_finished.toggled.connect(self.refresh)
        top.addWidget(self.status, 1); top.addWidget(self.show_finished)
        top.addWidget(self.start_btn)
        v.addLayout(top)

        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.table = QtWidgets.QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show_details)
        split.addWidget(self.table)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        split.addWidget(self.details)
        split.setSizes([360, 160])
        v.addWidget(split, 1)

        btns = QtWidgets.QHBoxLayout()
        new = QtWidgets.QPushButton("New job…"); new.clicked.connect(self._new)
        self.cancel_btn = QtWidgets.QPushButton("Cancel job")
        self.cancel_btn.clicked.connect(self._cancel)
        clear = QtWidgets.QPushButton("Clear finished")
        clear.setToolTip("Remove done / failed / cancelled / missed jobs from the list")
        clear.clicked.connect(self._clear_finished)
        btns.addWidget(new); btns.addWidget(self.cancel_btn); btns.addStretch()
        btns.addWidget(clear)
        v.addLayout(btns)

        self._jobs: dict = {}
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    # ── data ──
    def refresh(self):
        try:
            data = sch.load()
        except Exception as ex:
            self.status.setText(f"Cannot read {sch.JOBS_FILE}: {ex}")
            return
        r = data.get("runner") or {}
        import time
        alive = r and time.time() - float(r.get("ts", 0)) < sch.LEASE_S
        self.status.setText(f"Scheduler: running ({r['id']})" if alive else
                            "Scheduler: NOT running — jobs will not fire")
        self.status.setStyleSheet("" if alive else "color: #d62728; font-weight: bold;")
        self.start_btn.setEnabled(not alive)

        jobs = data["jobs"]
        self._jobs = jobs
        rows = [j for j in sorted(jobs.values(), key=lambda j: j.get("created_ts", 0))
                if self.show_finished.isChecked() or j.get("state") in sch.ACTIVE]
        sel = self._selected_id()
        self.table.setRowCount(len(rows))
        for i, j in enumerate(rows):
            last = (j.get("runs") or [None])[-1]
            last_txt = "" if not last else (
                f"{sch.fmt_ts(last.get('start_ts'))[11:]} "
                f"{'ok' if last.get('ok') else 'FAILED'}")
            vals = [j["id"], j["name"], j["state"], sch.describe_trigger(j["trigger"]),
                    " → ".join(sch.describe_action(a) for a in j["actions"]),
                    str(j.get("fire_count", 0)), last_txt]
            for c, val in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(val)
                if c == 2 and j["state"] in ("failed", "missed", "expired"):
                    it.setForeground(QtCore.Qt.red)
                self.table.setItem(i, c, it)
            if j["id"] == sel:
                self.table.selectRow(i)
        self._show_details()

    def _selected_id(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.text() if it else None

    def _show_details(self):
        j = self._jobs.get(self._selected_id() or "")
        self.cancel_btn.setEnabled(bool(j) and j.get("state") in sch.ACTIVE)
        if not j:
            self.details.setPlainText("")
            return
        lines = [f"{j['name']}  [{j['id']}]  {j['state']}  — created "
                 f"{sch.fmt_ts(j.get('created_ts'))} by {j.get('created_by')}",
                 f"When: {sch.describe_trigger(j['trigger'])}",
                 "Do:   " + " → ".join(sch.describe_action(a) for a in j["actions"]),
                 f"If an action fails: {j.get('on_error', 'stop')}", ""]
        for r in reversed(j.get("runs") or []):
            lines.append(f"{sch.fmt_ts(r.get('start_ts'))}  "
                         f"{'ok' if r.get('ok') else 'FAILED'}")
            lines += [f"    {x}" for x in r.get("results") or []]
        text = "\n".join(lines)
        if text != self.details.toPlainText():
            self.details.setPlainText(text)

    # ── actions ──
    def _start_runner(self):
        self.status.setText(sch.ensure_runner())

    def _new(self):
        d = NewJobDialog(self)
        if d.exec_() == QtWidgets.QDialog.Accepted and d.job:
            job = d.job
            sch.modify(lambda data: data["jobs"].__setitem__(job["id"], job))
            msg = sch.ensure_runner()
            if self.logger:
                self.logger.info(f"Job {job['id']} scheduled: {job['name']} ({msg})")
            self.refresh()

    def _cancel(self):
        jid = self._selected_id()
        j = self._jobs.get(jid or "")
        if not j:
            return
        if QtWidgets.QMessageBox.question(
                self, "Cancel job", f"Cancel '{j['name']}' ({jid})?") \
                != QtWidgets.QMessageBox.Yes:
            return

        def f(data):
            jj = data["jobs"].get(jid)
            if jj and jj["state"] in sch.ACTIVE:
                jj["state"] = "cancelled"
        sch.modify(f)
        self.refresh()

    def _clear_finished(self):
        def f(data):
            for k in [k for k, j in data["jobs"].items() if j.get("state") in sch.FINAL]:
                del data["jobs"][k]
        sch.modify(f)
        self.refresh()
