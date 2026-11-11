"""lint_tex.py: traps found by the 2026-11-11 reviews and builds (AI, IPA, DOS endsem). No TeX.

web_trap (warning)        a size switch wrapping multicols in braces ({\\small\\begin{multicols}..\\end{multicols}})
                          or \\begingroup in an atom/chapter: web.py renders paragraphs one by one and failed on both
                          (AI T45 \\begingroup: 2 render failures; AI recap chapters: fragments shown as raw text).
safe_name_label (error)   \\label{q:..} or \\pyqsolved{..} with the receipt file-safe form of a sub-part id
                          (MS2023B-2b_i_): the bank id is MS2023B-2b(i), so links dangled (4 undefined refs).
unsupported_stat (warning) an examiner statistic a writer cannot have computed ("every year since 2015",
                          "9 of the last 10 papers", "45% of the total marks"); reviewers missed planted ones in DOS
                          and AI. Not in the generated chapters 05_how_to_use and 20_exam_radar (computed from the bank).
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TMP = HERE / "_tmp" / "lint_review_traps"
sys.path.insert(0, str(HERE.parent / "tools"))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import lint_tex  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)


def codes(name, text):
    p = TMP / name
    p.write_text(text, "utf-8")
    return [r[2] for r in lint_tex.lint_files([p])]


check("brace-wrapped multicols is a web_trap",
      "web_trap" in codes("a1.tex", "{\\small\\begin{multicols}{2}\\raggedright\nx\n\\end{multicols}}\n"))
check("plain multicols with a size switch inside is fine",
      "web_trap" not in codes("a2.tex", "\\begin{multicols}{2}\\small\\raggedright\nx\n\\end{multicols}\n"))
check("\\begingroup is a web_trap", "web_trap" in codes("a3.tex", "\\begingroup\\sloppy\ntext\n\\endgroup\n"))
check("safe-name label is an error",
      "safe_name_label" in codes("b1.tex", "\\end{question}\\label{q:MS2023B-2b_i_}\n"))
check("safe-name pyqsolved is an error", "safe_name_label" in codes("b2.tex", "see \\pyqsolved{MS2022-5a_II_}.\n"))
check("bank-id label and safe-name receipt are fine",
      "safe_name_label" not in codes("b3.tex", "\\label{q:MS2022-2b(i)}\n\\receipt{MS2022-2b_i_}\n\\pyqsolved{ES2024-1b}\n"))
for i, s in enumerate(["This topic has appeared in 9 of the last 10 papers.",
                       "Examiners have asked this every year since 2016.",
                       "It carries about 45\\% of the total marks."]):
    check(f"unsupported statistic warned: {s[:30]}", "unsupported_stat" in codes(f"c{i}.tex", s + "\n"))
check("a sourced count from the bank is not warned",
      "unsupported_stat" not in codes("c9.tex", "Asked in ES2024 and ES2025 (2 of the 4 banked papers).\n"))
thead = ("\\begin{tabularx}{\\linewidth}{L{11mm}YYL{40mm}}\\toprule\n"
         "\\thead{} & \\thead{Advantages} & \\thead{Disadvantages} & \\thead{Fault: identify /\\\\tolerance / isolation}\\\\\n"
         "Mesh & a & b & c\\\\\n\\end{tabularx}\n")
check("a \\\\ inside \\thead{} is not a row end (CN T05 false positive)", "long_cell_word" not in codes("d1.tex", thead))
real = "\\begin{tabular}{L{11mm}l}\nEigenvalues/eigenvectors & x\\\\\n\\end{tabular}\n"
check("a real long word in a narrow first column is still caught", "long_cell_word" in codes("d2.tex", real))
(TMP / "chapters").mkdir()
check("generated exam radar is exempt",
      "unsupported_stat" not in codes("chapters/20_exam_radar.tex", "about 45\\% of the total marks\n"))
check("unsupported_stat and web_trap are warnings, not errors",
      not ({"unsupported_stat", "web_trap"} & lint_tex.ERRORS))   # 10 passing guides fall back to images for these
check("safe_name_label is an error", "safe_name_label" in lint_tex.ERRORS)

shutil.rmtree(TMP, ignore_errors=True)
print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
