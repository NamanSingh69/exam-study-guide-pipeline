"""layout_check.py: the automatic replacement for "look at every contact sheet".

Synthetic one-page PDFs drawn with pymupdf (no TeX), one defect each, on the print geometry (A4, 20 mm side
margins) and the phone geometry (105 x 187 mm, 5.5 mm). Every defect page must be flagged with its own kind,
and the clean pages (body text, a table with rules between rows, an underline, a label on a white-filled node
over an edge, sub/superscripts) must give nothing. Also checks the CLI output shape and --pages filtering.
"""
import subprocess, sys
from pathlib import Path

import pymupdf as fitz

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "layout"
TMP.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(PIPE / "tools"))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0
MM = 72 / 25.4
A4 = (595.28, 841.89)
PHONE = (105 * MM, 187 * MM)


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


def body(pg, x0, x1, y=120, n=8, size=10):
    for k in range(n):
        pg.insert_text((x0, y + k * 14), "Body text of the guide sits inside the frame.", fontsize=size)


def make(name, size, draw):
    doc = fitz.open()
    pg = doc.new_page(width=size[0], height=size[1])
    draw(pg)
    p = TMP / f"{name}.pdf"
    doc.save(p)
    return p


L, R = 20 * MM + 4, A4[0] - 20 * MM   # print frame


def clean(pg):
    body(pg, L, R)
    # a table: horizontal rules between rows, never through text
    for k in range(4):
        y = 300 + k * 16
        pg.draw_line((L, y), (L + 300, y), width=0.5)
        pg.insert_text((L + 4, y + 12), f"row {k}  value {k * 3}", fontsize=10)
    # an underline just below the baseline
    pg.insert_text((L, 420), "Underlined phrase", fontsize=10)
    pg.draw_line((L, 422), (L + 85, 422), width=0.4)
    # an edge with its label on a white-filled node drawn after the line (TikZ fill=white)
    pg.draw_line((L, 500), (L + 300, 500), width=0.8)
    pg.draw_rect(fitz.Rect(L + 120, 492, L + 180, 506), color=None, fill=(1, 1, 1))
    pg.insert_text((L + 124, 503), "label", fontsize=9)
    # a superscript touching its base word
    pg.insert_text((L, 560), "x squared", fontsize=10)
    pg.insert_text((L + 5.5, 556), "2", fontsize=6.5)


def outside(pg):
    body(pg, L, R)
    pg.insert_text((A4[0] - 30, 400), "spills past the margin", fontsize=10)


def overlap(pg):
    body(pg, L, R)
    pg.insert_text((L + 40, 400), "Sender window", fontsize=10)
    pg.insert_text((L + 46, 402), "Receiver buffer", fontsize=10)


def on_line(pg):
    body(pg, L, R)
    pg.insert_text((L + 100, 403), "ACK 2051", fontsize=10)
    pg.draw_line((L, 400), (L + 300, 400), width=0.8)   # straight through the label's middle


def tiny(pg):
    body(pg, L, R)
    pg.insert_text((L, 400), "a label shrunk by resizebox", fontsize=4)


def drawing_out(pg):
    body(pg, L, R)
    pg.draw_rect(fitz.Rect(L, 380, A4[0] - 4, 460), width=0.8)   # a TikZ figure wider than the frame


def calibrated_clean(pg):
    """False positives seen on the real CN guide (2026-11-10 calibration): all must stay unflagged."""
    body(pg, L, R)
    # booktabs \rowcolor shading: fill-only rects reaching 2.1 mm into the margin
    pg.draw_rect(fitz.Rect(L - 4 - 2.1 * MM, 300, L + 200, 312), color=None, fill=(0.93, 0.95, 0.97))
    # an enumerate label hanging 2.2 mm into the left margin
    pg.insert_text((L - 4 - 2.2 * MM, 340), "D45.", fontsize=10)
    # a storyboard frame printing the same node text twice at the same place
    pg.insert_text((L + 40, 380), "mail server", fontsize=10)
    pg.insert_text((L + 40.3, 380.2), "mail server", fontsize=10)
    # a deliberately struck-out grey table row (red diagonal over grey text)
    pg.insert_text((L + 40, 430), "R1 port 1", fontsize=10, color=(0.65, 0.65, 0.65))
    pg.draw_line((L + 30, 420), (L + 120, 434), width=0.8, color=(0.8, 0.1, 0.1))
    # a label sitting on top of a dotted threshold line (the line touches only its lowest part)
    pg.insert_text((L + 40, 470), "ssthresh = 8", fontsize=10)
    pg.draw_line((L, 471.5), (L + 300, 471.5), width=0.5)


def calibrated_clean2(pg):
    """Second calibration (all 14 guides): subscripts, code line numbers, off-page invisible text."""
    body(pg, L, R)
    # a word subscript (j_rand) at 4.9 pt inside a normal 10 pt sentence
    pg.insert_text((L, 330), "if r is at most CR or j equals j", fontsize=10)
    pg.insert_text((L + 160, 332), "rand", fontsize=4.9)
    pg.insert_text((L + 172, 330), "then take the mutant coordinate", fontsize=10)
    # listings line numbers 6 mm into the left margin
    pg.insert_text((L - 4 - 6 * MM, 380), "15", fontsize=7)
    pg.insert_text((L - 4 - 6 * MM, 392), "16", fontsize=7)
    pg.insert_text((L, 380), "cap.release()", fontsize=9)
    # invisible text entirely above the paper (e.g. an included page's cropped header)
    pg.insert_text((L, -10), "HS30101 header", fontsize=9)
    # a subscript of one line grazing the word below it
    pg.insert_text((L, 430), "tau", fontsize=10)
    pg.insert_text((L + 15, 434), "il", fontsize=6.5)
    pg.insert_text((L + 14, 440), "length of each tour", fontsize=10)


pl, pr = 5.5 * MM + 2, PHONE[0] - 5.5 * MM


def phone_tiny_figure(pg):
    phone_clean(pg)
    pg.insert_text((pl + 20, 300), "172.18.3.1", fontsize=3.6)   # a whole figure shrunk: unreadable on a phone
    pg.insert_text((pl + 20, 306), "172.18.3.2", fontsize=3.6)


def phone_subscripts(pg):
    phone_clean(pg)
    pg.insert_text((pl, 250), "x", fontsize=8)
    pg.insert_text((pl + 4.5, 252), "m1", fontsize=4.6)   # a scriptscript subscript: normal maths


def phone_clean(pg):
    for k in range(10):
        pg.insert_text((pl, 60 + k * 12), "Phone body line in frame.", fontsize=8)


def phone_out(pg):
    phone_clean(pg)
    pg.insert_text((pl, 250), "an unbreakable formula a + b + c + d + e + f + g + h + i + j + k + l + m + n + o + p",
                   fontsize=8)


import layout_check as lc  # noqa: E402

cases = {
    "clean": (A4, clean, set()),
    "outside": (A4, outside, {"outside"}),
    "overlap": (A4, overlap, {"overlap"}),
    "on_line": (A4, on_line, {"on_line"}),
    "tiny": (A4, tiny, {"tiny"}),
    "drawing_out": (A4, drawing_out, {"outside"}),
    "phone_clean": (PHONE, phone_clean, set()),
    "phone_out": (PHONE, phone_out, {"outside"}),
    "calibrated_clean": (A4, calibrated_clean, set()),
    "phone_subscripts": (PHONE, phone_subscripts, set()),
    "calibrated_clean2": (A4, calibrated_clean2, set()),
    "phone_tiny_figure": (PHONE, phone_tiny_figure, {"tiny"}),
}
for name, (size, fn, want) in cases.items():
    pdf = make(name, size, fn)
    got = lc.check(pdf)
    kinds = {f["kind"] for f in got}
    check(f"{name}: kinds {sorted(want)}", kinds == want, f"got {[(f['kind'], f['msg']) for f in got]}")
    check(f"{name}: findings carry page numbers", all(f["page"] == 1 for f in got))

# several pages: --pages limits the check; the CLI prints LAYOUT lines and a summary, exit 0 even with findings
doc = fitz.open()
for fn in (clean, outside, on_line):
    pg = doc.new_page(width=A4[0], height=A4[1])
    fn(pg)
multi = TMP / "multi.pdf"
doc.save(multi)
got = lc.check(multi)
check("multi: findings on pages 2 and 3 only", {f["page"] for f in got} == {2, 3}, str(got))
check("multi: pages filter", {f["page"] for f in lc.check(multi, pages={3})} == {3})
r = subprocess.run([sys.executable, str(PIPE / "tools" / "layout_check.py"), str(multi)], capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
out = r.stdout
check("cli: LAYOUT lines name the page", "LAYOUT p2" in out and "LAYOUT p3" in out, out[-500:])
check("cli: summary line", "FLAGGED 2 page(s)" in out, out[-300:])
check("cli: exit 0 (advisory)", r.returncode == 0, str(r.returncode))
r = subprocess.run([sys.executable, str(PIPE / "tools" / "layout_check.py"), str(TMP / "clean.pdf")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
check("cli: clean says FLAGGED 0", "FLAGGED 0 page(s)" in r.stdout, r.stdout[-300:])

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
