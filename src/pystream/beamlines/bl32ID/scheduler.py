"""32-ID job scheduler: fixed beamline actions at a time, on a schedule,
when a scan ends, or when a PV meets a condition.

Only the named actions below can be scheduled (no free caput, no shell):

    b_shutter   {"state": "open" | "close"}     B-station shutter (A: never)
    helium      {"value": 0..10}                He box PLC AO1 (V)
    shaker      {"state": "start" | "stop"}     condenser shaker
    camera      {"state": "start" | "stop"}     Oryx acquisition
    tomoscan    {"state": "start" | "abort", "scan": "TomoScan" | "TomoScanStep" | "TomoScanStream"}
    wait        {"seconds": 60 | "5m"}
    wait_until  {"pv": ..., "op": "==", "value": ..., "timeout": "30m"}   (read only)

Triggers:

    {"type": "at",    "time": "02:00" | "2026-11-24 02:00" | "+30m"}
    {"type": "every", "interval": "2h", "start": <time>?, "until": <time>?, "count": N?}
    {"type": "scan_end", "scan": "XANES 2D"}          registry scan (name substring)
    {"type": "scan_end", "tomoscan": "TomoScan"}       StartScan 1 → 0
    {"type": "pv", "pv": "S:SRcurrentAI", "op": ">", "value": 100, "hold_s": 0, "edge": false}
    any: "repeat": true (pv / scan_end), "max_fires": N, "expires": <time>

Jobs: ~/.aps_agents/jobs.json (any host adds / cancels). One runner:

    python -m pystream.beamlines.bl32ID.scheduler

It holds a lease in the job file (a second runner stands by), publishes
"Job scheduler" in the agent registry, logs to ~/.aps_agents/scheduler.log.
Time triggers more than 10 min late (runner was down) are skipped as
"missed", never fired late.
"""

from __future__ import annotations

import fcntl
import json
import logging
import operator
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

DIR = os.path.expanduser("~/.aps_agents")
JOBS_FILE = os.path.join(DIR, "jobs.json")
LOCK_FILE = os.path.join(DIR, "jobs.lock")
LOG_FILE = os.path.join(DIR, "scheduler.log")

POLL_S = 1.0
LEASE_S = 30.0
MISSED_GRACE_S = 600.0
KEEP_RUNS = 20
KEEP_FINISHED_S = 7 * 86400
ACTIVE = ("pending", "running")
FINAL = ("done", "failed", "cancelled", "missed", "expired")

LOG = logging.getLogger("bl32ID.scheduler")
_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt,
        "<=": operator.le, "==": operator.eq, "!=": operator.ne}

# ── the only things a job can do ───────────────────────────────────────

B_SHUTTER_OPEN = "32idb:rshtrB:Open.PROC"
B_SHUTTER_CLOSE = "32idb:rshtrB:Close.PROC"
B_SHUTTER_CLOSED = "PB:32ID:STA_B_SBS_CLSD_PL"     # 1 = closed
HELIUM_PV = "32idbSoft:PLC1:ao1"
HELIUM_RANGE = (0.0, 10.0)
SHAKER_PV = "32idbShaker:shaker:run"
CAMERA_PV = "32idbSP1:cam1:Acquire"
TOMOSCAN_PREFIXES = {
    "TomoScan": "32id:TomoScan:",
    "TomoScanStep": "32id:TomoScanStep:",
    "TomoScanStream": "32id:TomoScanStream:",
}
ACTION_TYPES = ("b_shutter", "helium", "shaker", "camera", "tomoscan",
                "wait", "wait_until")


# ── job file ───────────────────────────────────────────────────────────

@contextmanager
def _locked():
    os.makedirs(DIR, exist_ok=True)
    with open(LOCK_FILE, "a+") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def _read() -> dict:
    try:
        with open(JOBS_FILE) as f:
            d = json.load(f)
        if isinstance(d, dict):
            d.setdefault("jobs", {})
            return d
    except FileNotFoundError:
        pass
    except Exception as ex:
        LOG.warning("jobs file unreadable (%s)", ex)
    return {"jobs": {}, "runner": None}


def _write(d: dict):
    tmp = f"{JOBS_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, default=str)
    os.replace(tmp, JOBS_FILE)


def load() -> dict:
    with _locked():
        return _read()


def modify(fn):
    with _locked():
        d = _read()
        r = fn(d)
        _write(d)
        return r


# ── times ──────────────────────────────────────────────────────────────

_DUR = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(s|sec|m|min|h|hr|d)?\s*$", re.I)


def parse_duration(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    m = _DUR.match(str(v))
    if not m:
        raise ValueError(f"bad duration {v!r} (e.g. 90, '30m', '2h')")
    return float(m.group(1)) * {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600,
                                "hr": 3600, "d": 86400}[(m.group(2) or "s").lower()]


def parse_time(v, now: float | None = None) -> float:
    now = time.time() if now is None else now
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.startswith("+"):
        return now + parse_duration(s[1:])
    if s.lower() == "now":
        return now
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(s, fmt).time()
        except ValueError:
            continue
        dt = datetime.combine(datetime.fromtimestamp(now).date(), t)
        if dt.timestamp() <= now:
            dt += timedelta(days=1)
        return dt.timestamp()
    try:
        return datetime.fromisoformat(s.replace("T", " ")).timestamp()
    except ValueError:
        raise ValueError(f"bad time {v!r} (e.g. '02:00', '+30m', '2026-11-24 02:00')")


def fmt_ts(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "-"


# ── validation ─────────────────────────────────────────────────────────

def _check_cond(d: dict, what: str):
    if not d.get("pv"):
        raise ValueError(f"{what}: 'pv' missing")
    if d.get("op", "==") not in _OPS:
        raise ValueError(f"{what}: op must be one of {sorted(_OPS)}")
    if "value" not in d:
        raise ValueError(f"{what}: 'value' missing")


def _check_action(i: int, a: dict) -> dict:
    a = dict(a)
    t = a.get("type")
    st = str(a.get("state", "")).lower()
    if t == "b_shutter":
        if st not in ("open", "close"):
            raise ValueError(f"action {i}: b_shutter state must be open or close")
    elif t == "helium":
        try:
            v = float(a.get("value"))
        except (TypeError, ValueError):
            raise ValueError(f"action {i}: helium needs a numeric value")
        lo, hi = HELIUM_RANGE
        if not lo <= v <= hi:
            raise ValueError(f"action {i}: helium value must be {lo:g}–{hi:g} V")
        a["value"] = v
    elif t in ("shaker", "camera"):
        if st not in ("start", "stop"):
            raise ValueError(f"action {i}: {t} state must be start or stop")
    elif t == "tomoscan":
        if st not in ("start", "abort"):
            raise ValueError(f"action {i}: tomoscan state must be start or abort")
        a.setdefault("scan", "TomoScan")
        if a["scan"] not in TOMOSCAN_PREFIXES:
            raise ValueError(f"action {i}: scan must be one of {sorted(TOMOSCAN_PREFIXES)}")
    elif t == "wait":
        a["seconds"] = parse_duration(a.get("seconds", 0))
    elif t == "wait_until":
        _check_cond(a, f"action {i} wait_until")
        a["timeout_s"] = parse_duration(a.get("timeout", 600))
    else:
        raise ValueError(f"action {i}: type must be one of {', '.join(ACTION_TYPES)}")
    if "state" in a:
        a["state"] = st
    return a


def normalise(trigger: dict, actions: list, now: float | None = None):
    now = time.time() if now is None else now
    if not isinstance(trigger, dict):
        raise ValueError("trigger must be an object")
    t = dict(trigger)
    typ = t.get("type")
    if typ == "at":
        t["at_ts"] = parse_time(t.get("time"), now)
        if t["at_ts"] < now - 1:
            raise ValueError(f"time {fmt_ts(t['at_ts'])} is in the past")
    elif typ == "every":
        t["interval_s"] = parse_duration(t.get("interval"))
        if t["interval_s"] < 10:
            raise ValueError("interval must be ≥ 10 s")
        t["next_ts"] = parse_time(t["start"], now) if t.get("start") else now
        if t.get("until"):
            t["until_ts"] = parse_time(t["until"], now)
    elif typ == "scan_end":
        if t.get("tomoscan"):
            if t["tomoscan"] not in TOMOSCAN_PREFIXES:
                raise ValueError(f"tomoscan must be one of {sorted(TOMOSCAN_PREFIXES)}")
        elif not t.get("scan"):
            raise ValueError("scan_end needs 'scan' (registry name) or 'tomoscan'")
        t.setdefault("states", ["done", "error"])
    elif typ == "pv":
        _check_cond(t, "pv trigger")
        t["hold_s"] = parse_duration(t.get("hold_s", 0) or 0)
    else:
        raise ValueError("trigger type must be at, every, scan_end or pv")
    if t.get("expires"):
        t["expires_ts"] = parse_time(t["expires"], now)
    if not isinstance(actions, list) or not actions:
        raise ValueError("actions must be a non-empty list")
    return t, [_check_action(i, a) for i, a in enumerate(actions, 1)]


def new_job(name: str, trigger: dict, actions: list, on_error: str = "stop") -> dict:
    t, a = normalise(trigger, actions)
    return {
        "id": uuid.uuid4().hex[:8], "name": name or "job",
        "created_ts": time.time(),
        "created_by": f"{os.environ.get('USER', '?')}@{socket.gethostname().split('.')[0]}",
        "state": "pending", "trigger": t, "actions": a,
        "on_error": on_error if on_error in ("stop", "continue") else "stop",
        "fire_count": 0, "last_fired_ts": None, "runs": [],
    }


def describe_trigger(t: dict) -> str:
    typ = t.get("type")
    if typ == "at":
        return f"at {fmt_ts(t['at_ts'])}"
    if typ == "every":
        s = f"every {t['interval_s'] / 60:g} min, next {fmt_ts(t['next_ts'])}"
        if t.get("until_ts"):
            s += f", until {fmt_ts(t['until_ts'])}"
        return s
    if typ == "scan_end":
        return f"when {t.get('scan') or t.get('tomoscan')} ends ({'/'.join(t['states'])})"
    if typ == "pv":
        s = f"when {t['pv']} {t.get('op', '==')} {t['value']}"
        return s + (f" for {t['hold_s']:g} s" if t.get("hold_s") else "")
    return str(t)


def describe_action(a: dict) -> str:
    t = a["type"]
    if t == "helium":
        return f"helium {a['value']:g} V"
    if t == "tomoscan":
        return f"{a['scan']} {a['state']}"
    if t == "wait":
        return f"wait {a['seconds']:g} s"
    if t == "wait_until":
        return f"wait until {a['pv']} {a.get('op', '==')} {a['value']}"
    label = {"b_shutter": "B shutter", "shaker": "shaker", "camera": "camera"}.get(t, t)
    return f"{label} {a.get('state', '')}".strip()


# ── EPICS ──────────────────────────────────────────────────────────────

def _epics():
    import epics
    return epics


def _compare(cur, op, want) -> bool:
    if cur is None:
        return False
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return _OPS[op](float(cur), float(want))
        except (TypeError, ValueError):
            return False
    return _OPS[op](str(cur).strip(), str(want).strip())


def cond_true(c: dict):
    want = c["value"]
    as_string = not isinstance(want, (int, float)) or isinstance(want, bool)
    cur = _epics().caget(c["pv"], as_string=as_string, timeout=2.0)
    return _compare(cur, c.get("op", "=="), want), cur


def _put(pv, value) -> bool:
    return _epics().caput(pv, value, wait=False, timeout=5.0) is not None


# ── runner ─────────────────────────────────────────────────────────────

class Runner:
    def __init__(self):
        self.me = f"{socket.gethostname().split('.')[0]}:{os.getpid()}"
        self._busy: set = set()
        self._tstate: dict = {}
        self._pub = None
        self._last_beat = 0.0

    def _take_lease(self) -> bool:
        def f(d):
            r = d.get("runner") or {}
            now = time.time()
            if r.get("id") not in (None, self.me) and now - float(r.get("ts", 0)) < LEASE_S:
                return False
            d["runner"] = {"id": self.me, "ts": now}
            return True
        return modify(f)

    def _heartbeat(self, jobs):
        now = time.time()
        if now - self._last_beat < 30:
            return
        self._last_beat = now
        try:
            if self._pub is None:
                from beamline_agent.status import AgentStatusPublisher
                self._pub = AgentStatusPublisher(name="Job scheduler", kind="agent",
                                                 ttl_s=120, parent="")
            n = sum(1 for j in jobs.values() if j.get("state") in ACTIVE)
            self._pub.activity(f"{n} job(s) waiting/running on {self.me}" if n
                               else f"idle on {self.me}")
        except Exception as ex:
            LOG.debug("heartbeat: %s", ex)

    # triggers
    def _due(self, job, now):
        t = job["trigger"]
        st = self._tstate.setdefault(job["id"], {})
        if t.get("expires_ts") and now > t["expires_ts"]:
            return "expired"
        typ = t["type"]
        if typ == "at":
            if now >= t["at_ts"]:
                return "missed" if now - t["at_ts"] > MISSED_GRACE_S else "fire"
            return None
        if typ == "every":
            if t.get("until_ts") and t["next_ts"] > t["until_ts"]:
                return "done"
            if now >= t["next_ts"]:
                if now - t["next_ts"] > MISSED_GRACE_S:
                    st["skip"] = True
                return "fire"
            return None
        if typ == "scan_end" and t.get("tomoscan"):
            ok, _ = cond_true({"pv": TOMOSCAN_PREFIXES[t["tomoscan"]] + "StartScan",
                               "op": "==", "value": 0})
            if not ok:
                st["armed"] = True            # scan running → arm
                return None
            if st.pop("armed", False):
                return "fire"
            return None
        if typ == "pv":
            ok, cur = cond_true(t)
            if "armed" not in st:
                st["armed"] = not (t.get("edge") and ok)
            if not ok:
                st.pop("since", None)
                st["armed"] = True
                return None
            if not st["armed"]:
                return None
            st.setdefault("since", now)
            if now - st["since"] >= float(t.get("hold_s", 0) or 0):
                st["armed"] = False
                st.pop("since", None)
                return "fire"
            return None
        if typ == "scan_end":
            try:
                from beamline_agent.status import load_registry
            except Exception:
                return None
            want = str(t["scan"]).lower()
            seen = st.setdefault("seen", {})
            fire = False
            for rid, rec in load_registry().items():
                if not isinstance(rec, dict) or rec.get("kind") != "scan":
                    continue
                if want not in str(rec.get("name", "")).lower():
                    continue
                state, prev = rec.get("state"), seen.get(rid)
                seen[rid] = state
                if state not in t["states"]:
                    continue
                if prev in ("starting", "running"):
                    fire = True
                elif prev is None and float(rec.get("updated_ts") or 0) >= job["created_ts"] \
                        and float(rec.get("started_ts") or 0) >= job["created_ts"] - 1:
                    fire = True               # whole scan ran between two polls
            return "fire" if fire else None
        return None

    # actions
    def _cancelled(self, jid) -> bool:
        return load()["jobs"].get(jid, {}).get("state") == "cancelled"

    def _wait_cond(self, jid, c, timeout):
        end = time.time() + float(timeout)
        cur = None
        while time.time() < end:
            ok, cur = cond_true(c)
            if ok:
                return True, cur
            if self._cancelled(jid):
                return False, "cancelled"
            time.sleep(0.5)
        return False, cur

    def _do(self, jid, a):
        t, st = a["type"], a.get("state")
        if t == "b_shutter":
            pv = B_SHUTTER_OPEN if st == "open" else B_SHUTTER_CLOSE
            if not _put(pv, 1):
                return False, f"B shutter {st}: no connection to {pv}"
            want = 0 if st == "open" else 1
            ok, cur = self._wait_cond(jid, {"pv": B_SHUTTER_CLOSED, "op": "==",
                                            "value": want}, 30)
            return ok, (f"B shutter {st}" if ok else
                        f"B shutter {st} requested, status still {cur} after 30 s")
        if t == "helium":
            ok = _put(HELIUM_PV, a["value"])
            return ok, (f"helium {a['value']:g} V" if ok else
                        f"helium: no connection to {HELIUM_PV}")
        if t in ("shaker", "camera"):
            pv = SHAKER_PV if t == "shaker" else CAMERA_PV
            ok = _put(pv, 1 if st == "start" else 0)
            return ok, (f"{t} {st}" if ok else f"{t}: no connection to {pv}")
        if t == "tomoscan":
            prefix = TOMOSCAN_PREFIXES[a["scan"]]
            pv = prefix + ("StartScan" if st == "start" else "AbortScan")
            ok = _put(pv, 1)                  # StartScan is busy: no wait
            return ok, (f"{a['scan']} {st}" if ok else f"{a['scan']}: no connection to {pv}")
        if t == "wait":
            end = time.time() + a["seconds"]
            while time.time() < end:
                if self._cancelled(jid):
                    return False, "cancelled"
                time.sleep(min(1.0, max(0.0, end - time.time())))
            return True, f"waited {a['seconds']:g} s"
        if t == "wait_until":
            ok, cur = self._wait_cond(jid, a, a["timeout_s"])
            what = f"{a['pv']} {a.get('op', '==')} {a['value']}"
            return ok, (f"{what} (is {cur})" if ok else f"timeout waiting for {what} (is {cur})")
        return False, f"unknown action {t}"

    def _execute(self, jid):
        try:
            job = load()["jobs"].get(jid)
            run = {"start_ts": time.time(), "results": [], "ok": True}
            LOG.info("FIRE %s %r", jid, job["name"])
            for i, a in enumerate(job["actions"], 1):
                if self._cancelled(jid):
                    run["results"].append("cancelled")
                    run["ok"] = False
                    break
                try:
                    ok, msg = self._do(jid, a)
                except Exception as ex:
                    ok, msg = False, f"{type(ex).__name__}: {ex}"
                LOG.info("  %s %d: %s %s", jid, i, "ok" if ok else "FAILED", msg)
                run["results"].append(f"{'ok' if ok else 'FAILED'}: {msg}")
                if not ok:
                    run["ok"] = False
                    if job.get("on_error", "stop") == "stop":
                        break
            run["end_ts"] = time.time()

            def f(d):
                j = d["jobs"].get(jid)
                if j is None:
                    return
                j["runs"] = (j.get("runs", []) + [run])[-KEEP_RUNS:]
                if j["state"] == "cancelled":
                    return
                if not run["ok"]:
                    j["state"] = "failed"
                    return
                t = j["trigger"]
                once = t["type"] == "at" or (t["type"] in ("pv", "scan_end")
                                             and not t.get("repeat"))
                maxf = t.get("max_fires") or t.get("count")
                if once or (maxf and j["fire_count"] >= int(maxf)):
                    j["state"] = "done"
                elif t["type"] == "every" and t.get("until_ts") and t["next_ts"] > t["until_ts"]:
                    j["state"] = "done"
                else:
                    j["state"] = "pending"
            modify(f)
        finally:
            self._busy.discard(jid)

    def _start(self, jid, verdict, now):
        st = self._tstate.get(jid, {})

        def f(d):
            j = d["jobs"].get(jid)
            if j is None or j["state"] != "pending":
                return False
            t = j["trigger"]
            if verdict in ("missed", "expired", "done"):
                j["state"] = verdict
                return False
            if t["type"] == "every":
                n = t["next_ts"]
                while n <= now:
                    n += t["interval_s"]
                t["next_ts"] = n
                if st.pop("skip", False):
                    j.setdefault("runs", []).append(
                        {"start_ts": now, "end_ts": now, "ok": True,
                         "results": ["skipped: late (scheduler was not running)"]})
                    return False
            j["fire_count"] = j.get("fire_count", 0) + 1
            j["last_fired_ts"] = now
            j["state"] = "running"
            return True
        if modify(f):
            self._busy.add(jid)
            threading.Thread(target=self._execute, args=(jid,), daemon=True).start()
        elif verdict in ("missed", "expired"):
            LOG.info("%s %s", jid, verdict.upper())

    def _prune(self, d):
        now = time.time()
        for jid in [k for k, j in d["jobs"].items() if j.get("state") in FINAL
                    and now - float((j.get("runs") or [{}])[-1].get("end_ts")
                                    or j.get("created_ts", now)) > KEEP_FINISHED_S]:
            del d["jobs"][jid]

    def loop(self):
        LOG.info("scheduler %s starting (jobs: %s)", self.me, JOBS_FILE)
        standby_logged, last_prune = False, 0.0
        while True:
            try:
                if not self._take_lease():
                    if not standby_logged:
                        LOG.info("another runner holds the lease — standing by")
                        standby_logged = True
                    time.sleep(10)
                    continue
                standby_logged = False
                if time.time() - last_prune > 3600:
                    modify(self._prune)
                    last_prune = time.time()
                jobs = load()["jobs"]
                self._heartbeat(jobs)
                now = time.time()
                for jid, job in jobs.items():
                    if job.get("state") != "pending" or jid in self._busy:
                        if job.get("state") in FINAL:
                            self._tstate.pop(jid, None)
                        continue
                    try:
                        verdict = self._due(job, now)
                    except Exception as ex:
                        LOG.warning("trigger of %s: %s", jid, ex)
                        continue
                    if verdict:
                        self._start(jid, verdict, now)
            except Exception as ex:
                LOG.exception("scheduler loop: %s", ex)
            time.sleep(POLL_S)


def runner_alive():
    r = load().get("runner") or {}
    return r if r and time.time() - float(r.get("ts", 0)) < LEASE_S else None


def ensure_runner() -> str:
    """Start a detached runner on this host if none is alive."""
    r = runner_alive()
    if r:
        return f"scheduler running ({r['id']})"
    os.makedirs(DIR, exist_ok=True)
    with open(LOG_FILE, "a") as log:
        subprocess.Popen([sys.executable, "-m", "pystream.beamlines.bl32ID.scheduler"],
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True, cwd=os.path.expanduser("~"))
    for _ in range(20):
        time.sleep(0.25)
        r = runner_alive()
        if r:
            return f"scheduler started ({r['id']})"
    return f"scheduler started but not alive yet — see {LOG_FILE}"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Runner().loop()


if __name__ == "__main__":
    main()
