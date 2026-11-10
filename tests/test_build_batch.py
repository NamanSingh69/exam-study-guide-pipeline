"""build.py batched atom builds (cost: one call instead of one per atom and edition).

Uses test_build.make_subject (synthetic subject in tests/_tmp/build_batch/). Checks:
  --atom notes/T01,solve/C01            both build in one call, one terse OK line each, exit 0
  --atom notes/T01,notes/T02 (T02 broken)  T02 fails on its own (its ERROR lines are printed), T01 still OK, exit 1
  --both                                 each atom is built in print AND phone; a phone-only trap
                                         (\\answer inside \\caption) fails only the [phone] build
  terse output                           no per-atom PDF/WARN/RESULT chatter; one final STATUS and RESULT line
  --render on a batch                    layout_check runs; SHEETS only for flagged pages (none here)
  a single --atom keeps its old output   (PDF line, STATUS, RESULT)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_build as tb  # noqa: E402

ROOT = HERE / "_tmp" / "build_batch"
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


work = tb.make_subject(ROOT)
B = ["build.py", "TT", "--scope", "midsem"]

rc, out, _ = tb.run(B + ["--atom", "notes/T01,solve/C01"], ROOT)
lines = out.splitlines()
check("batch: exit 0", rc == 0, out[-800:])
check("batch: one OK line per atom", sum(l.startswith("OK ") for l in lines) == 2
      and any("notes/T01" in l for l in lines if l.startswith("OK ")) and any("solve/C01" in l for l in lines if l.startswith("OK ")), out[-800:])
check("batch: terse (no per-atom PDF/WARN lines)", not any(l.startswith(("PDF ", "WARN")) for l in lines), out[-800:])
check("batch: one final STATUS and RESULT", sum(l.startswith("STATUS") for l in lines) == 1
      and lines[-1].startswith("RESULT PASS"), out[-300:])
check("batch: both PDFs exist", (work / "build" / "atom_notes_T01" / "atom_notes_T01.pdf").exists()
      and (work / "build" / "atom_solve_C01" / "atom_solve_C01.pdf").exists())

tb.write(work / "atoms" / "notes" / "T02.tex", "\\section{Broken}\\label{sec:T02}\n\\topicbadge{T01}\n\\nosuchmacro{x}\n")
rc, out, _ = tb.run(B + ["--atom", "notes/T01,notes/T02"], ROOT)
lines = out.splitlines()
check("broken: exit 1", rc == 1, out[-800:])
check("broken: T01 still OK", any(l.startswith("OK ") and "notes/T01" in l for l in lines), out[-800:])
check("broken: T02 FAIL line", any(l.startswith("FAIL") and "notes/T02" in l for l in lines), out[-800:])
check("broken: T02's error is printed", any(l.startswith("ERROR") and "nosuchmacro" in l.lower() for l in lines)
      or any("Undefined control sequence" in l for l in lines), out[-800:])
check("broken: RESULT BLOCKED names the count", lines[-1].startswith("RESULT BLOCKED") and "1 of 2" in lines[-1], lines[-1])

tb.write(work / "atoms" / "notes" / "T02.tex",
         "\\section{Phone trap}\\label{sec:T02}\n\\topicbadge{T01}\n\\begin{figure}[htbp]\\centering\\fbox{x}"
         "\\caption{The answer is \\answer{42}.}\\end{figure}\n")
rc, out, _ = tb.run(B + ["--atom", "notes/T01,notes/T02", "--both"], ROOT, timeout=1200)
lines = out.splitlines()
okl = [l for l in lines if l.startswith("OK ")]
fl = [l for l in lines if l.startswith("FAIL")]
check("both: T01 OK in print and phone", any("notes/T01" in l and "[print]" in l for l in okl)
      and any("notes/T01" in l and "[phone]" in l for l in okl), out[-1200:])
print_ok = any("notes/T02" in l and "[print]" in l for l in okl)
phone_fail = any("notes/T02" in l and "[phone]" in l for l in fl)
check("both: the caption trap fails only the phone build", print_ok and phone_fail and rc == 1, out[-1200:])
tb.rm(work / "atoms" / "notes" / "T02.tex")

rc, out, _ = tb.run(B + ["--atom", "notes/T01,solve/C01", "--render"], ROOT)
check("render batch: layout check summary", "FLAGGED 0 page(s)" in out, out[-600:])
check("render batch: no sheets when nothing is flagged", "sheet-" not in out, out[-600:])

rc, out, _ = tb.run(B + ["--atom", "notes/T01"], ROOT)
check("single atom: old output kept", rc == 0 and "PDF " in out and "RESULT PASS" in out, out[-600:])

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
