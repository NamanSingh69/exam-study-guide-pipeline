"""Automatic layout check of a built PDF: replaces looking at every contact sheet.

    py _pipeline/tools/layout_check.py <pdf> [--pages 3,7-9] [--max 40]

Finds, per page, from the PDF's own text spans and vector drawings (pymupdf):
  outside   text or a drawing that runs past the side margins of the edition's geometry
            (print A4: 20 mm, phone 105x187 mm: 5.5 mm, cheatsheet A4 landscape: 9 mm) or off the paper
  overlap   two pieces of text from different lines printed on top of each other (TikZ nodes, labels)
  on_line   a straight line drawn through the middle of a label (an arrow or edge crossing its text), unless a
            filled node is painted over the line under the label (TikZ fill=white)
  tiny      text below 5 pt (usually a figure shrunk by \\resizebox / scale)

Prints one `LAYOUT p<N> <kind>: ...` line per finding (at most --max), then `FLAGGED <k> page(s): ...`.
Exit 0 always: the check is advisory, and build.py renders contact sheets only for the flagged pages, which are
the only pages an agent needs to look at. Overfull boxes, floats and half-empty pages stay in build.py's log
analysis.
"""
import argparse
import re
import sys
from pathlib import Path

import pymupdf as fitz

MM = 72 / 25.4
TOL = 3 * MM         # list labels hang ~2.2 mm and \rowcolor shading ~2.1 mm into the margin by design
TINY = 5.0           # pt, for words of 3+ characters (sub/superscripts are 1-2 characters and legitimately small)
TINY_ANY = 3.5       # pt, for anything
WORD = re.compile(r"[A-Za-z0-9]")


def frame(w, h):
    """(left, right) text-frame edges for the edition this page size belongs to, else the paper edges."""
    def near(a, b):
        return abs(a - b) < 4
    if near(w, 595.28) and near(h, 841.89):
        return 20 * MM, w - 20 * MM
    if near(w, 841.89) and near(h, 595.28):
        return 9 * MM, w - 9 * MM
    if near(w, 105 * MM) and near(h, 187 * MM):
        return 5.5 * MM, w - 5.5 * MM
    return 3 * MM, w - 3 * MM


def spans(page):
    out = []
    # no mediabox clip: text that runs off the paper must still be seen (and seen whole)
    d = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_MEDIABOX_CLIP)
    for b, blk in enumerate(d.get("blocks", [])):
        for li, line in enumerate(blk.get("lines", [])):
            for s in line.get("spans", []):
                t = s.get("text", "")
                if not t.strip():
                    continue
                c = s.get("color", 0)
                rgb = ((c >> 16) & 255, (c >> 8) & 255, c & 255)
                out.append({"text": t.strip(), "rect": fitz.Rect(s["bbox"]), "size": s.get("size", 0),
                            "line": (b, li), "alnum": len(WORD.findall(t)),
                            "grey": min(rgb) > 140 and max(rgb) - min(rgb) < 30})
    return out


def _clip(p1, p2, r):
    """Liang-Barsky: does segment p1-p2 enter rect r?"""
    x0, y0, dx, dy = p1.x, p1.y, p2.x - p1.x, p2.y - p1.y
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - r.x0), (dx, r.x1 - x0), (-dy, y0 - r.y0), (dy, r.y1 - y0)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def _snip(t, n=28):
    return t if len(t) <= n else t[:n - 1] + "…"


def check_page(page, pno):
    W, H = page.rect.width, page.rect.height
    left, right = frame(W, H)
    sp = spans(page)
    found = []

    def add(kind, msg, rect=None):
        f = {"page": pno, "kind": kind, "msg": msg}
        if rect is not None:
            f["bbox"] = [round(v, 1) for v in rect]
            msg += f" (at {rect.x0 / MM:.0f},{rect.y0 / MM:.0f} mm from top-left)"
            f["msg"] = msg
        found.append(f)

    # outside: text
    for s in sp:
        r = s["rect"]
        if r.x1 <= 0 or r.x0 >= W or r.y1 <= 0 or r.y0 >= H:
            continue   # wholly off the paper: invisible (an included page's cropped content), not a defect
        if r.x1 <= left and s["alnum"] <= 3:
            continue   # line numbers and list labels sitting in the left margin by design
        if r.x0 < left - TOL or r.x1 > right + TOL or r.y0 < 0 or r.y1 > H:
            side = "left" if r.x0 < left - TOL else "right" if r.x1 > right + TOL else "top/bottom"
            over = (left - r.x0) if side == "left" else (r.x1 - right) if side == "right" else 0
            add("outside", f"text '{_snip(s['text'])}' runs past the {side} margin"
                           + (f" by {over / MM:.1f} mm" if over else ""), r)
            break   # one per page is enough to send the agent there
    drawings = page.get_drawings()
    # outside: drawings (ignore hairline page-wide decorations: header/footer rules, full-bleed banners)
    for d in drawings:
        r = d.get("rect")
        if r is None or r.is_empty:
            continue
        if r.width > 0.97 * W:
            continue
        if d.get("color") is None and d.get("type") == "f":
            continue   # fill-only shading (\rowcolor, box backgrounds): no visible edge to cut off
        if r.x0 < left - TOL or r.x1 > right + TOL:
            side = "left" if r.x0 < left - TOL else "right"
            over = (left - r.x0) if side == "left" else (r.x1 - right)
            add("outside", f"a drawing (figure/box) runs past the {side} margin by {over / MM:.1f} mm", r)
            break
    # tiny
    # tiny: only where small text is the MAJORITY of its block (a shrunk figure, table or box). A subscript such as
    # j_rand is small too, but it is a minority inside a normal-size sentence.
    chars, small_chars = {}, {}
    for s in sp:
        b = s["line"][0]
        chars[b] = chars.get(b, 0) + s["alnum"]
        if 0 < s["size"] < TINY:
            small_chars[b] = small_chars.get(b, 0) + s["alnum"]
    small = [s for s in sp if 0 < s["size"] < TINY and s["alnum"]
             and small_chars.get(s["line"][0], 0) > 0.5 * chars[s["line"][0]]
             and (s["alnum"] >= 3 or s["size"] < TINY_ANY)]
    if small:
        s = min(small, key=lambda s: s["size"])
        add("tiny", f"text '{_snip(s['text'])}' is {s['size']:.1f} pt (a scaled figure? use a smaller font, not scale)", s["rect"])
    # overlap: text from different lines on top of each other
    words = sorted((s for s in sp if s["alnum"] >= 2), key=lambda s: s["rect"].y0)
    hits = 0
    for i, a in enumerate(words):
        ra = a["rect"]
        for b in words[i + 1:]:
            rb = b["rect"]
            if rb.y0 >= ra.y1:
                break
            if a["line"] == b["line"] or a["text"] == b["text"]:
                continue   # same line, or the same text printed twice in place (storyboard frames): looks fine
            if min(a["size"], b["size"]) < 0.75 * max(a["size"], b["size"]):
                continue   # a sub/superscript grazing the neighbouring line: normal maths typesetting
            inter = ra & rb
            if inter.is_empty:
                continue
            small_area = min(ra.width * ra.height, rb.width * rb.height) or 1
            vshare = inter.height / (min(ra.height, rb.height) or 1)
            if inter.width * inter.height / small_area > 0.3 and vshare > 0.5:
                add("overlap", f"'{_snip(a['text'])}' and '{_snip(b['text'])}' are printed on top of each other", ra | rb)
                hits += 1
                break
        if hits >= 3:
            break
    # on_line: a stroked straight segment through the middle band of a label
    segs, fills = [], []
    for d in drawings:
        seq = d.get("seqno", 0)
        if d.get("fill") is not None and d.get("rect") is not None:
            fills.append((seq, d["rect"]))
        if d.get("color") is None or not d.get("width"):
            continue
        for it in d.get("items", []):
            if it[0] == "l":
                segs.append((seq, it[1], it[2]))
    hits = 0
    for s in sp:
        if s["alnum"] < 2 or s["grey"] or hits >= 3:   # grey text under a line = a deliberate strike-out
            continue
        r = s["rect"]
        band = fitz.Rect(r.x0 + 1, r.y0 + 0.35 * r.height, r.x1 - 1, r.y0 + 0.65 * r.height)
        if band.is_empty:
            continue
        mid = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        for seq, p1, p2 in segs:
            if not _clip(p1, p2, band):
                continue
            if any(fs > seq and fr.contains(mid) for fs, fr in fills):
                continue   # a filled node is painted over the line under this label
            add("on_line", f"a line is drawn through the label '{_snip(s['text'])}' (move the label: above/below, "
                           f"or give the node fill=white)", r)
            hits += 1
            break
    return found


def parse_pages(spec):
    if not spec:
        return None
    out = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def check(pdf, pages=None):
    """List of {'page': 1-based, 'kind', 'msg'} for the PDF (or only `pages`)."""
    out = []
    with fitz.open(pdf) as doc:
        for i, page in enumerate(doc):
            if pages and i + 1 not in pages:
                continue
            out += check_page(page, i + 1)
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("--pages", help="e.g. 3,7-9 (1-based)")
    ap.add_argument("--max", type=int, default=40, help="most LAYOUT lines to print")
    a = ap.parse_args()
    found = check(Path(a.pdf), parse_pages(a.pages))
    for f in found[:a.max]:
        print(f"LAYOUT p{f['page']} {f['kind']}: {f['msg']}")
    if len(found) > a.max:
        print(f"LAYOUT ... {len(found) - a.max} more")
    pages = sorted({f["page"] for f in found})
    print(f"FLAGGED {len(pages)} page(s)" + (": " + ",".join(map(str, pages)) if pages else ""))


if __name__ == "__main__":
    main()
