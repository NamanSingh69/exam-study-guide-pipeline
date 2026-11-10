"""
receipts.py: crop every banked PYQ from its paper page ("show the receipt").

For each question in <SUBJ>/work/<scope>/pyq_bank.json:
  1. find the paper file: papers[].source_slug -> manifest.json -> the PDF under the subject folder
     (fallback: the rendered pages work/pyq_pages/<slug>_pN.png)
  2. get the page words with boxes: pymupdf words for pages with a usable text layer, Tesseract TSV for
     scanned pages, or pages whose text layer is garbage (also tried whenever the text layer matches badly)
  3. align the question text against the paper's words (the same fitting alignment as verify_pyqs.py)
  4. crop a full-text-width band covering the matched lines (+ a trailing "[n Marks]" line), at 150 dpi;
     a question that runs over a page break becomes one image stacked from both pages
A manual override in the bank wins: "receipt": {"page": 2, "rect": [x0, y0, x1, y1]} (PDF points; a list of
such dicts for several pieces).

Writes work/<scope>/receipts/<qid>.png and work/<scope>/receipts/receipts.json:
  {qid: {page, rect, match, method, parts, tri, file, text_sha, paper}}
  match  = fraction of the question's tokens found in the cropped words (verify_pyqs needs >= 0.6)
  method = pdf-words | tesseract | png-tesseract | manual

  py _pipeline/tools/receipts.py CN --scope midsem [--only QID ...]
  exit 0 = every question has a good receipt, 1 = some are missing/low-match (RESULT BLOCKED), 2 = usage
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workdir  # noqa: E402
import verify_pyqs as vp  # noqa: E402

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

TESSERACT = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OCR_DPI = 300
OUT_DPI = 150
PNG_DPI = 170          # ingest renders pyq_pages/ at this
PAD_Y, PAD_X = 4.0, 8.0
MARKS_LINE = re.compile(r"^\W*(\d+(\.\s?\d+)?\s*(\+\s*\d+(\.\d+)?)*\s*(marks?|m)\b|\[?\s*\d+(\.\d+)?\s*marks?)", re.I)


try:                                   # pymupdf's own errors (e.g. a failed malloc while rendering)
    from pymupdf.mupdf import FzErrorBase as _FZ_ERROR
except ImportError:  # pragma: no cover
    _FZ_ERROR = RuntimeError


def _save_pixmap(page, png, dpi, clip=None):
    """Render to a PNG file and free the pixmap and pymupdf's store at once (a 300 dpi page is ~25 MB)."""
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    try:
        pix.save(png)
    finally:
        del pix
        try:
            fitz.TOOLS.store_shrink(100)
        except Exception:  # noqa
            pass


def have_tesseract():
    return Path(TESSERACT).exists()


SPREAD_RATIO = 1.15      # a page this much wider than tall is a 2-up booklet spread


def tesseract_page(png, scale, x_off=0.0, y_off=0.0):
    """Words of a page image; a landscape (2-up spread) image is OCR'd as left half then right half, so a
    question's words stay contiguous in reading order. Each word: (x0, y0, x1, y1, text, line_key, col)."""
    from PIL import Image
    with Image.open(png) as im:
        w, h = im.size
        whole = tesseract_words(png, scale, x_off, y_off)
        if w < SPREAD_RATIO * h or not whole:
            return [t + (0,) for t in whole]
        mid = x_off + (w / 2) * scale            # a spread has a gutter: almost no word crosses the middle
        crossing = sum(1 for t in whole if t[0] < mid - 2 < mid + 2 < t[2])
        if crossing > 0.03 * len(whole):
            return [t + (0,) for t in whole]
        out = []
        for col, (a, b) in enumerate(((0, w // 2), (w // 2, w))):
            half = Path(png).with_name(Path(png).stem + f"_c{col}.png")
            im.crop((a, 0, b, h)).save(half)
            out += [t[:5] + ((col,) + t[5],) + (col,) for t in tesseract_words(half, scale, x_off + a * scale, y_off)]
        return out


def tesseract_words(png, scale, x_off=0.0, y_off=0.0):
    """Words of a page image as (x0, y0, x1, y1, text, line_key) in PDF points (px * scale + offset)."""
    if not have_tesseract():
        return []
    try:
        r = subprocess.run([TESSERACT, str(png), "stdout", "--psm", "6", "tsv"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
    except Exception:  # noqa
        return []
    out = []
    for row in r.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5" or not c[11].strip():
            continue
        l, t, w, h = (float(c[6]), float(c[7]), float(c[8]), float(c[9]))
        out.append((x_off + l * scale, y_off + t * scale, x_off + (l + w) * scale, y_off + (t + h) * scale,
                    c[11], ("t", c[2], c[3], c[4])))
    return out


def text_layer_ok(words):
    if len(words) < 25:
        return False
    return vp_garble(" ".join(w[4] for w in words)) < 0.25


def vp_garble(text):
    ws = re.findall(r"\S+", text)
    if not ws:
        return 1.0
    bad = sum(1 for w in ws if len(w) > 3 and not re.search(r"[aeiouAEIOU0-9]", w)
              or re.search(r"[a-z]\.[a-z]", w) or re.search(r"[^\w\-.,;:()\[\]'\"/%+=*<>&!?#]", w))
    return bad / len(ws)


class Paper:
    """Page words of one paper, from the PDF (text layer or Tesseract) or from the rendered PNGs."""

    def __init__(self, pdf=None, pngs=None, tmp=None, order=None, pages=None):
        self.pdf, self.pngs, self.tmp = pdf, pngs or [], tmp
        self.doc = fitz.open(pdf) if pdf else None
        self.n = len(self.doc) if self.doc else len(self.pngs)
        self._streams = {}
        # one question set of a PDF that holds several ("pages": [first, last]): only its pages are searched
        if pages and not (1 <= pages[0] <= pages[1] <= self.n):
            raise ValueError(f"pages {list(pages)} outside the paper's 1..{self.n}")
        self.range = range(pages[0], pages[1] + 1) if pages else range(1, self.n + 1)
        # pages whose text layer is a scanner's OCR (invisible text over the page image): OCR quality
        self.scan = vp.scan_layer_pages(pdf) if pdf else set()
        # booklet reading order, e.g. ["1R", "2L", "2R", "1L"] (page + L/R half); unlisted parts follow in order
        self.order = []
        for item in order or []:
            m = re.fullmatch(r"\s*(\d+)\s*([LR])?\s*", str(item), re.I)
            if not m or not 1 <= int(m.group(1)) <= self.n:
                raise ValueError(f"bad reading_order item {item!r} (use e.g. '2L', '2R' or '3')")
            cols = {"L": [0], "R": [1]}.get((m.group(2) or "").upper(), [0, 1])
            self.order += [(int(m.group(1)), c) for c in cols]

    def page_rect(self, p):
        if self.doc:
            r = self.doc[p - 1].rect
            return (r.x0, r.y0, r.x1, r.y1)
        from PIL import Image
        with Image.open(self.pngs[p - 1]) as im:
            w, h = im.size
        s = 72.0 / PNG_DPI
        return (0.0, 0.0, w * s, h * s)

    def words(self, p, method):
        if method == "pdf-words":
            ws = self.doc[p - 1].get_text("words")
            return [(w[0], w[1], w[2], w[3], w[4], ("p", w[5], w[6]), 0) for w in ws]
        if method == "tesseract":
            page = self.doc[p - 1]
            png = Path(self.tmp) / f"p{p}.png"
            _save_pixmap(page, png, OCR_DPI)
            return tesseract_page(png, 72.0 / OCR_DPI, page.rect.x0, page.rect.y0)
        if method == "png-tesseract":
            return tesseract_page(self.pngs[p - 1], 72.0 / PNG_DPI)
        raise ValueError(method)

    def methods(self):
        """Word sources to try, best first."""
        if not self.doc:
            return ["png-tesseract"] if have_tesseract() else []
        ms = []
        pdf_ok = any(text_layer_ok(self.words(p, "pdf-words")) for p in self.range)
        if pdf_ok:
            ms.append("pdf-words")
        if have_tesseract():
            # a scanner's invisible OCR layer does not sit exactly on the printed glyphs: crop from the image
            if all(p in self.scan for p in self.range):
                ms.insert(0, "tesseract")
            else:
                ms.append("tesseract")
        if not pdf_ok and not have_tesseract():
            ms.append("pdf-words")
        return ms

    def stream(self, method):
        """(tokens, words_by_page, lines_by_page) for one word source."""
        if method in self._streams:
            return self._streams[method]
        toks, words, lines = [], {}, {}
        for p in range(1, self.n + 1):
            ws = self.words(p, method) if p in self.range else []
            words[p] = ws
            lines[p] = visual_lines(ws)
        chunks = [pc for pc in self.order if pc[0] in self.range] + \
                 [(p, c) for p in self.range for c in (0, 1) if (p, c) not in self.order]
        self.chunks = chunks
        for p, c in chunks:                       # token stream in reading order
            for w in words[p]:
                mk = vp.MARKS_NOTE_RE.fullmatch(w[4].strip())
                if w[6] != c or (mk and vp._is_marks_note(mk)):       # '[5]' margin marks: not question text
                    continue
                toks += vp.tokenize(w[4], ocr=method != "pdf-words" or p in self.scan, page=p,
                                    box=w[:4] + (w[6],))
        self._streams[method] = (toks, words, lines)
        return self._streams[method]

    def crop(self, parts, out, rotate=0):
        """Render [(page, rect)] at OUT_DPI, turn each by `rotate` degrees (a page scanned sideways) and stack them
        vertically into one PNG."""
        from PIL import Image
        ims = []
        for p, (x0, y0, x1, y1) in parts:
            if self.doc:
                pix = self.doc[p - 1].get_pixmap(dpi=OUT_DPI, clip=fitz.Rect(x0, y0, x1, y1))
                ims.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            else:
                s = PNG_DPI / 72.0
                with Image.open(self.pngs[p - 1]) as im:
                    c = im.convert("RGB").crop((int(x0 * s), int(y0 * s), int(x1 * s), int(y1 * s)))
                k = OUT_DPI / PNG_DPI
                ims.append(c.resize((max(1, int(c.width * k)), max(1, int(c.height * k)))))
        if rotate:
            rl = rotate if isinstance(rotate, list) else [rotate] * len(ims)
            ims = [i.rotate(r, expand=True, fillcolor="white") if r else i for i, r in zip(ims, rl)]
        gap = 8
        W = max(i.width for i in ims)
        H = sum(i.height for i in ims) + gap * (len(ims) - 1)
        canvas = Image.new("RGB", (W, H), "white")
        y = 0
        for k, im in enumerate(ims):
            canvas.paste(im, (0, y))
            y += im.height
            if k < len(ims) - 1:
                for x in range(0, W, 6):          # dashed rule marks the page break
                    canvas.paste((170, 170, 170), (x, y + gap // 2, min(W, x + 3), y + gap // 2 + 1))
                y += gap
        # 16-level greyscale: receipts are scans of printed text; RGB made 251 CN receipts 29 MB and the
        # PYQ archive PDF 13.7 MB. The OCR re-check reads its own 300 dpi render, not this file.
        canvas.convert("L").quantize(colors=16).save(out, optimize=True)


def visual_lines(ws):
    """Printed lines of a page, (y0, y1, text, col), by clustering word centres vertically per column.
    (A text layer's own (block, line) groups can span several printed lines, so they are not used.)"""
    out = []
    for col in sorted({w[6] for w in ws}):
        cw = sorted((w for w in ws if w[6] == col), key=lambda w: (w[1] + w[3]) / 2)
        hs = sorted(w[3] - w[1] for w in cw)
        hmed = hs[len(hs) // 2] if hs else 10.0
        groups, cur, yc = [], [], None
        for w in cw:
            c = (w[1] + w[3]) / 2
            if cur and abs(c - yc) > 0.5 * hmed:
                groups.append(cur); cur = []
            cur.append(w)
            yc = sum((x[1] + x[3]) / 2 for x in cur) / len(cur)
        if cur:
            groups.append(cur)
        for g in groups:
            # one inflated box (a text layer's ':' 23 pt tall on a 15 pt line) must not stretch the line over its
            # neighbour; every normal-height word counts, so tall glyphs ([, (, ascenders) are not clipped
            hl = sorted(w[3] - w[1] for w in g)[len(g) // 2]
            core = [w for w in g if w[3] - w[1] <= 1.4 * hl] or g
            out.append((min(w[1] for w in core), max(w[3] for w in core),
                        " ".join(w[4] for w in sorted(g, key=lambda w: w[0])), col))
    return sorted(out, key=lambda t: t[0])


def _roman(n):
    vals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    s = ""
    for v, r in vals:
        while n >= v:
            s += r; n -= v
    return s


def next_labels(qno):
    """Possible labels of the next sub-part: '1(a)' -> {'b'}, '5(ii)' -> {'iii'}, '2(A)' -> {'b'};
    a single i / v / x may be a letter or a roman numeral: '1(i)' -> {'j', 'ii'}. Empty if no label."""
    m = re.match(r"\s*Q?\s*\d+\s*[.(]?\s*\(?\s*([ivx]+|[a-z])\s*\)", str(qno), re.I)
    if not m:
        return set()
    lab = m.group(1).lower()
    out = set()
    romans = {_roman(i): i for i in range(1, 40)}
    if lab in romans:
        out.add(_roman(romans[lab] + 1))
    if len(lab) == 1 and lab < "z":
        out.add(chr(ord(lab) + 1))
    return out


def text_band(words, rect):
    """Left/right extent of the page's text column (robust to a few stray OCR specks)."""
    if not words:
        return rect[0] + 20, rect[2] - 20
    # specks (OCR noise in the margins) are short or oversized boxes; real words set the column's extremes
    hs = sorted(w[3] - w[1] for w in words)
    hmed = hs[len(hs) // 2]
    real = [w for w in words if len(re.sub(r"[^A-Za-z0-9]", "", w[4])) >= 2 and (w[3] - w[1]) <= 2 * hmed] or words
    return max(rect[0], min(w[0] for w in real) - PAD_X), min(rect[2], max(w[2] for w in real) + PAD_X)


def locate(paper, method, qtoks):
    """Align a question on one word source. Returns (match, tri, parts) or None."""
    toks, words, lines = paper.stream(method)
    if not toks:
        return None
    al = vp.align(qtoks, toks)
    a = vp.assess(qtoks, toks, al)
    hits = sorted(a["aligned"].values())
    if not hits:
        return None
    # a fitting alignment can pick up a stray function word or two from a neighbour's line ("the", "of"):
    # drop an edge cluster of <= 2 short aligned words (<= 4 letters) cut off by >= 3 skipped words.
    # (A real two-word tail like "Network Topology" after "[2.5 Marks x 2]" is kept.)
    clusters = [[hits[0]]]
    for h in hits[1:]:
        if h[0] - clusters[-1][-1][0] > 3:
            clusters.append([])
        clusters[-1].append(h)

    def stray(c):
        return len(c) <= 2 and all(len(toks[cj].plain) <= 4 and not toks[cj].crit for cj, _e in c)
    while len(clusters) > 1 and stray(clusters[0]):
        clusters.pop(0)
    while len(clusters) > 1 and stray(clusters[-1]):
        clusters.pop()
    hits = [h for c in clusters for h in c]
    by_col = {}        # (page, column): column 1 is the right half of a 2-up spread
    for cj, _e in hits:
        t = toks[cj]
        by_col.setdefault((t.page, t.box[4]), []).append(t)
    most = max(len(v) for v in by_col.values())
    parts = []
    for (p, col), ts in by_col.items():          # insertion order = reading order
        if len(ts) < 3 and len(ts) < most:      # a stray match elsewhere
            continue
        y0, y1 = min(t.box[1] for t in ts), max(t.box[3] for t in ts)
        clines = [l for l in lines[p] if l[3] == col]
        # take whole lines, then a trailing marks-only line
        for ly0, ly1, _txt, _c in clines:
            if ly1 > y0 and ly0 < y1:
                y0, y1 = min(y0, ly0), max(y1, ly1)
        below = [l for l in clines if l[0] >= y1 - 1]
        if below and MARKS_LINE.match(below[0][2].strip()) and below[0][0] - y1 < 2.5 * (below[0][1] - below[0][0]) + 6:
            y1 = max(y1, below[0][1])
        rect = paper.page_rect(p)
        if any(w[6] for w in words[p]):          # spread: the column is half the page
            mid = (rect[0] + rect[2]) / 2
            rect = (rect[0], rect[1], mid, rect[3]) if col == 0 else (mid, rect[1], rect[2], rect[3])
        x0, x1 = text_band([w for w in words[p] if w[6] == col], rect)
        # band edges: the pad above / below, but never past the midpoint to an overlapping neighbour line
        # (text-layer line boxes overlap: a plain pad would show a sliver of the previous question's last line)
        top, bot = y0 - PAD_Y, y1 + PAD_Y
        ks = [i for i, l in enumerate(clines) if l[1] > y0 and l[0] < y1]
        if ks:
            top = max(top, boundary_above(clines, ks[0]))
            if ks[-1] + 1 < len(clines):
                bot = min(bot, max(y1 - 1, boundary_above(clines, ks[-1] + 1)))
        parts.append((p, (round(x0, 1), round(max(rect[1], top), 1), round(x1, 1),
                          round(min(rect[3], bot), 1))))
    return a["tok"], a["tri"], parts


def _col_of(paper, method, p, rect):
    words = paper.stream(method)[1][p]
    if not any(w[6] for w in words):
        return 0
    pr = paper.page_rect(p)
    return 1 if rect[0] >= (pr[0] + pr[2]) / 2 - 1 else 0


def boundary_above(clines, k):
    """y between printed line k and the line above it: midway between their centres (text-layer line boxes
    overlap, so a line's own top would still show the bottom of the line above)."""
    ly0, ly1 = clines[k][0], clines[k][1]
    top = ly0 - PAD_Y
    if k == 0 or clines[k - 1][1] <= top:
        return top
    py0, py1 = clines[k - 1][0], clines[k - 1][1]
    return max(top, ((py0 + py1) / 2 + (ly0 + ly1) / 2) / 2)


def own_label(qno):
    m = re.match(r"\s*Q?\s*\d+\s*[.(]?\s*\(?\s*([ivx]+|[a-z])\s*\)", str(qno), re.I)
    return m.group(1).lower() if m else None


def snap_top(paper, method, parts, qno, qtoks):
    """Move the top of the first crop band down to the question's own label line ('b) Consider 2 ...') when
    the question's first words are on that line: words above it belong to the previous sub-part. A shared
    stem printed above the label ('Write short notes (any two)' ... '(ii) SMTP') is kept, because the
    question's first words are not on the label line then."""
    lab = own_label(qno)
    if not lab or not parts or not qtoks:
        return parts
    lab_re = re.compile(r"^\W{0,3}" + re.escape(lab) + r"\s*[.):\]}]", re.I)
    lines = paper.stream(method)[2]
    p, (x0, y0, x1, y1) = parts[0]
    col = _col_of(paper, method, p, (x0, y0, x1, y1))
    first = {t.fold for t in qtoks[:4]}
    need = 2 if len(qtoks) >= 3 else 1
    clines = [l for l in lines[p] if l[3] == col]
    for k, (ly0, _ly1, txt, _c) in enumerate(clines):
        if not (y0 + PAD_Y + 2 < ly0 < y1) or not lab_re.match(txt.strip()):
            continue
        # the line must BEGIN with the question's first words: an internal item 'a. What are the ...' of the
        # question itself only shares a word or two with it somewhere
        after = txt.strip()[lab_re.match(txt.strip()).end():]
        if len(first & {t.fold for t in vp.tokenize(after, ocr=True)[:4]}) >= need:
            return [(p, (x0, round(boundary_above(clines, k), 1), x1, y1))] + parts[1:]
        break
    return parts


def extend_for_table(paper, method, parts, n_lines):
    """A question whose table follows its prose: grow the last band down by up to n_lines printed lines (the
    table's rows), continuing at the top of the next page / half in reading order if the table is printed
    there. The usual cuts (next sub-part label, next question) are applied afterwards."""
    _toks, words, lines = paper.stream(method)
    p, (x0, y0, x1, y1) = parts[-1]
    col = _col_of(paper, method, p, (x0, y0, x1, y1))
    # OCR splits a table row over several printed lines: allow twice the table's lines; the cuts at the next
    # sub-part / next question (applied after this) are what stop the crop
    want = 2 * n_lines + 1
    below = [l for l in lines[p] if l[3] == col and l[0] > y1 - PAD_Y - 1]
    take = below[:want]
    out = list(parts)
    if take:
        out[-1] = (p, (x0, y0, x1, round(max(y1, take[-1][1] + PAD_Y), 1)))
    if len(take) < n_lines:                           # the page / half ran out: the table is printed overleaf
        chunks = getattr(paper, "chunks", [])
        k = chunks.index((p, col)) + 1 if (p, col) in chunks else len(chunks)
        while k < len(chunks) and not [l for l in lines[chunks[k][0]] if l[3] == chunks[k][1]]:
            k += 1                                    # skip empty halves of non-spread pages
        if k < len(chunks):
            np_, ncol = chunks[k]
            nl = [l for l in lines[np_] if l[3] == ncol][:want - len(take) + 3]   # + running page header
            if nl:
                rect = paper.page_rect(np_)
                if any(w[6] for w in words[np_]):
                    mid = (rect[0] + rect[2]) / 2
                    rect = (rect[0], rect[1], mid, rect[3]) if ncol == 0 else (mid, rect[1], rect[2], rect[3])
                bx0, bx1 = text_band([w for w in words[np_] if w[6] == ncol], rect)
                out.append((np_, (round(bx0, 1), round(max(rect[1], nl[0][0] - PAD_Y), 1), round(bx1, 1),
                                  round(min(rect[3], nl[-1][1] + PAD_Y), 1))))
    return out


def trim_parts(paper, method, parts, qno, qtext, others, table_rows=0, table_last=False):
    """Cut each crop band where the next sub-part's label line starts ('(b)', 'b)', 'ii.') and where the next
    question of the same paper starts (others: (page, x0, x1, top, paper) of their first crop band).
    A table question whose table comes last is first extended over the table's rows (table_rows lines)."""
    if table_rows and table_last:
        parts = extend_for_table(paper, method, parts, table_rows)
    lines = paper.stream(method)[2]
    labels = next_labels(qno)
    # a question whose own text carries that label (its own (i)/(ii) items) must not be cut at it
    t = vp.normalize(qtext)
    labels = {l for l in labels if not re.search(r"(?:^|[\s(])" + re.escape(l) + r"\s*[.)]", t, re.I)}
    lab_re = re.compile(r"^\W{0,3}(?:" + "|".join(map(re.escape, sorted(labels))) + r")\s*[.):\]}]", re.I) if labels else None
    out = []
    for p, (x0, y0, x1, y1) in parts:
        cut = y1
        col = _col_of(paper, method, p, (x0, y0, x1, y1))
        clines = [l for l in lines[p] if l[3] == col]
        if lab_re:
            for k, (ly0, _ly1, txt, _c) in enumerate(clines):
                if y0 + PAD_Y + 2 < ly0 < cut and lab_re.match(txt.strip()):
                    cut = min(cut, boundary_above(clines, k))
        for op, ox0, ox1, oy0, _pid in others:     # oy0: top of the other question's first band
            if op == p and min(x1, ox1) - max(x0, ox0) > 0.3 * (x1 - x0) and y0 + 2 < oy0 < cut:
                cut = oy0
        if cut - y0 >= 6:
            out.append((p, (x0, y0, x1, round(cut, 1))))
    return out or parts


def crop_match(paper, method, parts, qtoks):
    """(tok, tri) of the question against the words inside the crop band(s) only."""
    toks = [t for t in paper.stream(method)[0]
            if any(t.page == p and r[0] <= (t.box[0] + t.box[2]) / 2 <= r[2] and r[1] <= (t.box[1] + t.box[3]) / 2 <= r[3]
                   for p, r in parts)]
    if not toks or not qtoks:
        return 0.0, 0.0
    a = vp.assess(qtoks, toks, vp.align(qtoks, toks))
    return a["tok"], a["tri"]


def tesseract_text(png, psm):
    try:
        r = subprocess.run([TESSERACT, str(png), "stdout", "--psm", psm], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
    except Exception:  # noqa
        return ""
    return " ".join(r.stdout.split())


def region_ocr(paper, parts, qtoks, tmp):
    """Re-OCR only the crop region(s) at OCR_DPI (psm 6 and 4; whole-page OCR garbles lines that a region
    OCR reads cleanly). Returns (text, tok_match, label) of the better reading, or (None, 0, None)."""
    if not have_tesseract():
        return None, 0.0, None
    from PIL import Image
    best = (None, 0.0, None)
    Path(tmp).mkdir(parents=True, exist_ok=True)
    pngs = []
    for k, (p, (x0, y0, x1, y1)) in enumerate(parts):
        png = Path(tmp) / f"region_{k}.png"
        if paper.doc:
            _save_pixmap(paper.doc[p - 1], png, OCR_DPI, fitz.Rect(x0, y0, x1, y1))
        else:
            s = PNG_DPI / 72.0
            with Image.open(paper.pngs[p - 1]) as im:
                im.crop((int(x0 * s), int(y0 * s), int(x1 * s), int(y1 * s))).save(png)
        pngs.append(png)

    def part_text(png, psm, rot):
        src = png
        if rot:
            src = png.with_name(f"{png.stem}_rot{rot}.png")
            with Image.open(png) as im:
                im.rotate(rot, expand=True).save(src)
        return tesseract_text(src, psm)

    def score(text):
        rt = vp.tokenize(text, ocr=True)
        return vp.assess(qtoks, rt, vp.align(qtoks, rt))["tok"] if rt and qtoks else 0.0

    for psm in ("6", "4"):
        text = " ".join(part_text(png, psm, 0) for png in pngs)
        tok = score(text)
        if best[0] is None or tok > best[1]:
            best = (text, tok, f"region-ocr-psm{psm}")
    # a page scanned sideways (EE ES2023SP, 2026-11-08): read each part turned, keep the turn that reads best for
    # THAT part (pages of one scan can be turned opposite ways, so a 2-page question needs a turn per part)
    if best[1] < vp.RECEIPT_MIN:
        texts, rots = [], []
        for png in pngs:
            cand = [(score(t), r, t) for r in (0, 90, 270, 180) for t in [part_text(png, "6", r)]]
            s, r, t = max(cand, key=lambda c: c[0])
            texts.append(t); rots.append(r)
        text = " ".join(texts)
        tok = score(text)
        if tok > best[1] and any(rots):
            best = (text, tok, "region-ocr-psm6-rot" + "+".join(str(r) for r in rots))
    return best


def region_text(paper, method, parts):
    """The words of one word source inside the crop rect(s), in reading order: the receipt's fresh text."""
    toks, words, _lines = paper.stream(method)
    out = []
    for p, r in parts:
        for w in words[p]:
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            if r[0] <= cx <= r[2] and r[1] <= cy <= r[3]:
                out.append(w[4])
    return " ".join(out)


def manual_parts(spec):
    items = spec if isinstance(spec, list) else [spec]
    parts = []
    for it in items:
        p, r = int(it["page"]), [float(x) for x in it["rect"]]
        if len(r) != 4 or r[2] <= r[0] or r[3] <= r[1]:
            raise ValueError(f"bad rect {r}")
        parts.append((p, tuple(r)))
    return parts


def manual_match(paper, parts, qtoks):
    """(match, method) of the best word source inside the manual rect(s)."""
    best = (None, None)
    for m in paper.methods():
        toks = [t for t in paper.stream(m)[0]
                if any(t.page == p and r[0] <= (t.box[0] + t.box[2]) / 2 <= r[2] and r[1] <= (t.box[1] + t.box[3]) / 2 <= r[3]
                       for p, r in parts)]
        if toks:
            a = vp.assess(qtoks, toks, vp.align(qtoks, toks))
            if best[0] is None or a["tok"] > best[0]:
                best = (a["tok"], m)
    return best


def paper_source(subj, shared, slug):
    man = shared / "manifest.json"
    if man.exists():
        files = json.loads(man.read_text("utf-8")).get("files", {})
        for rel, m in files.items():
            if m.get("slug") == slug and (subj / rel).exists() and rel.lower().endswith(".pdf"):
                return subj / rel, []
    pngs = sorted((shared / "pyq_pages").glob(f"{slug}_p*.png"),
                  key=lambda f: int(re.search(r"_p(\d+)\.png$", f.name).group(1)))
    pngs = [f for f in pngs if re.fullmatch(re.escape(slug) + r"_p\d+\.png", f.name)]
    return None, pngs


def main():
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject")
    ap.add_argument("--scope", required=True, choices=workdir.SCOPES)
    ap.add_argument("--only", nargs="*", help="re-crop only these question ids")
    a = ap.parse_args()
    subj, shared, work = workdir.resolve(a.subject, a.scope)
    bank_path = work / "pyq_bank.json"
    if not bank_path.exists():
        print(f"no bank at {bank_path}\nRESULT BLOCKED: pyq_bank.json missing")
        sys.exit(1)
    bank = json.loads(bank_path.read_text("utf-8"))
    rdir = work / "receipts"
    rdir.mkdir(parents=True, exist_ok=True)
    rjson = vp.receipts_path(work)
    old = json.loads(rjson.read_text("utf-8")) if rjson.exists() else {}
    papers = {p.get("id"): p for p in bank.get("papers", [])}
    qids = {str(q.get("id")) for q in bank.get("questions", [])}
    result = {k: v for k, v in old.items() if k in qids}     # replaced entry by entry as questions are done
    bad, rows = [], []
    finished = False
    try:
        with tempfile.TemporaryDirectory(prefix="receipts_") as tmp:
            cache = {}

            def paper_of(p):
                slug, rng = p.get("source_slug", ""), vp.page_range(p)
                key = (slug, rng)            # question sets of one PDF each get their own page range
                if key not in cache:
                    pdf, pngs = paper_source(subj, shared, slug)
                    sub = Path(tmp) / (slug + (f"_p{rng[0]}-{rng[1]}" if rng else ""))
                    sub.mkdir(exist_ok=True)
                    try:
                        cache[key] = (Paper(pdf, pngs, sub, p.get("reading_order"), rng) if (pdf or pngs)
                                      else f"no PDF or page images for {slug}")
                    except ValueError as e:
                        cache[key] = f"paper {p.get('id')}: {e}"
                return cache[key]

            # pass 1: locate every question of every paper involved, so each crop can stop where the next
            # question of its paper starts (manual rects count as starts too)
            want_papers = {q.get("paper") for q in bank.get("questions", []) if not a.only or str(q.get("id")) in a.only}
            located, starts = {}, {}
            for q in bank.get("questions", []):
                p = papers.get(q.get("paper"))
                if q.get("paper") not in want_papers or not p or isinstance(paper_of(p), str):
                    continue
                paper, qid = paper_of(p), str(q.get("id"))
                qtoks = vp.tokenize(vp.match_text(q))        # prose only: no [table], no $...$ maths
                if q.get("receipt"):
                    try:
                        parts = manual_parts(q["receipt"])
                    except (ValueError, KeyError, TypeError):
                        continue
                else:
                    best = None
                    for m in paper.methods():
                        r = locate(paper, m, qtoks) if qtoks else None
                        if r and r[2] and (best is None or r[0] > best[1][0]):
                            best = (m, r)
                        if best and best[1][0] >= 0.9:
                            break
                    if not best:
                        continue
                    m0, (t0, r0, parts) = best
                    parts = snap_top(paper, m0, parts, q.get("qno", ""), qtoks)
                    best = (m0, (t0, r0, parts))
                    located[qid] = best
                pg, (x0, y0, x1, _y1) = parts[0]
                starts[qid] = (pg, x0, x1, y0, q.get("paper"))

            # pass 2: crop
            for q in bank.get("questions", []):
                qid = str(q.get("id"))
                if a.only and qid not in a.only:
                    continue
                p = papers.get(q.get("paper"))
                if not p:
                    bad.append(qid); rows.append((qid, None, "-", f"unknown paper {q.get('paper')}")); continue
                slug = p.get("source_slug", "")
                paper = paper_of(p)
                if isinstance(paper, str):
                    bad.append(qid); rows.append((qid, None, "-", paper)); continue
                qtoks = vp.tokenize(vp.match_text(q))
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", qid)
                entry = {"paper": q.get("paper"), "file": f"receipts/{safe}.png", "text_sha": vp.receipt_sha(q)}
                try:
                    if q.get("receipt"):
                        parts = manual_parts(q["receipt"])
                        match, wm = manual_match(paper, parts, qtoks) if qtoks else (None, None)
                        entry.update(method="manual", match=round(match, 3) if match is not None else None, tri=None)
                        m = wm
                    else:
                        best = located.get(qid)
                        if not best:
                            raise LookupError("question text not found on the paper's pages")
                        m, (_m0, _t0, parts) = best
                        # stop at the next sub-part's label and at the next question's start (same paper)
                        others = [s for oid, s in starts.items() if oid != qid and s[4] == q.get("paper")]
                        tab = q.get("table") if isinstance(q.get("table"), dict) else None
                        parts = trim_parts(paper, m, parts, q.get("qno", ""), q.get("text") or "", others,
                                           table_rows=len(tab.get("rows") or []) + 1 if tab else 0,
                                           table_last=bool(tab) and not vp.tokenize(
                                               (q.get("text") or "").split(vp.TABLE_MARK, 1)[-1]))
                        match, tri = crop_match(paper, m, parts, qtoks)
                        entry.update(method=m, match=round(match, 3), tri=round(tri, 3))
                    paper.crop(parts, rdir / f"{safe}.png")
                    entry.update(page=parts[0][0], rect=list(parts[0][1]),
                                 parts=[{"page": pg, "rect": list(rc)} for pg, rc in parts])
                    # fresh text of the cropped region; the gate re-checks against it if the corpus is damaged.
                    # A text layer is used as is; an OCR'd region is re-OCR'd on its own when that reads better.
                    if m:
                        entry.update(ocr_text=region_text(paper, m, parts), ocr_method=m,
                                     ocr_is_ocr=m != "pdf-words" or all(pg in paper.scan for pg, _r in parts))
                    if m != "pdf-words" and qtoks and (entry.get("match") or 0) < 0.999:
                        # the paper's own folder (tmp/<slug>_p<a>-<b> for one set of a multi-set PDF, real ML 2026-11-06)
                        rtext, rtok, rlabel = region_ocr(paper, parts, qtoks, paper.tmp or (Path(tmp) / slug))
                        if rtext is not None and rtok > (entry.get("match") or 0):
                            entry.update(ocr_text=rtext, ocr_method=rlabel, ocr_is_ocr=True, match=round(rtok, 3))
                            rot = re.search(r"-rot([\d+]+)$", rlabel or "")
                            if rot:                     # store the crop upright, as it was read (a turn per part)
                                rl = [int(x) for x in rot.group(1).split("+")]
                                entry["rotate"] = rl[0] if len(set(rl)) == 1 else rl
                                paper.crop(parts, rdir / f"{safe}.png", rotate=rl)
                    ok = entry["method"] == "manual" or entry["match"] >= vp.RECEIPT_MIN
                    rows.append((qid, entry.get("match"), entry["method"],
                                 "ok" if ok else f"LOW (< {vp.RECEIPT_MIN}): check the crop, or add a manual rect"))
                    if not ok:
                        bad.append(qid)
                except (LookupError, ValueError, KeyError, RuntimeError, MemoryError, _FZ_ERROR) as e:
                    entry.update(method="none", match=0.0, file=None)
                    bad.append(qid); rows.append((qid, 0.0, "-", str(e)))
                result[qid] = entry
        finished = True
    finally:
        # always leave receipts.json consistent with the PNGs on disk: entries made this run replace the
        # old ones, unprocessed questions keep theirs (a crash mid-run must not orphan new PNGs)
        tmpf = rjson.with_suffix(".json.tmp")
        tmpf.write_text(json.dumps(result, indent=1, ensure_ascii=False), "utf-8")
        os.replace(tmpf, rjson)
        if not finished:
            print(f"receipts.py stopped early: {len(rows)} question(s) processed; receipts.json updated for those", file=sys.stderr)
    for f in rdir.glob("*.png"):          # crops of questions no longer in the bank
        if f.stem not in {re.sub(r"[^A-Za-z0-9_.-]", "_", x) for x in qids}:
            f.unlink()

    print(f"receipts {a.subject} --scope {a.scope}: {len(rows)} question(s) -> {rdir}")
    print(f"{'id':16s} {'match':>6s}  {'method':14s} status")
    for qid, m, meth, st in rows:
        print(f"{qid:16s} {('%.2f' % m) if m is not None else '  -  ':>6s}  {meth:14s} {st}")
    good = len(rows) - len(bad)
    print(f"\n{good}/{len(rows)} receipt(s) good (match >= {vp.RECEIPT_MIN} or manual)")
    print("RESULT PASS" if not bad else f"RESULT BLOCKED: {len(bad)} receipt(s) missing or low-match: {' '.join(bad[:12])}")
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
