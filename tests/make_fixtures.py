"""Rebuild the SYNTHETIC test fixtures that need generated files (PDFs, corpus text, receipts).

    py tests/make_fixtures.py [receipts_rotated] [verify_ci_rescue]      (default: both)

Every question text here was written for this repository: none is taken from a real exam paper. The structures
(ids, marks, sub-parts, years, table rows, garbled corpus rows, sideways pages) mirror the real cases that broke
the tools, so each test keeps the strength it had:

  receipts_rotated   every page is a picture of text turned sideways, p1 and p3 one way, p2 the other, so the
                     corpus OCR is noise and the manual receipt rects are tall strips. Guards 019d047
                     (receipts.py reads sideways scans).
  verify_ci_rescue   two papers whose Q1 table rows are missing / garbled in the corpus OCR; the rows pass on the
                     receipt's fresh OCR. Stray corpus positions of those rows must not trigger the duplicate
                     check. Guards 31c5b73 (verify_pyqs.py).

Output is deterministic: same code + same fonts -> same bytes in the JSON files; PDFs embed lossless PNG pages.
Needs Pillow and PyMuPDF; fonts are read from C:/Windows/Fonts (arial.ttf) or any DejaVuSans.ttf on the path.
The other fixtures (score_cn3, web_cn_trial, web_svp_snippets) are plain JSON / LaTeX files edited by hand and
need no generator.
"""
import io, json, shutil, sys, textwrap
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
DPI = 200
PX = DPI / 72.0                       # pixels per PDF point


def font(size):
    for f in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    raise SystemExit("no usable TrueType font found")


def wrap_lines(text, fnt, width_px, draw):
    """Greedy word wrap of text (explicit newlines kept) to width_px."""
    out = []
    for para in text.split("\n"):
        line = ""
        for w in para.split():
            t = (line + " " + w).strip()
            if draw.textlength(t, font=fnt) <= width_px or not line:
                line = t
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def pages_to_pdf(images, size_pt, out):
    """Image-only PDF: one lossless page picture per page (no text layer, like a scan)."""
    doc = pymupdf.open()
    for im in images:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        pg = doc.new_page(width=size_pt[0], height=size_pt[1])
        pg.insert_image(pg.rect, stream=buf.getvalue())
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out, deflate=True)
    doc.close()


# =====================================================================================================
# receipts_rotated: a sideways scan
# =====================================================================================================
RR_PAPER = {
    "id": "ES2023SP", "year": 2023, "session": "spring", "exam": "endsem",
    "source_slug": "PYQE_sample_endsem_economics_scan", "course_code": "XX2002",
    "full_marks": 50, "duration": "3 h", "pattern": "Q1 compulsory 10x1; any 5 of Q2-Q8",
    "instructions": "Answer any SIX questions. Section A is compulsory. The figures in the margin indicate full marks.",
    "pages": [1, 6],
}
RR_PDF_REL = "Endsem PYQs/Sample endsem economics (XX2002), sideways scan.pdf"
# (id, qno, marks, type, text, page, extra) : the text is wrapped into a strip that is turned with its page
RR_Q = [
    ("ES2023SP-1a", "1(a)", 1, "theory", 1,
     "Explain how a price floor on farm produce can protect small growers when harvest prices fall and "
     "input costs keep rising."),
    ("ES2023SP-1b", "1(b)", 1, "numerical", 1,
     "State the formula that links marginal revenue (MR), price (P) and elasticity of demand (e), and "
     "find MR when P = 40 and e = 2."),
    ("ES2023SP-1d", "1(d)", 1, "theory", 2,
     "Describe how the average variable cost curve and the marginal cost curve are related to each other."),
]
RR_2A_P2 = ("(i) What do you understand by consumer surplus and producer surplus? Illustrate both with "
            "demand and supply curves.\n(ii) Two buyers (B1 and B2) and two firms (F1 and F2) trade a good Y.")
RR_2A_P3 = ("By using the schedule, find the market clearing price and quantity and name the buyer and the firm "
            "that behave rationally. (Where, Py = price of good Y)")
RR_TABLE = {"header": ["Py", "B1", "B2", "F1", "F2"],
            "rows": [["80", "1", "3", "7", "2"], ["70", "2", "3", "6", "2"], ["60", "3", "3", "5", "2"],
                     ["50", "4", "3", "4", "2"], ["40", "5", "3", "3", "2"], ["30", "6", "3", "2", "2"],
                     ["20", "7", "3", "1", "2"]]}
# page turns (PIL counter-clockwise degrees): p1 and p3 one way, p2 the other, p4-p6 alternate
RR_TURN = {1: 90, 2: 270, 3: 90, 4: 270, 5: 90, 6: 270}
RR_FILLER = [
    "Section B. Attempt any one question from this section. Show every step of the working.",
    "Section C. Attempt any one question from this section. Diagrams must be neat and labelled.",
    "Section D. Attempt any one question from this section. Assume any missing data sensibly.",
    "End of the question paper. Please check that all pages are present before you leave the hall.",
]


def draw_strip(text, width_px, fnt, pad=10, table=None):
    """Upright strip image holding wrapped text (and an optional table under it); its height fits the content."""
    probe = ImageDraw.Draw(Image.new("L", (10, 10)))
    lines = wrap_lines(text, fnt, width_px - 2 * pad, probe)
    lh = int(fnt.size * 1.35)
    rows = (1 + len(table["rows"])) if table else 0
    h = pad * 2 + lh * len(lines) + (lh * rows + pad if table else 0)
    im = Image.new("L", (width_px, h), 255)
    d = ImageDraw.Draw(im)
    y = pad
    for ln in lines:
        d.text((pad, y), ln, fill=0, font=fnt)
        y += lh
    if table:
        y += pad // 2
        colw = 130
        for ri, row in enumerate([table["header"]] + table["rows"]):
            for ci, cell in enumerate(row):
                x = pad + ci * colw
                d.rectangle([x, y, x + colw, y + lh], outline=0)
                d.text((x + 10, y + 4), cell, fill=0, font=fnt)
            y += lh
    return im


def build_receipts_rotated():
    root = FIX / "receipts_rotated"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    W, H = int(595.44 * PX), int(421.2 * PX)               # landscape page, content turned 90 deg
    fnt = font(36)
    strip_w = int((409.0 - 12.0) * PX)                      # strip height on the page = text line length
    pages = {k: Image.new("L", (W, H), 255) for k in RR_TURN}
    cursor = {k: 14.0 for k in RR_TURN}                     # next free x (pt) on each page
    rects = {}

    def place(pg, text, table=None, tag=None):
        im = draw_strip(text, strip_w, fnt, table=table)
        x0 = cursor[pg]
        w_pt = round(im.height / PX, 1)
        x1 = round(x0 + w_pt, 1)
        turned = im.rotate(RR_TURN[pg], expand=True)
        pages[pg].paste(turned, (int(x0 * PX), int(12.0 * PX)))
        cursor[pg] = x1 + 6.0
        rects[tag] = {"page": pg, "rect": [round(x0, 1), 12.0, x1, 409.0]}

    for qid, _qno, _m, _t, pg, text in RR_Q:
        place(pg, text, tag=qid)
    place(2, RR_2A_P2, tag="2a-p2")
    place(3, RR_2A_P3, table=RR_TABLE, tag="2a-p3")
    for k, pg in enumerate((4, 5, 6, 4)):
        place(pg, RR_FILLER[k], tag=f"filler{k}")
    pdf_path = root / RR_PDF_REL
    pages_to_pdf([pages[k].rotate(0) for k in sorted(pages)], (595.44, 421.2), pdf_path)

    # corpus OCR of a sideways scan: read the whole pages with Tesseract the way ingest does (no turning);
    # on turned text this is noise, which is the point
    slug = RR_PAPER["source_slug"]
    corpus = [f"# SOURCE: {RR_PDF_REL}", "# CATEGORY: pyq_endsem | PAGES: 6 | OCR pages: 6", "# ORIGIN: instructor",
              "", ""]
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as td:
        for k in sorted(pages):
            png = Path(td) / f"p{k}.png"
            pages[k].save(png)
            r = subprocess.run(["tesseract", str(png), "stdout", "--psm", "3"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            corpus += [f"## [{slug} p{k}] (OCR)", "", r.stdout.strip(), ""]
    (root / "corpus").mkdir()
    (root / "corpus" / f"{slug}.md").write_text("\n".join(corpus) + "\n", encoding="utf-8")

    size = pdf_path.stat().st_size
    write_json(root / "manifest.json", {"files": {RR_PDF_REL: {
        "slug": slug, "category": "pyq_endsem", "origin": "instructor", "kind_detected": "pdf", "ext_kind": "pdf",
        "mismatch": False, "pages": 6, "ocr_pages": 6, "text_pages": 6, "image_only_pages": 0, "blank_pages": 0,
        "lost_pages": [], "chars": 0, "garble": 0.07, "ocr_conf": 39.0, "figures": 0,
        "stamp": f"{size}-synthetic|ocr1|v4", "ocr_available": True,
        "quality": "POOR - read page images (work/note_pages or work/pyq_pages)"}}})

    fix = ("text layer unusable: every page is scanned rotated 90 deg, so the OCR is noise; "
           "whole text read from the rotated page image")
    qs = []
    for qid, qno, marks, typ, _pg, text in RR_Q:
        qs.append({"id": qid, "paper": "ES2023SP", "qno": qno, "marks": marks, "compulsory": True, "text": text,
                   "type": typ, "verified": "vision", "ocr_fixes": fix, "figure": "", "receipt": rects[qid],
                   "cluster": "C01", "topic": "T01", "in_scope": True})
    qs.append({"id": "ES2023SP-2a", "paper": "ES2023SP", "qno": "2(a)", "marks": 4, "compulsory": False,
               "text": RR_2A_P2 + "\n[table]\n" + RR_2A_P3, "type": "numerical", "verified": "vision",
               "ocr_fixes": fix, "figure": "", "table": RR_TABLE,
               "receipt": [rects["2a-p2"], rects["2a-p3"]], "cluster": "C01", "topic": "T01", "in_scope": True})
    write_json(root / "bank.json", {"papers": [RR_PAPER], "questions": qs, "clusters": [{"id": "C01", "topic": "T01"}]})
    (root / "README.md").write_text(
        "SYNTHETIC fixture (generated by tests/make_fixtures.py; no real exam content).\n\n"
        "A 6-page 'paper' whose every page is a picture of text turned sideways: p1/p3 one way, p2 the other, so the\n"
        "corpus OCR (Tesseract with no turning) is noise and the questions' manual receipt rects are tall strips.\n"
        "Questions 1(a), 1(b) (p1), 1(d) (p2) and 2(a) (a strip on p2 and one on p3, turned opposite ways) are\n"
        "invented. It reproduces the bug fixed in commit 019d047 (receipts.py: read sideways scans): the old tool\n"
        "OCRs each strip as is, scores ~0 and never records a turn. Used by tests/test_receipts.py.\n",
        encoding="utf-8")
    print("receipts_rotated:", {k: v["rect"] for k, v in rects.items()})


# =====================================================================================================
# verify_ci_rescue: Q1 table rows lost from the corpus OCR
# =====================================================================================================
VC_HEADER = ["EXAMPLE UNIVERSITY - MID-SEMESTER EXAMINATION {y}", "School of Engineering (synthetic sample paper)",
             "Subject: Sample Systems Modelling (XX3001) (Regular)",
             "> 4 (four) questions are to be attempted.",
             "> Section A is compulsory; attempt any 1 question from each of Sections B, C and D.",
             "Time: 1.5 hours Full Marks: 20", "The figures in the right-hand side indicate full marks."]

# text, marks, type, extra ; every question of both papers (ids are fixed by tests/test_verify.py)
VC_P24 = [
    ("1a", 1, "theory", "State the main stages of a closed-loop feedback controller."),
    ("1b", 1, "compare", "Why does gradient descent become unstable when the step size is too large?"),
    ("1c", 1, "theory", "Name the smallest network depth that can separate the XOR pattern."),
    ("1d", 1, "theory", "Why are smooth squashing functions chosen as the activation in a layered model?"),
    ("1e", 1, "numerical", "A set is given as A={0.2/1, 0.4/2, 0.5/4, 0.9/5, 0.3/6, 0.5/7}. State whether it is convex. Justify."),
    ("2", 5, "numerical", "Consider a universe X of ages X = {5, 15, 25, 35, 45, 55, 65, 75, 85}.\n[table]\nAnswer the following\n"
     "1. Build the sets named young, adult and senior over X.\n2. Give the support of each set.\n"
     "3. What is the width of the set young?\n4. Is the set adult normal or subnormal?\n5. What is the core of the set senior?"),
    ("3", 5, "numerical", "Let M be a set describing how mature a person is at a given age. Its membership rule is\n"
     "$\\mu_M(x) = \\begin{cases}0, if\\ x \\leq 5\\\\\\left(\\frac{x-5}{20}\\right)^2, if\\ 5 < x \\leq 25\\\\1, if\\ x > 25\\end{cases}$\n"
     "The universe is X={3, 8, 10, 12, 15, 18, 20, 24, 27, 32}. Find the alpha-cut and the strong alpha-cut for alpha=0.4."),
    ("4a", 2, "diagram", "Sketch the block model of a single artificial unit and mark every unknown parameter."),
    ("4b", 3, "numerical", "A two-class training set is listed below. Find the weights after the first iteration, starting "
     "from W=[1 -0.5].\n[table]"),
    ("5a", 2, "theory", "Write down the learning rule of a linear adaptive unit."),
    ("5b", 3, "numerical", "With starting weights W=[0.2, 0.3], update the weights for the input X=[-1 -1] when the target is d=-1."),
    ("6a", 1, "theory", "How does a radial basis layer turn a nonlinearly separable task into a linearly separable one?"),
    ("6b", 4, "numerical", "Use the XOR function with Gaussian basis functions to illustrate your answer."),
    ("7a", 1, "theory", "What is meant by the cooperation step in a self organising map?"),
    ("7b", 4, "numerical", "A map has two inputs and two output units with initial weights\n"
     "$W = \\begin{bmatrix}0.2 & 0.3\\\\0.7 & 0.4\\end{bmatrix}$\n"
     "Find the output unit closest to the input [0.4 0.3] and update its weights with a learning rate of 0.5."),
]
VC_P25 = [
    ("1a", 1, "compare", "Compare a living nerve cell with a model unit."),
    ("1b", 1, "theory", "How can the behaviour of a model unit be written down mathematically?"),
    ("1c", 1, "theory", "What does the winner-takes-all learning rule do?"),
    ("1d", 1, "theory", "Which kind of learning does vector coding by prototypes use?"),
    ("1e", 1, "diagram", "Draw a fuzzy set to describe the statement the room is warm, over a continuous temperature axis."),
    ("2", 5, "numerical", "Two sets are given as P = ((x1, 0.1), (x2, 0.2), (x3, 0.7), (x4, 0.5), (x5, 0.4)) and "
     "Q = ((x1, 0.9), (x2, 0.6), (x3, 0.3), (x4, 0.2), (x5, 0.8)). Determine the following. "
     "i) $P_{0.2}$ and $Q_{0.3}$ ii) The support of each set iii) The core of set P iv) Convexity of set Q v) Normality of set P"),
    ("3", 5, "numerical", "Take the sets L = {(low,1),(medium,0.2),(high,0.5)} and K = {(positive,0.9),(zero,0.4),(negative,0.9)}. "
     "Form the product relation R = L x K and then the diagonal of $R\\circ R^{T}$."),
    ("4a", 1, "theory", "A single linear unit cannot split classes that are not linearly separable. Justify this."),
    ("4b", 4, "numerical", "Train the OR function (binary inputs and targets) on one unit with one neuron for one epoch, with "
     "initial weights and bias w1=0.1, w2=-0.5, b=0.1 and learning rate 0.5."),
    ("5", 5, "numerical", "Train the AND function (bipolar inputs and targets) on a two-input one-output adaptive unit "
     "from w1=0.2, w2=0.2, b=0.2 for one epoch with learning rate 0.5."),
    ("6", 5, "derivation", "Design a radial basis network for a classification task and show that the problem becomes "
     "linearly separable in the hidden space, taking the XOR function as the example."),
    ("7", 5, "numerical", "The output layer of a map is a ring of six nodes A to F (dashed links A-B-C-D-E-F-A). Each node has two "
     "inputs x1 and x2 (not shown). The initial weights are\n[table]\n"
     "a) Find the winning node for the input x = [2, -4].\nb) Adjust the winning node's weights with a learning rate of 0.5."),
]
VC_TABLES = {
    "MS2024B-2": {"header": ["Age", "Young", "Adult", "Senior"],
                  "rows": [["5", "0", "0", "0"], ["15", "0.2", "0.1", "0"], ["25", "0.8", "0.6", "0"],
                           ["35", "0.5", "1", "0.1"], ["45", "0.1", "0.7", "0.4"], ["55", "0", "0.3", "0.8"],
                           ["65", "0", "0.1", "1"], ["75", "0", "0", "1"], ["85", "0", "0", "1"]]},
    "MS2024B-4b": {"header": ["x1", "x2", "d"], "rows": [["1", "2", "1"], ["-1", "2", "0"]]},
    "MS2025-7": {"header": ["-", "A", "B", "C", "D", "E", "F"],
                 "rows": [["w1", "-1", "0", "3", "-2", "3", "4"], ["w2", "2", "4", "-2", "-3", "2", "-1"]]},
}
# Q1 rows whose line is missing / garbled in the corpus OCR (the table's row lines were lost); the others read well.
# value: the corpus line kept (stray tail), or None = the row is absent from the corpus
VC_LOST = {"MS2024B-1a": None, "MS2024B-1b": None, "MS2024B-1c": "that can separate the XOR pattern.",
           "MS2025-1c": None}
VC_FIGURE = {"MS2025-7": "Output ring: six nodes A, B, C, D, E, F joined by dashed lines (A-B-C-D-E-F-A)."}
VC_PAPERS = [
    ("MS2024B", 2024, "5th Sem, 2024 mid sample (XX3001).pdf", "PYQM_synthetic_2024_mid_sample_XX3001", VC_P24),
    ("MS2025", 2025, "5th Sem, 2025 mid sample (XX3001).pdf", "PYQM_synthetic_2025_mid_sample_XX3001", VC_P25),
]
VC_PATTERNS = {
    "MS2024B": "Q1 compulsory 5x1; any 3 of Q2-Q7 (one each from Section B = Q2,Q3; C = Q4,Q5; D = Q6,Q7)",
    "MS2025": "Q1 compulsory 5x1; any 3 of Q2-Q7 (one from each of Section B Q2/Q3, Section C Q4/Q5, Section D Q6/Q7)"}


def build_verify_ci_rescue():
    root = FIX / "verify_ci_rescue"
    if root.exists():
        shutil.rmtree(root)
    (root / "Midsem PYQs").mkdir(parents=True)
    (root / "corpus").mkdir()
    fnt = font(30)
    probe = ImageDraw.Draw(Image.new("L", (10, 10)))
    PW, PH = 595, 842
    questions, papers, receipts, manifest = [], [], {}, {}
    for pid, year, fname, slug, qrows in VC_PAPERS:
        # ---- lay the paper out: page 1 = header + Section A (Q1 table) + first questions, page 2 = the rest
        pages = [Image.new("L", (int(PW * PX), int(PH * PX)), 255) for _ in range(2)]
        draws = [ImageDraw.Draw(p) for p in pages]
        corpus_lines = {1: [], 2: []}
        pg, y = 0, 40.0                                    # y in points
        for h in VC_HEADER:
            draws[0].text((70 * PX, y * PX), h.format(y=year), fill=0, font=fnt)
            corpus_lines[1].append(h.format(y=year))
            y += 15
        y = 330.0
        colw = int(440 * PX) - 60
        qdefs = []
        rowh = 0
        for qno_id, marks, typ, text in qrows:
            qid = f"{pid}-{qno_id}"
            is_q1 = qno_id.startswith("1") and len(qno_id) == 2 and qno_id[0] == "1" and pid != "x"
            body = text.replace("[table]", "")
            lines = wrap_lines(body, fnt, colw, probe)
            if qid in VC_TABLES:
                nrow = 1 + len(VC_TABLES[qid]["rows"])
            else:
                nrow = 0
            hpt = (len(lines) + nrow * 0.8) * 15.5 + 6
            if pg == 0 and y + hpt > PH - 40:
                pg, y = 1, 60.0
            y0 = y
            for ln in lines:
                draws[pg].text((90 * PX, y * PX), ln, fill=0, font=fnt)
                y += 15.5
            if nrow:
                draws[pg].rectangle([90 * PX, y * PX, 90 * PX + 330, (y + nrow * 12.5) * PX], outline=0)
                y += nrow * 12.5
            y += 6
            qdefs.append((qid, qno_id, marks, typ, text, pg + 1, round(y0 - 2, 1), round(y, 1), lines))
        # ---- corpus text: what the page OCR read; lost rows are absent or only their tail survives
        for qid, qno_id, marks, typ, text, pgn, ya, yb, lines in qdefs:
            label = f"Q{qno_id[0]}." if qno_id in ("1a", "2", "3", "4a", "5a", "5", "6a", "6", "7a", "7") else ""
            if qid in VC_LOST:
                tail = VC_LOST[qid]
                if tail:
                    corpus_lines[pgn].append(tail)
                continue
            for k, ln in enumerate(lines):
                if "$" in ln or "begin" in ln or "cases" in ln:
                    continue                                 # maths: garbled / lost in OCR
                s = ln
                if k == 0 and label:
                    s = f"{label} {s}"
                if k == len(lines) - 1:
                    s = f"{s} CO{1 + len(qno_id) % 3} [{marks:g}]"
                corpus_lines[pgn].append(s)
        slugfile = root / "corpus" / f"{slug}.md"
        body = [f"# SOURCE: Midsem PYQs/{fname}", "# CATEGORY: pyq_midsem | PAGES: 2 | OCR pages: 2", "# ORIGIN: instructor", "", ""]
        for k in (1, 2):
            body += [f"## [{slug} p{k}] (OCR)", ""] + corpus_lines[k] + [""]
        slugfile.write_text("\n".join(body), encoding="utf-8")
        pdf = root / "Midsem PYQs" / fname
        pages_to_pdf(pages, (PW, PH), pdf)
        manifest[f"Midsem PYQs/{fname}"] = {
            "slug": slug, "category": "pyq_midsem", "origin": "instructor", "kind_detected": "pdf", "ext_kind": "pdf",
            "mismatch": False, "pages": 2, "ocr_pages": 2, "text_pages": 2, "image_only_pages": 0, "blank_pages": 0,
            "lost_pages": [], "chars": sum(len(l) for k in (1, 2) for l in corpus_lines[k]), "garble": 0.02,
            "ocr_conf": 85.0, "figures": 0, "stamp": f"{pdf.stat().st_size}-synthetic|ocr1|v4", "ocr_available": True,
            "quality": "ok"}
        papers.append({"id": pid, "year": year, "session": "autumn", "exam": "midsem", "source_slug": slug,
                       "course_code": "XX3001", "full_marks": 20, "duration": "1.5 h", "pattern": VC_PATTERNS[pid],
                       "instructions": "Section A is compulsory. The figures in the right-hand side indicate full marks. "
                                       "All parts of a question should be answered at one place only.",
                       "pages": [1, 2], "coverage": ["U1", "U2", "U3"], "weight": 1})
        for qid, qno_id, marks, typ, text, pgn, ya, yb, lines in qdefs:
            qno = qno_id[0] + (f"({qno_id[1]})" if len(qno_id) == 2 else "")
            q = {"id": qid, "paper": pid, "qno": qno, "marks": marks, "compulsory": qno_id[0] == "1", "type": typ,
                 "verified": "vision", "receipt": {"page": pgn, "rect": [70, ya, 510, yb]}, "text": text,
                 "topic": "T01", "cluster": "C01", "in_scope": True}
            fixes = []
            if qid in VC_LOST:
                fixes.append("this row is missing from the corpus OCR; read from the image" if not VC_LOST[qid]
                             else "the first line is missing from the corpus OCR; read from the image")
            if "$" in text:
                fixes.append("the formula was garbled in OCR; read from the image as a maths span")
            if qid in VC_TABLES:
                q["table"] = VC_TABLES[qid]
                fixes.append("the table was garbled in OCR")
            q["ocr_fixes"] = "; ".join(fixes)
            if pid == "MS2025":
                q["figure"] = VC_FIGURE.get(qid, "")
            questions.append(q)
            # the receipt's fresh region OCR: the crop's words with the margin's noise around them
            rtext = f"{qno_id[-1] if len(qno_id) == 2 else qno_id} | " + text.replace("\n", " ").replace("[table]", "") + f" | CO{1 + len(qno_id) % 3}"
            rec_text = rtext
            receipts[qid] = {"page": pgn, "rect": [70.0, ya, 510.0, yb], "parts": [{"page": pgn, "rect": [70.0, ya, 510.0, yb]}],
                             "match": 1.0, "method": "manual", "ocr_text": rec_text, "ocr_method": "region-ocr-psm6",
                             "ocr_is_ocr": True}
    write_json(root / "bank.json", {"papers": papers, "questions": questions, "clusters": [{"id": "C01", "topic": "T01"}]})
    write_json(root / "receipts.json", receipts)
    write_json(root / "manifest.json", {"files": manifest})
    (root / "README.md").write_text(
        "SYNTHETIC fixture (generated by tests/make_fixtures.py; no real exam content).\n\n"
        "Two invented midsem papers (MS2024B, MS2025) with their corpus OCR text, page-picture PDFs, manifest rows\n"
        "and receipts (rects + fresh region OCR). MS2024B-1a/1b/1c and MS2025-1c are Q1 table rows lost from the\n"
        "corpus OCR (absent, or only a tail survives): they pass only via the receipt's fresh OCR. The tail words\n"
        "also occur in other questions of the same paper, so those rows keep stray corpus positions that no other\n"
        "question owns. It reproduces the bug fixed in commit 31c5b73: the old verify_pyqs.py let those stray\n"
        "positions into the duplicate check and blocked the rows as 'duplicates another question (owns 0 ...)'.\n"
        "Used by tests/test_verify.py.\n", encoding="utf-8")
    print("verify_ci_rescue: wrote", len(questions), "questions")


if __name__ == "__main__":
    want = sys.argv[1:] or ["receipts_rotated", "verify_ci_rescue"]
    for w in want:
        {"receipts_rotated": build_receipts_rotated, "verify_ci_rescue": build_verify_ci_rescue}[w]()
