"""
state.py: the resume ledger of a pipeline run (<SUBJ>/work/<scope>/run_state.json).

  py _pipeline/tools/state.py CN --scope midsem set <stage> <key> <status> [--note "..."]
  py _pipeline/tools/state.py CN --scope midsem show
  py _pipeline/tools/state.py CN --scope midsem next        # what to resume, in order

status: todo | running | ok | failed. Stages and keys keep the order in which they were first set (the
orchestrator registers a phase's keys as `todo` before fanning out). `next` prints every stage/key that is
not `ok`, in that order, one per line as "<stage> <key> <status>[  # note]", or "nothing to resume".

The file is rewritten atomically (temp file + os.replace) under an OS lock on run_state.json.lock (a
permanent file), so parallel agents calling `set` at the same moment neither corrupt it nor lose each other's
updates. Transient Windows refusals are retried with backoff; a write that still fails exits 1 with the
reason, and every write is read back before `set` reports success.

  {"subject": "CN", "scope": "midsem", "updated": "<iso>",
   "stages": {"<stage>": {"<key>": {"status": "ok", "note": "", "updated": "<iso>"}}}}

exit 0 = OK, 1 = the ledger is unreadable or a write failed, 2 = usage error
"""
import argparse, json, os, random, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workdir  # noqa: E402

if os.name == "nt":
    import msvcrt
else:
    import fcntl

STATUSES = ("todo", "running", "ok", "failed")
LOCK_TIMEOUT = 60.0     # seconds to wait for other writers before giving up (exit 1)
IO_TIMEOUT = float(os.environ.get("STUDYPREP_STATE_IO_TIMEOUT") or 15.0)  # retry window for transient refusals


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path_for(work):
    return work / "run_state.json"


def _retry(fn, what):
    """Run fn(), retrying PermissionError (Windows: a file being replaced or held open) with backoff.
    After IO_TIMEOUT the error is raised, never swallowed."""
    t0, delay = time.monotonic(), 0.005
    while True:
        try:
            return fn()
        except PermissionError:
            if time.monotonic() - t0 > IO_TIMEOUT:
                raise PermissionError(f"{what}: still refused after {IO_TIMEOUT:.0f} s")
            time.sleep(delay * (0.5 + random.random()))
            delay = min(delay * 2, 0.2)


def load(path, subject="", scope=""):
    if not path.exists():
        return {"subject": subject, "scope": scope, "updated": None, "stages": {}}
    data = json.loads(_retry(lambda: path.read_text("utf-8"), f"read {path}"))
    data.setdefault("stages", {})
    return data


def write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        _retry(lambda: os.replace(tmp, path), f"replace {path}")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Lock:
    """Exclusive inter-process lock: an OS byte-range lock on run_state.json.lock.

    The lock file is created once and never deleted. (Round 4 bug: an O_EXCL lock file that each holder
    deleted on exit failed on Windows. While the file is "delete pending", os.open raises PermissionError,
    not FileExistsError, so a waiting writer crashed and its update was lost.) The OS drops the lock when
    its holder exits or crashes, so there are no stale locks to break.
    """

    def __init__(self, path):
        self.path = path.with_name(path.name + ".lock")
        self.fd = None

    def _try(self):
        if os.name == "nt":
            os.lseek(self.fd, 0, os.SEEK_SET)
            msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __enter__(self):
        self.fd = _retry(lambda: os.open(self.path, os.O_RDWR | os.O_CREAT), f"open {self.path}")
        t0, delay = time.monotonic(), 0.002
        while True:
            try:
                self._try()
                return self
            except OSError:
                if time.monotonic() - t0 > LOCK_TIMEOUT:
                    os.close(self.fd)
                    raise TimeoutError(f"{self.path}: another writer held the lock for {LOCK_TIMEOUT:.0f} s")
                time.sleep(delay * (0.5 + random.random()))
                delay = min(delay * 2, 0.05)

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)


def set_status(work, subject, scope, stage, key, status, note=None):
    """Read-modify-write under the lock, then read back: a write that did not land raises (exit 1)."""
    path = path_for(work)
    with Lock(path):
        data = load(path, subject, scope)
        data["subject"], data["scope"] = subject, scope
        entry = data["stages"].setdefault(stage, {}).setdefault(key, {"status": "todo", "note": ""})
        entry["status"] = status
        if note is not None:
            entry["note"] = note
        entry["updated"] = data["updated"] = now()
        write_atomic(path, data)
        back = load(path).get("stages", {}).get(stage, {}).get(key, {})
        if back != entry:
            raise OSError(f"{path}: read-back after the write does not show {stage}/{key} = {status}")
    return data


def pending(data):
    """[(stage, key, status, note)] for everything not ok, in ledger order."""
    return [(s, k, e.get("status"), e.get("note", "")) for s, keys in data["stages"].items()
            for k, e in keys.items() if e.get("status") != "ok"]


def main():
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject")
    ap.add_argument("--scope", required=True, choices=workdir.SCOPES)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set")
    s.add_argument("stage"); s.add_argument("key"); s.add_argument("status", choices=STATUSES)
    s.add_argument("--note")
    sub.add_parser("show")
    sub.add_parser("next")
    a = ap.parse_args()
    if a.cmd == "set" and (not a.stage.strip() or not a.key.strip()):
        ap.error("stage and key must be non-empty")
    _subj, _shared, work = workdir.resolve(a.subject, a.scope, create=(a.cmd == "set"))
    path = path_for(work)
    try:
        if a.cmd == "set":
            set_status(work, a.subject, a.scope, a.stage, a.key, a.status, a.note)
            print(f"{a.stage} {a.key} {a.status}")
            return
        data = load(path, a.subject, a.scope)
    except (ValueError, OSError, TimeoutError) as e:
        print(f"cannot use {path}: {e}", file=sys.stderr)
        sys.exit(1)
    if a.cmd == "show":
        if not data["stages"]:
            print(f"no run state yet ({path})")
            return
        print(f"run state {a.subject} --scope {a.scope} (updated {data.get('updated')})")
        for st, keys in data["stages"].items():
            n_ok = sum(1 for e in keys.values() if e.get("status") == "ok")
            print(f"[{st}] {n_ok}/{len(keys)} ok")
            for k, e in keys.items():
                note = f"  # {e['note']}" if e.get("note") else ""
                print(f"  {k:28s} {e.get('status', '?'):8s} {e.get('updated', '')}{note}")
    else:
        todo = pending(data)
        if not todo:
            print("nothing to resume" if data["stages"] else f"nothing to resume (no run state yet: {path})")
        for st, k, status, note in todo:
            print(f"{st} {k} {status}" + (f"  # {note}" if note else ""))


if __name__ == "__main__":
    main()
