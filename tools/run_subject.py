"""Run a deterministic phase for one subject: one command for the main session instead of ~40 turns.

    py _pipeline/tools/run_subject.py <SUBJ> --scope S --phase ingest|gate|post [--dry-run] [--interactive] [--phone]

  ingest  ingest.py                                   (shared work/, both scopes)
  gate    receipts.py -> verify_pyqs.py -> score.py   (after the bank is transcribed and merged)
  post    lint_tex.py -> build guide -> flashcards.py -> web.py -> metrics.py -> layout summary
          (after the writers; --phone adds the phone edition, which the user dropped on 2026-11-10;
          --interactive adds the interactive edition)

Each step runs to its gate (exit 0 and, where the tool prints one, `RESULT PASS` / `STATUS OK`); the ledger
(state.py) gets ok/failed with a one-line note; the first failure stops the phase. The console gets at most
15 lines: one per step plus the failing step's key lines. Full output: work/<scope>/logs/run_<phase>.log.
Exit 0 all steps passed, 1 a step failed, 2 usage error.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workdir import resolve, setup_stdout  # noqa: E402

TOOLS = Path(__file__).resolve().parent


def steps(phase, subj, scope, interactive=False, phone=False):
    sc = ["--scope", scope]
    if phase == "ingest":
        return [("ingest", "all", "ingest", ["ingest.py", subj])]
    if phase == "gate":
        return [("receipts", "all", "receipts", ["receipts.py", subj] + sc),
                ("gate", "verify", "verify", ["verify_pyqs.py", subj] + sc),
                ("score", "all", "score", ["score.py", subj] + sc)]
    if phase == "post":
        s = [("lint", "all", "lint", ["lint_tex.py", subj] + sc),    # 1 s; catches traps before a 5-min build
             ("build", "guide", "build guide", ["build.py", subj] + sc)]
        if phone:   # the user dropped the phone edition (2026-11-10): only on request
            s.append(("build", "phone", "build phone", ["build.py", subj] + sc + ["--phone"]))
        if interactive:
            s.append(("build", "interactive", "build interactive", ["build.py", subj] + sc + ["--interactive"]))
        return s + [("flashcards", "all", "flashcards", ["flashcards.py", subj] + sc),
                    ("web", "all", "web", ["web.py", subj] + sc),
                    ("metrics", "all", "metrics", ["metrics.py", subj] + sc)]
    return None


def ledger(subj, scope, stage, key, status, note):
    subprocess.run([sys.executable, str(TOOLS / "state.py"), subj, "--scope", scope, "set", stage, key, status,
                    "--note", note[:200]], capture_output=True, text=True, encoding="utf-8", errors="replace")


def key_lines(out):
    keep = []
    for l in out.splitlines():
        if not l.startswith(("RESULT", "STATUS", "ERROR", "FAIL", "GATE", "PDF ", "BLOCKED", "LAYOUT")):
            continue
        m = re.match(r"GATE\s+(\S+)\s+(\S+)\s*$", l)
        if m and (m.group(2) == "0" or (m.group(1) == "pyq_gate" and m.group(2) == "1")):
            continue   # a gate that passed is noise in a failure report
        keep.append(l)
    return keep


def summary(out, rc):
    res = [l for l in out.splitlines() if l.startswith(("RESULT", "STATUS"))]
    pdf = re.search(r"\((\d+) pages\)", out)
    tail = (res[-1] if res else f"exit {rc}")
    return tail + (f"  ({pdf.group(1)} pp)" if pdf else "")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("subject")
    ap.add_argument("--scope", required=True)
    ap.add_argument("--phase", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--phone", action="store_true", help="also build the phone edition (off by default since 2026-11-10)")
    a = ap.parse_args()
    subj_dir, shared, work = resolve(a.subject, a.scope)
    plan = steps(a.phase, a.subject, work.name, a.interactive, a.phone)
    if plan is None:
        print(f"unknown phase {a.phase!r}: ingest | gate | post", file=sys.stderr)
        sys.exit(2)
    if a.dry_run:
        for _st, _k, label, cmd in plan:
            print(f"STEP {label}: py _pipeline/tools/{' '.join(cmd)}")
        sys.exit(0)
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = (logs / f"run_{a.phase}.log").open("w", encoding="utf-8")
    printed = 0
    for stage, key, label, cmd in plan:
        ledger(a.subject, work.name, stage, key, "running", "run_subject")
        t0 = time.time()
        r = subprocess.run([sys.executable, str(TOOLS / cmd[0])] + cmd[1:], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        log.write(f"===== {label}: {' '.join(cmd)}  rc={r.returncode}  {time.time() - t0:.0f}s\n{out}\n")
        log.flush()
        ok = r.returncode == 0 and not re.search(r"^RESULT BLOCKED|^STATUS\s+FAILED", out, re.M)
        note = summary(out, r.returncode)
        ledger(a.subject, work.name, stage, key, "ok" if ok else "failed", note)
        if ok:
            print(f"OK   {label:18s} {note}  [{time.time() - t0:.0f}s]")
            printed += 1
            if label == "metrics":
                for l in out.splitlines():
                    if l.startswith("     ") and re.search(r"(answers_vs_checks|over_budget_pages|iq_count_vs_target|"
                                                            r"cheatsheet_pages_vs_target)\s+\S", l) and printed < 13:
                        print("     " + l.strip())
                        printed += 1
            continue
        print(f"FAIL {label:18s} {note}")
        for l in key_lines(out)[:max(1, 13 - printed)]:
            print("  " + l[:160])
        print(f"STOPPED  full output: {logs / ('run_' + a.phase + '.log')}")
        log.close()
        sys.exit(1)
    if a.phase == "post":
        try:
            import layout_check
            for suffix in ("_Guide.pdf",) + (("_Guide_Phone.pdf",) if a.phone else ()):
                pdf = next(iter(sorted(subj_dir.glob(f"*_{work.name.capitalize()}{suffix}"))), None)
                if pdf:
                    pages = sorted({f["page"] for f in layout_check.check(pdf)})
                    print(f"LAYOUT {pdf.name}: {len(pages)} flagged page(s)"
                          + (f" (py _pipeline/tools/layout_check.py \"{pdf}\")" if pages else ""))
        except Exception as e:   # the summary is advisory
            print(f"LAYOUT summary skipped: {e}")
    log.close()
    print("RESULT PASS")


if __name__ == "__main__":
    main()
