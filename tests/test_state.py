"""state.py: set/show/next, order, validation, atomic writes and parallel writers (tests/_tmp/state/)."""
import json, os, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "state"
TOOL = str(PIPE / "tools" / "state.py")
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
(TMP / "CN" / "work").mkdir(parents=True)
env = dict(os.environ, STUDYPREP_ROOT=str(TMP))
LEDGER = TMP / "CN" / "work" / "midsem" / "run_state.json"


def st(*args, scope="midsem"):
    cmd = [sys.executable, TOOL, "CN"] + (["--scope", scope] if scope else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


r = st("next")
check("next with no ledger", r.returncode == 0 and "nothing to resume" in r.stdout, r.stdout.strip())
for key in ("U1", "U2", "U3"):
    st("set", "units", key, "todo")
st("set", "ingest", "-", "ok")
st("set", "units", "U1", "ok")
st("set", "units", "U2", "failed", "--note", "Float too large p12")
st("set", "pyq", "MS2024", "running")
check("ledger file written", LEDGER.exists())
data = json.loads(LEDGER.read_text("utf-8"))
check("statuses stored", data["stages"]["units"]["U2"] == {**data["stages"]["units"]["U2"], "status": "failed",
                                                             "note": "Float too large p12"})
r = st("next")
lines = r.stdout.strip().splitlines()
check("next lists what is not ok, in first-set order", lines == [
    "units U2 failed  # Float too large p12", "units U3 todo", "pyq MS2024 running"], str(lines))
st("set", "units", "U2", "ok")
check("note kept when status changes without --note", json.loads(LEDGER.read_text("utf-8"))["stages"]["units"]["U2"]["note"]
      == "Float too large p12")
r = st("show")
check("show prints stages with counts", r.returncode == 0 and "[units] 3/3 ok" not in r.stdout and "[units] 2/3 ok" in r.stdout,
      r.stdout.splitlines()[1:3])
check("bad status is a usage error", st("set", "units", "U1", "done").returncode == 2)
check("missing --scope is a usage error", st("next", scope=None).returncode == 2)
check("bad scope is a usage error", st("next", scope="final").returncode == 2)
check("empty key is a usage error", st("set", "units", " ", "ok").returncode == 2)

# parallel writers: 48 concurrent sets x 3 rounds must all land, with exit 0, and the file must stay valid
# JSON throughout. Readers (`next`) run at the same time: an open reader must not make a write fail.
WRITERS, ROUNDS = 48, 3
for rnd in range(ROUNDS):
    stage = f"atoms{rnd}"
    with ThreadPoolExecutor(WRITERS + 4) as ex:
        futs = [ex.submit(st, "set", stage, f"T{i:02d}", "ok", "--note", f"w{i}") for i in range(WRITERS)]
        readers = [ex.submit(st, "next") for _ in range(4)]
        rs = [f.result() for f in futs]
        rd = [f.result() for f in readers]
    data = json.loads(LEDGER.read_text("utf-8"))
    got = data["stages"].get(stage, {})
    bad = [r for r in rs if r.returncode != 0]
    check(f"parallel sets all recorded (round {rnd + 1}: {WRITERS} writers + 4 readers)",
          not bad and len(got) == WRITERS and all(got[f"T{i:02d}"]["note"] == f"w{i}" for i in range(WRITERS) if f"T{i:02d}" in got)
          and all(r.returncode == 0 for r in rd),
          f"{len(got)}/{WRITERS} recorded, {len(bad)} writer(s) exit!=0"
          + (": " + " | ".join(r.stderr.strip()[-200:] for r in bad[:3]) if bad else "")
          + ("; reader failed: " + " | ".join(r.stderr.strip()[-200:] for r in rd if r.returncode) if any(r.returncode for r in rd) else ""))
# the lock file is permanent by design (deleting it was the Round 4 race); temp files must never be left
check("no temp files left (only the ledger and its permanent lock file)",
      sorted(p.name for p in LEDGER.parent.iterdir()) == ["run_state.json", "run_state.json.lock"],
      str(sorted(p.name for p in LEDGER.parent.iterdir())))

# exclusivity: while another process holds the lock, a writer waits and then lands
HOLD = (f"import sys, time; sys.path.insert(0, {str(PIPE / 'tools')!r}); import state; from pathlib import Path\n"
        f"l = state.Lock(Path({str(LEDGER)!r})); l.__enter__(); print('held', flush=True); time.sleep(float(sys.argv[1]))\n"
        f"l.__exit__(None, None, None)\n")
import time
h = subprocess.Popen([sys.executable, "-c", HOLD, "2.0"], stdout=subprocess.PIPE, text=True)
h.stdout.readline()
t0 = time.time()
r = st("set", "excl", "k", "ok")
waited = time.time() - t0
h.wait()
check("a held lock makes the writer wait, then the write lands",
      r.returncode == 0 and waited >= 1.5 and json.loads(LEDGER.read_text("utf-8"))["stages"]["excl"]["k"]["status"] == "ok",
      f"waited {waited:.1f}s rc={r.returncode}")
# a holder that dies leaves no stale lock
h = subprocess.Popen([sys.executable, "-c", HOLD, "60"], stdout=subprocess.PIPE, text=True)
h.stdout.readline()
h.kill(); h.wait()
t0 = time.time()
r = st("set", "excl", "after_crash", "ok")
check("a crashed lock holder does not block the next writer", r.returncode == 0 and time.time() - t0 < 10,
      f"{time.time() - t0:.1f}s rc={r.returncode}")

# a write that cannot land fails loudly (exit 1), it is never reported as done
os.chmod(LEDGER, 0o444)
env_fast = dict(env, STUDYPREP_STATE_IO_TIMEOUT="1")
r = subprocess.run([sys.executable, TOOL, "CN", "--scope", "midsem", "set", "ro", "k", "ok"], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", env=env_fast)
os.chmod(LEDGER, 0o666)
check("an unwritable ledger makes set exit 1 with the reason", r.returncode == 1 and "run_state.json" in r.stderr
      and "ro" not in json.loads(LEDGER.read_text("utf-8"))["stages"], f"rc={r.returncode} {r.stderr.strip()[-120:]}")
check("no temp file left after the failed write",
      sorted(p.name for p in LEDGER.parent.iterdir()) == ["run_state.json", "run_state.json.lock"])

# corrupt ledger: reported, not silently reset
LEDGER.write_text("{not json", "utf-8")
r = st("next")
check("unreadable ledger exits 1", r.returncode == 1, f"rc={r.returncode}")

shutil.rmtree(TMP, ignore_errors=True)
print("OK test_state" if not fails else f"FAIL test_state: {fails} check(s)")
sys.exit(1 if fails else 0)
