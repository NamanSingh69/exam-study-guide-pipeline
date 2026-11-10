"""Regression tests for tools/web.py (static web export).

  py _pipeline/tests/test_web.py

1. Unit checks of the LaTeX helpers (comment stripping, SVG number packing, rewrite of \\answer in maths).
2. A crafted fixture subject ZZ (tests/_tmp/web/ZZ) that exercises every feature the spec names:
   \\input'd atoms, \\stepanim -> web animation, tables, lists, nested maths, a receipt, q1_drill,
   an orphan solved-idea atom, \\flashcard, and blocks the converter does NOT know (they must fall
   back to rendered images and be listed in CONVERSION_REPORT.md).
3. The real CN midsem trial chapters, copied to tests/_tmp/web/CN (never the real folder).
Every page: no raw LaTeX in visible text, every local href/src exists, metadata present.
"""
import json, os, re, shutil, subprocess, sys, xml.dom.minidom
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
ROOT = PIPE.parent
TMP = HERE / "_tmp" / "web"
TOOL = PIPE / "tools" / "web.py"
sys.path.insert(0, str(PIPE / "tools"))
fails = 0


def ok(cond, name, extra=""):
    global fails
    if cond:
        print(f"OK {name}")
    else:
        fails += 1
        print(f"FAIL {name} {extra}")


def run(subject, *args, root=TMP):
    env = dict(os.environ, STUDYPREP_ROOT=str(root))
    r = subprocess.run([sys.executable, str(TOOL), subject, "--scope", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=900)
    return r.returncode, r.stdout + r.stderr


def visible_text(h):
    h = re.sub(r'<span class="m"[^>]*>.*?</span>|<div class="md"[^>]*>.*?</div>|<script.*?</script>|'
               r'<code>.*?</code>|<pre>.*?</pre>|<head>.*?</head>', " ", h, flags=re.S)
    return re.sub(r"<[^>]+>", " ", h)


def check_site(web, label, min_pages):
    pages = sorted(web.glob("*.html"))
    ok(len(pages) >= min_pages, f"{label}: at least {min_pages} pages", f"got {len(pages)}")
    leaks, broken, nometa = [], [], []
    for p in pages:
        h = p.read_text(encoding="utf-8")
        t = visible_text(h)
        for m in re.finditer(r"\\[A-Za-z]{2,}|\$[^$\s]", t):
            leaks.append(f"{p.name}: {t[max(0, m.start() - 30):m.end() + 30]!r}")
        for m in re.finditer(r'(?:href|src)="([^"#:]+)(?:#[^"]*)?"', h):
            u = m.group(1)
            if u and not u.startswith("pdf/") and not (web / u).exists():   # pdf/ = publish placeholders
                broken.append(f"{p.name} -> {u}")
        if not re.search(r"<title>[^<]{10,}</title>", h) or 'name="description"' not in h or 'property="og:title"' not in h:
            nometa.append(p.name)
    ok(not leaks, f"{label}: no raw LaTeX in visible text", "; ".join(leaks[:5]))
    ok(not broken, f"{label}: every local link and image exists", "; ".join(broken[:5]))
    ok(not nometa, f"{label}: title, description and OpenGraph on every page", ", ".join(nometa[:5]))
    idx = json.loads((web / "search.json").read_text(encoding="utf-8"))
    ok(len(idx) == len(pages) - 1 and all({"t", "u", "k", "x"} <= set(e) for e in idx),
       f"{label}: search.json indexes every page except the index", f"{len(idx)} vs {len(pages)}")
    sm = (web / "sitemap-fragment.xml").read_text(encoding="utf-8")
    xml.dom.minidom.parseString(sm)
    ok(sm.count("<url>") == len(pages), f"{label}: sitemap fragment lists every page")
    for f in ("assets/site.css", "assets/site.js", "og.png", "CONVERSION_REPORT.md", "site.json"):
        ok((web / f).exists(), f"{label}: {f} written")
    svgs = list((web / "fig").glob("*.svg"))
    bad = []
    import pymupdf
    for s in svgs:
        try:
            pymupdf.open(str(s))[0].get_pixmap(dpi=12)
        except Exception as e:      # noqa: BLE001 - any parse error is a failure
            bad.append(f"{s.name}: {e}")
    ok(svgs and not bad, f"{label}: {len(svgs)} SVGs all parse", "; ".join(bad[:3]))
    return pages


# ------------------------------------------------------------------ 1. unit checks
import web  # noqa: E402

s = web.strip_comments("a % comment\nb\n\n% only a comment\nc 50\\% d")
ok(s == "a b\n\nc 50\\% d", "strip_comments: % eats the newline, \\% kept", repr(s))
ok("\n\n" not in web.strip_comments("line one\n% note\nline two"), "a commented line never splits a paragraph")
svg = '<svg width="10" height="10" viewBox="0 0 10 10"><path d="M.09599304-.000076293948 .14 .9996.5"/></svg>'
o = web.optimise_svg(svg)
nums = re.findall(r"-?(?:\d+\.?\d*|\.\d+)", re.search(r'd="([^"]*)"', o).group(1))
ok(len(nums) == 5, "optimise_svg keeps packed path numbers apart", o)
ok(web.rewrite_cmd(r"x=\answer{$2$ bits}", "answer", lambda a: "[" + a + "]") == "x=[$2$ bits]",
   "rewrite_cmd handles nested groups")


# ------------------------------------------------------------------ 2. crafted fixture
def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


shutil.rmtree(TMP, ignore_errors=True)
zz = TMP / "ZZ" / "work" / "endsem"
write(zz / "blueprint.json", json.dumps({
    "subject": "Zeta Studies", "code": "ZS 101", "scope": "Endsem",
    "units": [{"id": "U1", "title": "Basics", "in_scope": True, "chapter": "30_basics",
               "topics": [{"id": "T01", "title": "Stop and go"}, {"id": "T02", "title": "Tables and lists"}]}]}))
write(zz / "pyq_bank.json", json.dumps({
    "papers": [{"id": "ES2025", "year": 2025, "exam": "endsem"}, {"id": "ES2019", "year": 2019, "exam": "endsem"}],
    "questions": [
        {"id": "ES2019-3b", "paper": "ES2019", "qno": "3(b)", "marks": 5,
         "text": "Every 4th packet is lost; count the transmissions for 7 packets.",
         "topic": "T01", "cluster": "C01", "type": "numerical", "in_scope": True},
        {"id": "ES2025-1a", "paper": "ES2025", "qno": "1(a)", "marks": 1, "text": "Define a stop. Give one example.",
         "topic": "T01", "cluster": "C01", "type": "theory", "in_scope": True},
        {"id": "ES2025-2a", "paper": "ES2025", "qno": "2(a)", "marks": 5,
         "text": "A sender sends 9 packets; every 5th is lost. How many transmissions? (verbatim & <exact>)",
         "topic": "T01", "cluster": "C01", "type": "numerical", "in_scope": True}],
    "clusters": [{"id": "C01", "topic": "T01", "label": "Count transmissions with periodic loss"}]}))
write(zz / "important_questions.json", json.dumps({
    "model": {"papers_used": {"ES2025": 1.0}},
    "clusters": [{"cluster": "C01", "topic": "T01", "label": "Count transmissions with periodic loss",
                  "tier": "A", "P": 0.8, "question_ids": ["ES2025-2a", "ES2025-1a"]}],
    "topics": [{"topic": "T01", "P": 0.8}, {"topic": "T02", "P": 0.1}],
    "plans": {"3h": {"clusters": ["C01"], "minutes": 180, "expected_marks": 6.5, "p_safe": 0.9}},
    "q1_drill": {"pyq": ["ES2025-1a"], "predicted": ["C01"]}}))
write(zz / "chapters" / "30_basics.tex", r"""\chapter{Basics}
\label{ch:basics}
Intro text for the unit with a \keyword{keyword}. % a comment that must vanish
\input{atoms/notes/T01}
\input{atoms/notes/T02}
""")
write(zz / "atoms" / "notes" / "T01.tex", r"""\section{Stop and go}\label{sec:T01}
\topicbadge{T01}
\begin{definitionbox}[Stop]
A \textbf{stop} is when $U=\frac{1}{1+2a}$ and $x=\answer{$20$ bits}$. \src{N_slides p3}
\end{definitionbox}
\flashcard{What is $U$ for stop-and-wait?}{$U=\frac{1}{1+2a}$}
\stepanim{3}{2}{0.48\linewidth}{Three frames of a stop.\label{fig:stop}}{%
  \path[use as bounding box] (0,0) rectangle (4,2);
  \node[blk] at (1,1) {A};
  \ifnum\f>1 \node[blkok] at (3,1) {B};\fi
  \ifnum\f>2 \draw[arr] (1.5,1) -- (2.5,1);\fi
}
Figure~\ref{fig:stop} shows it. A thing only LaTeX knows: \LaTeXe.
\begin{tcolorbox}[colback=white]
An unknown environment: it must become an image.
\end{tcolorbox}
Maths KaTeX lacks: $a \leftrightharpoons b$.
\begin{question}{Worked example}{2}
Find it.
\end{question}
\begin{solution}[the answer]
It is \answer{14}.
\end{solution}
""")
write(zz / "atoms" / "notes" / "T02.tex", r"""\section{Tables and lists}\label{sec:T02}
\begin{table}[H]\centering\zebra
\begin{tabularx}{\linewidth}{L{20mm}Yc}\toprule
\thead{A} & \thead{B} & \thead{C}\\\midrule
\multicolumn{2}{l}{wide cell} & 3\\
x & \cellcolor{sgamber!27}y & $z^2$\\\bottomrule
\end{tabularx}
\caption{A table.}\label{tab:t}
\end{table}
\begin{enumerate}[label=(\alph*)]
  \item first with \emph{emphasis}
  \item second, see \S\ref{sec:T01} and solved on p.\,\pageref{q:ES2025-2a}
\end{enumerate}
\begin{itemize}\item plain \item two\end{itemize}
Built in \texorpdfstring{$O(n)$}{O(n)} time.
""")
write(zz / "atoms" / "solve" / "C01.tex", r"""\begin{solvedidea}{C01}{Count transmissions with periodic loss}
Every 5th lost: $T-\lfloor T/5\rfloor\ge 9 \Rightarrow T=11$.
\end{solvedidea}
""")
write(zz / "chapters" / "700_pyq_es2025.tex", r"""\chapter{2025 Endsem paper --- solutions}
\label{ch:pyq_es2025}
\section{Question 2}
\needspace{8\baselineskip}
\begin{question}{2025 Endsem Q2(a)}{5}
A sender sends 9 packets; every 5th is lost. How many transmissions?
\end{question}
\label{q:ES2025-2a}
\receipt{ES2025-2a}
\begin{solution}
Count them: \answer{11}. \seesolved{C01}
\end{solution}
\begin{examtip}Count retransmissions too.\end{examtip}
""")
# an archive paper (assignments.json kind pyq_older): question + receipt + \seesolved, no full solution
write(zz / "chapters" / "701_pyq_es2019.tex", r"""\chapter{2019 Endsem paper --- questions}
\needspace{8\baselineskip}
\begin{question}{2019 Endsem Q3(b)}{5}
Every 4th packet is lost; count the transmissions for 7 packets.
\end{question}
\label{q:ES2019-3b}
\receipt{ES2019-3b}
\seesolved{C01}. Here: \answer{9}.
""")
write(zz / "assignments.json", json.dumps({"chapters": [
    {"stem": "30_basics", "kind": "unit"}, {"stem": "700_pyq_es2025", "kind": "pyq_full", "paper": "ES2025"},
    {"stem": "701_pyq_es2019", "kind": "pyq_older", "paper": "ES2019"}]}))
from PIL import Image  # noqa: E402
(zz / "receipts").mkdir(parents=True, exist_ok=True)
Image.new("RGB", (1800, 120), (230, 230, 230)).save(zz / "receipts" / "ES2019-3b.png")
(zz / "receipts").mkdir(parents=True, exist_ok=True)
Image.new("RGB", (400, 60), (240, 240, 240)).save(zz / "receipts" / "ES2025-2a.png")

code, out = run("ZZ", "endsem")
ok(code == 0 and "RESULT PASS" in out, "ZZ fixture: web.py exits 0 with RESULT PASS", out[-800:])
w = zz / "web"
pages = check_site(w, "ZZ", 8)
names = {p.name for p in pages}
tp = next((w / n for n in names if n.startswith("t-T01-")), None)
ok(tp is not None, "topic page for T01 (from an \\input atom)")
if tp:
    h = tp.read_text(encoding="utf-8")
    m = re.search(r'<figure class="anim" data-n="3">(.*?)</figure>', h, re.S)
    ok(m is not None, "\\stepanim became a web animation with 3 frames")
    if m:
        srcs = re.findall(r'src="(fig/[0-9a-f]+\.svg)"', m.group(1))
        ok(len(srcs) == 3 and 'class="play"' in m.group(1) and 'class="next"' in m.group(1),
           "animation has 3 frame SVGs and play/step controls")
        vbs = {re.search(r'viewBox="([^"]+)"', (w / s).read_text(encoding="utf-8")).group(1) for s in srcs}
        ok(len(vbs) == 1, "all frames of one animation share one crop box", str(vbs))
    ok('<span class="m">' in h and "katex.min.js" in h and "cdnjs.cloudflare.com/ajax/libs/KaTeX/" in h,
       "maths as KaTeX spans, KaTeX from cdnjs")
    ok(re.search(r"KaTeX/\d+\.\d+\.\d+/katex\.min\.js", h) is not None, "KaTeX version pinned exactly")
    ok("\\boxed{\\text{$20$ bits}}" in h, "\\answer with nested maths inside maths -> \\boxed{\\text{..}}")
    ok('<details class="box box-sol ans">' in h, "topic-page solutions are collapsed <details> (self-test)")
    ok('class="fallback"' in h, "unknown blocks fall back to rendered images")
    ok('id="self-test"' in h and "What is" in h, "the topic's \\flashcard appears as a self-test card")
    ok("ES2025-2a" in h and "pyq-ES2025-2a" in h, "topic page lists its past questions with anchors")
rep = (w / "CONVERSION_REPORT.md").read_text(encoding="utf-8")
nfb = int(re.search(r"fallbacks \(blocks rendered as images\): (\d+)", rep).group(1))
ok(nfb >= 3 and "tcolorbox" in rep and "LaTeXe" in rep and "leftrightharpoons" in rep,
   "CONVERSION_REPORT lists every fallback with its reason", f"{nfb} fallbacks")
qp = next((w / n for n in names if n.startswith("q-es2025-2a-")), None)
ok(qp is not None, "a page per solved PYQ (7NN_ stem chapter)")
if qp:
    h = qp.read_text(encoding="utf-8")
    ok("<title>ZZ Endsem 2025 Q2(a) — Count transmissions with periodic loss (solved) | Unofficial KIIT guide</title>" in h,
       "PYQ page title format", re.search(r"<title>.*?</title>", h).group(0))
    ok("every 5th is lost. How many transmissions? (verbatim &amp; &lt;exact&gt;)" in h,
       "PYQ page shows the bank text verbatim (escaped)")
    ok('src="receipts/ES2025-2a.png"' in h and (w / "receipts" / "ES2025-2a.png").exists(), "receipt image shown and copied")
    ok('<details class="box box-sol ans" open>' in h, "PYQ solution open by default")
    ok(re.search(r'href="t-T01-[^"]+">Notes:', h) is not None, "PYQ page links to its topic page")
    ok(re.search(r'href="zz_atoms_solve\.html#solve-C01"|href="ch-zz-atoms-solve\.html#solve-C01"', h) is not None,
       "\\seesolved links to the orphan solved-idea atom page", re.findall(r'seesolved.*?</span>', h)[:1])
    ok('og:description' in h and 'twitter:card' in h, "OpenGraph/Twitter tags")
    ok(h.count('src="receipts/ES2025-2a.png"') == 1, "receipt shown once even when the chapter also has \\receipt")
ap = next((w / n for n in names if n.startswith("q-es2019-3b-")), None)
ok(ap is not None, "archive paper (pyq_older) keeps a page per PYQ")
if ap:
    h = ap.read_text(encoding="utf-8")
    ok("<title>ZZ Endsem 2019 Q3(b) — Count transmissions with periodic loss (answer) | Unofficial KIIT guide</title>" in h,
       "archive PYQ title says (answer), not (solved)", re.search(r"<title>.*?</title>", h).group(0))
    ok(re.search(r'Full model solution of this idea: <a class="xref" href="ch-zz-atoms-solve\.html#solve-C01"', h) is not None
       and re.search(r'href="t-T01-[^"]+">Notes:', h) is not None, "archive PYQ links to the solve page and the topic page")
    ok(h.count('src="receipts/ES2019-3b.png"') == 1 and "<summary>Answer</summary>" in h, "archive: one receipt, Answer box")
    from PIL import Image as _I
    rim = _I.open(w / "receipts" / "ES2019-3b.png")
    ok(rim.width <= 1100 and rim.mode in ("P", "L"), "receipts are shrunk for the web (<= 1100 px, greyscale palette)",
       f"{rim.size} {rim.mode}")
pp = next((w / n for n in names if n.startswith("paper-es2019")), None)
ok(pp is not None and "(archive)" in pp.read_text(encoding="utf-8"), "archive paper page is labelled as the archive")
t2 =next((w / n for n in names if n.startswith("t-T02-")), None)
if t2:
    h = t2.read_text(encoding="utf-8")
    ok('colspan="2"' in h and "<thead>" in h and "rgba(217,119,6,0.27)" in h, "table: header, multicolumn, cellcolor")
    ok('<span class="li-l">(a)</span>' in h and '<span class="li-l">(b)</span>' in h, "enumerate label=(\\alph*)")
    ok(re.search(r'href="q-es2025-2a-[^"]+">→ 2025 Q2\(a\)', h) is not None, "p.\\,\\pageref{q:..} -> link to the PYQ page")
    ok(re.search(r'href="t-T01-[^"]+">Stop and go</a>', h) is not None, "\\ref{sec:..} -> link with the topic title")
    ok("texorpdfstring" not in h and '<p>Built in <span class="m">O(n)</span> time.</p>' in h,
       "\\texorpdfstring{tex}{pdf} renders its TeX argument")
d = (w / "drill.html").read_text(encoding="utf-8")
ok("Define a stop. Give one example." in d and "Expected (not a past question)" in d and '<details class="ans">' in d,
   "drill page built from q1_drill (PYQ + predicted), answers folded")
ix = (w / "index.html").read_text(encoding="utf-8")
ok("3h plan" in ix and "expected 6.5 marks" in ix and "p_safe 90%" in ix, "index shows the study plans")
ok('class="pill p-phigh">P high' in ix and 'data-file="Zeta_Studies_Endsem_Guide.pdf"' in ix,
   "index: topic P bands (1 paper -> band) and PDF download placeholders")
ok("Unofficial" in ix and "Not issued by" in ix, "unofficial notice on every page")
# a folder that is not a web.py output is never wiped
other = TMP / "notweb"
write(other / "keep.txt", "x")
code2, out2 = run("ZZ", "endsem", "--out", str(other))
ok(code2 == 2 and (other / "keep.txt").exists(), "refuses to wipe a foreign --out folder", out2[-300:])
code3, _ = run("ZZ")
ok(code3 == 2, "--scope is required (exit 2)")

# ------------------------------------------------------------------ 2b. real SVP snippets that broke web.py
# tests/fixtures/web_svp_snippets (see its SOURCE.txt): 4 render failures + 15 fallbacks on 2026-11-06.
ok(web.latex_balanced(r"\begin{a}{x}\end{a}") and not web.latex_balanced(r"\begin{scope}x")
   and not web.latex_balanced("{a") and not web.latex_balanced(r"x\end{minipage}"),
   "latex_balanced spots fragments that cannot compile alone")
s_ = r"\flashcard{F}{$\begin{bmatrix}u\\v\end{bmatrix}$} rest"
ok(s_[web.arg_chain_end(s_, len(r"\flashcard")):] == " rest", "arg_chain_end keeps a command's arguments together")
sv = TMP / "SVP" / "work" / "endsem"
shutil.copytree(HERE / "fixtures" / "web_svp_snippets", sv)
code, out = run("SVP", "endsem")
print("   svp: " + " ".join(l for l in out.splitlines() if l.startswith(("web:", "RESULT"))))
ok(code == 0 and "RESULT PASS (0 fallbacks)" in out and " 0 render failures" in out,
   "SVP snippets: 0 render failures and 0 fallbacks", out[-900:])
w = sv / "web"
check_site(w, "SVP", 5)
t38 = next(w.glob("t-T38-*.html")).read_text(encoding="utf-8")
m = re.search(r'<figure class="anim" data-n="4">(.*?)</figure>', t38, re.S)
ok(m is not None and len(re.findall(r'src="fig/[0-9a-f]+\.svg"', m.group(1))) == 4 and 'class="fallback' not in t38,
   "\\providecommand + scope body: definition kept whole, the 4-frame ASM animation renders")
t31 = next(w.glob("t-T31-*.html")).read_text(encoding="utf-8")
ok('class="fallback' not in t31 and t31.count('<details class="card ans">') == 3,
   "\\flashcard with matrix back: 3 self-test cards, no fallback")
ok(r"\begin{bmatrix}u\\v\end{bmatrix}" in t31 and r"\begin{bmatrix}R(0)&amp;R(1)\\R(1)&amp;R(0)\end{bmatrix}" in t31,
   "'\\\\v' and '\\\\R' row breaks stay KaTeX maths (not unknown macros)")
ok(r"\left(\begin{smallmatrix}1.2&amp;0.1&amp;30" in t31, "psmallmatrix -> \\left(\\begin{smallmatrix}..\\right)")
ok('<span class="m">(I_x,I_y,I_t)=(1,0,-2)</span>, <span class="m">(0,1,-1)</span>' in t31,
   "a long inline list of tuples is split so a phone line can wrap it")
ok(web.split_tuple_list(r"\{(1,2),(3,4)\}") == [r"\{(1,2),(3,4)\}"] and
   web.split_tuple_list("(a,b),(c,d)") == ["(a,b)", "(c,d)"], "split_tuple_list never splits a set or bracket")
js = (PIPE / "latex" / "web" / "site.js").read_text(encoding="utf-8")
ok("m-wide" in js and "span.m.m-wide" in (PIPE / "latex" / "web" / "site.css").read_text(encoding="utf-8"),
   "safety net: an unbreakable inline formula gets its own scroller (site.js + site.css)")
ok("<table>" in t31 and "Practice numericals" in t31, "\\par\\nobreak is ignored, the table follows")
iq = next(w.glob("ch-60-*.html")).read_text(encoding="utf-8")
ok('class="fallback' not in iq and "<em>Write a Python program using OpenCV" in iq and "<pre><code>import cv2" in iq,
   "solved idea: \\emph{..} argument and the listing convert (no fallback)")
ok("<em>A <span class=\"m\">2\\times2</span> block" in iq and r"\left[\begin{smallmatrix}67&amp;76" in iq,
   "\\emph{..} holding a smallmatrix stays one argument (was 'Missing \\endcsname')")
fc = (w / "flashcards.html").read_text(encoding="utf-8")
ok("3 cards" in fc, "SVP snippets: flashcards page has the 3 cards")


# ------------------------------------------------------------------ 3. the frozen CN trial fixture
# tests/fixtures/web_cn_trial = the round-3 CN chapters (CN/work/midsem/prev/2026-11-04) + the minimal
# bank/blueprint/important_questions they reference (see its SOURCE.txt). Frozen: live CN data changes.
fx = HERE / "fixtures" / "web_cn_trial"
cn = TMP / "CN" / "work" / "midsem"
shutil.copytree(fx, cn)
code, out = run("CN", "midsem")
print("   " + "\n   ".join(l for l in out.splitlines() if l.startswith(("web:", "RESULT"))))
ok(code == 0 and "RESULT PASS (0 fallbacks)" in out and " 0 render failures" in out,
   "CN trial: web.py exits 0 with 0 fallbacks and 0 render failures", out[-800:])
w = cn / "web"
pages = check_site(w, "CN", 30)
ok(len(list(w.glob("t-T*.html"))) == 13 and len(list(w.glob("q-ms2024-*.html"))) == 13,
   "CN trial: 13 topic pages (T12-T24) and 13 solved 2024 PYQ pages")
anims = sum(len(re.findall(r'<figure class="anim"', p.read_text(encoding="utf-8"))) for p in pages)
ok(anims == 6, "CN trial: all 6 \\stepanim became web animations", str(anims))
size = sum(f.stat().st_size for f in w.rglob("*") if f.is_file())
ok(size < 6 * 1024 * 1024, f"CN trial: output stays small ({size / 1024:.0f} KiB < 6 MiB)")
q4b = next(w.glob("q-ms2024-4b-*.html")).read_text(encoding="utf-8")
ok(re.search(r"<title>CN Midsem 2024 Q4\(b\) — [^<]+ \(solved\) \| Unofficial KIIT guide</title>", q4b) is not None,
   "CN trial: PYQ title format 'CN Midsem 2024 Q4(b) — … (solved) | Unofficial KIIT guide'")


# ------------------------------------------------------------------ 4. smoke test: copy of the LIVE CN folder
# Invariants only (the pipeline legitimately regenerates this data). Never writes the real folder.
def no_hscroll_markers(h):
    """Static markers of sideways scrolling: a table outside its .tbl scroller, a fixed pixel width > 360."""
    outside = re.sub(r'<div class="tbl">.*?</div>', "", h, flags=re.S)
    return "<table" not in outside and not re.search(r'style="[^"]*\bwidth:\s*(3[6-9]\d|[4-9]\d\d|\d{4,})px', h)


src = ROOT / "CN" / "work" / "midsem"
if (src / "chapters").is_dir() and os.environ.get("SG_SKIP_LIVE") != "1":
    live = TMP / "live" / "CN" / "work" / "midsem"
    live.mkdir(parents=True, exist_ok=True)
    for d in ("chapters", "atoms", "receipts"):
        if (src / d).is_dir():
            shutil.copytree(src / d, live / d)
    for f in ("blueprint.json", "pyq_bank.json", "important_questions.json", "badges.tex", "assignments.json"):
        if (src / f).exists():
            shutil.copyfile(src / f, live / f)
    real_web = src / "web"
    before = sorted((p.name, p.stat().st_mtime) for p in real_web.rglob("*")) if real_web.exists() else None
    code, out = run("CN", "midsem", "--base-url", "https://example.invalid/CN/midsem", root=TMP / "live")
    after = sorted((p.name, p.stat().st_mtime) for p in real_web.rglob("*")) if real_web.exists() else None
    print("   live: " + " ".join(l for l in out.splitlines() if l.startswith(("web:", "RESULT"))))
    ok(before == after, "live smoke: the real CN folder was not written")
    ok(code == 0, "live smoke: web.py exits 0", out[-600:])
    m = re.search(r"(\d+) fallbacks, (\d+) render failures", out)
    MAX_FALLBACKS = 25
    ok(m is not None and int(m.group(1)) <= MAX_FALLBACKS and m.group(2) == "0",
       f"live smoke: at most {MAX_FALLBACKS} fallbacks, 0 render failures", m.group(0) if m else out[-300:])
    lw = live / "web"
    hs = {p.name: p.read_text(encoding="utf-8") for p in lw.glob("*.html")}
    bad = [n for n, h in hs.items() if not no_hscroll_markers(h)]
    ok(not bad, "live smoke: no horizontal-scroll markers", ", ".join(bad[:5]))
    qpages = {n: h for n, h in hs.items() if n.startswith("q-")}
    badq = [n for n, h in qpages.items()
            if not re.search(r"<title>[^<]{20,}</title>", h) or '<link rel="canonical" href="https://example.invalid/' not in h]
    ok(qpages and not badq, f"live smoke: all {len(qpages)} PYQ pages have a title and a canonical tag", ", ".join(badq[:5]))
else:
    print("SKIP live smoke (no CN/work/midsem/chapters, or SG_SKIP_LIVE=1)")

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
