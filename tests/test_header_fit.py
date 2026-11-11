"""studyguide.sty: the print running header never prints the chapter title over the subject and code (IPA endsem,
2026-11-11).

On 14 pages of the IPA guide the right header "Chapter 15. 2025 Endsem paper, autumn -- questions and solutions" ran
into the left header "Image Processing and Applications CS 30015" (layout_check: '30015' and 'Chapter' overlap).
The test compiles a page with that subject and chapter title (and a still longer one), then requires that, on every
page with a running header, the left and right header texts do not overlap and stay inside the text width.
Needs pdflatex (MiKTeX or TeX Live) and pymupdf; about 5 s.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
LATEX = HERE.parent / "latex"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


TITLES = ["2025 Endsem paper, autumn --- questions and solutions",
          "2024 Endsem paper, spring (supplementary) --- questions, solutions and examiner notes"]
FILL = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 40 + "\n\n") * 6


def doc():
    body = "".join(rf"\chapter{{{t}}}" "\n" + FILL for t in TITLES)
    return (r"\documentclass[11pt,a4paper]{report}" "\n" r"\usepackage{studyguide}" "\n"
            r"\setsubject{Image Processing and Applications}{CS 30015}{Endsem guide}" "\n"
            r"\begin{document}" "\n" + body + r"\end{document}" "\n")


d = Path(tempfile.mkdtemp(prefix="sg_header_"))
try:
    (d / "t.tex").write_text(doc(), "utf-8")
    env = dict(os.environ, TEXINPUTS=os.pathsep.join([str(LATEX), ""]))
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "t.tex"], cwd=d, env=env, capture_output=True,
                   timeout=300)
    pdf = d / "t.pdf"
    check("document compiles", pdf.exists())
    if pdf.exists():
        doc_ = pymupdf.open(pdf)
        mm = 72 / 25.4
        checked = bad = 0
        worst = ""
        for pno, page in enumerate(doc_, 1):
            words = [w for w in page.get_text("words") if w[3] < 25 * mm]       # header band
            left = [w for w in words if w[0] < page.rect.width / 2 and "Image" in w[4]]
            if not left or not any("Chapter" in w[4] for w in words):
                continue
            checked += 1
            ws = sorted(words, key=lambda w: w[0])
            for a, b in zip(ws, ws[1:]):
                if b[0] < a[2] - 0.5:                                           # next word starts inside previous
                    bad += 1
                    worst = worst or f"p{pno}: '{a[4]}' and '{b[4]}'"
            if max(w[2] for w in words) > page.rect.width - 20 * mm + 1:
                bad += 1
                worst = worst or f"p{pno}: header runs past the right margin"
        check("pages with a chapter running header were found", checked >= 4, f"{checked} pages")
        check("left and right header never overlap and stay in the text width", bad == 0, worst)
finally:
    shutil.rmtree(d, ignore_errors=True)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
