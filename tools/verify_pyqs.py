"""
verify_pyqs.py: the hard gate against fabricated or mis-transcribed PYQs (Round 4).

Every question in <SUBJ>/work/<scope>/pyq_bank.json is aligned against the text of ITS OWN paper
(work/corpus/<source_slug>.md) with a fitting alignment: the whole question against the best-matching
window of the paper. Then:

  tokens      every token of >= 2 characters counts, plus every number of any length. Case-folded;
              ligatures, quotes, dashes and the multiplication sign are normalised; on OCR'd pages the
              l / 1 / I confusion is folded on both sides.
  tok         fraction of the question's tokens aligned to a token of the window        >= TOK_MIN
  tri         word-trigram containment of the question in the window                    >= TRI_MIN
  critical    every number and ALL-CAPS token (>= 2 letters) must be aligned exactly, in order, inside
              the matched window. A critical token that is in the window but not in place is tolerated
              only if the question is verified "vision" and its ocr_fixes names that token.
  short       a question of fewer than MIN_TOKENS tokens needs verified: "vision"
  unique      a question must own >= UNIQUE_MIN aligned tokens that no other question of the paper uses
              (blocks a sub-part duplicated over a dropped one)

Paper checks: >= 1 question; marks must be JSON numbers > 0; marks must add up to full_marks allowing for
choice (compulsory questions + k equal-valued optional questions, internal "any two" choice honoured; the
counts in the paper's `pattern` string are checked when it states them); the corpus file must exist.
Bank checks: non-empty; required keys; unique ids; known paper / cluster / blueprint topic; no paper banked
twice. Receipts (receipts.py): every question needs receipts/<qid>.png with a match >= RECEIPT_MIN for its
current text; a low match is accepted only with verified: "vision" plus a manual "receipt" rect.

  py _pipeline/tools/verify_pyqs.py CN --scope midsem [--all]
  exit 0 = RESULT PASS, 1 = RESULT BLOCKED, 2 = usage error
"""
import argparse, hashlib, json, re, sys, unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workdir  # noqa: E402

TOK_MIN = 0.80
TRI_MIN = 0.60
MIN_TOKENS = 4
UNIQUE_MIN = 2
RECEIPT_MIN = 0.60
EDIT_MAX = 0.04      # unaligned question tokens not named in ocr_fixes: at most max(1, 4 %)
REQUIRED = ("id", "paper", "qno", "marks", "text", "topic", "cluster", "type")

# ----------------------------------------------------------------------------- text normalisation
_TRANS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
    "×": "x", "­": "", "​": "", "﻿": "",
})
TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)+[A-Za-z]*|[A-Za-z0-9]+(?:'[A-Za-z]+)?")
_FOLD = str.maketrans("i10", "llo")  # after casefold: I/i/l/1 -> l, 0 -> o (compared on OCR'd text only)


def normalize(s):
    return unicodedata.normalize("NFKC", s or "").translate(_TRANS)


def _numcanon(t):
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)   # 1,000 -> 1000
    return t.replace(",", ".")                        # OCR 2,5 -> 2.5


class Tok:
    __slots__ = ("raw", "plain", "fold", "crit", "ocr", "page", "box", "strict")

    def __init__(self, raw, ocr=False, page=None, box=None):
        self.raw = raw
        p = raw.casefold().replace("'", "")
        if any(ch.isdigit() for ch in p):
            p = _numcanon(p)
        self.plain = p
        self.fold = p.translate(_FOLD)
        if any(ch.isdigit() for ch in raw):
            self.crit = "number"
        elif len(raw) >= 2 and raw.isalpha() and raw.isupper():
            self.crit = "acronym"
        else:
            self.crit = None
        self.ocr, self.page, self.box = ocr, page, box
        self.strict = False      # OCR copy of a page that has a clean text layer: no OCR-damage excuse

    def __repr__(self):
        return self.raw


def tokenize(s, ocr=False, page=None, box=None):
    s = normalize(s)
    if ocr:                     # OCR reads a lone 1 (or l / I) as a pipe: "by | MSS"
        s = s.replace("|", "1")
    out = []
    for m in TOKEN_RE.finditer(s):
        raw = m.group(0)
        if len(raw) >= 2 or raw.isdigit():
            out.append(Tok(raw, ocr, page, box))
    return out


PAGE_RE = re.compile(r"^## \[(?P<slug>[^\]]+?) p(?P<page>\d+)\](?P<tag>[^\n]*)$", re.M)
ALT_OCR_RE = re.compile(r"^\[OCR of the page image[^\n]*\]\s*$", re.M)


MARKS_NOTE_RE = re.compile(r"([\[({])\s*(\d+(?:\.\d+)?)\s*(marks?)?\s*([\])}])", re.I)


def _is_marks_note(m):
    # '[5]', '[3 Marks]', '(2 marks)', OCR's '(5]' / '[5)'; never a bare '(2)' as in 'C1(2)'
    return bool(m.group(3)) or m.group(1) in "[{" or m.group(4) in "]}"


def strip_marks(text, marks):
    """Drop the margin's marks annotations ('[5]', '[3 Marks]', '(2 marks)') that OCR interleaves into question
    lines, when the number is one of the paper's sub-part marks. Other bracketed numbers stay."""
    if not marks:
        return text
    return MARKS_NOTE_RE.sub(lambda m: " " if _is_marks_note(m) and float(m.group(2)) in marks else m.group(0), text)


def corpus_tokens(text, marks=None, pages=None, rough=()):
    """Tokens of an ingest corpus file, tagged with page number and whether that text is OCR quality.

    marks: the paper's sub-part marks (annotations with these numbers are dropped); pages: (first, last) when
    several papers share one PDF; rough: pages whose *text layer* is itself OCR (a scanner's invisible text
    over the page image, or a file ingest rated POOR): they count as OCR for the OCR-damage rules."""
    toks = []
    heads = list(PAGE_RE.finditer(text))
    for k, h in enumerate(heads):
        body = text[h.end(): heads[k + 1].start() if k + 1 < len(heads) else len(text)]
        page, ocr = int(h.group("page")), "(OCR)" in h.group("tag")
        if pages and not pages[0] <= page <= pages[1]:
            continue
        parts = ALT_OCR_RE.split(body, maxsplit=1)
        toks += tokenize(strip_marks(parts[0], marks), ocr=ocr or page in rough, page=page)
        if len(parts) > 1:
            alt = tokenize(strip_marks(parts[1], marks), ocr=True, page=page)
            if not ocr and page not in rough:     # the page has a clean text layer: it decides
                for t in alt:
                    t.strict = True
            toks += alt
    return toks


def scan_layer_pages(pdf):
    """Pages of a PDF whose text layer is a scanner's OCR: (almost) all of its text invisible (render mode 3)
    over an image covering (almost) the whole page."""
    out = set()
    try:
        import pymupdf
        doc = pymupdf.open(pdf)
    except Exception:  # noqa
        return out
    for i, page in enumerate(doc, start=1):
        try:
            chars = inv = 0
            for tr in page.get_texttrace():
                n = len(tr["chars"])
                chars += n
                inv += n if tr["type"] == 3 else 0
            if not chars or inv < 0.9 * chars:
                continue
            area = abs(page.rect) or 1
            cover = max((abs(pymupdf.Rect(im["bbox"]) & page.rect) / area for im in page.get_image_info()), default=0)
            if cover >= 0.9:
                out.add(i)
        except Exception:  # noqa
            continue
    return out


def page_range(paper):
    """(first, last) from a paper's "pages": [first, last] (several papers in one PDF), else None."""
    p = paper.get("pages")
    if isinstance(p, list) and len(p) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in p) \
            and 1 <= p[0] <= p[1]:
        return (p[0], p[1])
    return None


# ----------------------------------------------------------------------------- visual-only content
TABLE_MARK = "[table]"
MATH_MAX = 0.60      # at most this share of a question's tokens may sit inside $...$


def math_spans(t):
    """([(start, end, content)], unmatched_dollar_positions) of $...$ maths in a question text.
    '\\$' is a literal dollar. A '$' before a digit is currency ('$17,000 and ...') unless its span is a compact
    formula with an operator and no spaces ('$1/2$', '$10^8$')."""
    pos = [m.start() for m in re.finditer(r"(?<!\\)\$", t)]
    spans, loose, i = [], [], 0
    while i < len(pos):
        a = pos[i]
        if i + 1 < len(pos):
            content = t[a + 1:pos[i + 1]]
            digit_start = content[:1].isdigit()
            if content.strip() and (not digit_start or (re.search(r"[/^_\\=+*{}()]", content)
                                                        and not re.search(r"\s", content))):
                spans.append((a, pos[i + 1] + 1, content))
                i += 2
                continue
        if not t[a + 1:a + 2].isdigit():
            loose.append(a)                      # an opening $ with no partner
        i += 1
    return spans, loose


def match_text(q):
    """The question's prose for the text-window match: the [table] placeholder and $...$ maths removed."""
    t = (q.get("text") or "").replace(TABLE_MARK, " ")
    spans, _loose = math_spans(t)
    for a, b, _c in reversed(spans):
        t = t[:a] + " " + t[b:]
    return t


def visual_parts(q):
    """(has_visual, problems) for a question's table and $...$ maths, which only the page image can confirm."""
    t, probs = q.get("text") or "", []
    tab = q.get("table")
    has = False
    if tab is not None:
        has = True
        if TABLE_MARK not in t:
            probs.append(f"has a table but no {TABLE_MARK} placeholder in its text")
        elif t.count(TABLE_MARK) > 1:
            probs.append(f"{t.count(TABLE_MARK)} {TABLE_MARK} placeholders for one table")
        hdr, rows = (tab.get("header"), tab.get("rows")) if isinstance(tab, dict) else (None, None)
        if not isinstance(hdr, list) or not hdr or not isinstance(rows, list) or not rows \
                or not all(isinstance(r, list) for r in rows):
            probs.append("malformed table: needs {\"header\": [..], \"rows\": [[..], ..]} with at least one row")
        else:
            for i, r in enumerate(rows, 1):
                if len(r) != len(hdr):
                    probs.append(f"table row {i} has {len(r)} cell(s), header has {len(hdr)}")
            cells = [("header", c) for c in hdr] + [(f"row {i}", c) for i, r in enumerate(rows, 1) for c in r]
            empty = [w for w, c in cells if not isinstance(c, (str, int, float)) or isinstance(c, bool)
                     or (str(c).strip() == "")]
            if empty:
                probs.append(f"table has an empty cell in {empty[0]} (write '-' for a printed dash)")
    elif TABLE_MARK in t:
        probs.append(f"{TABLE_MARK} placeholder but no table field")
    found, loose = math_spans(t)
    spans = [c for _a, _b, c in found]
    if loose:
        probs.append("unbalanced $ (write maths as $...$; a literal dollar as \\$)")
    if spans:
        has = True
        n_in = len(tokenize(" ".join(spans)))
        n_out = len(tokenize(match_text(q)))
        if n_in + n_out and n_in / (n_in + n_out) > MATH_MAX:
            probs.append(f"{n_in} of {n_in + n_out} tokens are inside $...$ (max {MATH_MAX:.0%}): only formulas "
                         f"go in $...$, the prose is matched against the paper")
    return has, probs


def receipt_sha(q):
    """What a receipt certifies: the question text, plus its table when it has one."""
    t = q.get("text") or ""
    if q.get("table") is not None:
        t += "\n" + json.dumps(q["table"], sort_keys=True, ensure_ascii=False)
    return text_sha(t)


# ----------------------------------------------------------------------------- alignment
def _lev_le(a, b, k):
    """True if the edit distance of a and b is <= k (small k, short words)."""
    if abs(len(a) - len(b)) > k:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > k:
            return False
        prev = cur
    return prev[-1] <= k


_EQ = {}


def tok_eq(q, c):
    """2 = same token, 1 = OCR-typo-close word (never for numbers/acronyms), 0 = different."""
    if (q.fold == c.fold) if c.ocr else (q.plain == c.plain):
        return 2
    if q.crit or c.crit == "number" or len(q.plain) < 4 or not q.plain.isalpha():
        return 0
    key = (q.fold, c.fold)
    r = _EQ.get(key)
    if r is None:
        r = 1 if _lev_le(q.fold, c.fold, max(1, len(q.fold) // 5)) else 0
        _EQ[key] = r
    return r


MATCH, FUZZY, MISMATCH, QGAP, CGAP = 2.0, 1.0, -1.0, -1.0, -0.25


def _fit(q, c):
    """Fitting alignment: all of q against a free-ended stretch of c. Returns (score, pairs)."""
    n, m = len(q), len(c)
    prev = [0.0] * (m + 1)
    ptrs = []
    for i in range(1, n + 1):
        qi = q[i - 1]
        eqrow = [tok_eq(qi, cj) for cj in c]
        cur = [prev[0] + QGAP] + [0.0] * m
        p = bytearray(m + 1)
        p[0] = 1
        for j in range(1, m + 1):
            e = eqrow[j - 1]
            d = prev[j - 1] + (MATCH if e == 2 else FUZZY if e == 1 else MISMATCH)
            u = prev[j] + QGAP
            l = cur[j - 1] + CGAP
            if d >= u and d >= l:
                cur[j] = d; p[j] = 0
            elif u >= l:
                cur[j] = u; p[j] = 1
            else:
                cur[j] = l; p[j] = 2
        ptrs.append((p, eqrow))
        prev = cur
    j = max(range(m + 1), key=lambda x: prev[x])
    score = prev[j]
    pairs = []   # (qi, cj or None, e)
    i = n
    while i > 0:
        p, eqrow = ptrs[i - 1]
        mv = p[j] if j > 0 else 1
        if mv == 0:
            pairs.append((i - 1, j - 1, eqrow[j - 1])); i -= 1; j -= 1
        elif mv == 1:
            pairs.append((i - 1, None, 0)); i -= 1
        else:
            j -= 1
    pairs.reverse()
    return score, pairs


def align(q, c):
    """Align question tokens q against corpus tokens c. Seeds the DP on the densest stretches."""
    n, M = len(q), len(c)
    res = {"pairs": [], "lo": None, "hi": None, "score": float("-inf")}
    if n == 0 or M == 0:
        return res
    qp, qf = {t.plain for t in q}, {t.fold for t in q}
    hits = [1 if ((t.fold in qf) if t.ocr else (t.plain in qp)) else 0 for t in c]
    w = max(n, 5)
    pre = [0]
    for h in hits:
        pre.append(pre[-1] + h)
    sums = [(pre[min(M, s + w)] - pre[s], s) for s in range(0, max(1, M - w + 1))]
    sums.sort(reverse=True)
    seeds = []
    for _sum, s in sums:
        if all(abs(s - t) >= w for t in seeds):
            seeds.append(s)
        if len(seeds) == 2:
            break
    for s in seeds:
        lo, hi = max(0, s - n - 10), min(M, s + 2 * n + 10)
        score, pairs = _fit(q, c[lo:hi])
        if score > res["score"]:
            pairs = [(qi, (cj + lo) if cj is not None else None, e) for qi, cj, e in pairs]
            res = {"pairs": pairs, "score": score}
    al = [cj for _qi, cj, e in res["pairs"] if cj is not None and e]
    res["lo"], res["hi"] = (min(al), max(al)) if al else (None, None)
    return res


def assess(q, c, al):
    """Containment metrics of question tokens q in corpus tokens c, given align() output."""
    n = len(q)
    aligned = {qi: (cj, e) for qi, cj, e in al["pairs"] if cj is not None and e}
    subs = {qi: cj for qi, cj, e in al["pairs"] if cj is not None and not e}
    tok = len(aligned) / n if n else 0.0
    lo, hi = al["lo"], al["hi"]
    window = c[lo:hi + 1] if lo is not None else []
    if n >= 3 and window:
        keys = [c[aligned[i][0]].fold if i in aligned else q[i].fold for i in range(n)]
        wk = [t.fold for t in window]
        wtri = {tuple(wk[k:k + 3]) for k in range(len(wk) - 2)}
        qtri = [tuple(keys[k:k + 3]) for k in range(n - 2)]
        tri = sum(t in wtri for t in qtri) / len(qtri)
    else:
        tri = tok
    return {"tok": tok, "tri": tri, "aligned": aligned, "subs": subs, "window": window,
            "lo": lo, "hi": hi}


# ----------------------------------------------------------------------------- bank helpers
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10}


def _num(s):
    s = s.lower()
    return int(s) if s.isdigit() else WORDNUM.get(s)


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def group_key(qno):
    """'3(a) [2nd Q3]' -> '3 [2nd Q3]'; '1(j)' -> '1'; '2(iv)' -> '2'; either-or alternative
    '1(b) OR' / '1(b)OR' / '1 OR (b)' -> '1 OR'. None if no question number."""
    m = re.match(r"\s*Q?\s*(\d+)", str(qno), re.I)
    if not m:
        return None
    rest = str(qno)[m.end():]
    alt_re = r"(?<![A-Za-z])OR(?![A-Za-z])"          # upper-case OR only
    alt = bool(re.search(alt_re, rest))
    rest = re.sub(alt_re, " ", rest)
    rest = re.sub(r"^\s*[.)]?\s*\(?\s*(?:[ivxlc]+|[a-z])\s*(?:\)|\.(?=\s)|(?=\s|\[|$))", "", rest, count=1, flags=re.I)
    key = (m.group(1) + " " + rest.strip()).strip()
    return key + " OR" if alt else key


def text_sha(s):
    return hashlib.sha1(normalize(s).encode("utf-8")).hexdigest()[:16]


def check_marks(pid, paper, qs):
    """Marks must add up to full marks allowing for choice. Returns (problems, summary)."""
    probs = []
    fm = paper.get("full_marks")
    if not is_number(fm) or fm <= 0:
        return [f"paper {pid}: full_marks {fm!r} is not a positive number"], ""
    if any(not is_number(q.get("marks")) or q["marks"] <= 0 for q in qs):
        return [], ""   # reported per question
    groups = {}
    for q in qs:
        g = group_key(q.get("qno", ""))
        if g is None:
            probs.append(f"paper {pid}: cannot read a question number from qno {q.get('qno')!r} ({q.get('id')})")
            continue
        groups.setdefault(g, []).append(q)
    if probs:
        return probs, ""
    comp, opt, gv = 0.0, {}, {}
    for g, gq in groups.items():
        flags = {bool(q.get("compulsory")) for q in gq}
        if len(flags) > 1:
            probs.append(f"paper {pid}: Q{g} mixes compulsory and optional sub-parts")
            continue
        marks = sorted((float(q["marks"]) for q in gq), reverse=True)
        k_in = None
        for q in gq:
            t = normalize(q.get("text", ""))
            m = re.search(r"\b(?:any|attempt)\s+(\w+)\b", t, re.I)
            if not (m and _num(m.group(1)) and len(gq) > 1):
                continue
            # "any two of the following: i. .. ii. .. iii. .." inside ONE sub-part is that sub-part's own
            # choice (it carries its full marks); only a choice across banked sub-parts is group-level. "Any two:
            # (i) .. (ii) .." over exactly its own two items (labels that are not the group's banked sub-parts) is
            # also its own wording (HPC ES2024 7(b), 2026-11-08)
            items = set(x.lower() for x in re.findall(r"(?:^|[\s(])([ivx]+|[a-h])[.)]\s", t[m.end():], re.I))
            banked = {x.lower() for b in gq for x in re.findall(r"\(([ivx]+|[a-z])\)", b.get("qno", ""), re.I)}
            if len(items) > _num(m.group(1)) or len(items - banked) >= _num(m.group(1)):
                continue
            # a group-level choice names its choice set: "any two of the following", "answer any two", or the
            # banked sub-part labels right after it ("(any two). (i) ..."). A free "examine any two distance
            # measures" is the question's own content, not a choice over sub-parts.
            tail = t[m.end():m.end() + 40]
            if not (re.search(r"\b(?:of|from)\s+the\s+following\b", tail, re.I)
                    or re.search(r"\b(?:answer|attempt)\s+any\b", t[max(0, m.start() - 8):m.end()], re.I)
                    or re.match(r"[\s).,:;\]]*\(?(?:[ivx]+|[a-h])[.)]\s", tail, re.I)
                    or re.search(r"\bshort\s+notes?\b", t[:m.end()], re.I)):
                continue
            k_in = _num(m.group(1))
        if k_in and k_in >= len(gq):
            probs.append(f"paper {pid}: Q{g} says 'any {k_in}' but only {len(gq)} part(s) are banked: "
                         f"a sub-part is missing")
            continue
        gv[g] = (sum(marks[:k_in] if k_in else marks), flags == {True})
    # either-or pairs ("Qn ... OR ..."): Qn and Qn OR are ONE choice slot worth one alternative
    slots = {}
    for g in gv:
        slots.setdefault(g[:-3] if g.endswith(" OR") else g, []).append(g)
    for base, alts in slots.items():
        if base not in gv:
            probs.append(f"paper {pid}: Q{base} OR is banked but its first alternative Q{base} is not")
            continue
        if len(alts) == 2:
            (v1, c1), (v2, c2) = gv[base], gv[base + " OR"]
            if abs(v1 - v2) > 1e-6 or c1 != c2:
                probs.append(f"paper {pid}: Q{base} ({v1:g}) and its OR alternative ({v2:g}) carry different "
                             f"marks: sub-part missing or extra?")
                continue
        val, is_comp = gv[base]
        if is_comp:
            comp += val
        else:
            opt[base] = val
    if probs:
        return probs, ""
    pat = normalize(paper.get("pattern", ""))
    want_k = want_n = None
    m = re.search(r"\bany\s+(\w+)\s+(?:questions?\s+)?(?:of|from)\s+(?:Q\.?\s*(\d+)\s*(?:-|to)\s*Q?\.?\s*(\d+)|the\s+(?:remaining|rest|other)\s+(\w+))",
                  pat, re.I)
    if m:
        want_k = _num(m.group(1))
        if m.group(2):
            want_n = int(m.group(3)) - int(m.group(2)) + 1
        elif m.group(4):
            want_n = _num(m.group(4))
    m = re.search(r"Q\.?\s*(\d+)\s+compulsory\s*\(?\s*(\d+)\s*x\s*(\d+(?:\.\d+)?)", pat, re.I)
    if m:
        g = m.group(1)
        gq = groups.get(g, [])
        n1, m1 = int(m.group(2)), float(m.group(3))
        if len(gq) != n1 or any(abs(float(q["marks"]) - m1) > 1e-6 for q in gq):
            probs.append(f"paper {pid}: pattern says Q{g} is {n1} x {m1:g} marks, bank has "
                         f"{len(gq)} part(s) worth {[q['marks'] for q in gq]}")
    if not opt:
        if abs(comp - fm) > 1e-6:
            probs.append(f"paper {pid}: banked marks add up to {comp:g}, full marks {fm:g} (no optional questions)")
        return probs, f"{comp:g} compulsory = {fm:g}"
    vals = sorted(set(round(v, 6) for v in opt.values()))
    if len(vals) > 1:
        detail = ", ".join(f"Q{g}={v:g}" for g, v in opt.items())
        probs.append(f"paper {pid}: optional questions carry unequal marks ({detail}): sub-part missing or extra?")
        return probs, ""
    v = vals[0]
    k = (fm - comp) / v
    if abs(k - round(k)) > 1e-6 or not (1 <= round(k) <= len(opt)):
        probs.append(f"paper {pid}: compulsory {comp:g} + k x {v:g} cannot make full marks {fm:g} "
                     f"with {len(opt)} optional question(s)")
        return probs, ""
    k = round(k)
    if want_k is not None and want_k != k:
        probs.append(f"paper {pid}: pattern says answer {want_k} optional questions, the marks imply {k}")
    n_alts = sum(len(slots[b]) for b in opt)       # a pattern may count either-or alternatives separately
    if want_n is not None and want_n not in (len(opt), n_alts):
        probs.append(f"paper {pid}: pattern lists {want_n} optional questions, bank has {len(opt)} "
                     f"({', '.join('Q' + g for g in opt)})")
    ors = sum(1 for b in opt if len(slots[b]) == 2)
    return probs, (f"{comp:g} compulsory + {k} of {len(opt)} x {v:g} = {fm:g}"
                   + (f" ({ors} either-or pair(s))" if ors else ""))


def receipts_path(work):
    return work / "receipts" / "receipts.json"


# ----------------------------------------------------------------------------- the gate
_CACHE = {}


def _clean_crit(t):
    """A legible number or acronym (a mismatch with one may be a swap)."""
    if t.crit == "number":
        return bool(re.fullmatch(r"\d+(?:\.\d+)?(?:st|nd|rd|th)?", t.plain))
    return t.crit == "acronym"


def _subseq(short, long):
    it = iter(long)
    return len(short) < len(long) and all(ch in it for ch in short)


def is_swap(t, other):
    """The paper shows a DIFFERENT legible number/acronym where the question has t: a swap, never excused.
    OCR near-misses are not swaps: a number whose digits survive as a strict subsequence ('$00,000' for
    '800,000'), an acronym within edit distance 1 (2 from 5 letters: 'EPRAME' for 'FRAME')."""
    if other is None or not _clean_crit(other) or other.fold == t.fold:
        return False
    if t.crit == "number" and other.crit == "number":
        return not _subseq(other.plain, t.plain)
    if t.crit == "acronym" and other.crit == "acronym":
        return not _lev_le(t.fold, other.fold, 1 if len(t.plain) <= 4 else 2)
    return True


def check_question(q, ctoks, ckey, receipt_ok=False):
    """Text checks of one question against its paper's tokens. Returns (metrics, reasons, notes).

    A number or ALL-CAPS token not aligned in place is excused only when ALL of these hold: the matched window
    is OCR text (never a text layer); the question is verified "vision"; the token is named in its ocr_fixes;
    its receipt image exists with match >= RECEIPT_MIN; and the paper does not show a different legible
    number/acronym at that spot (a swap is never excused)."""
    text = q.get("text")
    reasons, notes = [], []
    if not isinstance(text, str) or not text.strip():
        return {"tok": 0.0, "tri": 0.0, "n": 0}, ["empty question text"], notes
    vision = q.get("verified") == "vision"
    # a table and $...$ maths cannot be read reliably by OCR: only the page image (receipt) confirms them
    has_visual, vprobs = visual_parts(q)
    reasons += vprobs
    if has_visual and not (vision and receipt_ok):
        reasons.append("its table / $...$ maths can only be checked on the page image: needs verified: \"vision\" "
                       "and a good receipt")
    elif has_visual:
        notes.append("table / maths confirmed by vision + receipt")
    text = match_text(q)
    qt = tokenize(text)
    if len(qt) < MIN_TOKENS and not vision:
        reasons.append(f"only {len(qt)} token(s) and not vision-verified")
    if not qt:
        return {"tok": 0.0, "tri": 0.0, "n": 0}, reasons or ["no tokens"], notes
    k = (ckey, text)
    if k not in _CACHE:
        al = align(qt, ctoks)
        _CACHE[k] = (al, assess(qt, ctoks, al))
    al, a = _CACHE[k]
    met = {"tok": a["tok"], "tri": a["tri"], "n": len(qt), "lo": a["lo"], "hi": a["hi"],
           "cpos": {cj for cj, _e in a["aligned"].values()}}
    if a["tok"] < TOK_MIN:
        reasons.append(f"only {a['tok']:.0%} of its tokens found in the paper (need {TOK_MIN:.0%})")
    if a["tri"] < TRI_MIN:
        reasons.append(f"word-trigram containment {a['tri']:.0%} (need {TRI_MIN:.0%})")
    wplain = {t.plain for t in a["window"]}
    wfold = {t.fold for t in a["window"] if t.ocr}
    fixes = normalize(q.get("ocr_fixes") or "").casefold()
    fix_toks = {t.plain for t in tokenize(q.get("ocr_fixes") or "")}
    # verbatim means: only OCR typos fixed. A word the paper does not have there must be named in ocr_fixes.
    unexplained = [t.raw for i, t in enumerate(qt) if i not in a["aligned"] and t.plain not in fix_toks]
    allow = max(1, round(EDIT_MAX * len(qt)))
    met["edits"] = len(unexplained)
    if len(unexplained) > allow:
        reasons.append(f"{len(unexplained)} unexplained edit(s) vs the paper (max {allow}; name OCR fixes in "
                       f"ocr_fixes): {' '.join(unexplained[:8])}")
    ocr_window = bool(a["window"]) and all(t.ocr and not t.strict for t in a["window"])
    for i, t in enumerate(qt):
        if not t.crit:
            continue
        if i in a["aligned"] and a["aligned"][i][1] == 2:
            continue
        present = t.plain in wplain or t.fold in wfold
        other = ctoks[a["subs"][i]] if i in a["subs"] else None
        swap = is_swap(t, other)
        if present or swap:
            why = f"{t.crit} '{t.raw}' out of place (the paper has '{other.raw if other else 'nothing'}' there)"
        else:
            why = f"{t.crit} '{t.raw}' not in the matched paper text"
        if not swap and ocr_window and vision and t.plain in fix_toks and receipt_ok:
            notes.append(f"{t.crit} '{t.raw}' read through OCR damage (ocr_fixes; see the receipt)")
        else:
            reasons.append(why)
    return met, reasons, notes


PYQ_CATEGORIES = ("pyq_midsem", "pyq_endsem")


def check_no_papers(bank, shared, topics, probs, out):
    """Weak-input mode: a bank with "no_papers": true passes only if the subject really has no papers."""
    if bank.get("papers") or bank.get("questions"):
        probs.append(f"no_papers is true but the bank has {len(bank.get('papers') or [])} paper(s) and "
                     f"{len(bank.get('questions') or [])} question(s)")
    man = shared / "manifest.json"
    if not man.exists():
        probs.append("manifest.json missing: cannot confirm the subject has no past papers (run ingest.py)")
    else:
        try:
            files = json.loads(man.read_text("utf-8")).get("files", {})
            pyq = sorted(rel for rel, m in files.items() if m.get("category") in PYQ_CATEGORIES)
            if pyq:
                probs.append(f"no_papers is true but ingest found {len(pyq)} past-paper file(s): "
                             f"{', '.join(pyq[:5])}{' ...' if len(pyq) > 5 else ''}: bank them")
        except (ValueError, AttributeError) as e:
            probs.append(f"manifest.json unreadable: {e}")
    clusters = bank.get("clusters") or []
    if not clusters:
        probs.append("no_papers bank has no clusters (they come from the syllabus and the seniors' lists)")
    seen = set()
    for c in clusters:
        cid = c.get("id")
        if cid in seen:
            probs.append(f"duplicate cluster id {cid}")
        seen.add(cid)
        if topics and c.get("topic") not in topics:
            probs.append(f"cluster {cid}: topic {c.get('topic')} not in blueprint")
    out(f"no_papers bank: {len(clusters)} cluster(s), 0 papers (weak-input mode)")
    for p in probs:
        out(f"PROBLEM {p}")
    if probs:
        return False, [f"{len(probs)} bank/paper problem(s)"], None
    return True, [], "no papers: weak-input mode"


def run(subject, scope, show_all=False, out=print):
    """Run the gate. Returns (ok, blockers, mode); mode is a note for the PASS line or None."""
    _subj, shared, work = workdir.resolve(subject, scope)
    blockers = []
    bank_path = work / "pyq_bank.json"
    if not bank_path.exists():
        out(f"no bank at {bank_path}")
        return False, ["pyq_bank.json missing"], None
    try:
        bank = json.loads(bank_path.read_text("utf-8"))
    except (ValueError, OSError) as e:
        out(f"cannot read {bank_path}: {e}")
        return False, ["pyq_bank.json unreadable"], None
    papers_l = bank.get("papers") or []
    questions = bank.get("questions") or []

    topics = None
    bp_path = work / "blueprint.json"
    if bp_path.exists():
        try:
            bp = json.loads(bp_path.read_text("utf-8"))
            topics = {t["id"] for u in bp.get("units", []) for t in u.get("topics", [])}
        except (ValueError, KeyError, TypeError):
            pass
    probs = []
    if topics is None:
        probs.append("blueprint.json missing or unreadable: topics cannot be checked")
        topics = set()

    if bank.get("no_papers") is True:
        return check_no_papers(bank, shared, topics, probs, out)
    if "no_papers" in bank and bank["no_papers"] is not False:
        out(f"no_papers must be true or false, not {bank['no_papers']!r}")
        return False, ["bad no_papers flag"], None
    if not papers_l or not questions:
        out(f"empty bank: {len(papers_l)} paper(s), {len(questions)} question(s)"
            + ("" if papers_l else " (a subject with no past papers at all needs \"no_papers\": true)"))
        return False, ["empty bank"], None

    papers = {}
    for p in papers_l:
        if p.get("id") in papers:
            probs.append(f"duplicate paper id {p.get('id')}")
        papers[p.get("id")] = p
    clusters = {c.get("id"): c for c in bank.get("clusters") or []}
    for cid, c in clusters.items():
        if topics and c.get("topic") not in topics:
            probs.append(f"cluster {cid}: topic {c.get('topic')} not in blueprint")

    # several papers in one PDF (question sets): each needs its own "pages": [first, last], without overlap
    by_slug = {}
    for pid, p in papers.items():
        by_slug.setdefault(p.get("source_slug"), []).append(pid)
        if isinstance(p.get("pages"), list) and page_range(p) is None:
            probs.append(f"paper {pid}: pages {p.get('pages')!r} must be [first, last] page numbers")
    for slug, pids in by_slug.items():
        if slug and len(pids) > 1:
            rngs = {pid: page_range(papers[pid]) for pid in pids}
            if any(r is None for r in rngs.values()):
                probs.append(f"papers {', '.join(pids)} share source_slug {slug}: give each its \"pages\": "
                             f"[first, last] so each is checked against its own pages only")
            else:
                s = sorted(rngs.items(), key=lambda kv: kv[1])
                for (a, ra), (b, rb) in zip(s, s[1:]):
                    if rb[0] <= ra[1]:
                        probs.append(f"papers {a} {list(ra)} and {b} {list(rb)} overlap in {slug}")

    manifest = {}
    if (shared / "manifest.json").exists():
        try:
            manifest = json.loads((shared / "manifest.json").read_text("utf-8")).get("files", {})
        except ValueError:
            manifest = {}
    ctoks, ckeys, pmarks = {}, {}, {}
    for q in questions:
        if is_number(q.get("marks")):
            pmarks.setdefault(q.get("paper"), set()).add(float(q["marks"]))
    rough_cache = {}
    for pid, p in papers.items():
        f = shared / "corpus" / f"{p.get('source_slug', '')}.md"
        if not p.get("source_slug") or not f.exists():
            probs.append(f"paper {pid}: corpus file {f.name} not found")
            continue
        slug = p["source_slug"]
        if slug not in rough_cache:          # pages whose text layer is itself OCR
            rough = set()
            for rel, m in manifest.items():
                if m.get("slug") == slug:
                    if str(m.get("quality", "")).upper().startswith("POOR"):
                        rough = set(range(1, int(m.get("pages") or 0) + 1))
                    elif rel.lower().endswith(".pdf") and (_subj / rel).exists():
                        rough = scan_layer_pages(_subj / rel)
            rough_cache[slug] = rough
        t = f.read_text("utf-8", errors="replace")
        rng, mk = page_range(p), pmarks.get(pid, set())
        ctoks[pid] = corpus_tokens(t, marks=mk, pages=rng, rough=rough_cache[slug])
        ckeys[pid] = hashlib.sha1((t + repr((sorted(mk), rng, sorted(rough_cache[slug])))).encode("utf-8")).hexdigest()

    rpath = receipts_path(work)
    receipts = None
    if rpath.exists():
        try:
            receipts = json.loads(rpath.read_text("utf-8"))
        except ValueError:
            probs.append(f"{rpath.name} unreadable")
    receipts = receipts or {}

    rows, seen, per_paper, metrics = [], set(), {}, {}
    n_receipt = 0
    for q in questions:
        qid = str(q.get("id", "?"))
        reasons, notes = [], []
        for k in REQUIRED:
            if k not in q:
                reasons.append(f"missing key '{k}'")
        if qid in seen:
            reasons.append("duplicate question id")
        seen.add(qid)
        if "marks" in q and (not is_number(q["marks"]) or q["marks"] <= 0):
            reasons.append(f"marks {q['marks']!r} is not a positive number")
        if q.get("cluster") not in clusters:
            reasons.append(f"unknown cluster {q.get('cluster')}")
        if topics and q.get("topic") not in topics:
            reasons.append(f"topic {q.get('topic')} not in blueprint")
        # receipts (checked first: an OCR-damage excuse needs a good receipt)
        rec = receipts.get(qid)
        manual = isinstance(q.get("receipt"), (dict, list)) and q.get("verified") == "vision"
        rr = None
        if not rec:
            rr = "no receipt (run receipts.py)"
        elif not rec.get("file") or not (work / rec["file"]).exists():
            rr = "receipt image missing"
        elif rec.get("text_sha") != receipt_sha(q):
            rr = "receipt is stale (question text changed since receipts.py ran)"
        elif not manual and (not is_number(rec.get("match")) or rec["match"] < RECEIPT_MIN):
            rr = f"low-match receipt ({rec.get('match')}; needs >= {RECEIPT_MIN} or vision + manual rect)"
        # a good receipt: fresh image with match >= RECEIPT_MIN, or a vision-checked manual rect (spec exemption)
        receipt_ok = rr is None and (manual or (is_number(rec.get("match")) and rec["match"] >= RECEIPT_MIN))
        pid = q.get("paper")
        met = {"tok": 0.0, "tri": 0.0, "n": 0}
        if pid not in papers:
            reasons.append(f"unknown paper {pid}")
        else:
            per_paper.setdefault(pid, []).append(q)
            if pid in ctoks:
                met, r2, notes = check_question(q, ctoks[pid], ckeys[pid], receipt_ok)
                if r2 and receipt_ok and isinstance(rec.get("ocr_text"), str) and rec["ocr_text"].strip():
                    # the corpus OCR is damaged here: run the SAME checks on receipts.py's fresh 300 dpi OCR
                    # (or text layer) of the cropped region; it decides only if it passes in full
                    rt = tokenize(strip_marks(rec["ocr_text"], pmarks.get(pid, set())),
                                  ocr=bool(rec.get("ocr_is_ocr", True)))
                    m2, r3, n3 = check_question(q, rt, "receipt:" + text_sha(rec["ocr_text"]), receipt_ok)
                    if not r3:
                        notes = n3 + [f"corpus text damaged ({'; '.join(r2)[:80]}...): matched the receipt's "
                                      f"fresh OCR (tok {m2['tok']:.2f}, tri {m2['tri']:.2f})"]
                        # the corpus alignment failed, so its positions are stray: they must not take part
                        # in the duplicate check (that would block it, or a neighbour, as a copy). A rescued
                        # question is checked for copies by its text and its receipt region instead.
                        met = dict(met, tok=m2["tok"], tri=m2["tri"], cpos=set(),
                                   rescued=(rec.get("page"), tuple(rec.get("rect") or ()),
                                            " ".join(t.fold for t in rt)))
                        r2 = []
                reasons += r2
                metrics[qid] = (pid, met)
            else:
                reasons.append("paper corpus missing: text cannot be verified")
        if rr:
            reasons.append(rr)
            n_receipt += 1
        rows.append((qid, met, reasons, notes, rr))      # rr: this row's receipt reason (or None)

    # questions of one paper must not be copies of each other
    # (either-or alternatives "Qn" and "Qn OR" are not compared with each other: they may share wording)
    def branch(q):
        g = group_key(q.get("qno", "")) or ""
        return (g[:-3], True) if g.endswith(" OR") else (g, False)

    for pid, qs in per_paper.items():
        mine = [(str(q.get("id")), branch(q), metrics[str(q.get("id"))][1].get("cpos") or set())
                for q in qs if str(q.get("id")) in metrics]
        for row in rows:
            qid, met = row[0], row[1]
            if qid not in metrics or metrics[qid][0] != pid or not met.get("cpos"):
                continue
            me = next((b for i, b, _c in mine if i == qid), None)
            others = set()
            for i, b, c in mine:
                if i == qid or (me and b[0] == me[0] and b[1] != me[1]):
                    continue
                others |= c
            own = sum(1 for cj in met["cpos"] if cj not in others)
            if own < min(UNIQUE_MIN, len(met["cpos"])):
                row[2].append(f"duplicates another question of {pid} (owns {own} aligned token(s))")
        # receipt-rescued questions (no usable corpus positions): a copy has the same words, or was located on
        # the same receipt region (same page, rect and fresh OCR text)
        fold = {str(q.get("id")): " ".join(t.fold for t in tokenize(match_text(q))) for q in qs}
        for row in rows:
            qid, met = row[0], row[1]
            if qid not in metrics or metrics[qid][0] != pid or "rescued" not in met:
                continue
            me = next((b for i, b, _c in mine if i == qid), None)
            for i, b, _c in mine:
                if i == qid or (me and b[0] == me[0] and b[1] != me[1]):
                    continue
                other = metrics[i][1]
                same_text = fold.get(i) and fold.get(i) == fold.get(qid)
                same_spot = "rescued" in other and other["rescued"] == met["rescued"] and met["rescued"][1]
                if same_text or same_spot:
                    row[2].append(f"duplicates another question of {pid} ({i}: same "
                                  f"{'words' if same_text else 'receipt region'})")
                    break

    # papers
    summaries = {}
    for pid, p in papers.items():
        qs = per_paper.get(pid, [])
        if not qs:
            probs.append(f"paper {pid}: no questions banked")
            continue
        pr, summ = check_marks(pid, p, qs)
        probs += pr
        summaries[pid] = summ
    ids = list(per_paper)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a = [" ".join(t.fold for t in tokenize(q.get("text", ""))) for q in per_paper[ids[i]]]
            b = {" ".join(t.fold for t in tokenize(q.get("text", ""))) for q in per_paper[ids[j]]}
            same = sum(1 for x in a if x and x in b)
            if a and b and same / min(len(a), len(b)) > 0.6:
                probs.append(f"papers {ids[i]} and {ids[j]} look like the SAME paper ({same} identical "
                             f"questions): bank it once, note the duplicate in warnings")

    # report
    out(f"verify_pyqs {subject} --scope {scope}: {len(papers)} paper(s), {len(questions)} question(s)")
    for pid, p in papers.items():
        out(f"  paper {pid} [{p.get('source_slug')}]: {len(per_paper.get(pid, []))} question(s); "
            f"marks {summaries.get(pid) or 'see problems'}")
    bad = [r for r in rows if r[2]]
    show = rows if show_all else bad
    if show:
        out(f"\n{'id':16s} {'tok':>5s} {'tri':>5s} {'n':>4s}  reason")
        for qid, met, reasons, notes, _rr in show:
            why = "; ".join(reasons) if reasons else "ok"
            if notes:
                why += "  [" + "; ".join(notes) + "]"
            out(f"{qid:16s} {met.get('tok', 0):5.2f} {met.get('tri', 0):5.2f} {met.get('n', 0):4d}  {why}")
    for p in probs:
        out(f"PROBLEM {p}")
    n_text = sum(1 for r in bad if any(x is not r[4] for x in r[2]))   # any reason other than the receipt's
    if n_text:
        blockers.append(f"{n_text} question(s) failed text checks")
    if n_receipt:
        blockers.append(f"{n_receipt} receipt(s) missing/stale/low-match")
    if probs:
        blockers.append(f"{len(probs)} bank/paper problem(s)")
    return not blockers, blockers, None


def main():
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject")
    ap.add_argument("--scope", required=True, choices=workdir.SCOPES)
    ap.add_argument("--all", action="store_true", help="print every question's row, not only failures")
    a = ap.parse_args()
    ok, blockers, mode = run(a.subject, a.scope, a.all)
    if ok:
        print("\nRESULT PASS" + (f" ({mode})" if mode else ""))
    else:
        print(f"\nRESULT BLOCKED: {'; '.join(blockers)}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
