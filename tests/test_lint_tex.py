"""lint_tex.py: pre-build LaTeX trap lint on a synthetic subject (no TeX).

One positive and one negative case per trap: answer_in_caption, dup_newcommand, long_cell_word, banned,
printed_id (warning only). Also the CLI: LINT lines, RESULT PASS|FAIL, exit 1 on errors, 0 on warnings.
"""
import os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "lint_tex"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(PIPE / "tools"))

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
work = TMP / "TT" / "work" / "endsem"
(work / "atoms" / "solve").mkdir(parents=True)
(work / "chapters").mkdir(parents=True)


def put(rel, text):
    p = work / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")
    return p


try:
    import lint_tex
except ImportError as e:
    check("import lint_tex", False, str(e))
    sys.exit(1)


def codes(p, extra=()):
    return sorted({c for (_, _, c, _) in lint_tex.lint_files([p, *extra])})


# 1 answer_in_caption
def L(*lines):
    return "\n".join(lines) + "\n"


pos = put("atoms/cap_pos.tex", L(r"\begin{figure}", r"\caption{Result \answer{42} here}", r"\end{figure}"))
neg = put("atoms/cap_neg.tex", L(r"\begin{figure}", r"\caption{Result here}", r"\end{figure}", r"So \answer{42}."))
check("answer_in_caption positive", "answer_in_caption" in codes(pos))
check("answer_in_caption negative", "answer_in_caption" not in codes(neg))

# 2 dup_newcommand
a = put("atoms/dup_a.tex", L(r"\newcommand{\foo}{x}", r"\providecommand{\bar}{y}"))
b = put("atoms/dup_b.tex", L(r"\newcommand{\foo}{z}", r"\providecommand{\bar}{w}"))
dups = [r for r in lint_tex.lint_files([a, b]) if r[2] == "dup_newcommand"]
check("dup_newcommand positive", any("foo" in r[3] for r in dups))
check("dup_newcommand providecommand twice is fine", not any("bar" in r[3] for r in dups))

# 3 long_cell_word
def tab(cell, spec="L{42mm}X"):
    return L(r"\begin{tabularx}{\linewidth}{" + spec + "}", r"\toprule", cell + r" & note \\", r"\bottomrule",
             r"\end{tabularx}")


pos = put("atoms/cell_pos.tex", tab("Eigenvalues/eigenvectors"))
neg = put("atoms/cell_neg.tex", tab("Eigenvalues and eigenvectors"))
check("long_cell_word positive", "long_cell_word" in codes(pos))
check("long_cell_word negative (spaces)", "long_cell_word" not in codes(neg))
neg2 = put("atoms/cell_neg2.tex", L(r"\begin{tabular}{p{20mm}l}", r"CRC & ok \\", r"\end{tabular}"))
check("long_cell_word negative (short word, narrow column)", "long_cell_word" not in codes(neg2))
neg3 = put("atoms/cell_neg3.tex", tab(r"$\lambda_{1}/\lambda_{2}/\lambda_{3}/\lambda_{4}$ see \ref{sec:a/b/c/d/e/f/g/h}"))
check("long_cell_word negative (math and ref ignored)", "long_cell_word" not in codes(neg3))
neg4 = put("atoms/cell_neg4.tex", tab(r"Eigenvalues/eigen\-vectors"))
check("long_cell_word negative (discretionary hyphen)", "long_cell_word" not in codes(neg4))
neg5 = put("atoms/cell_neg5.tex", tab("Eigenvalues/eigenvectors", "XX"))
check("long_cell_word negative (X-only columns)", "long_cell_word" not in codes(neg5))

# 4 banned
pos = put("atoms/ban_pos.tex", L(r"\begin{figure}[H]", "x", r"\end{figure}", r"{\tiny small}"))
neg = put("atoms/ban_neg.tex", L(r"\begin{figure}[htbp]", "x", r"\end{figure}", r"{\footnotesize ok} \tinyfoo"))
check("banned positive", sum(1 for r in lint_tex.lint_files([pos]) if r[2] == "banned") == 2)
check("banned negative", "banned" not in codes(neg))

# 5 printed_id warning only
pos = put("atoms/id_pos.tex", L(r"Use the rule (convention \texttt{ack\_number}) here."))
neg = put("atoms/id_neg.tex", L(r"Use the acknowledgment number here. % \texttt{ack\_number}"))
check("printed_id positive", "printed_id" in codes(pos))
check("printed_id negative", "printed_id" not in codes(neg))

# CLI
env = dict(os.environ, STUDYPREP_ROOT=str(TMP))
r = subprocess.run([sys.executable, str(PIPE / "tools" / "lint_tex.py"), "TT", "--scope", "endsem"],
                   capture_output=True, text=True, encoding="utf-8", env=env)
check("cli exit 1 and RESULT FAIL on errors", r.returncode == 1 and "RESULT FAIL" in r.stdout, r.stdout[-200:])
check("cli LINT line format", "LINT work/endsem/atoms/cap_pos.tex:2 answer_in_caption" in r.stdout.replace("\\", "/"),
      r.stdout[:300])
r = subprocess.run([sys.executable, str(PIPE / "tools" / "lint_tex.py"), "TT", "--scope", "endsem",
                    "--files", str(work / "atoms" / "id_pos.tex") + "," + str(work / "atoms" / "cap_neg.tex")],
                   capture_output=True, text=True, encoding="utf-8", env=env)
check("cli warnings only: RESULT PASS exit 0", r.returncode == 0 and "RESULT PASS" in r.stdout and "printed_id" in r.stdout,
      r.stdout[-200:])

print("FAILS", fails)
sys.exit(1 if fails else 0)
