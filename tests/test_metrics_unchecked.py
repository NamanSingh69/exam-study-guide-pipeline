"""metrics.py numbers_without_checks (tracked, not a hard gate), on a synthetic work folder (no TeX).

numbers_without_checks  every \\answer{} box holding a printed number that no check script backs, as "file:line ...".
                        A box maps to its check by the nearest preceding \\label{q:<qid>} (checks/<qid>.py), else by the
                        atom file stem (atoms/solve/<Cid>.tex -> checks/<Cid>.py or checks/<Cid>_*.py).

Split with answers_vs_checks: that metric needs a check that EXISTS and compares what it prints with the box (case d:
the check runs but prints another number -> only answers_vs_checks reports it). numbers_without_checks reports the
case where NO check backs the box (case b). A box is never in both.
"""
import shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
sys.path.insert(0, str(PIPE / "tools"))
TMP = HERE / "_tmp" / "metrics_unchecked"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import metrics  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
work = TMP / "TT" / "work" / "midsem"
(work / "chapters").mkdir(parents=True)
(work / "atoms" / "solve").mkdir(parents=True)
(work / "checks").mkdir()
for n in ("MS2022-1a", "MS2022-4a"):
    (work / "checks" / (n + ".py")).write_text("print(1)\n", "utf-8")
names = {"MS2022-1a", "MS2022-4a"}

(work / "chapters" / "700_pyq.tex").write_text(
    "\\begin{question}{2022 Q1(a)}{2}\nMargin?\n\\end{question}\\label{q:MS2022-1a}\n"            # 1-3
    "\\begin{solution}\\answer{0.25}\\end{solution}\n"                                           # 4   (a) checked
    "\\begin{question}{2022 Q2(a)}{2}\nKernel?\n\\end{question}\\label{q:MS2022-2a}\n"           # 5-7
    "\\begin{solution}Value \\answer{$K=36$}.\\end{solution}\n"                                  # 8   (b) no check file
    "\\begin{question}{2022 Q3(a)}{1}\nType?\n\\end{question}\\label{q:MS2022-3a}\n"             # 9-11
    "\\begin{solution}\\answer{Unsupervised Learning}\\end{solution}\n"                          # 12  (c) no digits
    "\\begin{question}{2022 Q4(a)}{1}\nCount?\n\\end{question}\\label{q:MS2022-4a}\n"            # 13-15
    "\\begin{solution}\\answer{7}\\end{solution}\n"                                              # 16  (d) check prints 1
    "\\begin{question}{2022 Q5(a)}{1}\nPick?\n\\end{question}\\label{q:MS2022-5a}\n"             # 17-19
    "\\begin{solution}\\answer{(iii) Reinforcement Learning}\\end{solution}\n"                   # 20  (e) option label
    "\\begin{solution}\\answer{Q5 of the Paper 2024 (MS2022-5a)}\\end{solution}\n", "utf-8")     # 21  (e) Q5, year, qid

(work / "atoms" / "solve" / "C07.tex").write_text(
    "\\begin{solvedidea}{C07}{Margin}\n\\answer{2.5}\n\\end{solvedidea}\n", "utf-8")             # no checks/C07*.py: counted
(work / "atoms" / "solve" / "C08.tex").write_text(
    "\\begin{solvedidea}{C08}{Margin}\n\\answer{4}\n\\end{solvedidea}\n", "utf-8")               # checks/C08_variant.py: not counted
(work / "checks" / "C08_variant.py").write_text("print(4)\n", "utf-8")
names.add("C08_variant")

# real-subject noise seen on ML/CN (2026-11-10): formula reminders in the cheatsheet, matching answers "1--x",
# and important-question boxes under \label{iq:<Cid>} (backed by checks/<Cid>*.py), plus mock/drill boxes
(work / "chapters" / "cheatsheet.tex").write_text("\\answer{margin $2/\\|W\\|$}\n", "utf-8")
(work / "chapters" / "60_important_questions.tex").write_text(
    "\\subsection*{Margin}\\label{iq:C08}\n\\answer{4}\n"                                        # 2 backed by C08_variant
    "\\subsection*{Match}\\label{iq:C09}\n\\answer{1--x, 2--ix, 3--i}\n", "utf-8")              # 4 matching: no number
(work / "chapters" / "80_mock.tex").write_text("\\answer{12}\n", "utf-8")                       # backed by mock_Q1
(work / "checks" / "mock_Q1.py").write_text("print(12)\n", "utf-8")
names.add("mock_Q1")

try:
    bad = metrics.numbers_without_checks(work, names)
except AttributeError:
    bad = None
check("unchecked: the function exists", bad is not None)
bad = bad or []
text = " | ".join(bad)
check("unchecked: (a) boxed number with a check is not counted", not any("700_pyq.tex:4" in b for b in bad), bad)
check("unchecked: (b) missing check is counted with file:line",
      any(b.startswith("chapters/700_pyq.tex:8") and "MS2022-2a" in b for b in bad), bad)
check("unchecked: (c) box without digits is not counted", not any("700_pyq.tex:12" in b for b in bad), bad)
check("unchecked: (d) check exists but prints another number: not this metric",
      not any("700_pyq.tex:16" in b for b in bad), bad)
check("unchecked: (e) option label is not counted", not any("700_pyq.tex:20" in b for b in bad), bad)
check("unchecked: (e) Q5 / paper year / qid are not counted", not any("700_pyq.tex:21" in b for b in bad), bad)
check("unchecked: atom box with no checks/<Cid>*.py is counted", any("atoms/solve/C07.tex:2" in b for b in bad), bad)
check("unchecked: atom box backed by <Cid>_variant is not counted", not any("C08.tex" in b for b in bad), bad)
check("unchecked: cheatsheet formula reminders are not counted", not any("cheatsheet" in b for b in bad), bad)
check("unchecked: iq:<Cid> box backed by <Cid>_* is not counted", not any("60_important_questions.tex:2" in b for b in bad), bad)
check("unchecked: matching answer '1--x' is not counted", not any("60_important_questions.tex:4" in b for b in bad), bad)
check("unchecked: mock box backed by mock_Q* is not counted", not any("80_mock" in b for b in bad), bad)
check("unchecked: exactly two", len(bad) == 2, bad)
# the other metric still owns case (d)
mism = metrics.answers_vs_checks(work, {"MS2022-4a": "1\n"})
check("unchecked: (d) is reported by answers_vs_checks", any("MS2022-4a" in b for b in mism), mism)
check("unchecked: tracked, not a hard gate", "numbers_without_checks" not in metrics.HARD_GATES)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
