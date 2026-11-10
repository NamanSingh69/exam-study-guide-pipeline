"""
pairs.py: blind pairwise pairs for the review (previous round vs this round).

Picks N units present in BOTH the previous round's snapshot (--prev, e.g. work/<scope>/prev/2026-11-05/,
holding chapters/ and atoms/) and the current work/<scope>/chapters + atoms, by label:
  sec:<Tid>  a topic section        (the \\section carrying the label, up to the next \\section/\\chapter)
  q:<qid>    a PYQ solution         (the environment the label follows or sits in, up to the next q: unit)
  iq:<Cid>   an important question  (the \\subsection carrying the label, or as q:)
Default mix for --n 6: 3 sec, 2 q, 1 iq (the orchestrator's rule), tiers A/B first when
important_questions.json gives tiers. Units whose two versions are identical are skipped (nothing to judge).

For each pair it randomly decides which version is X, then writes:
  --out  (default work/<scope>/reviews/pairs/pairs.json): what reviewers get. Per pair: pair id, label,
         kind, the X and Y LaTeX and their files (pair_NN_X.tex / pair_NN_Y.tex, next to --out). No hint of
         which version is which.
  --key  (default work/<scope>/reviews/_keys/pairs[_r<round>].json): the mapping X/Y -> prev/new with the
         source file and line of each version, the seed and the --prev path. Never give it to a reviewer.

  py _pipeline/tools/pairs.py CN --scope midsem --prev CN/work/midsem/prev/2026-11-05 --n 6 [--seed 7]
     [--round 4] [--out <file>] [--key <file>]
  exit 0 = pairs written (a warning if fewer than N), 1 = no comparable pair, 2 = usage error
"""
import argparse, json, os, random, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workdir  # noqa: E402

KINDS = ("sec", "q", "iq")
LABEL_RE = re.compile(r"\\label\{((sec|q|iq):[^}]+)\}")
SECTIONING = ["chapter", "section", "subsection", "subsubsection", "paragraph"]
SEC_RE = re.compile(r"(?m)^[ \t]*\\(chapter|section|subsection|subsubsection|paragraph)\*?\s*[\[{]")
BEGIN_RE = re.compile(r"\\begin\{([^}]+)\}")
END_RE = re.compile(r"\\end\{([^}]+)\}")
DECOR_RE = re.compile(r"^[ \t]*(%.*|\\needspace\{[^}]*\}|\\Needspace\*?\{[^}]*\}|\\clearpage|\\newpage)?[ \t]*$")


def line_start(text, pos):
    return text.rfind("\n", 0, pos) + 1


def sectioning_at(text, lpos):
    """(level, start) if the label belongs to a sectioning command on its line or the line before."""
    ls = line_start(text, lpos)
    prev_ls = line_start(text, max(0, ls - 1)) if ls > 0 else 0
    found = None                 # the NEAREST sectioning command before the label ('\section{Tier A}' on the
    for m in SEC_RE.finditer(text, prev_ls, lpos):          # line above '\subsection*{..}\label' is not it)
        between = text[m.end():lpos]
        if "\\begin{" not in between and "\n\n" not in between:
            found = (SECTIONING.index(m.group(1)), m.start())
    return found


def env_start(text, lpos):
    """Start of the environment the label sits in, or of the one it directly follows."""
    before = text[:lpos]
    m = re.search(r"\\end\{([^}]+)\}\s*$", before)
    if m:                                   # \end{question}\n\label{q:..}
        name, depth, i = m.group(1), 0, m.start()
        for t in reversed(list(re.finditer(r"\\(begin|end)\{" + re.escape(name) + r"\}", before[:m.end()]))):
            depth += 1 if t.group(1) == "end" else -1
            if depth == 0:
                return t.start()
        return i
    stack = []                              # innermost open environment at the label
    for t in re.finditer(r"\\(begin|end)\{([^}]+)\}", before):
        if t.group(1) == "begin":
            stack.append((t.group(2), t.start()))
        elif stack and stack[-1][0] == t.group(2):
            stack.pop()
    stack = [s for s in stack if s[0] != "document"]
    return stack[-1][1] if stack else line_start(text, lpos)


LIST_RE = re.compile(r"\\(begin|end)\{(itemize|enumerate|description)\}|\\item\b")


def item_span(text, lpos):
    """(start, end) of the \\item the label sits on ('\\item\\phantomsection\\label{iq:C07} ...'), up to the next
    \\item of the same list or the list's end; None if the label is not on an \\item line."""
    ls = line_start(text, lpos)
    k = text.rfind("\\item", ls, lpos)
    if k < 0:
        return None
    depth, end = 0, len(text)
    for m in LIST_RE.finditer(text, lpos):
        if m.group(1) == "begin":
            depth += 1
        elif m.group(1) == "end":
            if depth == 0:
                end = m.start(); break
            depth -= 1
        elif depth == 0:          # the next \item of the same list
            end = m.start(); break
    return k, end


def with_decoration(text, start, floor):
    """Move the start up over comment / \\needspace / blank lines directly above (not past floor)."""
    s = start
    while s > floor:
        ps = line_start(text, s - 1)
        if ps < floor or not DECOR_RE.match(text[ps:s - 1] if s - 1 >= ps else ""):
            break
        s = ps
    while s < start and text[s:start].startswith("\n"):
        s += 1
    return s


def units_in(text):
    """{label: (start, end, line)} for every sec:/q:/iq: label of one .tex file."""
    labs = []
    for m in LABEL_RE.finditer(text):
        if text[line_start(text, m.start()):m.start()].lstrip().startswith("%"):
            continue
        sec = sectioning_at(text, m.start())
        item = None if sec else item_span(text, m.start())
        if sec:
            labs.append([m.group(1), m.group(2), sec[1], sec[0]])
        elif item:
            labs.append([m.group(1), m.group(2), item[0], "item", item[1]])
        else:
            labs.append([m.group(1), m.group(2), env_start(text, m.start()), None])
    out = {}
    secs = [(m.start(), SECTIONING.index(m.group(1))) for m in SEC_RE.finditer(text)]
    for k, (label, kind, start, level, *rest) in enumerate(labs):
        if level == "item":
            end = rest[0]
        elif level is None:
            floor = max([p for p, _l in secs if p <= start] + [0])
            prev_same = [lab[2] for lab in labs[:k] if lab[1] == kind]
            start = with_decoration(text, start, max([floor] + prev_same))
            nxt = [lab[2] for lab in labs[k + 1:] if lab[1] == kind and lab[3] in (None, "item")]
            end = min([p for p, _l in secs if p > start] + nxt + [len(text)])
            if nxt:      # the next unit's decoration lines belong to it
                end = min(end, with_decoration(text, min(nxt), start + 1))
        else:            # a section unit also ends where the next unit of its kind starts (e.g. an \item list)
            nxt = [lab[2] for lab in labs[k + 1:] if lab[1] == kind and lab[2] > start]
            end = min([p for p, lvl in secs if p > start and lvl <= level] + nxt + [len(text)])
        body = text[start:end]
        lines = re.split(r"\\end\{document\}", body)[0].rstrip().split("\n")
        while len(lines) > 1 and re.fullmatch(r"\s*(%.*)?", lines[-1]):   # trailing separators / blanks
            lines.pop()
        body = "\n".join(lines) + "\n"
        out[label] = (body, text.count("\n", 0, start) + 1)
    return out


def collect(root):
    """{label: (latex, 'rel/file.tex:line')} over chapters/ and atoms/ (or every .tex) below root."""
    root = Path(root)
    dirs = [d for d in (root / "chapters", root / "atoms") if d.is_dir()] or [root]
    found = {}
    for d in dirs:
        for f in sorted(d.rglob("*.tex")):
            if any(part in ("prev", "build", "reviews") for part in f.relative_to(root).parts[:-1]):
                continue
            text = f.read_text("utf-8", errors="replace")
            for label, (body, line) in units_in(text).items():
                found.setdefault(label, (body, f"{f.relative_to(root).as_posix()}:{line}"))
    return found


def tiers(work):
    """{label: tier letter} from important_questions.json (clusters, topics) and the bank (q -> cluster)."""
    t = {}
    iq = work / "important_questions.json"
    try:
        data = json.loads(iq.read_text("utf-8")) if iq.exists() else {}
    except ValueError:
        data = {}
    for key, prefix, idk in (("clusters", "iq:", "cluster"), ("topics", "sec:", "topic")):
        items = data.get(key) or []
        if isinstance(items, dict):
            items = [dict(v, id=k) for k, v in items.items() if isinstance(v, dict)]
        for c in items:
            cid = isinstance(c, dict) and (c.get("id") or c.get(idk))
            if cid and c.get("tier"):
                t[prefix + str(cid)] = str(c["tier"])
    try:
        bank = json.loads((work / "pyq_bank.json").read_text("utf-8"))
        for q in bank.get("questions", []):
            if "iq:" + str(q.get("cluster")) in t:
                t["q:" + str(q.get("id"))] = t["iq:" + str(q["cluster"])]
    except (OSError, ValueError):
        pass
    return t


def quotas(n):
    sec = round(n / 2)
    q = round(n / 3)
    return {"sec": sec, "q": q, "iq": max(0, n - sec - q)}


def pick(common, n, tier, rng):
    by_kind = {k: [] for k in KINDS}
    for lab in common:
        by_kind[lab.split(":", 1)[0]].append(lab)
    for k in KINDS:
        rng.shuffle(by_kind[k])
        by_kind[k].sort(key=lambda lab: (tier.get(lab, "Z") not in ("A", "B"), tier.get(lab, "Z")))
    want = quotas(n)
    chosen = []
    for k in KINDS:
        chosen += by_kind[k][:want[k]]
        by_kind[k] = by_kind[k][want[k]:]
    rest = [lab for k in KINDS for lab in by_kind[k]]
    rest.sort(key=lambda lab: (tier.get(lab, "Z") not in ("A", "B"), rng.random()))
    chosen += rest[:max(0, n - len(chosen))]
    order = {k: i for i, k in enumerate(KINDS)}
    return sorted(chosen, key=lambda lab: (order[lab.split(":", 1)[0]], lab))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)


def main():
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject")
    ap.add_argument("--scope", required=True, choices=workdir.SCOPES)
    ap.add_argument("--prev", required=True, help="previous round's snapshot (holds chapters/ and atoms/)")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--round", type=int, help="names the default key file pairs_r<round>.json")
    ap.add_argument("--out")
    ap.add_argument("--key")
    a = ap.parse_args()
    if a.n < 1:
        ap.error("--n must be >= 1")
    _subj, _shared, work = workdir.resolve(a.subject, a.scope)
    prev = Path(a.prev)
    if not prev.is_absolute() and not prev.exists():
        prev = workdir.ROOT / a.prev
    if not prev.is_dir():
        print(f"--prev {a.prev}: no such directory", file=sys.stderr)
        sys.exit(2)
    out = Path(a.out) if a.out else work / "reviews" / "pairs" / "pairs.json"
    key = Path(a.key) if a.key else work / "reviews" / "_keys" / (f"pairs_r{a.round}.json" if a.round else "pairs.json")
    seed = a.seed if a.seed is not None else int.from_bytes(os.urandom(4), "big")
    rng = random.Random(seed)

    old, new = collect(prev), collect(work)
    common = sorted(set(old) & set(new))
    same = [lab for lab in common if old[lab][0].strip() == new[lab][0].strip()]
    usable = [lab for lab in common if lab not in same]
    print(f"pairs {a.subject} --scope {a.scope}: {len(old)} labelled unit(s) in prev, {len(new)} now, "
          f"{len(common)} in both, {len(same)} unchanged (skipped)")
    if not usable:
        print("RESULT BLOCKED: no comparable changed unit (sec:/q:/iq:) in both versions")
        sys.exit(1)
    chosen = pick(usable, a.n, tiers(work), rng)
    pdir = out.parent
    pdir.mkdir(parents=True, exist_ok=True)
    for f in pdir.glob("pair_*_[XY].tex"):
        f.unlink()
    pairs, mapping = [], {}
    for i, lab in enumerate(chosen, 1):
        pid = f"pair_{i:02d}"
        x_is_prev = rng.random() < 0.5
        x, y = (old[lab], new[lab]) if x_is_prev else (new[lab], old[lab])
        xf, yf = pdir / f"{pid}_X.tex", pdir / f"{pid}_Y.tex"
        xf.write_text(x[0], "utf-8")
        yf.write_text(y[0], "utf-8")
        pairs.append({"pair": pid, "label": lab, "kind": lab.split(":", 1)[0], "X": x[0], "Y": y[0],
                      "x_file": str(xf), "y_file": str(yf)})
        mapping[pid] = {"label": lab, "X": "prev" if x_is_prev else "new", "Y": "new" if x_is_prev else "prev",
                        "prev_src": old[lab][1], "new_src": new[lab][1]}
        print(f"  {pid}  {lab}")
    write_json(out, {"subject": a.subject, "scope": a.scope, "n": len(pairs),
                     "instructions": "X and Y are the same unit from two versions, in random order.",
                     "pairs": pairs})
    write_json(key, {"subject": a.subject, "scope": a.scope, "seed": seed, "prev": str(prev),
                     "round": a.round, "pairs": mapping})
    print(f"wrote {out}\nkey   {key}")
    if len(pairs) < a.n:
        print(f"WARNING: only {len(pairs)} of {a.n} requested pairs could be made")


if __name__ == "__main__":
    main()
