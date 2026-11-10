"""Regression tests for build.py + studyguide.sty + visual_cookbook.tex (Round 4, workstream T4).

Builds a small synthetic subject in tests/_tmp/build/ (STUDYPREP_ROOT); never touches a real subject.
Set T4_PIPE=<another _pipeline copy> to run the suite against other tools/latex (the RED check: the
pre-Round-4 files must fail these tests). Prints 'OK <name>' per test; exit 0 only if all pass.
make_subject() is also used by test_metrics.py.
"""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = Path(os.environ.get("T4_PIPE") or HERE.parent).resolve()
TOOLS = PIPE / "tools"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

# ----------------------------------------------------------------------------- fixture
CH = {
"05_how_to_use": r"""\chapter{How to use this guide}
Badges: \tier{A} \prob{70} (auto chapter: hand-placed pills are allowed here).
""",
"20_exam_radar": r"""\chapter{Exam radar}
\begin{tabularx}{\linewidth}{lY}\toprule Idea & Why\\\midrule C01 & asked in P2024\\\bottomrule\end{tabularx}
""",
"30_unit_one": r"""\chapter{Unit one}
\input{atoms/notes/T01}
""",
"60_important_questions": r"""\chapter{Important questions}
\section{Idea one}\label{iq:C01}
\clusterbadge{C01} \seesolved{C01}. Past paper: \pyqsolved{P2024-1a}.
""",
"700_pyq_p2024": r"""\chapter{2024 Midsem paper}
\needspace{8\baselineskip}
\begin{question}{2024 Midsem Q1(a)}{1}
Every 4th packet is lost; 15 packets must be delivered. How many transmissions?
\end{question}\label{q:P2024-1a}
\receipt{P2024-1a}
\input{atoms/solve/C01}
""",
"80_mock_paper": r"""\chapter{Mock paper}
Revise section~\ref{sec:T01} on p.~\pageref{sec:T01}. DANGLING
""",
"cheatsheet": r"""\section*{Cheatsheet}
\begin{multicols}{3}
Stop-and-wait: $\eta=\dfrac{1}{1+2a}$, $a=T_p/T_t$. GBN window $\le 2^m-1$.
\end{multicols}
""",
}
ATOMS = {
"notes/T01": r"""\section{Topic one: stop-and-wait}\label{sec:T01}
\topicbadge{T01}
\flashcard{Stop-and-wait efficiency?}{$1/(1+2a)$}
Text about the topic.
\stepanim{3}{2}{0.46\linewidth}{Stop-and-wait in three steps.}{%
  \path[use as bounding box] (-0.4,-0.9) rectangle (5.2,0.8);
  \foreach \i in {0,...,4}{\node[cell] at (\i*0.8,0) {\i};}
  \ifnum\f>1 \node[cellhl] at (0,0) {0};\fi
  \node[note] at (2,-0.6) {frame \f};}
""",
"solve/C01": r"""\begin{solvedidea}{C01}{Stop-and-wait: count transmissions}
Successes after $T$ transmissions: $T-\lfloor T/4\rfloor$; the first $T$ with 15 successes is \answer{19}.
\end{solvedidea}
""",
}
BLUEPRINT = {"subject": "Test Subject", "code": "TS 101", "scope": "Midsem",
             "exam_pattern": {"full_marks": 20},
             "units": [{"id": "U1", "title": "Unit One", "in_scope": True, "lectures": 4, "chapter": "30_unit_one",
                        "topics": [{"id": "T01", "title": "Stop-and-wait", "lectures": 2, "visual": "storyboard"}]},
                       {"id": "U9", "title": "Later unit", "in_scope": False, "lectures": 3, "chapter": "",
                        "topics": []}]}
BANK = {"papers": [{"id": "P2024", "year": 2024, "exam": "midsem", "source_slug": "PYQM_2024_x", "full_marks": 20,
                    "pattern": "Q1 compulsory 5x1"}],
        "questions": [{"id": "P2024-1a", "paper": "P2024", "qno": "1(a)", "marks": 1, "compulsory": True,
                       "text": "Every 4th packet is lost; 15 packets must be delivered. How many transmissions?",
                       "topic": "T01", "cluster": "C01", "type": "numerical", "in_scope": True, "verified": "vision"}],
        "clusters": [{"id": "C01", "topic": "T01", "label": "stop-and-wait counting", "type": "numerical"}]}
IQ = {"model": {}, "clusters": [{"cluster": "C01", "topic": "T01", "tier": "A", "P": 0.79}],
      "topics": [{"topic": "T01", "P": 0.84}], "plans": {},
      "backtest": {"summary": {"new": {"cover_6h": {"mean": 0.62}}}}}


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_subject(root: Path, dangling=True, subj="TT"):
    """A complete little midsem work folder. dangling=True leaves one \\pageref{q:P2022-9z} undefined."""
    if root.exists():
        shutil.rmtree(root)
    shared = root / subj / "work"
    work = shared / "midsem"
    for stem, body in CH.items():
        write(work / "chapters" / f"{stem}.tex", body.replace("DANGLING", r"See also p.~\pageref{q:P2022-9z}." if dangling else ""))
    for stem, body in ATOMS.items():
        write(work / "atoms" / f"{stem}.tex", body)
    write(work / "blueprint.json", json.dumps(BLUEPRINT, indent=1))
    write(work / "pyq_bank.json", json.dumps(BANK, indent=1))
    write(work / "important_questions.json", json.dumps(IQ, indent=1))
    write(work / "badges.tex", "\\sgdefbadge{C01}{A}{79}{high}{1.58}\n\\sgdeftopic{T01}{84}{high}\n")
    write(work / "checks" / "P2024-1a.py", "print(19)\n")
    write(shared / "manifest.json", json.dumps({"files": {}, "health": {"errors": 0}}))
    from PIL import Image
    (work / "receipts").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (900, 110), (235, 235, 242)).save(work / "receipts" / "P2024-1a.png")
    write(work / "receipts" / "receipts.json", json.dumps({"P2024-1a": {"page": 1, "rect": [0, 0, 1, 1], "match": 1.0,
                                                                         "method": "manual", "file": "receipts/P2024-1a.png"}}))
    return work


ARCH_CH = r"""\chapter{2019 Midsem paper --- questions}
\begin{question}{2019 Midsem Q2(b)}{2.5}
Every 3rd packet is lost; 10 packets must be delivered. How many transmissions?
\end{question}\label{q:P2019-2b}
\receipt{P2019-2b}
\textbf{Short answer:} 14. \seesolved{C01}. Background on p.~\pageref{sec:T01}. GUIDEMISS
"""


def make_archive_subject(root: Path, missing=None, assignments=True, one_pdf=False):
    """make_subject + an older paper P2019 whose chapter goes to the PYQ archive (assignments.json kind pyq_older).
    missing="guide": the archive also \\seesolved{C09} (exists nowhere); missing="archive": the guide also
    \\pyqsolved{P2019-9z} (a bank question of the archived paper whose label the archive never sets)."""
    work = make_subject(root, dangling=False)
    write(work / "chapters" / "701_pyq_p2019.tex",
          ARCH_CH.replace("GUIDEMISS", r"Also \seesolved{C09}." if missing == "guide" else ""))
    iq = work / "chapters" / "60_important_questions.tex"
    extra = r" Older form: \pyqsolved{P2019-2b}." + (r" And \pyqsolved{P2019-9z}." if missing == "archive" else "")
    iq.write_text(iq.read_text("utf-8").rstrip() + extra + "\n", "utf-8")
    bank = json.loads(json.dumps(BANK))
    bank["papers"].append({"id": "P2019", "year": 2019, "exam": "midsem", "source_slug": "PYQM_2019_x", "full_marks": 20})
    for qid, qno in (("P2019-2b", "2(b)"), ("P2019-9z", "9(z)")):
        bank["questions"].append(dict(BANK["questions"][0], id=qid, paper="P2019", qno=qno, marks=2.5, type="theory"))
    write(work / "pyq_bank.json", json.dumps(bank, indent=1))
    from PIL import Image
    for qid in ("P2019-2b", "P2019-9z"):
        Image.new("RGB", (900, 110), (235, 235, 242)).save(work / "receipts" / f"{qid}.png")
    if assignments:
        kinds = {"05_how_to_use": "auto", "20_exam_radar": "auto", "30_unit_one": "unit", "60_important_questions": "iq",
                 "700_pyq_p2024": "pyq_full", "701_pyq_p2019": "pyq_older", "80_mock_paper": "mock", "cheatsheet": "cheatsheet"}
        write(work / "assignments.json", json.dumps(dict({"chapters": [dict({"stem": s, "kind": k}, **(
            {"paper": "P2024"} if s.startswith("700") else {"paper": "P2019"} if s.startswith("701") else {}))
            for s, k in kinds.items()]}, **({"one_pdf": True} if one_pdf else {})), indent=1))
    return work


def aux_page(aux: Path, label: str):
    m = re.search(r"\\newlabel\{" + re.escape(label) + r"\}\{\{[^{}]*\}\{(\d+)\}", aux.read_text("latin-1")) if aux.exists() else None
    return int(m.group(1)) if m else None


def run(args, root, timeout=900):
    env = dict(os.environ, STUDYPREP_ROOT=str(root), PYTHONIOENCODING="utf-8")
    t0 = time.time()
    p = subprocess.Popen([sys.executable, str(TOOLS / args[0])] + args[1:], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out, time.time() - t0
    except subprocess.TimeoutExpired:
        # kill the whole tree: a hung pdflatex child would otherwise keep running and lock the fixture files
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        out, _ = p.communicate()
        return -9, f"TIMEOUT after {timeout}s\n{(out or '')[-2000:]}", time.time() - t0


def rm(p: Path):
    for _ in range(20):
        try:
            p.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(0.5)


# ----------------------------------------------------------------------------- harness
fails = 0
passed = 0


def check(name, cond, detail=""):
    global fails, passed
    if cond:
        passed += 1
        print(f"OK   {name}")
    else:
        fails += 1
        print(f"FAIL {name}\n     {str(detail)[-1500:]}")


def pdf_info(pdf: Path):
    import pymupdf as fitz
    d = fitz.open(pdf)
    out = {"pages": len(d), "meta": d.metadata, "toc": d.get_toc(simple=True),
           "sizes": [(round(p.rect.width), round(p.rect.height)) for p in d],
           "text": [p.get_text() for p in d]}
    d.close()
    return out


def deliverable(work, suffix):
    return work.parents[1] / f"Test_Subject_Midsem{suffix}"


def main():
    root = HERE / "_tmp" / "build"
    work = make_subject(root, dangling=True)
    sys.path.insert(0, str(TOOLS))

    # 1. robust pills: \mks / \clusterbadge in a \section title used to hang pdflatex (old timeout 900 s)
    write(work / "chapters" / "40_pills.tex", "\\chapter{Pills \\mks{5}}\n\\section{Sliding window \\mks{2.5} \\clusterbadge{C01} \\topicbadge{T01}}\nText.\n")
    rc, out, dt = run(["build.py", "TT", "--scope", "midsem", "--chapter", "40_pills"], root, timeout=240)
    check("section title with \\mks/\\clusterbadge compiles (no hang)", rc == 0 and dt < 200 and "RESULT PASS" in out,
          f"rc={rc} {dt:.0f}s {out[-600:]}")
    pdf = work / "build" / "chk_40_pills" / "chk_40_pills.pdf"
    if pdf.exists():
        toc = pdf_info(pdf)["toc"]
        check("bookmarks get the text form of the pills", any("[2.5 M]" in t[1] and "[A, P 79%]" in t[1] for t in toc), toc)
    else:
        check("bookmarks get the text form of the pills", False, "no PDF")
    rm(work / "chapters" / "40_pills.tex")

    # 2. lint rules
    write(work / "chapters" / "41_lint.tex", "\n".join([
        r"\chapter{Lint}",
        r"\section{Bad heading \mks{2.5}}",
        r"\begin{figure}[H]\centering x\caption{c}\end{figure}",
        r"{\tiny small}",
        r"\tier{A} \prob{40}",
        r"\section{A table-only topic}\label{sec:T01}",
        r"\begin{tabularx}{\linewidth}{lY}a&b\\\end{tabularx}", ""]))
    import importlib
    build = importlib.import_module("build")
    issues = build.lint(work / "chapters" / "41_lint.tex")
    blob = "\n".join(issues)
    check("lint: badge inside \\section", re.search(r"badge .*mks.*inside", blob), blob)
    check("lint: [H] placement", "[H]" in blob, blob)
    check("lint: \\tiny", "tiny" in blob, blob)
    check("lint: hand-typed \\prob/\\tier outside the auto chapters", "hand-typed \\tier" in blob and "hand-typed \\prob" in blob, blob)
    check("lint: tier A topic with only a table", "only visual is a table" in blob, blob)
    check("lint: blueprint visual type missing", "lacks its blueprint visual type 'storyboard'" in blob, blob)
    check("lint: auto chapter may hand-place \\tier/\\prob",
          not any("hand-typed" in i for i in build.lint(work / "chapters" / "05_how_to_use.tex")))
    check("lint: storyboard topic via \\input atom passes",
          not any("sec:T01" in i for i in build.lint(work / "chapters" / "30_unit_one.tex")),
          build.lint(work / "chapters" / "30_unit_one.tex"))
    rm(work / "chapters" / "41_lint.tex")

    # 3. parse_log on synthetic logs (review section 2.3)
    tmp = root / "logs"
    tmp.mkdir(parents=True, exist_ok=True)
    cases = {
        "toc": "(build/guide/guide.toc\nbuild/guide/guide.toc:3: Undefined control sequence.\nl.3 \\contentsline {section}\n",
        "aux": "build/guide/guide.aux:12: Argument of \\@newl@bel has an extra }.\n",
        "def": "C:/Program Files/MiKTeX/tex/generic/pgf/pgfsys-pdftex.def:120: Package pgfsys Error: bad.\n",
        "space": "C:/Program Files/MiKTeX/tex/latex/foo/foo.sty:9: Undefined control sequence.\n",
    }
    for k, v in cases.items():
        (tmp / f"{k}.log").write_text(v, "latin-1")
        errs, _w = build.parse_log(tmp / f"{k}.log")
        check(f"parse_log catches an error in a .{k} file", any(re.search(r":\d+: ", e) for e in errs), errs)
    (tmp / "float.log").write_text("LaTeX Warning: Float too large for page by 184.7pt on input line 2.\n", "latin-1")
    errs, _w = build.parse_log(tmp / "float.log")
    check("parse_log: Float too large is a LAYOUT error", any("LAYOUT" in e and "Float too large" in e for e in errs), errs)
    (tmp / "undef.log").write_text("LaTeX Warning: Reference `q:X-1' on page 3 undefined on input line 9.\n"
                                   "LaTeX Warning: Reference `q:X-1' on page 4 undefined on input line 12.\n", "latin-1")
    info = build.analyze_log(tmp / "undef.log") if hasattr(build, "analyze_log") else {}
    check("analyze_log counts distinct undefined labels and '??'",
          info.get("undefined") == {"q:X-1": 2} and info.get("undefined_text") == 2, info)

    # 4. full print build with a dangling ref: FAILS, prints RESULT BLOCKED, never writes the deliverable
    dst = deliverable(work, "_Guide.pdf")
    write(dst, "previous deliverable")
    old_bytes = dst.read_bytes()
    write(work / "studyguide.sty", "% stale copy from an old build\n")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    check("full build with an undefined ref fails (exit 1)", rc == 1, out[-800:])
    check("full build names the undefined label and the '??' count",
          "q:P2022-9z" in out and re.search(r"1 distinct labels?, 1 '\?\?'", out), out[-800:])
    check("final line is RESULT BLOCKED", out.strip().splitlines()[-1].startswith(("RESULT BLOCKED", "NOT COPIED"))
          and "RESULT BLOCKED" in out, out[-300:])
    check("failed build leaves the previous deliverable untouched", dst.read_bytes() == old_bytes)
    check("stale studyguide.sty copy removed; style comes from TEXINPUTS", not (work / "studyguide.sty").exists())
    rm(dst)

    # 5. fix the ref -> passes, copies, metadata, cheatsheet appended at its TOC page
    make_subject(root, dangling=False)
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    check("full build without dangling refs passes", rc == 0 and "RESULT PASS" in out, out[-1500:])
    check("deliverable copied on success", dst.exists())
    if dst.exists():
        pi = pdf_info(dst)
        check("PDF title/author metadata from the blueprint",
              pi["meta"].get("title") == "Test Subject Midsem Study Guide (unofficial)"
              and pi["meta"].get("author") == "Unofficial student study guide"
              and "TS 101" in pi["meta"].get("keywords", ""), pi["meta"])
        cs = [p for lvl, t, p in pi["toc"] if t.startswith("Cheatsheet")]
        check("print guide: cheatsheet bookmark points at a landscape page",
              cs and pi["sizes"][cs[0] - 1][0] > pi["sizes"][cs[0] - 1][1], (cs, pi["sizes"][-2:]))
        check("receipt image and solved idea rendered", any("From the paper" in t for t in pi["text"])
              and any("Solved idea" in t for t in pi["text"]) and not any("receipt missing" in t for t in pi["text"]))
        check("\\seesolved / \\pyqsolved resolve to page numbers",
              any(re.search(r"full solution on\s+p\.\s*\d", t) for t in pi["text"])
              and any(re.search(r"solved on\s+p\.\s*\d", t) for t in pi["text"]), "")
        check("\\flashcard prints nothing", not any("Stop-and-wait efficiency?" in t for t in pi["text"]))
    check("no studyguide.sty copied into the work folder", not (work / "studyguide.sty").exists())

    # 6. interactive edition: animation + storyboard kept, cheatsheet appended, honest TOC line
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--interactive"], root)
    di = deliverable(work, "_Guide_Interactive.pdf")
    check("interactive build passes and is copied", rc == 0 and di.exists(), out[-1200:])
    if di.exists():
        pi = pdf_info(di)
        txt = "\n".join(pi["text"])
        check("interactive keeps the storyboard under the animation", "Step 3" in txt and "press play" in txt, txt[:400])
        cs = [p for lvl, t, p in pi["toc"] if t.startswith("Cheatsheet")]
        check("interactive: cheatsheet appended at the page its TOC line names",
              cs and pi["sizes"][cs[0] - 1][0] > pi["sizes"][cs[0] - 1][1] and "Stop-and-wait" in pi["text"][cs[0] - 1],
              (cs, pi["sizes"]))

    # 7. phone edition: small page, wide TikZ + tabular shrunk to the line
    write(work / "chapters" / "45_wide.tex", "\n".join([
        r"\chapter{Wide things}",
        r"\begin{tikzpicture}\draw (0,0) rectangle (16,2); \node at (8,1) {very wide picture};\end{tikzpicture}",
        "", r"\begin{tikzpicture}\draw (0,0) rectangle (15,1);\end{tikzpicture}", "",
        r"\begin{tabular}{llll}aaaaaaaaaaaaaaaaaaaaaaaa & bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb & cccccccccccccccccccc & dddddddddddddd\\\end{tabular}",
        "", r"\begin{tabularx}{\linewidth}{L{33mm}YL{30mm}L{15mm}}a & examine header, check errors & b & c\\\end{tabularx}",
        # real CN T10 (2026-11-06): fixed L{} widths sized for A4 starve the Y column on a phone page
        "", r"\begin{table}[!htbp]\centering\small\zebra",
        r"\begin{tabularx}{\linewidth}{L{12mm}L{20mm}L{38mm}Y}\toprule",
        r"\thead{Type} & \thead{Name} & \thead{Value} & \thead{Notes' example [Name, Value, Type, TTL]}\\\midrule",
        r"A & host name & IP address & [star.c10r.facebook.com, 31.13.72.33, A, 17]\\",
        r"NS & domain & its authoritative server's host name & [facebook.com, a.ns.facebook.com, NS, 172797]\\\bottomrule",
        r"\end{tabularx}\caption{RR table from real CN T10}\end{table}",
        # real CN PYQ shape tables (2026-11-06): tier pill + P pill in an L{24mm} column on the phone page
        "", r"{\centering\footnotesize\setlength{\tabcolsep}{3.5pt}",
        r"\begin{tabularx}{\linewidth}{@{}L{8mm}YL{5mm}L{24mm}|L{8mm}YL{5mm}L{24mm}@{}}\toprule",
        r"\sgdefbadge{CX1}{D}{24}{low}{0.5}\sgdefbadge{CX2}{C}{57}{high}{1.2}",
        r"1(a) & DNS names; CNAME & 1 & \clusterbadge{CX1} & 3(a) & delays; file-transfer time & 2.5 & \clusterbadge{CX2}\\\bottomrule",
        r"\end{tabularx}\par}",
        # real SVP C070/C016/C096 (2026-11-06): a long \src slug is one unbreakable word on the phone line
        "", r"\textbf{Limitations of the speaking-rate model} \src{N_SVP_Week6_Theory_Lecture2_Pattern_Matching_HMM p3, p14}: words vary.",
        "", r"\begin{tabularx}{\linewidth}{L{20mm}Y}\toprule a & b \src{N_SVP_Week5_Theory_Lecture2_MFCC_LPCC p7}\\\bottomrule\end{tabularx}",
        # real SVP T06 (2026-11-06): a wide gather* in a formulabox overflowed the phone page by 109 pt
        "", r"\begin{formulabox}[STFT parameters]\begin{gather*}",
        r"L=\frac{\text{frame (ms)}\times f_s}{1000},\qquad H=\frac{\text{hop (ms)}\times f_s}{1000},\qquad \text{frames}=1+\Bigl\lfloor\frac{N-L}{H}\Bigr\rfloor\\",
        r"X_m[k]=\sum_{n=0}^{L-1}x[n+mH]\,w[n]\,e^{-j2\pi kn/N_{FFT}},\qquad S_m[k]=20\log_{10}\bigl(|X_m[k]|+\varepsilon\bigr)",
        r"\end{gather*}\end{formulabox}",
        "", r"\begin{align*} a &= \frac{0.75\times20\times1500\times8}{0.06} + \frac{0.75\times20\times1500\times8}{0.06} + \frac{0.75\times20\times1500\times8}{0.06}\end{align*}",
        "", r"\[ x = \frac{0.75\times20\times1500\times8}{0.06} + \frac{0.75\times20\times1500\times8}{0.06} + \frac{0.75\times20\times1500\times8}{0.06} \]",
        ""]))
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--phone"], root)
    dp = deliverable(work, "_Guide_Phone.pdf")
    check("phone build passes (wide TikZ, tabular, tabularx, display maths shrunk: no overfull)", rc == 0 and dp.exists(), out[-1500:])
    if dp.exists():
        pi = pdf_info(dp)
        w, h = pi["sizes"][1]
        check("phone page is about 105 x 187 mm", abs(w - 297.6) < 3 and abs(h - 530.1) < 3, pi["sizes"][:3])
    rm(work / "chapters" / "45_wide.tex")

    # 8. chapter builds: other chapters' refs warn; own \pyqsolved target missing is an error; float too large fails
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--chapter", "80_mock_paper"], root)
    check("chapter build: refs into other chapters are warnings (exit 0)", rc == 0 and "sec:T01" in out, out[-600:])
    write(work / "chapters" / "701_pyq_p2025.tex", r"""\chapter{2025 paper}
\begin{question}{2025 Midsem Q1(a)}{1}Some question.\end{question}
Linked from the radar as \pyqsolved{P2025-1a}.
""")
    bank = json.loads((work / "pyq_bank.json").read_text("utf-8"))
    bank["papers"].append({"id": "P2025", "year": 2025, "exam": "midsem", "full_marks": 20})
    bank["questions"].append(dict(bank["questions"][0], id="P2025-1a", paper="P2025"))
    (work / "pyq_bank.json").write_text(json.dumps(bank), "utf-8")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--chapter", "701_pyq_p2025"], root)
    check("chapter build: its own SG-REF target q:P2025-1a undefined is an error", rc == 1 and "q:P2025-1a" in out, out[-600:])
    rm(work / "chapters" / "701_pyq_p2025.tex")
    (work / "pyq_bank.json").write_text(json.dumps(BANK), "utf-8")
    write(work / "chapters" / "46_tall.tex", r"""\chapter{Tall}
\storyboard{6}{1}{0.9\linewidth}{A storyboard taller than a page.}{\path[use as bounding box] (0,0) rectangle (6,5);\node at (3,2.5) {\f};}
""")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--chapter", "46_tall"], root)
    check("Float too large fails the build", rc == 1 and "Float too large" in out, out[-600:])
    rm(work / "chapters" / "46_tall.tex")

    # 9. TOC-based page fill: fires on a half-empty page inside a chapter, not before a new chapter
    write(work / "chapters" / "47_fill.tex", "\\chapter{Fill}\nShort text.\n\\clearpage\nMore text on the next page.\n\\chapter{Next}\nText.\n")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--chapter", "47_fill"], root)
    pdf = work / "build" / "chk_47_fill" / "chk_47_fill.pdf"
    warns = build.page_fill(pdf) if pdf.exists() else ["no pdf"]
    check("page-fill check fires inside a chapter (header says 'Chapter' on every page)",
          len(warns) == 1 and "page 1 " in warns[0], warns)
    rm(work / "chapters" / "47_fill.tex")

    # 10. atoms
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--atom", "notes/T01"], root)
    check("--atom notes/T01 builds standalone", rc == 0 and (work / "build" / "atom_notes_T01" / "atom_notes_T01.pdf").exists(), out[-600:])
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--atom", "solve/C01"], root)
    check("--atom solve/C01 builds standalone", rc == 0, out[-600:])
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--atom", "recall/night_before"], root)
    check("--atom rejects anything but notes/ and solve/ (exit 2)", rc == 2, out[-300:])
    rc, out, _ = run(["build.py", "TT"], root)
    check("--scope is required (exit 2)", rc == 2, out[-300:])

    # 11. timeouts as specified
    check("timeouts: 180 s per pass for chapter builds, 600 s otherwise",
          getattr(build, "TIMEOUT_SMALL", None) == 180 and getattr(build, "TIMEOUT_FULL", None) == 600)

    # 12. cookbook: obeys its own lint, has the new patterns, compiles in print / interactive / phone
    cb = (PIPE / "latex" / "visual_cookbook.tex").read_text("utf-8")
    body = re.sub(r"(?<!\\)%.*", "", cb)
    check("cookbook: no [H], no \\tiny, no unsupported 'examiners award' claim",
          not re.search(r"\[H\]", body) and not re.search(r"\\tiny\b", body) and "examiners award" not in body)
    need = ["UML class", "UML sequence", "Data flow diagram", "Neural-network", "Convolution", "Fuzzy membership",
            "Lamport", "Reorder buffer", "Decision-tree", "k-means"]
    check("cookbook: patterns for SE, ML/IPA, CI, DOS, HPC, DMDW", all(n in cb for n in need), [n for n in need if n not in cb])
    for opt in ([], ["--interactive"], ["--phone"]):
        rc, out, _ = run(["build.py", "--cookbook"] + opt, root)
        check(f"cookbook compiles cleanly {' '.join(opt) or '(print)'}", rc == 0 and "RESULT PASS" in out, out[-800:])

    test_archive()
    print(f"{passed}/{passed + fails} passed")
    sys.exit(1 if fails else 0)


def pdf_links(pdf: Path):
    import pymupdf as fitz
    with fitz.open(pdf) as d:
        return [l for p in d for l in p.get_links()]


def test_archive():
    """PYQ-archive edition: pyq_older chapters leave the main guide; cross-document refs resolve both ways."""
    root = HERE / "_tmp" / "build_archive"
    work = make_archive_subject(root)
    guide, arch = deliverable(work, "_Guide.pdf"), deliverable(work, "_PYQ_Archive.pdf")

    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    check("archive: main guide builds with an archived paper referenced", rc == 0 and guide.exists(), out[-1500:])
    if guide.exists():
        txt = "\n".join(pdf_info(guide)["text"])
        check("archive: main guide excludes pyq_older chapters", "2019 Midsem paper" not in txt, "")
        check("archive: \\pyqsolved to an archived paper prints 'PYQ archive, P2019 2(b)' (no ??)",
              "PYQ archive, P2019 2(b)" in txt and "??" not in txt, re.findall(r"PYQ archive[^\n]*", txt)[:3])
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--archive"], root)
    check("archive: --archive builds <Subject>_<Scope>_PYQ_Archive.pdf", rc == 0 and arch.exists() and "RESULT PASS" in out, out[-1500:])
    if arch.exists():
        pi = pdf_info(arch)
        txt = "\n".join(pi["text"])
        check("archive: own title page + intro", "Older papers, verbatim, with links to the full solutions in the Guide" in txt
              and "PYQ archive" in pi["text"][0], pi["text"][0][:300])
        check("archive: contains the older paper, not the guide chapters",
              "2019 Midsem paper" in txt and "Important questions" not in txt and "Unit one" not in txt)
        gp = aux_page(work / "build" / "guide" / "guide.aux", "solve:C01")
        check("archive: \\seesolved resolves to the guide page ('Guide, p. N', no ??)",
              gp and re.search(r"full solution in the\s+Guide,\s+p\.\s*%d\b" % gp, txt) and "??" not in txt,
              (gp, re.findall(r"full solution in the[^\n]*\n?[^\n]*", txt)[:2]))
        sp = aux_page(work / "build" / "guide" / "guide.aux", "sec:T01")
        check("archive: a raw \\pageref to a guide label prints the guide page", sp and re.search(r"%d \(Guide\)" % sp, txt),
              (sp, re.findall(r"Background on[^\n]*", txt)))
        links = pdf_links(arch)
        check("archive: guide pointers are links into the guide PDF",
              any(guide.name in str(l.get("file", "")) for l in links), [l for l in links if l.get("kind") != 1][:3])
        check("archive: PDF title metadata", pi["meta"].get("title") == "Test Subject Midsem PYQ Archive (unofficial)", pi["meta"])
    # second guide build: now the archive page is known
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    ap = aux_page(work / "build" / "archive" / "archive.aux", "q:P2019-2b")
    txt = "\n".join(pdf_info(guide)["text"]) if guide.exists() else ""
    check("archive: guide rebuilt after the archive shows the archive page",
          rc == 0 and ap and re.search(r"PYQ archive, P2019 2\(b\),\s+p\.\s*%d\b" % ap, txt), (ap, re.findall(r"PYQ archive[^\n]*", txt)[:2]))
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--archive", "--phone"], root)
    ph = deliverable(work, "_PYQ_Archive_Phone.pdf")
    check("archive: --archive --phone builds the phone archive", rc == 0 and ph.exists(), out[-1200:])
    if ph.exists():
        w, h = pdf_info(ph)["sizes"][-1]
        check("archive: phone archive page is about 105 x 187 mm", abs(w - 297.6) < 3 and abs(h - 530.1) < 3, (w, h))

    # deliberately missing cross-document targets fail, in both directions
    work = make_archive_subject(root, missing="guide")
    run(["build.py", "TT", "--scope", "midsem"], root)
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--archive"], root)
    check("archive: a \\seesolved target missing from the guide fails the archive build",
          rc == 1 and "solve:C09" in out and not deliverable(work, "_PYQ_Archive.pdf").exists(), out[-800:])
    work = make_archive_subject(root, missing="archive")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    check("archive: a \\pyqsolved target missing from the archive fails the guide build",
          rc == 1 and "q:P2019-9z" in out and "archive" in out.lower(), out[-800:])

    # without assignments.json: today's behaviour (everything in the guide); --archive has nothing to build
    work = make_archive_subject(root, assignments=False)
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    txt = "\n".join(pdf_info(deliverable(work, "_Guide.pdf"))["text"]) if deliverable(work, "_Guide.pdf").exists() else ""
    check("archive: no assignments.json -> older chapter stays in the guide, linked locally",
          rc == 0 and "2019 Midsem paper" in txt and "PYQ archive" not in txt, out[-800:])
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--archive"], root)
    check("archive: --archive without pyq_older chapters exits 1", rc == 1 and "RESULT BLOCKED" in out, out[-400:])
    test_one_pdf()


def test_one_pdf():
    """assignments.json one_pdf: true -> one PDF per subject: the pyq_older papers and the cheatsheet live inside
    the Guide (links local), and no separate _PYQ_Archive / _Cheatsheet deliverable is written."""
    root = HERE / "_tmp" / "build_one_pdf"
    work = make_archive_subject(root, one_pdf=True)
    guide = deliverable(work, "_Guide.pdf")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    check("one_pdf: guide builds", rc == 0 and guide.exists() and "RESULT PASS" in out, out[-1500:])
    txt = "\n".join(pdf_info(guide)["text"]) if guide.exists() else ""
    check("one_pdf: the older paper is inside the guide", "2019 Midsem paper" in txt, "")
    check("one_pdf: pointers to it are local (no 'PYQ archive, ...' cross-doc text, no ??)",
          "PYQ archive," not in txt and "??" not in txt, re.findall(r"PYQ archive[^\n]*", txt)[:3])
    check("one_pdf: no link into another PDF",
          not any(l.get("file") for l in pdf_links(guide)) if guide.exists() else False, "")
    check("one_pdf: the older papers sit under an 'Older papers' part divider", "Older papers" in txt, "")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--archive"], root)
    check("one_pdf: --archive has nothing to build and writes no archive PDF",
          rc == 1 and not deliverable(work, "_PYQ_Archive.pdf").exists(), out[-400:])
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem", "--cheatsheet"], root)
    check("one_pdf: --cheatsheet still compiles but delivers no separate _Cheatsheet.pdf",
          rc == 0 and not deliverable(work, "_Cheatsheet.pdf").exists(), out[-400:])
    rc, out, _ = run(["metrics.py", "TT", "--scope", "midsem"], root)
    check("one_pdf: metrics does not ask for an archive PDF", "_PYQ_Archive" not in out, out[-800:])
    test_updates_url(root, work)


def test_updates_url(root: Path, work: Path):
    """assignments.json updates_url: printed and clickable on the guide's title page; an unsafe URL fails the build."""
    guide = deliverable(work, "_Guide.pdf")
    url = "https://drive.google.com/drive/folders/1Ab-cD_9xYz"
    asg = json.loads((work / "assignments.json").read_text("utf-8"))
    (work / "assignments.json").write_text(json.dumps(dict(asg, updates_url=url), indent=1), "utf-8")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    pi = pdf_info(guide) if guide.exists() else {"text": [""]}
    first = re.sub(r"\s+", "", pi["text"][0])
    check("updates_url: guide builds", rc == 0 and "RESULT PASS" in out, out[-1200:])
    check("updates_url: the URL is printed on the title page", "Latestversionandcorrections" in first and url in first,
          pi["text"][0][-400:])
    links = pdf_links(guide) if guide.exists() else []
    check("updates_url: the URL is a clickable link", any(l.get("uri") == url for l in links),
          [l for l in links if l.get("uri")][:3])
    (work / "assignments.json").write_text(json.dumps(dict(asg, updates_url="https://x.test/a}\\input{evil"), indent=1), "utf-8")
    rc, out, _ = run(["build.py", "TT", "--scope", "midsem"], root)
    check("updates_url: an unsafe URL fails the build with a clear message", rc != 0 and "updates_url" in out, out[-600:])
    (work / "assignments.json").write_text(json.dumps(asg, indent=1), "utf-8")


if __name__ == "__main__":
    main()
