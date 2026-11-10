"""studyguide.sty: an inline \\answer{..} box never runs into the margin in the PRINT edition (ML endsem, 2026-11-10).

The guide build stopped on 6 overfull lines such as
  "\\seesolved{C25}. \\answer{Stochastic Gradient Descent (SGD)}"
TeX kept the box on the line (41 pt into the margin) because breaking before it left a line too loose for the
justified print page. The phone edition already had a painless break before the box; the print edition did not.
The test sets one realistic sentence before an answer box with every lead length from 0 to 40 words, compiles
print and phone, and requires zero "Overfull \\hbox" lines from those paragraphs.
Needs pdflatex (MiKTeX or TeX Live); about 10 s.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LATEX = HERE.parent / "latex"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

WORDS = ("the model is fitted with gradient descent on the full batch while the online variant updates after "
         "every single example which makes each step cheaper but noisier so the learning rate must be "
         "smaller and decay slowly over the epochs to converge").split()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


def doc(opts):
    paras = []
    for k in range(0, 41):
        lead = " ".join(WORDS[:k])
        paras.append(lead + r" {\sffamily\small\color{sgteal}Same idea as \textit{Compare batch and stochastic "
                     r"gradient descent}: full solution on p.~213}. \answer{Stochastic Gradient Descent (SGD)}" "\n")
        paras.append(lead + r" Seeds 102, 104, 107, Manhattan distance: \answer{medians $(4600, 4.35)$, "
                     r"$(7000, 4.7)$, $(10000, 4.9)$} for \{101,102\}." "\n")
    size = "10pt" if opts else "11pt"
    return (rf"\documentclass[{size},a4paper]{{report}}" "\n" rf"\usepackage[{opts}]{{studyguide}}" "\n"
            r"\begin{document}" "\n" + "\n".join(paras) + r"\end{document}" "\n")


def overfull(opts):
    d = Path(tempfile.mkdtemp(prefix="sg_answer_"))
    try:
        (d / "t.tex").write_text(doc(opts), "utf-8")
        env = dict(os.environ, TEXINPUTS=os.pathsep.join([str(LATEX), ""]))
        subprocess.run(["pdflatex", "-interaction=nonstopmode", "t.tex"], cwd=d, env=env,
                       capture_output=True, timeout=300)
        log = (d / "t.log").read_text("utf-8", errors="replace")
        ok = (d / "t.pdf").exists()
        return ok, re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\) in paragraph", log)
    finally:
        shutil.rmtree(d, ignore_errors=True)


if shutil.which("pdflatex") is None:
    print("FAIL pdflatex not found")
    sys.exit(1)
for opts, name in (("", "print"), ("phone", "phone")):
    built, ov = overfull(opts)
    check(f"{name}: builds", built)
    check(f"{name}: no answer box runs into the margin", not ov, f"{len(ov)} overfull: {ov[:6]}")

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
