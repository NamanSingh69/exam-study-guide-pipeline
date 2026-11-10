"""flashcards.py - collect \\flashcard{front}{back} into an Anki deck and a web self-test page.

  py _pipeline/tools/flashcards.py CN --scope midsem [--out-html DIR]

Sources: <S>/work/<sc>/chapters/*.tex and atoms/**/*.tex (each file read once; \\input is NOT followed,
so an atom included by a chapter is not counted twice). Arguments are parsed with balanced braces, so
fronts and backs may hold nested groups and maths.

Writes
  <S>/work/<sc>/flashcards.csv     Anki import: header lines '#separator:semicolon', '#html:true',
                                   '#columns:Front;Back;Tags', '#tags column:3'; fields are HTML with
                                   KaTeX/MathJax-compatible \\( .. \\) and \\[ .. \\] maths
  <S>/work/<sc>/web/flashcards.html  study-mode page (same assets as tools/web.py)
Tags per card: <SUBJ> <scope> <topic id> (the nearest preceding \\label{sec:Txx}, or the atom's file name).

Exit 0 with 'RESULT PASS (N cards)'; 1 'RESULT BLOCKED: ...' on a malformed \\flashcard; 2 usage.
"""
import argparse, csv, io, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workdir


def _web():
    import web
    return web


def sources(scoped: Path):
    files = sorted((scoped / "chapters").glob("*.tex")) if (scoped / "chapters").is_dir() else []
    if (scoped / "atoms").is_dir():
        files += sorted((scoped / "atoms").rglob("*.tex"))
    return files


def collect(scoped: Path, errors=None):
    """[{front, back, topic, file, line}] in source order. Malformed cards go to `errors`."""
    web = _web()
    cards = []
    cl_topic = {}
    bank = scoped / "pyq_bank.json"
    if bank.exists():
        import json
        try:
            cl_topic = {c["id"]: c.get("topic", "") for c in json.loads(bank.read_text(encoding="utf-8")).get("clusters", [])}
        except (ValueError, KeyError):
            cl_topic = {}
    for f in sources(scoped):
        txt = web.strip_comments(f.read_text(encoding="utf-8", errors="replace"))
        rel = f.relative_to(scoped).as_posix()
        default_topic = f.stem if re.fullmatch(r"T\d+\w*", f.stem) else cl_topic.get(f.stem, "")
        secs = [(m.start(), m.group(1)) for m in re.finditer(r"\\label\{sec:([^}]*)\}", txt)]
        for m in re.finditer(r"\\flashcard\b", txt):
            line = txt.count("\n", 0, m.start()) + 1
            try:
                j = web.skip_ws(txt, m.end())
                front, j = web.read_group(txt, j)
                j = web.skip_ws(txt, j)
                back, j = web.read_group(txt, j)
            except web.Unsupported as e:
                if errors is not None:
                    errors.append(f"{rel}:{line}: malformed \\flashcard ({e})")
                continue
            if not front.strip() or not back.strip():
                if errors is not None:
                    errors.append(f"{rel}:{line}: empty front or back")
                continue
            topic = default_topic
            for pos, tid in secs:
                if pos < m.start():
                    topic = tid
            cards.append({"front": front.strip(), "back": back.strip(), "topic": topic, "file": rel, "line": line})
    return cards


def to_anki_html(site, tex):
    """HTML for Anki: inline formatting kept, maths as \\( .. \\) (Anki renders it with MathJax)."""
    web = _web()
    page = web.Page("flashcards.html", "flash", "")
    cv = web.Conv(site, page, math="anki", allow_fallback=False)
    try:
        h = cv.inline(tex)
        h = site.resolve_refs(h, page) if "\x01REF" in h else h
    except web.Unsupported:
        h = web.esc(web.latex_to_text(tex))
    return re.sub(r"\s+", " ", h).strip()


def write_csv(path: Path, rows):
    buf = io.StringIO()
    buf.write("#separator:semicolon\n#html:true\n#columns:Front;Back;Tags\n#tags column:3\n")
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for r in rows:
        w.writerow(r)
    path.write_text(buf.getvalue(), encoding="utf-8")


def main(argv=None):
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description="collect \\flashcard{front}{back} into Anki CSV + web page")
    ap.add_argument("subject")
    ap.add_argument("--scope")
    ap.add_argument("--out-html", help="folder for flashcards.html (default <S>/work/<sc>/web)")
    args = ap.parse_args(argv)
    subj, shared, scoped = workdir.resolve(args.subject, args.scope)
    web = _web()
    errors = []
    cards = collect(scoped, errors)
    for e in errors:
        print("ERROR", e)
    out = Path(args.out_html).resolve() if args.out_html else scoped / "web"
    # A folder this run creates is a web.py output folder: mark it so web.py may rebuild it later
    # (otherwise the Phase E order flashcards -> web stops with "refusing to wipe"). Pre-existing
    # folders are never marked.
    fresh = not out.exists() or not any(out.iterdir())
    out.mkdir(parents=True, exist_ok=True)
    if fresh:
        (out / web.MARKER).write_text("written by _pipeline/tools/flashcards.py; web.py may rebuild this folder\n",
                                      encoding="utf-8")
    wargs = argparse.Namespace(base_url="", pdf_base="", no_render=True, jobs=1)
    site = web.Site(args.subject, subj, shared, scoped, out, wargs)
    rows = []
    for c in cards:
        tags = " ".join(x for x in (args.subject, scoped.name, c["topic"]) if x)
        rows.append([to_anki_html(site, c["front"]), to_anki_html(site, c["back"]), tags])
    write_csv(scoped / "flashcards.csv", rows)
    # the web page (study mode); math spans are rendered by KaTeX on the page
    html_cards = []
    for c in cards:
        page = web.Page("flashcards.html", "flash", "")
        cv = web.Conv(site, page, allow_fallback=False)
        try:
            f, b = cv.inline(c["front"]), cv.inline(c["back"])
            f, b = site.resolve_refs(f, page), site.resolve_refs(b, page)
        except web.Unsupported:
            f, b = web.esc(web.latex_to_text(c["front"])), web.esc(web.latex_to_text(c["back"]))
        html_cards.append({"front_html": f, "back_html": b, "topic": c["topic"]})
    pg = web.write_flashcards_page(site, html_cards)
    if not (out / "assets" / "site.css").exists():
        web.copy_assets(out)
    web.write_page(site, pg, [("Home", "index.html"), ("Flashcards", None)])
    print(f"flashcards: {len(cards)} cards from {len(sources(scoped))} files -> "
          f"{scoped / 'flashcards.csv'} and {out / 'flashcards.html'}")
    counts = {}
    for c in cards:
        counts[c["topic"] or "(no topic)"] = counts.get(c["topic"] or "(no topic)", 0) + 1
    known = [t["id"] for u in site.bp.get("units", []) if u.get("in_scope", True) for t in u.get("topics", [])]
    print("per-topic cards:")
    for tid in known + sorted(k for k in counts if k not in known):
        print(f"  {tid}: {counts.get(tid, 0)}")
    if errors:
        print(f"RESULT BLOCKED: {len(errors)} malformed \\flashcard(s)")
        return 1
    if not cards:
        print("WARN no \\flashcard found (writers add 2-5 per topic)")
    print(f"RESULT PASS ({len(cards)} cards)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
