"""run_subject.py: one command per phase for the main session, with ledger updates and <= 15 lines of output.

Synthetic subject in tests/_tmp/run_subject/ (STUDYPREP_ROOT), no TeX needed:
  --phase gate on a work folder without a bank   receipts is the first step and fails -> later steps never run,
                                                  ledger: receipts all = failed with a note, exit 1
  --dry-run                                       lists the steps of a phase, runs nothing, exit 0
  output                                          at most 15 lines; the full output goes to work/<scope>/logs/
  unknown phase                                   exit 2
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "run_subject"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({str(detail)[:600]})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
work = TMP / "TT" / "work" / "endsem"
work.mkdir(parents=True)
(TMP / "TT" / "work" / "manifest.json").write_text(json.dumps({"files": {}, "health": {"errors": 0}}), "utf-8")
env = dict(os.environ, STUDYPREP_ROOT=str(TMP), PYTHONIOENCODING="utf-8")


def run(*args):
    r = subprocess.run([sys.executable, str(PIPE / "tools" / "run_subject.py"), "TT", "--scope", "endsem", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=600)
    return r.returncode, r.stdout + r.stderr


rc, out = run("--phase", "gate", "--dry-run")
check("dry-run: exit 0", rc == 0, out)
check("dry-run: lists receipts, verify, score in order",
      out.find("receipts") < out.find("verify") < out.find("score") and out.find("receipts") >= 0, out)
check("dry-run: nothing ran (no ledger)", not (work / "run_state.json").exists())

rc, out = run("--phase", "gate")
check("gate without a bank: exit 1", rc == 1, out)
check("gate: stops at the first failed step", "FAIL" in out and "score" not in out.split("FAIL", 1)[1].split("\n", 1)[1], out)
check("gate: at most 15 lines", len(out.strip().splitlines()) <= 15, len(out.strip().splitlines()))
st = json.loads((work / "run_state.json").read_text("utf-8")) if (work / "run_state.json").exists() else {}
rec = st.get("stages", {}).get("receipts", {}).get("all", {})
check("gate: ledger receipts all = failed with a note", rec.get("status") == "failed" and rec.get("note"), rec)
check("gate: score never ran", "score" not in st.get("stages", {}), st.get("stages", {}).keys())
logs = list((work / "logs").glob("run_gate*.log")) if (work / "logs").exists() else []
check("gate: full log written", bool(logs) and "receipts" in logs[0].read_text("utf-8"), logs)

rc, out = run("--phase", "post", "--dry-run")
check("post dry-run: guide, flashcards, web, metrics",
      all(s in out for s in ("guide", "flashcards", "web", "metrics")), out)
# the user dropped the phone edition (2026-11-10): it is built only on request
check("post dry-run: no phone build by default", "--phone" not in out, out)
check("post dry-run: lint_tex runs first", out.strip().splitlines()[0].startswith("STEP lint") and "lint_tex.py" in out, out)
rc, out = run("--phase", "post", "--dry-run", "--phone")
check("post dry-run --phone: the phone build is added", "build phone" in out and "--phone" in out, out)

sys.path.insert(0, str(PIPE / "tools"))
import run_subject  # noqa: E402
sample = ("GATE tex_errors                   0\nGATE internal_leaks              26\nGATE pyq_gate                     1\n"
          "     over_budget_pages            3\nRESULT BLOCKED: internal_leaks=26\n")
kl = run_subject.key_lines(sample)
check("failure lines: only failing gates and the RESULT (real CN 2026-11-10 listed 9 passing gates)",
      kl == ["GATE internal_leaks              26", "RESULT BLOCKED: internal_leaks=26"], kl)

rc, out = run("--phase", "nope")
check("unknown phase: exit 2", rc == 2, out)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
