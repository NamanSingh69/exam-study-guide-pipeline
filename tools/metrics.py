"""
metrics.py — objective, reviewer-independent quality numbers for one subject/scope, and the release gate.

  py _pipeline/tools/metrics.py CN --scope midsem    -> prints every metric, appends to work/<scope>/metrics.jsonl,
                                                        final line RESULT PASS | RESULT BLOCKED: <gates>; exit 0 | 1
Reads the last full PRINT build (work/<scope>/build/guide/), so run `build.py <S> --scope <sc>` first.

HARD GATES (must be 0, or pyq_gate must be 1; any failure -> exit 1):
  ingest_errors      manifest.json -> health.errors (old manifests: entries with an "error" key)
  undefined_refs     distinct undefined labels in the full-build log ("??" in the PDF; undefined_text counts them)
  tex_errors         `file:line:` / `!` errors in the full-build log, or a nonzero pdflatex exit
  float_too_large    "Float too large for page" (a storyboard cut off)
  missing_chapters   expected chapters with no file: assignments.json -> chapters[].stem, else blueprint
                     units + auto/IQ/mock/cheatsheet chapters + one 7NN_pyq_<paper> per relevant paper
  missing_receipts   in-scope bank questions with no receipts/<qid>.png (or receipts.json file: null),
                     plus any \\receipt the guide could not find (SG-RECEIPT-MISSING)
  checks_failed      every checks/*.py (helpers named _*.py excepted) run with a 60 s timeout; nonzero exit = fail
  stale_pdf          a chapter, atom or badges.tex newer than the delivered <Subject>_<Scope>_Guide.pdf (or no PDF);
                     with a PYQ archive also: no _PYQ_Archive.pdf, an archive chapter newer than it, or it older than the guide
  cross_refs_unresolved  Guide <-> PYQ-archive references whose target the other document does not define
  (undefined_refs, tex_errors, float_too_large and cross_refs_unresolved cover the guide AND archive builds)
  pyq_gate           1 if verify_pyqs.py prints RESULT PASS
  out_of_window_in_chapters  \\label{q:<qid>} in chapters/atoms whose paper's year is outside blueprint.pyq_window (R4)
  internal_leaks     convention ids (conventions.json, with an underscore) printed in the guide PDF, e.g.
                     "(convention ack_number)": students must see the rule, never our internal name (2026-11-10)
TRACKED (lower is better unless noted):
  answers_vs_checks  checks/<qid>.py whose number appears in none of the \\answer{} boxes under \\label{q:<qid>}
  numbers_without_checks  \\answer{} boxes printing a number that no checks/<qid>.py (or <Cid>*.py for atom files) backs
  lint_issues, layout_warnings (TOC-based half-empty pages), overfull_boxes
  over_budget_pages  unit pages over important_questions.json targets.notes_pages[<unit>] (R4), else 1.5/lecture + 1
  iq_count_vs_target         {count, target, missing, extra}: iq: labels in 60_important_questions vs targets.iq_clusters
  cheatsheet_pages_vs_target {pages, target}: built cheatsheet pages before the night-before sheet vs targets.cheatsheet_pages
  numericals_without_check   in-scope numerical bank questions with no checks/<qid>.py or checks/<cluster>.py
  missing_badges     \\clusterbadge/\\topicbadge ids not defined in badges.tex (+ SG-BADGE-MISSING in the log)
  dup_solves         clusters with more than one \\begin{solvedidea}{Cid}, or atoms/solve/<Cid> \\input more than once
  pages_per_exam_mark   PYQ-chapter pages / marks of those papers, main guide only (contract: about 0.4)
  archive_pages, cross_refs_pending (refs printed without a page because the other PDF was not built yet)
  storyboards_per_process_topic (higher = better) mean storyboards in topics with blueprint visual "storyboard"
  visuals_per_topic  (higher = better) figures + tables + storyboards per sec:T.. section
  backtest_6h_cover  (higher = better) held-out marks covered by the 6 h plan (score.py / backtest.py)
"""
import argparse, json, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from workdir import resolve, setup_stdout, PIPE  # noqa: E402
import build  # noqa: E402

CHECK_TIMEOUT = 60
PAGES_PER_LECTURE = 1.5    # writer contract: unit notes <= 1.5 pages per lecture + 1 page (unit map, recap)
UNIT_EXTRA_PAGES = 1
HARD_GATES = ("ingest_errors", "undefined_refs", "tex_errors", "float_too_large", "missing_chapters",
              "missing_receipts", "checks_failed", "stale_pdf", "cross_refs_unresolved", "out_of_window_in_chapters",
              "internal_leaks")


def _count(v):
    return len(v) if isinstance(v, (list, dict, set)) else v


def run_checks(checks: Path):
    """[names that failed] — each check runs alone, cwd = checks/, so `import _arq` helpers resolve."""
    files = sorted(p for p in checks.glob("*.py") if not p.name.startswith("_")) if checks.exists() else []

    def one(p):
        try:
            r = subprocess.run([sys.executable, p.name], cwd=checks, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT)
            if r.returncode == 0:
                CHECK_OUT[p.stem] = r.stdout
            return None if r.returncode == 0 else f"{p.name} (exit {r.returncode}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ''})"
        except subprocess.TimeoutExpired:
            return f"{p.name} (timeout > {CHECK_TIMEOUT} s)"
    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(one, files))
    return [r for r in res if r], len(files)


CHECK_OUT = {}   # check name (file stem) -> stdout, filled by run_checks for answers_vs_checks


def internal_leaks(work: Path):
    """['p<N> <id>'] for convention ids with an underscore printed in the guide PDF (writers wrote
    'convention \\texttt{ack\\_number}'); None without a built guide. Plain-word ids are ordinary text."""
    pdf = work / "build" / "guide" / "guide.pdf"
    if not pdf.exists():
        return None
    conv = build.load_json(work / "conventions.json")
    ids = [c.get("id", "") for c in conv] if isinstance(conv, list) else list(conv) if isinstance(conv, dict) else []
    ids = [i for i in ids if isinstance(i, str) and "_" in i]
    if not ids:
        return []
    import pymupdf as fitz
    pat = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, sorted(ids, key=len, reverse=True))) + r")(?![A-Za-z0-9_])")
    out = []
    with fitz.open(pdf) as d:
        for i, page in enumerate(d):
            t = re.sub(r"-\s*\n\s*", "", page.get_text())       # undo hyphenated line breaks
            t = re.sub(r"\s+", " ", t)
            for cid in sorted(set(pat.findall(t))):
                out.append(f"p{i + 1} {cid}")
    return out


NUM = re.compile(r"(?:(?<![\w)\]}])-)?\d+(?:\.(\d+))?")    # a minus right after a symbol (S-1) is binary
GROUPED = re.compile(r"(?<![\d,])(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:,\d{2})+,\d{3})(?!\d)")   # 75,000 / 1,88,000


def nums(s):
    """[(value, decimals printed)]"""
    s = s.replace("{,}", "").replace(chr(92) + ",", "")        # LaTeX decimal comma / thin space
    s = GROUPED.sub(lambda m: m.group(0).replace(",", ""), s)   # western and Indian digit grouping
    return [(float(m.group(0)), len(m.group(1) or "")) for m in NUM.finditer(s)]


ANSWER_BOX = re.compile(r"\\answer\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}")
LABELS = re.compile(r"(?<![A-Za-z])[A-Za-z]+\d[\w-]*|\((?:[ivxIVX]+|[A-Za-z]|\d+)\)"      # Q5, MS2022-5a, (iii), (b), (2)
                    r"|(?i:paper|exam|midsem|endsem|year)\W{0,3}\d{4}")                     # "Paper 2024"


def numbers_without_checks(work: Path, names: set):
    """['<file>:<line> <owner>: \\answer{..}'] for \\answer{} boxes that print a number although no check backs them.
    Owner = nearest preceding \\label{q:<qid>} in the file (check <qid>), else the file stem (atoms/solve/<Cid>.tex:
    check <Cid> or <Cid>_*). Option labels, Q5, paper years and ids do not count as numbers. None without checks/."""
    if not (work / "checks").exists():
        return None
    out = []
    for p in all_sources(work):
        if "cheatsheet" in p.stem or "night" in p.stem:     # formula reminders, not computed results
            continue
        text = build.strip_comments(p.read_text("utf-8", errors="replace"))
        labels = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(r"\\label\{(q|iq):([^}]+)\}", text)]
        for m in ANSWER_BOX.finditer(text):
            body = re.sub(r"\b\d+\s*-{1,3}\s*[ivxlcdmIVXLCDM]+\b", " ", m.group(1))    # matching "1--x, 2--ix"
            if not nums(LABELS.sub(" ", body)):
                continue
            kind, q = next(((k, l) for pos, k, l in reversed(labels) if pos < m.start()), (None, None))
            if kind == "iq":                                 # important question: backed by checks/<Cid>*.py
                backed = q in names or any(n.startswith(q + "_") for n in names)
                q = "iq:" + q
            else:
                pre = [p.stem + "_"] + (["mock_"] if "mock" in p.stem else []) + (["drill_"] if "drill" in p.stem else [])
                backed = (q in names) if q else (p.stem in names or any(n.startswith(x) for n in names for x in pre))
            if not backed:
                out.append(f"{p.relative_to(work).as_posix()}:{build.line_of(text, m.start())} {q or p.stem}: {m.group(0)[:40]}")
    return out


def answers_vs_checks(work: Path, outs: dict):
    """['<qid>: check prints <n>, printed answer(s) <a>'] where a checks/<qid>.py's number appears in none of the
    \\answer{} boxes printed under \\label{q:<qid>} (up to the next question). Questions whose answer lives
    elsewhere (no \\answer under the label) are skipped."""
    if not outs:
        return None
    text = "\n".join(build.strip_comments(p.read_text("utf-8", errors="replace")) for p in all_sources(work))
    bad = []
    for qid, out in sorted(outs.items()):
        m = re.search(r"\\label\{q:" + re.escape(qid) + r"\}", text)
        if not m:
            continue
        rest = text[m.end():m.end() + 8000]
        stop = re.search(r"\\begin\{question\}|\\label\{q:", rest)
        region = rest[:stop.start()] if stop else rest
        answers = ANSWER_BOX.findall(region)
        if not answers:
            continue
        lines = [l for l in out.strip().splitlines() if l.strip()]
        want = [x for l in lines for x in nums(l)]                       # checks often print several results
        if not want:
            continue
        got = [x for a in answers for x in nums(a)]

        def close(w, g):
            (a, da), (b, db) = w, g
            if da == 0 and db == 0:
                return a == b                      # counts, sequence numbers, bytes: exact
            # both sides are rounded to the decimals they print: allow half a unit of each
            return abs(a - b) <= 0.5 * 10 ** -da + 0.5 * 10 ** -db + 1e-9
        if got and not any(close(w, g) for w in want for g in got):
            bad.append(f"{qid}: check prints {lines[-1].strip()[:70]}, printed answer(s) {', '.join(a[:30] for a in answers[:3])}")
    return bad


def ingest_errors(shared: Path):
    man = build.load_json(shared / "manifest.json")
    if not man:
        return None
    h = man.get("health")
    if isinstance(h, dict) and "errors" in h:
        return int(h["errors"] or 0)
    return sum(1 for f in man.get("files", {}).values() if isinstance(f, dict) and "error" in f)


def chapter_pages(work: Path, job="guide"):
    """{stem: pages} from the \\sgchapterend markers that build.py's wrapper writes into the .aux."""
    aux = work / "build" / job / f"{job}.aux"
    if not aux.exists():
        return {}
    ends = re.findall(r"\\sgchapterend\{([^}]+)\}\{(\d+)\}", aux.read_text("latin-1", errors="replace"))
    out, prev = {}, None
    for stem, page in ends:
        page = int(page)
        if prev is not None and stem != "frontmatter":
            out[stem] = max(1, page - prev)
        prev = page
    return out


def all_sources(work: Path):
    srcs = sorted((work / "chapters").glob("*.tex")) if (work / "chapters").exists() else []
    srcs += sorted((work / "atoms").rglob("*.tex")) if (work / "atoms").exists() else []
    return srcs


def compute(subject: str, scope: str, gate_fn=None, checks_fn=None):
    """All metrics as a dict (lists where the detail matters). gate_fn/checks_fn are injectable for tests."""
    subj, shared, work = resolve(subject, scope)
    build.SUBJ_DIR = subj
    m = {"time": time.strftime("%Y-%m-%d %H:%M"), "subject": subject, "scope": work.name}
    chapters = sorted(p for p in (work / "chapters").glob("*.tex")) if (work / "chapters").exists() else []
    info_t = build.topic_info(work)

    # ---- lint + log-derived numbers (last full print build)
    seen = set()
    m["lint_issues"] = sum(len(build.lint(c, info_t, seen)) for c in chapters)
    _main_ch, arch_ch = build.edition_chapters(work)
    jobs = ["guide"] + (["archive"] if arch_ch else [])      # the PYQ archive is a second document
    gdir = work / "build" / "guide"
    pdf, log = gdir / "guide.pdf", gdir / "guide.log"
    m["layout_warnings"] = len(build.page_fill(pdf)) if pdf.exists() else None
    log_badges, log_receipts = set(), set()
    if log.exists():
        for k in ("tex_errors", "overfull_boxes", "float_too_large", "undefined_refs", "undefined_text"):
            m[k] = 0
        m["undefined_labels"], m["multiply_defined_labels"] = [], []
        m["cross_refs_unresolved"], m["cross_refs_pending"] = [], 0
        for job in jobs:
            jl = work / "build" / job / f"{job}.log"
            if not jl.exists():
                continue   # an unbuilt archive is caught by stale_pdf
            res = build.load_json(work / "build" / job / "result.json")
            info = build.analyze_log(jl)
            tag = "" if job == "guide" else f"{job}:"
            m["tex_errors"] += max(info["tex_errors"], 1 if res.get("rc") not in (0, None) else 0)
            m["overfull_boxes"] += info["overfull"]
            m["float_too_large"] += info["float_too_large"]
            m["undefined_refs"] += len(info["undefined"])
            m["undefined_text"] += info["undefined_text"]
            m["undefined_labels"] += [tag + l for l in sorted(info["undefined"])]
            m["multiply_defined_labels"] += [tag + l for l in sorted(info["multiply_defined"])]
            x = res.get("xref") or {}
            m["cross_refs_unresolved"] += [tag + l for l in x.get("unresolved", [])]
            m["cross_refs_pending"] += x.get("pending", 0)
            log_badges |= info["badges_missing"]
            log_receipts |= info["receipts_missing"]
    else:
        for k in ("tex_errors", "overfull_boxes", "float_too_large", "undefined_refs", "undefined_text",
                  "cross_refs_unresolved"):
            m[k] = None
        m["note"] = "no full build log (run build.py first): log-based gates not measured"
    apdf = work / "build" / "archive" / "archive.pdf"
    m["archive_pages"] = build.pdf_pages(apdf) if arch_ch and apdf.exists() else None

    # ---- page budgets
    bp = build.load_json(work / "blueprint.json")
    iqj = build.load_json(work / "important_questions.json")
    targets = iqj.get("targets") or {}
    notes_t = targets.get("notes_pages") or {}
    pages = chapter_pages(work)
    over = 0
    for u in bp.get("units", []):
        stem = u.get("chapter")
        if not stem or not u.get("in_scope", True):
            continue
        n = pages.get(stem)
        if n is None:
            cpdf = work / "build" / f"chk_{stem}" / f"chk_{stem}.pdf"
            if cpdf.exists():
                try:
                    import pymupdf as fitz
                    n = len(fitz.open(cpdf))
                except ImportError:
                    n = None
        if n is not None:
            # R4: score.py's subject-scaled target (by unit id, or chapter stem) wins over the flat contract rule
            t = notes_t.get(u.get("id"), notes_t.get(stem))
            if isinstance(t, dict):          # score.py writes {"title", "pages", "lectures", "share", "why"}
                t = t.get("pages")
            budget = round(float(t)) if isinstance(t, (int, float)) else \
                round(PAGES_PER_LECTURE * (u.get("lectures") or 0) + UNIT_EXTRA_PAGES)
            over += max(0, n - budget)
    m["over_budget_pages"] = over
    # R4 targets (tracked): important-question clusters and cheatsheet length
    if targets.get("iq_clusters") is not None:
        iqch = work / "chapters" / "60_important_questions.tex"
        have = set(re.findall(r"\\label\{iq:([^}]+)\}", build.expand_inputs(iqch, work))) if iqch.exists() else set()
        t_iq = targets["iq_clusters"]
        # score.py writes {"clusters": [...], "count": n, "why": ...}; a bare list is accepted too
        want = [str(c) for c in (t_iq.get("clusters", []) if isinstance(t_iq, dict) else t_iq)]
        m["iq_count_vs_target"] = {"count": len(have), "target": len(want),
                                   "missing": sorted(set(want) - have), "extra": sorted(have - set(want))}
    else:
        m["iq_count_vs_target"] = None
    cpdf = work / "build" / "cheatsheet" / "cheatsheet.pdf"
    if targets.get("cheatsheet_pages") is not None:
        n_cs = None
        if cpdf.exists():
            try:
                import pymupdf as fitz
                with fitz.open(cpdf) as d:
                    texts = [p.get_text().lower() for p in d]
                # the night-before sheet (questions, then answers) is not part of the cheatsheet target
                nb = next((i for i, t in enumerate(texts) if "night before" in t[:400]), len(texts))
                n_cs = nb
            except ImportError:
                n_cs = build.pdf_pages(cpdf)
        t_cs = targets["cheatsheet_pages"]
        m["cheatsheet_pages_vs_target"] = {"pages": n_cs,
                                           "target": t_cs.get("pages") if isinstance(t_cs, dict) else t_cs}
    else:
        m["cheatsheet_pages_vs_target"] = None
    # R4 hard gate: no solved/printed PYQ (q: label) from a paper outside blueprint.pyq_window
    win = bp.get("pyq_window") or {}
    if win.get("from") is not None and win.get("to") is not None:
        years = {p["id"]: p.get("year") for p in build.bank_papers(work)}
        qpaper = {q["id"]: q.get("paper") for q in build.load_json(work / "pyq_bank.json").get("questions", [])}
        labs = set()
        for src in all_sources(work):
            labs |= set(re.findall(r"\\label\{q:([^}]+)\}", build.strip_comments(src.read_text("utf-8", errors="replace"))))
        out = sorted(q for q in labs if isinstance(years.get(qpaper.get(q, q.split("-")[0])), int)
                     and not int(win["from"]) <= years[qpaper.get(q, q.split("-")[0])] <= int(win["to"]))
        m["out_of_window_in_chapters"] = len(out)
        if out:
            m["out_of_window_labels"] = out
    else:
        m["out_of_window_in_chapters"] = 0
    m["guide_pages"] = sum(pages.values()) if pages else None
    papers = {p["id"]: p for p in build.bank_papers(work)}
    pyq_pages = {s: n for s, n in pages.items() if re.fullmatch(r"7\d*_pyq_.+", s)}
    marks = 0.0
    for s in pyq_pages:
        pid = s.split("_pyq_", 1)[1].lower()
        p = next((p for k, p in papers.items() if k.lower() == pid), None)
        marks += float((p or {}).get("full_marks") or 0)
    m["pages_per_exam_mark"] = round(sum(pyq_pages.values()) / marks, 3) if marks else None

    # ---- bank-derived
    bank = build.load_json(work / "pyq_bank.json")
    qs = [q for q in bank.get("questions", []) if q.get("in_scope", True)]
    checks = work / "checks"
    names = {p.stem for p in checks.glob("*.py")} if checks.exists() else set()
    # papers outside blueprint.pyq_window are record-only (R4): their numericals are never printed or solved
    wyears = {p["id"]: p.get("year") for p in bank.get("papers", [])}
    def _in_window(q):
        y = wyears.get(q.get("paper"))
        return not (win.get("from") is not None and win.get("to") is not None and isinstance(y, int)
                    and not int(win["from"]) <= y <= int(win["to"]))
    m["numericals_without_check"] = [q["id"] for q in qs if q.get("type") == "numerical" and _in_window(q)
                                     and q["id"] not in names and (q.get("cluster") or "") not in names]
    rdir = work / "receipts"
    rjson = build.load_json(rdir / "receipts.json")
    miss = {q["id"] for q in qs if not (rdir / f"{q['id']}.png").exists()
            or (q["id"] in rjson and isinstance(rjson[q["id"]], dict) and rjson[q["id"]].get("file", "x") is None)}
    m["missing_receipts"] = sorted(miss | set(log_receipts))
    m["ingest_errors"] = ingest_errors(shared)

    # ---- source-derived
    text = {p: build.strip_comments(p.read_text("utf-8", errors="replace")) for p in all_sources(work)}
    joined = "\n".join(text.values())
    badges_tex = (work / "badges.tex").read_text("utf-8", errors="replace") if (work / "badges.tex").exists() else ""
    defined = set(re.findall(r"\\sgdef(?:badge|topic)\{([^}]+)\}", badges_tex))
    used = set(re.findall(r"\\(?:clusterbadge|topicbadge)\{([^}]+)\}", joined))
    used |= set(re.findall(r"\\begin\{solvedidea\}\{([^}]+)\}", joined))   # its title shows the badge
    m["missing_badges"] = sorted((used - defined) | set(log_badges))
    solves = {}
    for c in re.findall(r"\\begin\{solvedidea\}\{([^}]+)\}", joined):
        solves[c] = solves.get(c, 0) + 1
    inputs = {}
    for c in re.findall(r"\\input\{atoms/solve/([^}.]+)(?:\.tex)?\}", joined):
        inputs[c] = inputs.get(c, 0) + 1
    m["dup_solves"] = sorted({c for c, n in solves.items() if n > 1} | {c for c, n in inputs.items() if n > 1})
    m["missing_chapters"] = [w for w, ok in build.expected_chapters(work) if not ok]

    # topics (chapters with their atoms inlined)
    vis, boards = [], []
    for ch in chapters:
        for tid, _, chunk in build.topic_sections(build.expand_inputs(ch, work)):
            vis.append(len(re.findall(r"\\begin\{(?:tikzpicture|table|xltabular|tabularx)\}|\\(?:stepanim|storyboard|figfromnotes)\b", chunk)))
            if (info_t.get(tid, {}).get("visual") or "").lower() == "storyboard":
                boards.append(len(re.findall(r"\\(?:stepanim|storyboard)\b", chunk)))
    m["visuals_per_topic"] = round(sum(vis) / len(vis), 2) if vis else None
    m["storyboards_per_process_topic"] = round(sum(boards) / len(boards), 2) if boards else None

    # ---- staleness
    # guide: every source except the archive chapters; archive: its chapters, and it must be newer than the guide
    # (its "Guide, p. N" pointers come from the guide build)
    dst = build.deliverable(subj, work, "_Guide.pdf")
    arch_set = set(arch_ch)
    newest = lambda ps: max((p for p in ps if p.exists()), key=lambda p: p.stat().st_mtime, default=None)
    stale = []
    g_new = newest([p for p in text if p not in arch_set] + [work / "badges.tex"])
    if not dst.exists():
        stale.append(f"no delivered {dst.name}")
    elif g_new and g_new.stat().st_mtime > dst.stat().st_mtime + 1:
        stale.append(f"{g_new.relative_to(work).as_posix()} is newer than {dst.name}")
    if arch_ch:
        adst = build.deliverable(subj, work, "_PYQ_Archive.pdf")
        a_new = newest(arch_ch + [work / "badges.tex"])
        if not adst.exists():
            stale.append(f"no delivered {adst.name}")
        elif a_new and a_new.stat().st_mtime > adst.stat().st_mtime + 1:
            stale.append(f"{a_new.relative_to(work).as_posix()} is newer than {adst.name}")
        # cross-document pages: each build recorded the other document's label->page table it used
        for job, side, other in (("guide", "main", "PYQ archive"), ("archive", "archive", "guide")):
            res = build.load_json(work / "build" / job / "result.json")
            used = res.get("xref_sig")
            now = build.xref_sig(build.xref_table(work, side, False), (res.get("xref") or {}).get("used"))
            if (work / "build" / job / "result.json").exists() and used != now:
                stale.append(f"the {job} was built against an older {other} (its cross-document page numbers are "
                             f"stale): rebuild the {job}")
    # phone editions: a failed phone build leaves the previous phone PDF in place (real SVP, 2026-11-06), so a
    # delivered phone PDF must be as fresh as the sources of its edition
    for suffix, src_new in (("_Guide_Phone.pdf", g_new), ("_PYQ_Archive_Phone.pdf", newest(arch_ch) if arch_ch else None)):
        pdst = build.deliverable(subj, work, suffix)
        if pdst.exists() and src_new and src_new.stat().st_mtime > pdst.stat().st_mtime + 1:
            stale.append(f"{src_new.relative_to(work).as_posix()} is newer than {pdst.name} (phone edition not rebuilt)")
    m["stale_pdf"] = int(bool(stale))
    if stale:
        m["stale_detail"] = "; ".join(stale)

    # ---- executed checks
    failed, n_checks = (checks_fn or run_checks)(checks)
    m["checks_run"], m["checks_failed"] = n_checks, failed
    m["answers_vs_checks"] = answers_vs_checks(work, dict(CHECK_OUT)) if checks_fn is None else None
    m["internal_leaks"] = internal_leaks(work)
    m["numbers_without_checks"] = numbers_without_checks(work, names)

    # ---- backtest
    iq = build.load_json(work / "important_questions.json")
    bt = iq.get("backtest") or build.load_json(PIPE / "model_params.json").get("backtest", {}).get(f"{subject}/{work.name}")
    try:
        m["backtest_6h_cover"] = bt["summary"]["new"]["cover_6h"]["mean"]
    except (TypeError, KeyError):
        m["backtest_6h_cover"] = None

    # ---- fidelity gate
    if gate_fn is None:
        r = subprocess.run([sys.executable, str(Path(__file__).parent / "verify_pyqs.py"), subject, "--scope", work.name],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        m["pyq_gate"] = int(bool(re.search(r"^RESULT PASS", r.stdout, re.M)))
        if not m["pyq_gate"]:
            m["pyq_gate_detail"] = (re.findall(r"^RESULT .*$", r.stdout, re.M) or [r.stdout.strip()[-300:]])[-1]
    else:
        m["pyq_gate"] = gate_fn()
    return m


def gates(m):
    """[reason] for every hard gate that failed."""
    bad = []
    for k in HARD_GATES:
        v = _count(m.get(k))
        if v is None:
            if k in ("undefined_refs", "tex_errors", "float_too_large", "cross_refs_unresolved"):
                bad.append(f"{k} not measured (no full build)")
            elif k == "ingest_errors":
                bad.append("ingest_errors not measured (no manifest.json)")
        elif v:
            bad.append(f"{k}={v}")
    if m.get("pyq_gate") != 1:
        bad.append("pyq_gate=0")
    return bad


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="quality metrics + release gate for one subject/scope")
    ap.add_argument("subject")
    ap.add_argument("--scope")
    a = ap.parse_args()
    m = compute(a.subject, a.scope)
    print(json.dumps(m, indent=1))
    _subj, _shared, work = resolve(a.subject, a.scope)
    with open(work / "metrics.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(m) + "\n")
    print("\nmetric                          value")
    for k, v in m.items():
        if k in ("time", "subject", "scope", "undefined_labels") or k.endswith("_detail"):
            continue
        tag = "GATE " if k in HARD_GATES or k == "pyq_gate" else "     "
        if isinstance(v, dict) and "target" in v:   # iq_count_vs_target / cheatsheet_pages_vs_target
            v = f"{v.get('count', v.get('pages'))}/{v['target']}"
        print(f"{tag}{k:28s} {_count(v)}")
    nwc = m.get("numbers_without_checks") or []
    for loc in nwc[:10]:
        print(f"  numbers_without_checks: {loc}")
    if len(nwc) > 10:
        print(f"  numbers_without_checks: ... {len(nwc) - 10} more (see metrics.jsonl)")
    bad = gates(m)
    print("RESULT PASS" if not bad else "RESULT BLOCKED: " + "; ".join(bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
