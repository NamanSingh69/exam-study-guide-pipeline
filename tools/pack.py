"""One compact context file per writer (cost: writers used to read the contract, 6 JSONs and whole corpus files).

    py _pipeline/tools/pack.py <SUBJ> --scope S --writer unit-U4a      # one unit writer (assignments.json writers)
    py _pipeline/tools/pack.py <SUBJ> --scope S --role notes           # lean mode: every notes atom not reused
    py _pipeline/tools/pack.py <SUBJ> --scope S --role pyq             # lean mode: every solve not reused
    [--max-kb 150]

Writes work/<scope>/packs/<writer|role>.md: the writer card (prompts/_writer_card.md), the assignment (atoms,
chapters, figures, solves), targets with their why, conventions, per topic its title / visual / P / tiers /
blueprint notes, the verbatim bank text of owned questions, and the corpus text of exactly the pages the
blueprint cites (a __vision_ transcription replaces the OCR text of its page), each under its [slug pN] tag.
Excerpts are truncated to fit --max-kb; ids never are. The agent brief becomes: "read packs/<name>.md".
Exit 0 written, 2 usage error (unknown writer or subject).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workdir import PIPE, resolve, setup_stdout  # noqa: E402

TAG = re.compile(r"^## \[(\S+) p(\d+)\]\s*$", re.M)


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def cited_pages(sources):
    """['N_Notes p1-2', 'N_Notes p5, p7'] -> [('N_Notes', 1), ('N_Notes', 2), ('N_Notes', 5), ('N_Notes', 7)]"""
    out = []
    for s in sources or []:
        m = re.match(r"\s*(\S+)\s+(.*)", str(s))
        if not m:
            continue
        slug, rest = m.groups()
        for a, b in re.findall(r"p(\d+)(?:\s*[-–]\s*p?(\d+))?", rest):
            a, b = int(a), int(b or a)
            if b - a > 12:          # a whole chapter range: quote the first 12 pages, the writer opens the rest
                b = a + 11
            out += [(slug, p) for p in range(a, b + 1)]
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def corpus_pages(corpus: Path, slug: str, cache: dict):
    if slug in cache:
        return cache[slug]
    pages = {}
    files = sorted(corpus.glob(f"{slug}.md")) + sorted(corpus.glob(f"{slug}__vision_*.md"))   # vision last: wins
    for f in files:
        txt = f.read_text("utf-8", errors="replace")
        ms = list(TAG.finditer(txt))
        for i, m in enumerate(ms):
            if m.group(1) != slug:
                continue
            end = ms[i + 1].start() if i + 1 < len(ms) else len(txt)
            pages[int(m.group(2))] = txt[m.end():end].strip()
    cache[slug] = pages
    return pages


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("subject")
    ap.add_argument("--scope", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--writer")
    g.add_argument("--role", choices=["notes", "pyq"])
    ap.add_argument("--max-kb", type=float, default=150)
    a = ap.parse_args()
    subj, shared, work = resolve(a.subject, a.scope)
    asg = load(work / "assignments.json", {})
    bp = load(work / "blueprint.json", {})
    iq = load(work / "important_questions.json", {})
    conv = load(work / "conventions.json", []) or []
    bank = load(work / "pyq_bank.json", {}) or {}
    writers = asg.get("writers", {})
    reused_atoms = {str(x).split("/")[-1] for x in asg.get("reused_atoms", [])}
    reused_solves = set(asg.get("reused_solves", []))

    topics_by_id, unit_of = {}, {}
    for u in bp.get("units", []):
        for t in u.get("topics", []):
            topics_by_id[t["id"]] = t
            unit_of[t["id"]] = u
    if a.writer:
        if a.writer not in writers and not any(o.get("owner") == a.writer for o in asg.get("solve_owners", {}).values()):
            print(f"unknown writer {a.writer}; assignments.json writers: {', '.join(writers) or '(none)'}", file=sys.stderr)
            sys.exit(2)
        name = a.writer
        tids = list(writers.get(a.writer, []))
        solves = {c: o for c, o in asg.get("solve_owners", {}).items() if o.get("owner") == a.writer}
        chapters = [c for c in asg.get("chapters", []) if c.get("owner") == a.writer]
    elif a.role == "notes":
        name = "notes"
        tids = [t for ts in writers.values() for t in ts if t not in reused_atoms]
        if not tids:
            tids = [t for t in topics_by_id if t not in reused_atoms and f"notes/{t}" in asg.get("atoms", {})]
        solves = {}
        chapters = [c for c in asg.get("chapters", []) if c.get("kind") == "unit" and c.get("owner") != "reused"]
    else:
        name = "pyq"
        tids = []
        solves = {c: o for c, o in asg.get("solve_owners", {}).items()
                  if c not in reused_solves and not o.get("reused_from_midsem")}
        chapters = [c for c in asg.get("chapters", []) if c.get("kind") != "unit" and c.get("owner") != "reused"]
    tset = set(tids)

    P = {t["topic"]: t.get("P_display") or (f"{round(100 * t['P'])}%" if t.get("P") is not None else "")
         for t in iq.get("topics", [])}
    tiers = {}
    for c in iq.get("clusters", []):
        tiers.setdefault(c.get("topic"), []).append(f"{c['cluster']}({c.get('tier', '?')})")
    qs = {q["id"]: q for q in bank.get("questions", [])}
    targets = iq.get("targets", {})

    fixed = [f"# Pack: {name} ({subj.name} {a.scope})",
             f"Work folder: `{subj.name}/work/{a.scope}/`. Build from the `Study Prep` folder with `py`.", ""]
    card = PIPE / "prompts" / "_writer_card.md"
    if card.exists():
        fixed += ["## WRITER CARD", card.read_text("utf-8").strip(), ""]
    fixed += ["## Your assignment"]
    if tids:
        fixed.append("Notes atoms: " + ", ".join(f"notes/{t}" for t in tids))
    if chapters:
        fixed.append("Chapters: " + "; ".join(f"{c['stem']} ({c.get('kind', '')}"
                                               + (f", {c['paper']}" if c.get("paper") else "") + ")" for c in chapters))
    figs = [f for f, atom in asg.get("figures", {}).items() if str(atom).split("/")[-1] in tset]
    if figs:
        fixed.append("Shared figures you own (draw them, label exactly): " + ", ".join(figs))
    if solves:
        fixed.append("Solve atoms you own:")
        for c, o in solves.items():
            q = qs.get(o.get("anchor"), {})
            fixed.append(f"- solve/{c} in {o.get('chapter', '?')}, anchor {o.get('anchor', '?')}"
                         + (f" [{q.get('marks')} marks]: {q.get('text', '')}" if q else ""))
    if a.role == "pyq" or solves:
        fp = asg.get("full_papers", [])
        if fp:
            fixed.append("In-window papers in full: " + ", ".join(map(str, fp)))
        if iq.get("exam_hall"):
            fixed.append("Exam-hall budget: " + json.dumps(iq["exam_hall"], ensure_ascii=False)[:600])
    units = []
    for t in tids:
        u = unit_of.get(t, {}).get("id")
        if u and u not in units:
            units.append(u)
    np_ = targets.get("notes_pages", {})
    for u in units:
        if u in np_:
            v = np_[u]
            fixed.append(f"Page target {u} ({v.get('title', '')}): {v.get('pages')} print pages. Why: {v.get('why', '')}")
    if a.role == "notes":
        for k in ("q1_drill", "cheatsheet_pages"):
            if k in targets:
                v = targets[k]
                fixed.append(f"Target {k}: {v.get('count', v.get('pages', ''))}. Why: {v.get('why', '')}")
    if conv:
        fixed += ["", "## Conventions (follow exactly)"]
        for c in conv:
            fixed.append(f"- {c.get('id')}: {str(c.get('decision', ''))[:400]}")
    fixed.append("")

    topic_head, quotes = [], []
    for t in tids:
        tp = topics_by_id.get(t, {})
        topic_head.append(f"### {t}: {tp.get('title', '?')}")
        topic_head.append(f"visual: {tp.get('visual', '?')} | P: {P.get(t, '?')} | clusters: {', '.join(tiers.get(t, [])) or '-'}"
                          f" | sources: {'; '.join(tp.get('sources', [])) or '-'}")
        if tp.get("notes"):
            topic_head.append(f"blueprint notes: {tp['notes']}")
        for slug, p in cited_pages(tp.get("sources")):
            quotes.append((t, slug, p))
    corpus = shared / "corpus"
    cache = {}
    body = [(t, slug, p, corpus_pages(corpus, slug, cache).get(p)) for t, slug, p in quotes]
    head = "\n".join(fixed + (["## Topics"] + topic_head + [""] if topic_head else []))
    cap = int(a.max_kb * 1024)
    room = cap - len(head.encode("utf-8")) - 1500          # reserve for the 'also cited' and 'missing' lists
    missing = [f"[{slug} p{p}]" for t, slug, p, txt in body if txt is None]
    present = [x for x in body if x[3] is not None]
    MIN_PER = 800                                          # bytes: below this an excerpt stops being useful
    also = []
    if present and room // len(present) < MIN_PER:
        # too many pages: keep each topic's first k cited pages (the blueprint lists the main pages first)
        ntop = len({x[0] for x in present})
        k = max(1, room // (MIN_PER * max(ntop, 1)))
        seen, kept = {}, []
        for x in present:
            seen[x[0]] = seen.get(x[0], 0) + 1
            (kept if seen[x[0]] <= k else also).append(x)
        present = kept
    per = max(room // max(len(present), 1), 200) if present else 0
    truncated = False
    out = [head]
    quoted = []
    used = len(head.encode("utf-8"))
    for t, slug, p, txt in present:
        enc = txt.encode("utf-8")
        if len(enc) > per:
            txt = enc[:per].decode("utf-8", errors="ignore") + f"\n[... truncated: read [{slug} p{p}] in work/corpus/ if needed]"
            truncated = True
        block = f"## [{slug} p{p}]  (for {t})\n{txt}\n"
        if used + len(block.encode("utf-8")) > cap - 1500:
            also.append((t, slug, p, None))
            continue
        used += len(block.encode("utf-8"))
        quoted.append(block)
    if quoted:
        out.append("## Cited pages (verbatim corpus; cite as \\src{<slug> p<N>})")
        out += quoted
    if also:
        by = {}
        for _, s, p, _ in also:
            by.setdefault(s, set()).add(p)
        parts = []
        for s, ps in by.items():
            ps, runs = sorted(ps), []
            for p in ps:
                if runs and p == runs[-1][1] + 1:
                    runs[-1][1] = p
                else:
                    runs.append([p, p])
            parts.append(f"[{s} " + ", ".join(f"p{x}" if x == y else f"p{x}-{y}" for x, y in runs) + "]")
        out.append("Also cited, not quoted here (open in work/corpus/ when you write that topic): " + "; ".join(parts))
    if missing:
        out.append("Not in the corpus text (open note_pages/ if you need them): " + ", ".join(missing))
    if truncated or also:
        out.append(f"\nNote: page excerpts were truncated or left out to fit {a.max_kb:g} KB.")
    body = quoted
    dst = work / "packs" / f"{name}.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(out) + "\n", "utf-8")
    kb = dst.stat().st_size / 1024
    print(f"PACK {dst} ({kb:.0f} KB, {len(tids)} topic(s), {len(solves)} solve(s), "
          f"{len(body)} page(s) quoted{', truncated' if truncated or also else ''})")


if __name__ == "__main__":
    main()
