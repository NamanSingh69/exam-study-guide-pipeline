"""
build.py — assemble, compile, lint and render study guides.

  py _pipeline/tools/build.py CN --scope midsem                  full print guide -> CN/<Subject>_<Scope>_Guide.pdf
  py _pipeline/tools/build.py CN --scope midsem --interactive    + animations (storyboards kept) -> _Guide_Interactive.pdf
  py _pipeline/tools/build.py CN --scope midsem --phone          105 x 187 mm single column -> _Guide_Phone.pdf
  py _pipeline/tools/build.py CN --scope midsem --archive [--phone]   older papers (assignments.json kind pyq_older)
                                                                 -> _PYQ_Archive.pdf / _PYQ_Archive_Phone.pdf
      Two documents: pyq_older chapters leave the main guide. \\seesolved / \\ref / \\pageref into the other
      document print "Guide, p. N" / "PYQ archive, MS2022 1(a), p. N" (linked to its PDF) from its .aux.
      Order: guide, then --archive, then the guide again (metrics.py stale_pdf says when a rebuild is due).
  py _pipeline/tools/build.py CN --scope midsem --chapter 32_transport_layer [--render]   ONE chapter (parallel-safe)
  py _pipeline/tools/build.py CN --scope midsem --atom notes/T07 [--render]              ONE atom (atoms/notes/T07.tex)
  py _pipeline/tools/build.py CN --scope midsem --cheatsheet     landscape cheatsheet -> _Cheatsheet.pdf
  py _pipeline/tools/build.py --cookbook [--interactive|--phone] [--render]              the visual cookbook
  --lint-only (with --chapter/--atom) lints without compiling.

Layout (relative to <SUBJ>/work/<scope>/):
  chapters/NN_name.tex     bare chapter bodies, assembled in filename order (00_cover first, cheatsheet last)
  atoms/notes|solve/*.tex  \\input by chapters; resolved through TEXINPUTS=<_pipeline/latex>;<work>;
  badges.tex, receipts/    produced by score.py / receipts.py; picked up by studyguide.sty
  build/<job>/             aux/log/pdf + result.json        qa/<job>/  rendered contact sheets
Rules (Round 4):
  * pdflatex's return code counts; every `file:line: msg` error counts (.toc/.aux/.def, paths with spaces).
  * `Float too large`, overfull vboxes and overfull hboxes > 4 pt are LAYOUT errors.
  * undefined references are ERRORS on full builds; on --chapter/--atom builds they are warnings, except
    \\pyqsolved/\\seesolved targets (SG-REF) that belong to the chapter itself (q:<paper>-.. in 7N_pyq_<paper>).
  * deliverables are copied into <SUBJ>/ only when the build succeeded.
Exit code 0 = PDF produced with no errors (final line RESULT PASS), 1 = failed (RESULT BLOCKED: ...), 2 = usage.
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from workdir import resolve, setup_stdout, PIPE, ROOT, SCOPES  # noqa: E402

LATEX = PIPE / "latex"
STY = LATEX / "studyguide.sty"
OVERFULL_PT = 4.0
TIMEOUT_SMALL = 180   # per pass: --chapter / --atom / --cheatsheet
TIMEOUT_FULL = 600    # per pass: full guides, cookbook
AUTO_CHAPTERS = ("05_how_to_use", "20_exam_radar")   # score.py output: may hand-place \prob / \tier

FORBIDDEN = [r"\\documentclass", r"\\usepackage", r"\\begin\{document\}", r"\\end\{document\}",
             r"\\usetikzlibrary", r"\\definecolor\{(sgnavy|sgteal|sgamber)"]
BADGES = r"\\(mks|clusterbadge|topicbadge|prob|tier|ev|asked|stepno)\b"
SECTIONING = r"\\(chapter|section|subsection|subsubsection|paragraph)\*?"

# visual types the blueprint assigns to a topic (topic.visual, vocabulary in schemas.md; lead decision R3)
V_TIKZ = r"\\begin\{tikzpicture\}|\\tikz\b"
V_BOARD = r"\\(stepanim|storyboard)\b"
V_TABLE = r"\\begin\{(tabular|tabularx|xltabular|longtable)\}"
V_IMG = r"\\(figfromnotes|includegraphics)\b"
V_PLOT = r"\\begin\{(axis|semilogyaxis|semilogxaxis|loglogaxis)\}"
V_DRAW = V_TIKZ + "|" + V_BOARD          # a storyboard body is a tikz picture too
# type -> list of regexes that must ALL match inside the topic's section
VISUAL_RULES = {
    "storyboard": [V_BOARD],
    "plot": [V_PLOT],
    "table": [r"\\begin\{(tabularx|xltabular)\}"],
    "figure": [r"\\figfromnotes\b"],
    "sequence": [V_DRAW, r"\blifeline\b"],
    "fsm": [V_DRAW, r"\[(?:[^\]]*,)?\s*state\b|\bsmstate\b"],
    "tree": [V_DRAW, r"\bchild\b"],
    "block": [V_DRAW], "graph": [V_DRAW], "array": [V_DRAW], "pipeline": [V_DRAW],
    "flowchart": [V_DRAW], "uml": [V_DRAW],
}
VISUAL_ANY_DRAWN = "|".join([V_TIKZ, V_BOARD, V_IMG, V_PLOT])   # everything except tables
SUBJ_DIR = None  # set by main() / metrics.py


# ------------------------------------------------------------------ helpers
def strip_comments(txt: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", txt)


def line_of(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


def brace_arg(text: str, i: int):
    """text[i] == '{' -> (content, index after the matching '}'), or (None, i)."""
    if i >= len(text) or text[i] != "{":
        return None, i
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "\\":
            continue
        if c == "{" and text[j - 1] != "\\":
            depth += 1
        elif c == "}" and text[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
    return None, i


def headings(body: str):
    """Yield (match, title, end) for every sectioning command with a balanced-brace title."""
    for m in re.finditer(SECTIONING + r"\s*(\[[^\]]*\])?\s*(?=\{)", body):
        title, end = brace_arg(body, m.end())
        if title is not None:
            yield m, title, end


def work_of(path: Path):
    for p in path.resolve().parents:
        if p.name in SCOPES:
            return p
    return None


def expand_inputs(path: Path, work: Path, seen=None):
    """Text of `path` with \\input{atoms/..}/\\input{chapters/..} inlined (comments stripped)."""
    seen = seen or set()
    if path in seen or not path.exists():
        return ""
    seen.add(path)
    body = strip_comments(path.read_text(encoding="utf-8", errors="replace"))

    def sub(m):
        f = m.group(1)
        p = work / (f if f.endswith(".tex") else f + ".tex")
        return expand_inputs(p, work, seen) if p.exists() else m.group(0)
    return re.sub(r"\\input\{([^}]+)\}", sub, body)


def input_files(path: Path, work: Path):
    """The files a chapter \\inputs (recursively) that live in the work folder."""
    out, todo = [], [path]
    while todo:
        p = todo.pop()
        if not p.exists():
            continue
        for f in re.findall(r"\\input\{([^}]+)\}", strip_comments(p.read_text("utf-8", errors="replace"))):
            q = work / (f if f.endswith(".tex") else f + ".tex")
            if q.exists() and q not in out:
                out.append(q); todo.append(q)
    return out


def load_json(p: Path):
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def topic_info(work: Path):
    """{topic id: {"visual": str|None, "tier": "A".."E"|None, "title": str}} from blueprint + important_questions."""
    info = {}
    bp = load_json(work / "blueprint.json")
    for u in bp.get("units", []):
        for t in u.get("topics", []):
            info[t.get("id")] = {"visual": (t.get("visual") or None), "tier": t.get("tier"), "title": t.get("title", ""),
                                 "unit": u.get("id"), "in_scope": u.get("in_scope", True)}
    iq = load_json(work / "important_questions.json")
    for c in iq.get("clusters", []):
        t, tier = c.get("topic"), c.get("tier")
        if t in info and tier:
            cur = info[t].get("tier")
            info[t]["tier"] = min(cur, tier) if cur else tier
    for t in iq.get("topics", []):
        if t.get("topic") in info and t.get("tier"):
            cur = info[t["topic"]].get("tier")
            info[t["topic"]]["tier"] = min(cur, t["tier"]) if cur else t["tier"]
    return info


def topic_sections(body: str):
    """[(topic id, start, chunk)] for every \\section{..}\\label{sec:Txx} in an (expanded) body."""
    secs = []
    for m, title, end in headings(body):
        if m.group(1) != "section":
            continue
        lm = re.match(r"\s*\\label\{sec:([^}]+)\}", body[end:end + 300])
        secs.append((lm.group(1) if lm else None, m.start(), end))
    out = []
    for k, (tid, start, end) in enumerate(secs):
        stop = secs[k + 1][1] if k + 1 < len(secs) else len(body)
        ch = re.search(r"\\chapter\*?\s*\{", body[end:stop])
        if ch:
            stop = end + ch.start()
        if tid:
            out.append((tid, start, body[end:stop]))
    return out


# ------------------------------------------------------------------ lint
def lint_file(path: Path):
    """Per-file checks (one chapter or atom body)."""
    issues = []
    txt = path.read_text(encoding="utf-8", errors="replace")
    body = strip_comments(txt)
    name = path.name
    for pat in FORBIDDEN:
        for m in re.finditer(pat, body):
            issues.append(f"{name}:{line_of(body, m.start())}: forbidden in a chapter body: {m.group(0)} (preamble lives in studyguide.sty)")
    opens = re.findall(r"\\begin\{([^}]+)\}", body)
    closes = re.findall(r"\\end\{([^}]+)\}", body)
    for env in sorted(set(opens) | set(closes)):
        if opens.count(env) != closes.count(env):
            issues.append(f"{name}: \\begin{{{env}}} x{opens.count(env)} vs \\end{{{env}}} x{closes.count(env)}")
    depth = 0
    for i, ch in enumerate(re.sub(r"\\[{}]", "", body)):
        depth += (ch == "{") - (ch == "}")
        if depth < 0:
            issues.append(f"{name}: unbalanced '}}' near char {i}"); break
    if depth > 0:
        issues.append(f"{name}: {depth} unclosed '{{'")
    for m in re.finditer(r"\\tiny\b", body):
        issues.append(f"{name}:{line_of(body, m.start())}: \\tiny text is unreadable in print - use \\scriptsize or larger")
    for m in re.finditer(r"\\begin\{(figure|table)\*?\}\s*\[H\]", body):
        issues.append(f"{name}:{line_of(body, m.start())}: [H] placement - use [!htbp] (an [H] float that does not fit leaves a half-empty page)")
    for m, title, _ in headings(body):
        b = re.search(BADGES, title)
        if b:
            issues.append(f"{name}:{line_of(body, m.start())}: badge \\{b.group(1)} inside \\{m.group(1)}{{..}} - put badges on the line after the heading")
    if path.stem not in AUTO_CHAPTERS:
        for m in re.finditer(r"\\(prob|tier)\s*\{", body):
            issues.append(f"{name}:{line_of(body, m.start())}: hand-typed \\{m.group(1)}{{..}} goes stale when score.py re-runs - use \\clusterbadge{{Cxx}} / \\topicbadge{{Txx}}")
    for m in re.finditer(r"\b(similarly|left as an exercise|refer to (the )?previous)\b", body, re.I):
        issues.append(f"{name}:{line_of(body, m.start())}: lazy phrase '{m.group(0)}' - solve it fully")
    work = work_of(path)
    for m in re.finditer(r"\\(?:includegraphics|figfromnotes)(\[[^\]]*\])?\{([^}]+)\}", body):
        f = m.group(2)
        bases = [b for b in ((work, work.parent) if work else (path.parent,))]
        if not any((b / f).exists() or (b / (f + ".png")).exists() for b in bases):
            issues.append(f"{name}: missing image {f}")
    return issues


def lint_topics(path: Path, work: Path, info=None):
    """Topic-level checks over a chapter with its \\input atoms inlined."""
    info = topic_info(work) if info is None else info
    body = expand_inputs(path, work)
    issues = []
    for tid, start, chunk in topic_sections(body):
        where = f"{path.name}: topic sec:{tid}"
        t = info.get(tid, {})
        drawn = re.search(VISUAL_ANY_DRAWN, chunk)
        table = re.search(V_TABLE, chunk)
        if not drawn and not table:
            issues.append(f"{where} has no visual (figure/table/storyboard) - every topic needs one")
            continue
        if t.get("tier") in ("A", "B") and not drawn:
            issues.append(f"{where} is tier {t['tier']} but its only visual is a table - tables do not count for tier A/B topics")
        v = (t.get("visual") or "").strip().lower()
        if v:
            rules = VISUAL_RULES.get(v)
            if rules is None:
                issues.append(f"{where} has unknown blueprint visual type '{v}' (see schemas.md 'Visual types')")
            elif not all(re.search(r, chunk) for r in rules):
                issues.append(f"{where} lacks its blueprint visual type '{v}' (needs: {' + '.join(rules)})")
    return issues


def lint(path: Path, info=None, seen=None):
    """All lint for one chapter (or atom): its own file, the atoms it \\inputs, then topic checks."""
    work = work_of(path)
    seen = set() if seen is None else seen
    issues = []
    for f in [path] + (input_files(path, work) if work else []):
        if f in seen:
            continue
        seen.add(f)
        issues += lint_file(f)
    if work:
        issues += lint_topics(path, work, info)
    return issues


def lint_cookbook(path: Path):
    body = strip_comments(path.read_text("utf-8", errors="replace"))
    out = [f"{path.name}:{line_of(body, m.start())}: [H] placement" for m in re.finditer(r"\\begin\{(figure|table)\}\s*\[H\]", body)]
    out += [f"{path.name}:{line_of(body, m.start())}: \\tiny" for m in re.finditer(r"\\tiny\b", body)]
    return out


# ------------------------------------------------------------------ metadata / expectations
def meta(work: Path):
    """(subject, code, Scope) — the scope comes from the work folder name, the rest from the blueprint."""
    d = load_json(work / "blueprint.json")
    scope = work.name.capitalize() if work.name in SCOPES else d.get("scope", "Exam")
    subj = d.get("subject") or (SUBJ_DIR.name if SUBJ_DIR else work.name)
    return subj, d.get("code", ""), scope


def deliverable(subj_dir: Path, work: Path, suffix: str) -> Path:
    subject, _, scope = meta(work)
    return subj_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', subject).strip('_')}_{scope}{suffix}"


def pdf_meta(work: Path, archive=False):
    subject, code, scope = meta(work)
    bp = load_json(work / "blueprint.json")
    clean = lambda s: re.sub(r"[\\{}%#^~$]", "", str(s)).replace("&", "and").strip()
    units = [clean(u.get("title", "")) for u in bp.get("units", []) if u.get("in_scope", True) and u.get("title")]
    kw = [clean(code), clean(subject), scope, "study guide", "past papers", "solved PYQs"] + units
    what = "PYQ Archive" if archive else "Study Guide"
    return {"pdftitle": f"{clean(subject)} {scope} {what} (unofficial)",
            "pdfauthor": "Unofficial student study guide",
            "pdfsubject": f"{clean(subject)}{' (' + clean(code) + ')' if code else ''}: {scope} examination preparation",
            "pdfkeywords": ", ".join(k for k in kw if k)}


def bank_papers(work: Path):
    return load_json(work / "pyq_bank.json").get("papers", [])


# ------------------------------------------------------------------ two documents: Guide + PYQ archive
ARCHIVE_KIND = "pyq_older"
DOCS = {"main": ("G", "Guide"), "archive": ("A", "PYQ archive")}


def chapter_kinds(work: Path):
    return {c["stem"]: c.get("kind") for c in load_json(work / "assignments.json").get("chapters", []) if c.get("stem")}


def one_pdf(work: Path) -> bool:
    """assignments.json "one_pdf": true -> one PDF per subject: the pyq_older papers go at the end of the guide
    (after a divider, before the cheatsheet) and no separate _PYQ_Archive / _Cheatsheet file is delivered."""
    return bool(load_json(work / "assignments.json").get("one_pdf"))


SAFE_URL = re.compile(r"https://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~/?=+-]*)?")


def updates_url(work: Path):
    """assignments.json updates_url (the shared folder with the latest version), or None. Raises ValueError when it
    is not a plain https URL: it is pasted into LaTeX, so braces, backslashes, %, # and spaces are refused."""
    u = load_json(work / "assignments.json").get("updates_url")
    if u in (None, ""):
        return None
    if not isinstance(u, str) or not SAFE_URL.fullmatch(u):
        raise ValueError(f"assignments.json updates_url {u!r} is not a plain https URL (letters, digits, . - _ ~ / ? = +)")
    return u


def older_chapters(work: Path):
    """The pyq_older chapters, whichever document they end up in."""
    chdir = work / "chapters"
    kinds = chapter_kinds(work)
    return sorted(p for p in chdir.glob("*.tex") if kinds.get(p.stem) == ARCHIVE_KIND) if chdir.exists() else []


def edition_chapters(work: Path):
    """(main-guide chapters, archive chapters). Archive = assignments.json kind pyq_older; without
    assignments.json every chapter stays in the main guide (pre-archive behaviour). one_pdf: the archive
    chapters are appended to the main guide and there is no second document."""
    chdir = work / "chapters"
    allc = sorted(p for p in chdir.glob("*.tex") if p.name not in ("00_cover.tex", "cheatsheet.tex")) if chdir.exists() else []
    arch = older_chapters(work)
    main = [p for p in allc if p not in arch]
    return (main + arch, []) if one_pdf(work) else (main, arch)


def archived_papers(work: Path):
    return {c.get("paper") for c in load_json(work / "assignments.json").get("chapters", [])
            if c.get("kind") == ARCHIVE_KIND and c.get("paper")}


def source_labels(paths, work: Path):
    """({labels defined by these chapters incl. their \\input atoms}, {solve:<Cid>: title})."""
    labels, titles = set(), {}
    for p in paths:
        body = expand_inputs(p, work)
        labels |= set(re.findall(r"\\label\{([^}]+)\}", body))
        for m in re.finditer(r"\\begin\{solvedidea\}\{([^}]+)\}", body):
            t, _ = brace_arg(body, m.end())
            labels.add(f"solve:{m.group(1)}")
            titles[f"solve:{m.group(1)}"] = (t or "").strip()
    return labels, titles


def aux_labels(aux: Path):
    """{label: (number, page, title)} from \\newlabel lines of a built document's .aux."""
    out = {}
    if not aux.exists():
        return out
    t = aux.read_text("latin-1", errors="replace")
    for m in re.finditer(r"^\\newlabel\{([^}]+)\}", t, re.M):
        outer, _ = brace_arg(t, m.end())
        if outer is None:
            continue
        parts, i = [], 0
        while i < len(outer) and len(parts) < 3:
            if outer[i] == "{":
                v, i = brace_arg(outer, i)
                parts.append(v or "")
            else:
                i += 1
        if len(parts) >= 2:
            out[m.group(1)] = (parts[0], parts[1], parts[2] if len(parts) > 2 else "")
    return out


def other_job(side: str, phone: bool):
    base = "archive" if side == "main" else "guide"
    return f"{base}_phone" if phone else base


def xref_table(work: Path, side: str, phone=False):
    """The other document's labels for a `side` ("main" | "archive") build, or None without an archive."""
    main, arch = edition_chapters(work)
    if not arch:
        return None
    this, other = (main, arch) if side == "main" else (arch, main)
    mine, _ = source_labels(this, work)
    theirs, titles = source_labels(other, work)
    oj = other_job(side, phone)
    aux = aux_labels(work / "build" / oj / f"{oj}.aux")
    oside = "archive" if side == "main" else "main"
    key, name = DOCS[oside]
    suffix = {"main": "_Guide", "archive": "_PYQ_Archive"}[oside] + ("_Phone" if phone else "") + ".pdf"
    q = {x["id"]: x for x in load_json(work / "pyq_bank.json").get("questions", [])}
    entries = []
    for lab in sorted(theirs - mine):
        n, p, t = aux.get(lab, ("", "", ""))
        entries.append((lab, n, p, t or titles.get(lab, "")))
    return {"key": key, "name": name, "file": deliverable(SUBJ_DIR or work.parents[1], work, suffix).name,
            "entries": entries, "labels": theirs, "built": bool(aux), "aux_job": oj, "side": side,
            "q": {lab[2:]: q[lab[2:]] for lab, *_ in entries if lab.startswith("q:") and lab[2:] in q} if side == "main" else {}}


def xref_sig(table, used=None):
    """Fingerprint of the other document's pages for the labels a build actually cited (`used`; all labels
    when None). None without an archive."""
    if not table:
        return None
    import hashlib
    keep = set(used) if used is not None else None
    rows = [(l, p) for l, _n, p, _t in table["entries"] if keep is None or l in keep]
    return hashlib.sha1(json.dumps(rows).encode()).hexdigest()[:16]


def write_xref(work: Path, job: str, table):
    """work/_xref_<job>.tex for the wrapper (empty file when there is no second document)."""
    esc = lambda s: str(s).replace("\\", "").replace("&", r"\&").replace("%", r"\%").replace("#", r"\#").replace("_", r"\_")
    lines = ["% generated by build.py: labels of the other document (Guide <-> PYQ archive)"]
    if table:
        lines.append(rf"\sgxdoc{{{table['key']}}}{{{table['name']}}}{{{table['file']}}}")
        for lab, n, p, t in table["entries"]:
            lines.append(rf"\sgxlabel{{{table['key']}}}{{{lab}}}{{{n}}}{{{p if p.isdigit() else ''}}}{{{t}}}")
        for qid, qq in table["q"].items():
            lines.append(rf"\sgxq{{{qid}}}{{{esc(qq.get('paper', ''))}}}{{{esc(qq.get('qno', ''))}}}")
    f = work / f"_xref_{job}.tex"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f.name


def xref_report(work: Path, log: Path, table, undefined, paths=()):
    """(errors, warnings, summary) for cross-document references of one build. \\seesolved / \\pyqsolved
    report themselves (SG-XREF typeouts); raw \\ref/\\pageref/\\nameref to external labels come from `paths`."""
    errs, warns = [], []
    text = log.read_text("latin-1", errors="replace") if log.exists() else ""
    found = re.findall(r"SG-XREF:(\w+):(\S+?):(resolved|pending)", text)
    if table:
        pages = {l: p for l, _n, p, _t in table["entries"]}
        body = "\n".join(expand_inputs(p, work) for p in paths)
        for lab in set(re.findall(r"\\(?:page|name|auto)?ref\*?\{([^}]+)\}", body)):
            if lab in pages:
                found.append((table["key"], lab, "resolved" if pages[lab].isdigit() else "pending"))
    resolved = sorted({l for _, l, s in found if s == "resolved"})
    pending = sorted({l for _, l, s in found if s == "pending"} - set(resolved))
    missing = sorted({l for _, l, _ in found if table and l not in table["labels"]})
    for l in missing:
        errs.append(f"CROSS-DOC target {l} is not defined in the {table['name']}")
    if pending and table:
        warns.append(f"{len(pending)} cross-document refs have no page yet: build the {table['name']} "
                     f"({'--archive' if table['side'] == 'main' else 'guide'}{' --phone' if 'phone' in table['aux_job'] else ''}) "
                     f"and rebuild this one")
    cross_missing = sorted(set(missing) | {l for l in undefined if is_cross_target(work, l, table)})
    return errs, warns, {"resolved": len(resolved), "pending": len(pending), "unresolved": cross_missing,
                         "used": sorted(set(resolved) | set(pending))}


def is_cross_target(work: Path, label: str, table):
    """Would this label have to come from the other document? (archive builds: anything not local;
    main builds: q: labels of archived papers)."""
    if not table:
        return False
    if table["side"] == "archive":
        return True
    kind, _, key = label.partition(":")
    if kind != "q":
        return False
    qp = {x["id"]: x.get("paper") for x in load_json(work / "pyq_bank.json").get("questions", [])}
    return (qp.get(key) or key.split("-")[0]) in archived_papers(work)


def expected_chapters(work: Path):
    """[(what, satisfied?)] — every chapter the scope needs.
    assignments.json (orchestrator) -> chapters[].stem when it exists (lead decision R3); otherwise the auto
    chapters, one per in-scope blueprint unit, important questions / mock / cheatsheet, and one PYQ chapter
    7NN_pyq_<paperid> per relevant paper in the bank (endsem: endsem papers + the 3 latest midsems)."""
    chdir = work / "chapters"
    stems = sorted(p.stem for p in chdir.glob("*.tex")) if chdir.exists() else []
    asg = load_json(work / "assignments.json")
    if asg.get("chapters"):
        return [(f"{c['stem']} ({c.get('kind', '?')}{', paper ' + c['paper'] if c.get('paper') else ''})",
                 c["stem"] in stems) for c in asg["chapters"] if c.get("stem")]
    has = lambda pred: any(pred(s) for s in stems)
    out = []
    for pre, what in (("05_", "05_how_to_use"), ("20_", "20_exam_radar"), ("60_", "60_important_questions"),
                      ("80_", "80_mock_paper")):
        out.append((what, has(lambda s, p=pre: s.startswith(p))))
    out.append(("cheatsheet", "cheatsheet" in stems))
    for u in load_json(work / "blueprint.json").get("units", []):
        if u.get("in_scope", True) and u.get("chapter"):
            out.append((f"{u['chapter']} (unit {u.get('id')})", u["chapter"] in stems))
    papers = bank_papers(work)
    qs = load_json(work / "pyq_bank.json").get("questions", [])
    in_scope_papers = {q.get("paper") for q in qs if q.get("in_scope", True)}
    # PYQ stems are 7NN_pyq_<paperid> (any number of digits; never assume one-digit 7N_)
    pyq = lambda pid: has(lambda s: re.fullmatch(rf"7\d*_pyq_{re.escape(pid.lower())}", s.lower()) is not None)
    rec = lambda p: (p.get("year", 0), 1 if p.get("session") == "autumn" else 0)
    if work.name == "endsem":
        rel = [p for p in papers if p.get("exam") == "endsem"]
        rel += sorted((p for p in papers if p.get("exam") == "midsem"), key=rec)[-3:]
    else:
        rel = [p for p in papers if p.get("exam", "midsem") == "midsem" or p["id"] in in_scope_papers]
    for p in rel:
        out.append((f"7NN_pyq_{p['id'].lower()} (paper {p['id']})", pyq(p["id"])))
    return out


# ------------------------------------------------------------------ TeX
_MIKTEX = None


def is_miktex():
    global _MIKTEX
    if _MIKTEX is None:
        try:
            _MIKTEX = "MiKTeX" in subprocess.run(["pdflatex", "--version"], capture_output=True, text=True, timeout=60).stdout
        except Exception:
            _MIKTEX = False
    return _MIKTEX


def tex_env(work: Path):
    env = dict(os.environ)
    env["TEXINPUTS"] = os.pathsep.join([str(LATEX), str(work), ""])   # trailing separator = + system paths
    env["max_print_line"] = "10000"      # TeX Live: no wrapped log lines
    return env


def drop_stale_sty(work: Path):
    """Older builds copied studyguide.sty into the work folder; that copy would shadow TEXINPUTS."""
    old = work / "studyguide.sty"
    if work.resolve() != LATEX.resolve() and old.exists():
        old.unlink()
        print(f"NOTE    removed the stale copy {old} (the style now comes from {LATEX} via TEXINPUTS)")


def wrapper(work: Path, job: str, inputs, title_page: bool, opts: str, cheat=False, phone=False,
            archive=False, xref=None):
    """Write work/_<job>.tex. `inputs`: relative .tex paths, or "CHEATPDF" to append the built cheatsheet.
    archive=True: the PYQ-archive title page; xref: the _xref_<job>.tex table of the other document."""
    subject, code, scope = meta(work)
    esc = lambda s: str(s).replace("&", r"\&").replace("_", r"\_").replace("%", r"\%").replace("#", r"\#")
    size = "10pt" if (cheat or phone) else "11pt"
    md = pdf_meta(work, archive)
    lines = [rf"\documentclass[{size},a4paper]{{report}}",
             rf"\usepackage[{opts}]{{studyguide}}"]
    if xref:
        lines.append(rf"\makeatletter\input{{{xref}}}\makeatother")
    if "CHEATPDF" in inputs:
        # pdfpages >= 0.6 passes the tagging key `artifact` to \includegraphics; older graphicx lacks it
        lines += [r"\usepackage{pdfpages}",
                  r"\makeatletter\@ifundefined{KV@Gin@artifact}{\define@key{Gin}{artifact}[true]{}}{}\makeatother"]
    lines += [r"\graphicspath{{./}{../}}",  # figures/ may live in the shared work dir
              r"\hypersetup{" + ",".join(f"{k}={{{v}}}" for k, v in md.items()) + "}",
              rf"\setsubject{{{esc(subject)}}}{{{esc(code)}}}{{{esc(scope)} {'PYQ archive' if archive else 'guide'}}}",
              r"\begin{document}"]
    if title_page and archive:
        guide = deliverable(SUBJ_DIR or work.parents[1], work, "_Guide_Phone.pdf" if phone else "_Guide.pdf").name
        lines += [r"\begin{titlepage}\centering\vspace*{%s}" % ("12mm" if phone else "40mm"),
                  rf"{{\sffamily\Huge\bfseries\color{{sgnavy}} {esc(subject)}\par}}\vspace{{6mm}}",
                  rf"{{\sffamily\Large\color{{sgteal}} {esc(scope)} PYQ archive\par}}\vspace{{4mm}}",
                  rf"{{\sffamily {esc(code)}\par}}\vspace{{12mm}}",
                  r"{\large Older papers, verbatim, with links to the full solutions in the Guide\par}\vfill",
                  r"{\small\raggedright Each question is printed as it appeared on the paper, with a crop of the original, "
                  r"a short answer, and a pointer to its full model solution in the " + esc(subject) + " " + esc(scope)
                  + r" Guide (\texttt{" + esc(guide) + r"}). Keep both PDFs in the same folder so the links open.\par}",
                  r"\vspace{4mm}{\scriptsize\color{muted} Unofficial student study guide; not issued by the university.\par}",
                  r"\end{titlepage}",
                  r"\tableofcontents", r"\sgmarkchapterend{frontmatter}"]
    elif title_page:
        if (work / "chapters" / "00_cover.tex").exists():
            lines.append(r"\input{chapters/00_cover.tex}")
        else:
            lines += [r"\begin{titlepage}\centering\vspace*{%s}" % ("12mm" if phone else "40mm"),
                      rf"{{\sffamily\Huge\bfseries\color{{sgnavy}} {esc(subject)}\par}}\vspace{{6mm}}",
                      rf"{{\sffamily\Large\color{{sgteal}} {esc(scope)} Examination Guide\par}}\vspace{{4mm}}",
                      rf"{{\sffamily {esc(code)}\par}}\vfill",
                      r"{\small Exam radar $\cdot$ unit notes $\cdot$ ranked important questions $\cdot$ verbatim PYQ solutions $\cdot$ mock paper $\cdot$ cheatsheet\par}"]
            url = updates_url(work)
            if url:   # SAFE_URL-checked: no TeX specials; \url breaks it at / and - on the narrow phone page
                lines.append(r"\vspace{4mm}{\small Latest version and corrections:\\ \url{" + url + r"}\par}")
            lines += [r"\vspace{4mm}{\scriptsize\color{muted} Unofficial student study guide; not issued by the university.\par}",
                      r"\end{titlepage}"]
        lines += [r"\tableofcontents", r"\sgmarkchapterend{frontmatter}"]
    for i in inputs:
        if i == "CHEATPDF":
            # the landscape cheatsheet is compiled on its own and its pages are included as-is (fitpaper keeps
            # their size); the TOC line and bookmark point at its real first page in every edition
            # unnumbered TOC line + bookmark anchored on the first cheatsheet page (addtotoc would number it)
            first = (r"\includepdf[pages=1,fitpaper,pagecommand={\thispagestyle{empty}\phantomsection"
                     r"\addcontentsline{toc}{chapter}{Cheatsheet (landscape pages)}}]{build/cheatsheet/cheatsheet.pdf}")
            lines.append(first)
            if pdf_pages(work / "build" / "cheatsheet" / "cheatsheet.pdf") > 1:
                lines.append(r"\includepdf[pages=2-,fitpaper]{build/cheatsheet/cheatsheet.pdf}")
        elif i == "OLDERPART":
            # one_pdf: divider page in front of the older in-window papers
            lines += [r"\clearpage\thispagestyle{empty}\phantomsection"
                      r"\addcontentsline{toc}{chapter}{Older papers (in window)}",
                      r"\vspace*{%s}\begin{center}" % ("20mm" if phone else "50mm"),
                      r"{\sffamily\Huge\bfseries\color{sgnavy} Older papers\par}\vspace{5mm}",
                      r"{\small Older in-window papers, verbatim, each with its answer or a pointer to the full "
                      r"solution earlier in this guide.\par}",
                      r"\end{center}\clearpage"]
        else:
            lines.append(rf"\input{{{i}}}\sgmarkchapterend{{{Path(i).stem}}}")
    lines.append(r"\end{document}")
    f = work / f"_{job}.tex"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


def pdf_pages(pdf: Path) -> int:
    try:
        import pymupdf as fitz
        with fitz.open(pdf) as d:
            return len(d)
    except Exception:
        return 1


def compile_tex(work: Path, texfile, job: str, passes: int, timeout=TIMEOUT_FULL, tex_arg=None):
    """Run pdflatex `passes` times. Returns (pdf or None, errors, warns); details in build/<job>/result.json."""
    out = work / "build" / job
    out.mkdir(parents=True, exist_ok=True)
    drop_stale_sty(work)
    pdf = out / f"{job}.pdf"
    log = out / f"{job}.log"
    for stale in (pdf, log):
        if stale.exists():
            stale.unlink()   # a fatal error must never leave the previous PDF looking fresh
    cmd = ["pdflatex", "-interaction=nonstopmode", "-file-line-error"]
    if is_miktex():
        cmd.append("-max-print-line=10000")
    cmd += [f"-output-directory=build/{job}", f"-jobname={job}", tex_arg or Path(texfile).name]
    rc, t0, extra = None, time.time(), []
    for k in range(passes):
        try:
            r = subprocess.run(cmd, cwd=work, capture_output=True, timeout=timeout, env=tex_env(work))
            rc = r.returncode
        except subprocess.TimeoutExpired:
            extra.append(f"TIMEOUT: pdflatex pass {k + 1} ran > {timeout} s (infinite loop in a tikz/foreach, or a fragile command in a heading?)")
            rc = -1
            break
        t = log.read_text("latin-1", errors="replace") if log.exists() else ""
        if not pdf.exists() or "Emergency stop" in t or "Fatal error occurred" in t:
            break   # later passes cannot fix a fatal error
    info = analyze_log(log)
    if rc not in (0, None, -1):   # nonzero exit = TeX saw an error, even one the log regexes missed
        info["errors"].append(f"pdflatex exited with code {rc} (see {log})")
        info["tex_errors"] = max(info["tex_errors"], 1)
    if extra:
        info["errors"] = extra + info["errors"]
        info["tex_errors"] += len(extra)
    errors = info["errors"]
    info.update(rc=rc, seconds=round(time.time() - t0, 1), passes=passes, job=job)
    (out / "result.json").write_text(json.dumps({k: (sorted(v) if isinstance(v, set) else v) for k, v in info.items()},
                                                indent=1), "utf-8")
    return (pdf if pdf.exists() else None), errors, info["warns"]


# ------------------------------------------------------------------ log analysis
ERR_RE = re.compile(r"^(.+?\.\w+):(\d+): (.*)$", re.M)
UNDEF_RE = re.compile(r"LaTeX Warning: (Hyper reference|Reference) `([^']+)' on page \S+ undefined")
DEST_RE = re.compile(r"pdfTeX warning \(dest\): name\{([^}]+)\} has been referenced but does not exist")
FLOAT_RE = re.compile(r"LaTeX Warning: Float too large for page by ([\d.]+)pt on input line (\d+)")
# file opens look like "(./chapters/x.tex" or, via TEXINPUTS, "(C:\Users\..\Study Prep\..\chapters/x.tex"
OVERFULL_RE = re.compile(r"\(((?:[A-Za-z]:)?[^()\n]*?\.tex)(?=[\s)]|$)|Overfull \\([hv])box \((\d+\.?\d*)pt too (?:wide|high)\)([^\n]*)", re.M)


def analyze_log(log: Path):
    """Structured view of a pdflatex log (shared by build.py and metrics.py)."""
    info = {"errors": [], "warns": [], "layout": [], "undefined": {}, "undefined_text": 0, "sg_refs": set(),
            "float_too_large": 0, "overfull": 0, "badges_missing": set(), "receipts_missing": set(),
            "multiply_defined": set(), "tex_errors": 0, "rerun": False}
    if not log.exists():
        info["errors"].append("no log produced")
        info["tex_errors"] = 1
        return info
    t = log.read_text(encoding="latin-1", errors="replace")
    seen = set()
    for m in ERR_RE.finditer(t):
        f, msg = m.group(1).strip().lstrip("("), m.group(3).strip()
        if "Warning" in f:
            continue
        ctx = t[m.end():m.end() + 400].split("\n")
        hint = next((c.strip() for c in ctx if c.startswith("l.")), "")
        key = (f, m.group(2), msg)
        if key not in seen:
            seen.add(key)
            info["errors"].append(f"{f}:{m.group(2)}: {msg}  {hint}".rstrip())
    for m in re.finditer(r"^! (.+)$", t, re.M):
        if not any(m.group(1) in e for e in info["errors"]):
            info["errors"].append("! " + m.group(1))
    info["tex_errors"] = len(info["errors"])
    stack = []
    for m in OVERFULL_RE.finditer(t):
        if m.group(1):
            stack.append(m.group(1)); continue
        src = next((s for s in reversed(stack) if re.search(r"[\\/](chapters|atoms)[\\/]", s)), stack[-1] if stack else "?")
        src = re.sub(r"^.*?[\\/](?=(chapters|atoms)[\\/])", "", src)
        amount, where = float(m.group(3)), m.group(4).strip()
        if m.group(2) == "v" and amount > 2:
            info["layout"].append(f"LAYOUT Overfull \\vbox {amount:g}pt (content cut off the page)  {src}  {where}")
        elif m.group(2) == "h" and amount > OVERFULL_PT:
            info["layout"].append(f"LAYOUT Overfull \\hbox {amount:g}pt (runs into the margin)  {src}  {where}")
    info["overfull"] = len(info["layout"])
    for m in FLOAT_RE.finditer(t):
        info["float_too_large"] += 1
        info["layout"].append(f"LAYOUT Float too large for page by {m.group(1)}pt (input line {m.group(2)}): a storyboard/figure "
                              f"is cut off - fewer frames per figure, smaller frames, or split it")
    for m in UNDEF_RE.finditer(t):
        info["undefined"][m.group(2)] = info["undefined"].get(m.group(2), 0) + 1
        if m.group(1) == "Reference":
            info["undefined_text"] += 1   # each prints "??" in the PDF
    for m in DEST_RE.finditer(t):
        info["undefined"].setdefault(m.group(1), 0)
    info["sg_refs"] = set(re.findall(r"SG-REF:(\S+)", t))
    info["badges_missing"] = set(re.findall(r"SG-BADGE-MISSING:(\S+)", t))
    info["receipts_missing"] = set(re.findall(r"SG-RECEIPT-MISSING:(\S+)", t))
    info["multiply_defined"] = set(re.findall(r"Label `([^']+)' multiply defined", t))
    info["rerun"] = bool(re.search(r"Rerun to get cross-references right|Label\(s\) may have changed", t))
    for m in re.finditer(r"File `([^']+)' not found", t):
        if not any(m.group(1) in e for e in info["errors"]):
            info["errors"].append(f"missing file: {m.group(1)}")
    info["errors"] += info["layout"]
    if info["badges_missing"]:
        info["warns"].append(f"badges missing from badges.tex (red ?Cxx pills): {', '.join(sorted(info['badges_missing']))}")
    if info["receipts_missing"]:
        info["warns"].append(f"receipts missing (red boxes): {', '.join(sorted(info['receipts_missing']))}")
    if info["multiply_defined"]:
        info["warns"].append(f"labels defined more than once: {', '.join(sorted(info['multiply_defined']))}")
    if info["rerun"]:
        info["warns"].append("LaTeX still asks for a rerun (cross-references may be stale)")
    return info


def parse_log(log: Path):
    """Back-compatible: (errors, warnings) with undefined references listed as warnings."""
    info = analyze_log(log)
    warns = info["warns"] + [f"undefined reference: {k}" for k in sorted(info["undefined"])]
    return info["errors"], warns


def classify_undefined(work: Path, labels, sg_refs, table=None):
    """Human-readable reason for each undefined label (dangling vs target chapter missing vs cross-document)."""
    papers = {p["id"] for p in bank_papers(work)}
    qpaper = {q["id"]: q.get("paper") for q in load_json(work / "pyq_bank.json").get("questions", [])}
    stems = {p.stem.lower() for p in (work / "chapters").glob("*.tex")}
    out = []
    for lab in sorted(labels):
        kind, _, key = lab.partition(":")
        why = "dangling: no \\label{%s} anywhere" % lab
        if is_cross_target(work, lab, table):
            why = (f"CROSS-DOC target missing: not defined in this document nor in the {table['name']}"
                   if table["side"] == "archive" else
                   f"CROSS-DOC target missing: paper {qpaper.get(key) or key.split('-')[0]} is in the PYQ archive, "
                   f"but the archive never sets \\label{{{lab}}}")
        elif kind == "q":
            pid = qpaper.get(key) or key.split("-")[0]
            if pid in papers and not any(pid.lower() in s for s in stems):
                why = f"the PYQ chapter for paper {pid} is missing"
            elif key not in qpaper:
                why = f"no question {key} in pyq_bank.json"
        elif kind == "solve" and not (work / "atoms" / "solve" / f"{key}.tex").exists():
            why = f"atoms/solve/{key}.tex is missing (or not \\input anywhere)"
        elif kind == "sec" and not (work / "atoms" / "notes" / f"{key}.tex").exists():
            why = f"no section labelled sec:{key} (its unit chapter or atom is missing?)"
        via = "; linked by \\pyqsolved/\\seesolved" if lab in sg_refs else ""
        out.append(f"{lab}  ({why}{via})")
    return out


def own_ref_errors(work: Path, stem: str, labels, sg_refs):
    """On a chapter/atom build: undefined SG-REF targets that this chapter itself should define."""
    qpaper = {q["id"]: q.get("paper") for q in load_json(work / "pyq_bank.json").get("questions", [])}
    bad = []
    for lab in labels:
        if lab not in sg_refs:
            continue
        kind, _, key = lab.partition(":")
        pid = qpaper.get(key) or key.split("-")[0]
        if kind == "q" and pid and re.search(rf"_pyq_{re.escape(pid.lower())}$", stem.lower()):
            bad.append(lab)
        elif kind == "solve" and stem.lower() == key.lower():   # --atom solve/<Cid> must define solve:<Cid>
            bad.append(lab)
    return sorted(bad)


# ------------------------------------------------------------------ page fill (TOC based)
def page_fill(pdf: Path, threshold=0.6):
    """Pages whose content stops above `threshold` of the page height although the next page does not start
    a chapter (chapter starts come from the PDF outline, not from page text, which the running header pollutes).
    Usually a big float that jumped to the next page. Returns warning strings."""
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            return []
    out = []
    doc = fitz.open(pdf)
    toc = doc.get_toc(simple=True)
    starts = {p for lvl, _, p in toc if lvl == 1 and p > 0}
    first = min(starts) if starts else 1
    for i in range(max(first - 1, 0), len(doc) - 1):
        nxt = i + 2   # 1-based number of the following page
        if nxt in starts:
            continue
        pg = doc[i]
        H = pg.rect.height
        ys = [b[3] for b in pg.get_text("blocks")]
        ys += [d["rect"].y1 for d in pg.get_drawings()]
        try:
            ys += [pg.get_image_bbox(im).y1 for im in pg.get_images(full=True)]
        except Exception:
            pass
        ys = [y for y in ys if H * 0.08 < y < H * 0.93]   # ignore running header and footer
        if not ys:
            continue
        bottom = max(ys) / H
        if bottom < threshold:
            out.append(f"LAYOUT page {i + 1} is only {bottom:.0%} filled and page {nxt} does not start a chapter "
                       f"(a float jumped: shrink it, use [!htbp], or move it)")
    doc.close()
    return out


# ------------------------------------------------------------------ render
def render(pdf: Path, qa: Path, dpi=60, per_sheet=6):
    """Render pages and tile them into contact sheets (2x3) so an agent can eyeball layout cheaply."""
    if qa.exists():
        shutil.rmtree(qa)
    qa.mkdir(parents=True)
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(qa / "p")], capture_output=True)
    pages = sorted(qa.glob("p-*.png"))
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return pages
    sheets = []
    for s in range(0, len(pages), per_sheet):
        ims = [Image.open(p) for p in pages[s:s + per_sheet]]
        w, h = ims[0].size
        sheet = Image.new("RGB", (w * 3 + 20, h * 2 + 10), "white")
        for k, im in enumerate(ims):
            x, y = (k % 3) * (w + 10), (k // 3) * (h + 10)
            if im.size != (w, h):  # landscape cheatsheet pages: shrink to fit, don't crop
                im = im.copy(); im.thumbnail((w, h))
            sheet.paste(im, (x, y))
            ImageDraw.Draw(sheet).text((x + 4, y + 2), f"p{s + k + 1}", fill=(200, 0, 0))
        out = qa / f"sheet-{s // per_sheet + 1:02d}.png"
        sheet.save(out)
        sheets.append(out)
    return sheets


def render_flagged(pdf: Path, qa: Path, dpi=60, per_sheet=6, max_lines=25):
    """layout_check.py on the PDF; contact sheets only for the pages it flags (the only pages worth an image read).
    Prints the LAYOUT lines and the FLAGGED summary; returns the sheet paths."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import layout_check
    found = layout_check.check(pdf)
    for f in found[:max_lines]:
        print(f"LAYOUT p{f['page']} {f['kind']}: {f['msg']}")
    if len(found) > max_lines:
        print(f"LAYOUT ... {len(found) - max_lines} more (py _pipeline/tools/layout_check.py {pdf})")
    pages = sorted({f["page"] for f in found})
    print(f"FLAGGED {len(pages)} page(s)" + (": " + ",".join(map(str, pages)) if pages else ""))
    if qa.exists():
        shutil.rmtree(qa)
    if not pages:
        return []
    qa.mkdir(parents=True)
    for p in pages:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(p), "-l", str(p), str(pdf), str(qa / f"f{p:04d}")],
                       capture_output=True)
    ims = sorted(qa.glob("f*.png"))
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ims
    sheets = []
    for s in range(0, len(ims), per_sheet):
        group = [Image.open(p) for p in ims[s:s + per_sheet]]
        w, h = group[0].size
        sheet = Image.new("RGB", (w * 3 + 20, h * ((len(group) + 2) // 3) + 10), "white")
        for k, im in enumerate(group):
            x, y = (k % 3) * (w + 10), (k // 3) * (h + 10)
            if im.size != (w, h):
                im = im.copy(); im.thumbnail((w, h))
            sheet.paste(im, (x, y))
            ImageDraw.Draw(sheet).text((x + 4, y + 2), f"p{pages[s + k]}", fill=(200, 0, 0))
        out = qa / f"sheet-{s // per_sheet + 1:02d}.png"
        sheet.save(out)
        sheets.append(out)
    return sheets


def sheets_for(a, pdf: Path, qa: Path, dpi=60, per_sheet=6):
    """--render: flagged pages only (default), or every page with --sheets all (reviewers' sample)."""
    if getattr(a, "sheets", "flagged") == "all":
        return render(pdf, qa, dpi=dpi, per_sheet=per_sheet)
    return render_flagged(pdf, qa, dpi=dpi, per_sheet=per_sheet)


def batch_atoms(a, work: Path, atoms):
    """--atom a,b,c [--both]: build every atom (print, and phone with --both / phone only with --phone) in one call.
    Terse: per atom and edition one OK/FAIL line; LINT/ERROR lines only for failures; one STATUS and RESULT."""
    import argparse as _ap
    import contextlib
    import io
    editions = ["print", "phone"] if a.both else (["phone"] if a.phone else ["print"])
    results = []
    for atom in atoms:
        src = work / "atoms" / (atom if atom.endswith(".tex") else atom + ".tex")
        rel = src.relative_to(work).as_posix()
        for ed in editions:
            job = "atom_" + re.sub(r"[^A-Za-z0-9]+", "_", atom.removesuffix(".tex")) + ("_phone" if ed == "phone" and a.both else "")
            sub = _ap.Namespace(**dict(vars(a), phone=(ed == "phone"), render=False))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = small_build(sub, work, src, job, rel)
            lines = buf.getvalue().splitlines()
            m = next((re.search(r"\((\d+) pages\)", l) for l in lines if l.startswith("PDF ")), None)
            npg = f"{m.group(1)}pp" if m else "no PDF"
            if rc == 0:
                print(f"OK   {atom} [{ed}] {npg}")
            else:
                bad = [l for l in lines if l.startswith(("LINT", "ERROR"))]
                for l in bad[:15]:
                    print(l)
                if len(bad) > 15:
                    print(f"ERROR   ... {len(bad) - 15} more")
                print(f"FAIL {atom} [{ed}] {len([l for l in bad if l.startswith('ERROR')])} error(s), "
                      f"{len([l for l in bad if l.startswith('LINT')])} lint")
            if a.render and rc == 0:
                pdf = work / "build" / job / f"{job}.pdf"
                if pdf.exists():
                    sh = sheets_for(a, pdf, work / "qa" / job, dpi=110 if ed == "phone" else 60)
                    if sh:
                        print("SHEETS ", *sh, sep="\n  ")
            results.append(rc)
    nbad = sum(1 for r in results if r)
    print("STATUS ", "OK" if not nbad else "FAILED")
    print("RESULT PASS" if not nbad else f"RESULT BLOCKED: {nbad} of {len(results)} atom build(s) failed")
    return 1 if nbad else 0


def report(pdf, errors, warns, issues, extra_reasons=()):
    if pdf:
        warns = warns + page_fill(pdf)
    for i in issues:
        print("LINT   ", i)
    for e in errors:
        print("ERROR  ", e)
    for w in warns:
        print("WARN   ", w)
    if pdf:
        try:
            import pypdf
            n = len(pypdf.PdfReader(str(pdf)).pages)
        except Exception:
            n = "?"
        print(f"PDF    {pdf}  ({n} pages)")
    ok = bool(pdf) and not errors
    print("STATUS ", "OK" if ok else "FAILED")
    reasons = list(extra_reasons) or ([] if ok else ["no PDF" if not pdf else f"{len(errors)} error(s)"])
    print("RESULT PASS" if ok else "RESULT BLOCKED: " + "; ".join(reasons))
    return 0 if ok else 1


def copy_out(ok: bool, pdf, dst: Path):
    if ok and pdf:
        shutil.copy2(pdf, dst)
        print("COPIED ", dst)
    else:
        print(f"NOT COPIED (build failed): {dst} {'left as it was' if dst.exists() else 'not created'}")


# ------------------------------------------------------------------ main
def build_cookbook(a):
    work = LATEX
    opt = "interactive" if a.interactive else "phone" if a.phone else ""
    job = "visual_cookbook" + (f"_{opt}" if opt else "")
    arg = (rf"\PassOptionsToPackage{{{opt}}}{{studyguide}}\input{{visual_cookbook.tex}}" if opt else "visual_cookbook.tex")
    pdf, errors, warns = compile_tex(work, work / "visual_cookbook.tex", job, 2, TIMEOUT_FULL, tex_arg=arg)
    info = json.loads((work / "build" / job / "result.json").read_text("utf-8"))
    if info["undefined"]:
        errors = errors + [f"UNDEFINED reference {k}" for k in sorted(info["undefined"])]
    rc = report(pdf, errors, warns, lint_cookbook(work / "visual_cookbook.tex"))
    if a.render and pdf:
        print("SHEETS ", *render(pdf, work / "qa" / job, dpi=110 if a.phone else 60), sep="\n  ")
    return rc


def small_build(a, work, src: Path, job: str, label: str):
    """--chapter / --atom: compile one body standalone; undefined refs are warnings except own SG-REF targets."""
    issues = lint(src)
    if a.lint_only:
        for i in issues:
            print("LINT   ", i)
        print("RESULT PASS" if not issues else f"RESULT BLOCKED: {len(issues)} lint issue(s)")
        return 1 if issues else 0
    cheat = src.stem == "cheatsheet"
    opts = ",".join(x for x in ("interactive" if a.interactive else "", "phone" if a.phone else "",
                                "cheatsheet" if cheat else "") if x)
    side = "archive" if chapter_kinds(work).get(src.stem) == ARCHIVE_KIND else "main"
    table = xref_table(work, side, a.phone) if not cheat else None
    tex = wrapper(work, job, [label], False, opts, cheat, a.phone, xref=write_xref(work, job, table))
    pdf, errors, warns = compile_tex(work, tex, job, 2, TIMEOUT_SMALL)
    info = json.loads((work / "build" / job / "result.json").read_text("utf-8"))
    und = set(info["undefined"])
    xerr, xwarn, _x = xref_report(work, work / "build" / job / f"{job}.log", table, set(), [src])
    errors, warns = errors + xerr, warns + xwarn
    own = own_ref_errors(work, src.stem, und, set(info["sg_refs"]))
    errors = errors + [f"UNDEFINED {lab}: this chapter links to its own question but never labels it (\\label{{{lab}}})" for lab in own]
    warns = warns + [f"undefined reference (fine in a chapter build if another chapter defines it): {l}"
                     for l in sorted(und - set(own))]
    rc = report(pdf, errors, warns, issues)
    if a.render and pdf:
        sh = sheets_for(a, pdf, work / "qa" / job, dpi=110 if a.phone else 60)
        if sh:
            print("SHEETS ", *sh, sep="\n  ")
    return rc


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("subject", nargs="?")
    ap.add_argument("--scope", help="midsem | endsem (required)")
    ap.add_argument("--chapter")
    ap.add_argument("--atom", help="e.g. notes/T07 or solve/C05 (atoms/<x>.tex); several: notes/T07,notes/T08,solve/C05 "
                                   "(one call, terse OK/FAIL lines)")
    ap.add_argument("--both", action="store_true", help="with --atom: build each atom in print AND phone")
    ap.add_argument("--sheets", choices=["flagged", "all"], default="flagged",
                    help="with --render: contact sheets for the pages layout_check flags (default) or for every page")
    ap.add_argument("--cheatsheet", action="store_true")
    ap.add_argument("--cookbook", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--noanim", action="store_true", help="(default; kept for compatibility)")
    ap.add_argument("--interactive", action="store_true",
                    help="animations + storyboards -> *_Guide_Interactive.pdf")
    ap.add_argument("--phone", action="store_true", help="105 x 187 mm single-column edition -> *_Guide_Phone.pdf")
    ap.add_argument("--archive", action="store_true",
                    help="the PYQ archive (assignments.json kind pyq_older) -> *_PYQ_Archive.pdf (with --phone: _Phone)")
    ap.add_argument("--lint-only", action="store_true")
    a = ap.parse_args()
    if a.interactive and a.phone:
        ap.error("--interactive and --phone are separate editions")
    if a.archive and (a.interactive or a.chapter or a.atom or a.cheatsheet or a.cookbook):
        ap.error("--archive builds the whole archive (print, or --phone)")

    if a.cookbook:
        sys.exit(build_cookbook(a))
    if not a.subject:
        ap.error("subject required")
    global SUBJ_DIR
    SUBJ_DIR, _shared, work = resolve(a.subject, a.scope)
    chdir = work / "chapters"

    if a.atom:
        atoms = [x.strip() for x in a.atom.split(",") if x.strip()]
        for x in atoms:
            if not re.fullmatch(r"(notes|solve)/[A-Za-z0-9_\-]+(\.tex)?", x):
                print("--atom takes notes/<Tid> or solve/<Cid> (atoms/recall/* compile through --cheatsheet)", file=sys.stderr)
                sys.exit(2)
            if not (work / "atoms" / (x if x.endswith(".tex") else x + ".tex")).exists():
                print(f"atom {x} not found", file=sys.stderr); sys.exit(2)
        if len(atoms) > 1 or a.both:
            if a.interactive or a.lint_only:
                ap.error("batched --atom builds take --phone / --both / --render only")
            sys.exit(batch_atoms(a, work, atoms))
        src = work / "atoms" / (a.atom if a.atom.endswith(".tex") else a.atom + ".tex")
        if not src.exists():
            print(f"atom {a.atom} not found: {src}", file=sys.stderr); sys.exit(2)
        rel = src.relative_to(work).as_posix()
        job = "atom_" + re.sub(r"[^A-Za-z0-9]+", "_", a.atom.removesuffix(".tex"))
        sys.exit(small_build(a, work, src, job, rel))

    if a.chapter:
        cand = sorted(p for p in chdir.glob("*.tex") if p.stem == a.chapter) or \
               sorted(p for p in chdir.glob("*.tex") if p.stem.startswith(a.chapter))
        if not cand:
            print(f"chapter {a.chapter} not found in {chdir}", file=sys.stderr); sys.exit(2)
        ch = cand[0]
        sys.exit(small_build(a, work, ch, f"chk_{ch.stem}", f"chapters/{ch.name}"))

    if a.cheatsheet:
        ch = chdir / "cheatsheet.tex"
        if not ch.exists():
            print(f"no {ch}", file=sys.stderr); sys.exit(1)
        tex = wrapper(work, "cheatsheet", ["chapters/cheatsheet.tex"], False, "cheatsheet", True)
        pdf, errors, warns = compile_tex(work, tex, "cheatsheet", 2, TIMEOUT_SMALL)
        rc = report(pdf, errors, warns, lint(ch))
        if one_pdf(work):
            print("ONE-PDF  the cheatsheet ships inside the guide; no separate _Cheatsheet.pdf")
        else:
            copy_out(rc == 0, pdf, deliverable(SUBJ_DIR, work, "_Cheatsheet.pdf"))
        if a.render and pdf:
            print("SHEETS ", *sheets_for(a, pdf, work / "qa" / "cheatsheet", dpi=80, per_sheet=3), sep="\n  ")
        sys.exit(rc)

    # ---- full builds: guide (print / interactive / phone) or PYQ archive (print / phone)
    main_ch, arch_ch = edition_chapters(work)
    side = "archive" if a.archive else "main"
    chapters = arch_ch if a.archive else main_ch
    info_t = topic_info(work)
    seen = set()
    issues = [i for ch in chapters for i in lint(ch, info_t, seen)]
    inputs = [f"chapters/{c.name}" for c in chapters]
    older = {f"chapters/{c.name}" for c in older_chapters(work)}
    if not a.archive and one_pdf(work) and older:
        k = next(n for n, i in enumerate(inputs) if i in older)
        inputs.insert(k, "OLDERPART")
    errors_pre = []
    try:
        updates_url(work)
    except ValueError as e:
        print("ERROR  ", e)
        print("STATUS  FAILED")
        print("RESULT BLOCKED: " + str(e))
        sys.exit(1)
    if a.archive:
        if not arch_ch:
            errors_pre.append("no PYQ-archive chapters: assignments.json has no chapters of kind pyq_older")
    elif (chdir / "cheatsheet.tex").exists():
        ctex = wrapper(work, "cheatsheet", ["chapters/cheatsheet.tex"], False, "cheatsheet", True)
        cpdf, cerr, _ = compile_tex(work, ctex, "cheatsheet", 2, TIMEOUT_SMALL)
        if cpdf and not cerr:
            inputs.append("CHEATPDF")
        else:
            errors_pre.append("cheatsheet did not build, so the guide would ship without it: " + "; ".join(cerr[:3]))
    else:
        errors_pre.append("chapters/cheatsheet.tex is missing")
    if a.archive and not arch_ch:
        print("ERROR  ", errors_pre[0])
        print("STATUS  FAILED")
        print("RESULT BLOCKED: " + errors_pre[0])
        sys.exit(1)
    edition = "interactive" if a.interactive else "phone" if a.phone else ""
    base = "archive" if a.archive else "guide"
    job = f"{base}_{edition}" if edition else base
    table = xref_table(work, side, a.phone)
    xref = write_xref(work, job, table)
    tex = wrapper(work, job, inputs, True, "phone" if a.phone else edition, phone=a.phone, archive=a.archive, xref=xref)
    pdf, errors, warns = compile_tex(work, tex, job, 3, TIMEOUT_FULL)
    info = json.loads((work / "build" / job / "result.json").read_text("utf-8"))
    reasons = []
    xerr, xwarn, xsum = xref_report(work, work / "build" / job / f"{job}.log", table, set(info["undefined"]), chapters)
    info["xref"] = xsum
    info["xref_sig"] = xref_sig(table, xsum["used"])   # metrics.py: stale when those pages have changed since
    (work / "build" / job / "result.json").write_text(json.dumps(info, indent=1), "utf-8")
    if table:
        print(f"XREF    {table['name']}: {xsum['resolved']} resolved, {xsum['pending']} without a page yet, "
              f"{len(xsum['unresolved'])} unresolved")
    errors, warns = errors + xerr, warns + xwarn
    if xsum["unresolved"]:
        reasons.append(f"{len(xsum['unresolved'])} cross-document target(s) missing")
    if info["undefined"]:
        n, nt = len(info["undefined"]), info["undefined_text"]
        errors = errors + [f"UNDEFINED {x}" for x in classify_undefined(work, info["undefined"], set(info["sg_refs"]), table)]
        errors.append(f"UNDEFINED total: {n} distinct labels, {nt} '??' in the PDF")
        reasons.append(f"{n} undefined references ({nt} '??')")
    errors = errors_pre + errors
    if errors_pre:
        reasons += errors_pre
    if info["float_too_large"]:
        reasons.append(f"{info['float_too_large']} float(s) too large")
    if info["tex_errors"]:
        reasons.append(f"{info['tex_errors']} TeX error(s)")
    if info["overfull"]:
        reasons.append(f"{info['overfull']} overfull box(es)")
    if not pdf:
        reasons.append("no PDF")
    rc = report(pdf, errors, warns, issues, reasons if errors or not pdf else ())
    suffix = ({"phone": "_PYQ_Archive_Phone.pdf"}.get(edition, "_PYQ_Archive.pdf") if a.archive else
              {"interactive": "_Guide_Interactive.pdf", "phone": "_Guide_Phone.pdf"}.get(edition, "_Guide.pdf"))
    copy_out(rc == 0, pdf, deliverable(SUBJ_DIR, work, suffix))
    if a.render and pdf:
        print("SHEETS ", *sheets_for(a, pdf, work / "qa" / job, dpi=110 if a.phone else 60), sep="\n  ")
    sys.exit(rc)


if __name__ == "__main__":
    main()
