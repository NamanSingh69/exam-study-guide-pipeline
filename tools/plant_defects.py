"""
plant_defects.py — make a scratch copy of a guide's sources with N planted defects (reviewer calibration).

  py _pipeline/tools/plant_defects.py CN --scope midsem --n 5 --seed 1 --out CN/work/midsem/reviews/copy_1
      copies chapters/, atoms/, badges.tex and the work folder's *.json into --out (paths relative to it),
      plants N defects, and writes the answer key to <S>/work/<sc>/reviews/_keys/<out folder name>.json
      (never inside --out). Key: [{file, where, kind, original, planted}].
  py _pipeline/tools/plant_defects.py --score review.json --key CN/work/midsem/reviews/_keys/copy_1.json
      recall of a reviewer's review.json (fixes[] with file/where/problem) against the key.

Defect kinds (one per kind while kinds last; the seed picks order and places):
  wrong_number        a final \\answer{..} number in a solution is changed
  invented_pyq        a fabricated sentence appended to a verbatim past-paper question box
  convention_mismatch one chapter states the conventions.json alternative instead of the decision
  figure_label        a TikZ label duplicated onto another label's position (overlap) or garbled
  long_answer         a 2.5-mark solution padded to about 3x its length
  unsupported_stat    an invented "asked in k of the last n papers / x% of the marks" claim
  cheatsheet_formula  a formula in chapters/cheatsheet.tex altered (fraction flipped or sign changed)
Exit 0 = all N planted, 1 = fewer could be planted, 2 = usage.
"""
import argparse, json, random, re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from workdir import resolve, setup_stdout  # noqa: E402

KINDS = ["wrong_number", "invented_pyq", "convention_mismatch", "figure_label", "long_answer",
         "unsupported_stat", "cheatsheet_formula"]
FAKE_PYQ = [
    "Also state two limitations of this approach and suggest a remedy for each.",
    "Justify your answer with a neat labelled diagram and compare it with the sliding window case.",
    "Further, derive the general expression and verify it for $n = 8$.",
    "Hence explain why this scheme is not used in modern high-speed networks.",
]
FAKE_STAT = [
    "This topic has appeared in {k} of the last {n} papers and carries about {p}\\% of the total marks.",
    "Examiners have asked this every year since {y}; it alone is worth roughly {p}\\% of the paper.",
    "In past papers {p}\\% of students lost marks here, so it is asked in {k} out of {n} sets.",
]


class Copy:
    """The copied files, edited in memory; tracks planted spans so later edits keep line numbers right."""

    def __init__(self, root: Path):
        self.root = root
        self.files = {p.relative_to(root).as_posix(): p.read_text("utf-8", errors="replace")
                      for p in sorted(root.rglob("*.tex"))}
        self.key = []        # dicts + internal _pos
        self.used = set()    # (file, line) already used

    def edit(self, rel, start, end, new, kind, where, original, planted):
        t = self.files[rel]
        self.files[rel] = t[:start] + new + t[end:]
        delta = len(new) - (end - start)
        for k in self.key:
            if k["file"] == rel and k["_pos"] > start:
                k["_pos"] += delta
        offset = new.find(planted) if planted and planted in new else 0
        self.key.append({"file": rel, "where": where, "kind": kind, "original": original, "planted": planted,
                         "_pos": start + max(offset, 0)})
        self.used.add((rel, t[:start].count("\n") + 1))

    def line(self, rel, pos):
        return self.files[rel][:pos].count("\n") + 1

    def free(self, rel, pos):
        ln = self.line(rel, pos)
        return all(not (f == rel and abs(ln - l) < 4) for f, l in self.used)

    def save(self):
        for rel, t in self.files.items():
            (self.root / rel).write_text(t, "utf-8")


def strip(t):
    return re.sub(r"(?<!\\)%.*", "", t)


def env_spans(t, env):
    """[(start of \\begin, start of body, start of \\end, end)] for non-nested occurrences of env."""
    out = []
    for m in re.finditer(r"\\begin\{" + re.escape(env) + r"\}", t):
        e = t.find(r"\end{" + env + "}", m.end())
        if e > 0:
            out.append((m.start(), m.end(), e, e + len(env) + 6))
    return out


def brace_arg_simple(t, i):
    """t[i:] starts with '{...}' (balanced) -> (content, index after it); otherwise (None, i)."""
    while i < len(t) and t[i] in " \t":
        i += 1
    if i >= len(t) or t[i] != "{":
        return None, i
    depth = 0
    for j in range(i, len(t)):
        if t[j] == "{" and t[j - 1] != "\\":
            depth += 1
        elif t[j] == "}" and t[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return t[i + 1:j], j + 1
    return None, i


def chapter_files(c, *, cheat=False):
    return [r for r in c.files if (r == "chapters/cheatsheet.tex") == cheat and not r.split("/")[-1].startswith("_")]


# ------------------------------------------------------------------ the plants
def plant_wrong_number(c, rng):
    cands = []
    for rel in chapter_files(c):
        t = c.files[rel]
        for m in re.finditer(r"\\answer\{", t):
            body_end = t.find("}", m.end())
            seg = t[m.end():body_end]
            for n in re.finditer(r"(?<![\w.^_])(\d+(?:\.\d+)?)(?![\w.])", seg):
                pos = m.end() + n.start()
                if c.free(rel, pos) and not strip(t[t.rfind("\n", 0, pos) + 1:pos]).strip() == "":
                    cands.append((rel, pos, n.group(1)))
                    break
    if not cands:
        return False
    rel, pos, num = rng.choice(cands)
    if "." in num:
        dec = len(num.split(".")[1])
        new = f"{float(num) * 1.5:.{dec}f}"
    else:
        v = int(num)
        new = str(v * 2 if v in (0, 1) or rng.random() < 0.5 else v + rng.choice((1, -1) if v > 1 else (1,)))
        new = "2" if new == num else new
    ctx = c.files[rel][max(0, pos - 40):pos + len(num) + 10].replace("\n", " ")
    c.edit(rel, pos, pos + len(num), new, "wrong_number",
           f"line {c.line(rel, pos)}: final \\answer{{}} of a solution (context: ...{ctx}...)", num, new)
    return True


def plant_invented_pyq(c, rng):
    cands = []
    for rel in chapter_files(c):
        t = c.files[rel]
        for b, body, e, _ in env_spans(t, "question"):
            head = t[body:body + 200]
            if re.match(r"\s*\{[^}]*(20\d\d|Q\d)", head) and c.free(rel, e):   # a dated past-paper question
                cands.append((rel, e))
    if not cands:
        return False
    rel, e = rng.choice(cands)
    sent = rng.choice(FAKE_PYQ)
    c.edit(rel, e, e, " " + sent + "\n", "invented_pyq",
           f"line {c.line(rel, e)}: last sentence of the past-paper question box ending here", "", sent)
    return True


def plant_convention_mismatch(c, rng, conventions):
    alts = [x for x in conventions if isinstance(x, dict) and x.get("alternative")
            and x["alternative"].strip().lower() not in ("none", "n/a", "")]
    cands = []
    for rel in chapter_files(c):
        t = c.files[rel]
        for m in re.finditer(r"\\section\*?\{[^\n]*\n", t):
            if c.free(rel, m.end()):
                cands.append((rel, m.end()))
    if not alts or not cands:
        # fallback: flip a size convention in one chapter (1 KB = 1024 B <-> 1000 B)
        for rel in chapter_files(c):
            t = c.files[rel]
            m = re.search(r"1\s*(?:\\,|~)?\s*KB\s*=\s*(1024|1000)", t)
            if m and c.free(rel, m.start(1)):
                new = "1000" if m.group(1) == "1024" else "1024"
                c.edit(rel, m.start(1), m.end(1), new, "convention_mismatch",
                       f"line {c.line(rel, m.start(1))}: size convention contradicts the other chapters", m.group(1), new)
                return True
        return False
    conv = rng.choice(alts)
    rel, pos = rng.choice(cands)
    alt = re.sub(r"\s*-\s*mention.*$|\s*\(.*?only.*?\)\s*$", "", conv["alternative"]).strip().rstrip(".")
    alt = alt.replace("%", r"\%").replace("_", r"\_").replace("&", r"\&").replace("#", r"\#")
    sent = f"Convention used in this section: {alt}."
    c.edit(rel, pos, pos, sent + "\n", "convention_mismatch",
           f"line {c.line(rel, pos)}: contradicts conventions.json '{conv.get('id', '?')}' ({conv.get('decision', '')[:90]})",
           "", sent)
    return True


def plant_figure_label(c, rng):
    cands = []
    for rel in chapter_files(c) + chapter_files(c, cheat=True):
        t = c.files[rel]
        for b, body, e, _ in env_spans(t, "tikzpicture"):
            pic = t[body:e]
            nodes = list(re.finditer(r"\\node\s*\[([^\]]*)\]\s*(?:\([^)]*\)\s*)?at\s*(\([^()]*\))\s*\{([^{}]{3,40})\}\s*;", pic))
            labeled = [n for n in nodes if re.search(r"[A-Za-z]{3}", n.group(3))]
            if len(labeled) >= 2 and c.free(rel, body):
                cands.append((rel, body, labeled))
    if not cands:
        return False
    rel, body, nodes = rng.choice(cands)
    a, b = rng.sample(nodes, 2)
    if rng.random() < 0.6:
        # overlap: b's label also drawn at a's position
        ins = f"\n  \\node[{b.group(1)}] at {a.group(2)} {{{b.group(3)}}};"
        pos = body + a.end()
        c.edit(rel, pos, pos, ins, "figure_label",
               f"line {c.line(rel, pos)}: label '{b.group(3)}' overlaps '{a.group(3)}' at {a.group(2)}", "", ins.strip())
    else:
        txt = a.group(3)
        letters = [i for i, ch in enumerate(txt) if ch.isalpha()]
        i, j = letters[0], letters[-1]
        g = list(txt)
        g[i], g[j] = g[j], g[i]
        mid = letters[len(letters) // 2]
        g[mid] = "@" if g[mid] not in "@" else "#"
        new = "".join(g).replace("#", r"\#")
        start = body + a.start(3)
        c.edit(rel, start, body + a.end(3), new, "figure_label",
               f"line {c.line(rel, start)}: garbled TikZ label", txt, new)
    return True


def plant_long_answer(c, rng):
    cands = []
    for rel in chapter_files(c):
        t = c.files[rel]
        for qb, qbody, qe, qend in env_spans(t, "question"):
            if not re.match(r"\s*\{[^}]*\}\s*\{\s*2\.5\s*\}", t[qbody:qbody + 200]):
                continue
            nxt = t.find(r"\begin{solution}", qend)
            if 0 <= nxt - qend < 600:
                sb = [s for s in env_spans(t, "solution") if s[0] == nxt]
                if sb and c.free(rel, sb[0][2]):
                    cands.append((rel, sb[0]))
    # Round 4 layout: the full answer of an idea lives once, in a solvedidea atom; pad one whose cluster carries
    # a 2.5-mark question in the bank
    bank = c.root / "pyq_bank.json"
    c25 = {q.get("cluster") for q in (json.loads(bank.read_text("utf-8")).get("questions", []) if bank.exists() else [])
           if str(q.get("marks")) in ("2.5", "2.50")}
    for rel in chapter_files(c):
        t = c.files[rel]
        for m in re.finditer(r"\\begin\{solvedidea\}\{([^}]+)\}", t):
            e = t.find(r"\end{solvedidea}", m.end())
            if m.group(1) in c25 and e > 0 and c.free(rel, e):
                _title, body_start = brace_arg_simple(t, m.end())
                cands.append((rel, (m.start(), body_start, e, e + len(r"\end{solvedidea}"))))
    if not cands:
        return False
    rel, (sb, sbody, se, send) = rng.choice(cands)
    body = c.files[rel][sbody:se]
    body = re.sub(r"^\[[^\]]*\]", "", body.lstrip())                # the optional title
    body = re.sub(r"\\label\{[^}]*\}", "", body)                      # no duplicate labels
    body = re.sub(r"\\(stepanim|storyboard)\*?", r"\\storyboard*", body)
    pad = "\n\\par In more detail:\n" + body.strip() + "\n\\par To restate the main points:\n" + body.strip() + "\n"
    c.edit(rel, se, se, pad, "long_answer",
           f"line {c.line(rel, se)}: a 2.5-mark solution padded to about 3x its length (the padding starts on this line)",
           "", "\\par In more detail:")
    return True


def plant_unsupported_stat(c, rng):
    cands = []
    for rel in chapter_files(c):
        t = c.files[rel]
        for m in re.finditer(r"\\(?:sub)?section\*?\{[^\n]*\n", t):
            if c.free(rel, m.end()):
                cands.append((rel, m.end()))
    if not cands:
        return False
    rel, pos = rng.choice(cands)
    n = rng.choice((5, 6, 8, 10))
    sent = rng.choice(FAKE_STAT).format(k=n - rng.choice((0, 1)), n=n, p=rng.choice((30, 35, 40, 45)), y=rng.choice((2012, 2015, 2016)))
    c.edit(rel, pos, pos, sent + "\n", "unsupported_stat",
           f"line {c.line(rel, pos)}: statistic not computed from pyq_bank.json", "", sent)
    return True


def plant_cheatsheet_formula(c, rng):
    rel = "chapters/cheatsheet.tex"
    if rel not in c.files:
        return False
    t = c.files[rel]
    fracs = [m for m in re.finditer(r"\\[dt]?frac\{([^{}]+)\}\{([^{}]+)\}", t) if m.group(1) != m.group(2) and c.free(rel, m.start())]
    if fracs:
        m = rng.choice(fracs)
        cmd = m.group(0).split("{", 1)[0]
        new = f"{cmd}{{{m.group(2)}}}{{{m.group(1)}}}"
        c.edit(rel, m.start(), m.end(), new, "cheatsheet_formula",
               f"line {c.line(rel, m.start())}: fraction inverted", m.group(0), new)
        return True
    for m in re.finditer(r"\$([^$]{3,80})\$", t):
        s = m.group(1)
        k = s.find("+") if "+" in s else s.find("-")
        if k > 0 and c.free(rel, m.start()):
            new = s[:k] + ("-" if s[k] == "+" else "+") + s[k + 1:]
            c.edit(rel, m.start(1), m.end(1), new, "cheatsheet_formula",
                   f"line {c.line(rel, m.start())}: sign flipped in a formula", s, new)
            return True
    return False


# ------------------------------------------------------------------ main
def make_copy(work: Path, out: Path):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for d in ("chapters", "atoms"):
        if (work / d).exists():
            shutil.copytree(work / d, out / d, ignore=shutil.ignore_patterns("_*.tex"))
    for f in list(work.glob("*.json")) + [work / "badges.tex"]:
        if f.exists():
            shutil.copy2(f, out / f.name)
    shared_conv = work.parent / "conventions.json"
    if shared_conv.exists() and not (out / "conventions.json").exists():
        shutil.copy2(shared_conv, out / "conventions.json")


def plant(work: Path, out: Path, n: int, seed: int):
    make_copy(work, out)
    rng = random.Random(seed)
    c = Copy(out)
    conv = json.loads((out / "conventions.json").read_text("utf-8")) if (out / "conventions.json").exists() else []
    if isinstance(conv, dict):
        conv = conv.get("conventions", list(conv.values()))
    fns = {"wrong_number": plant_wrong_number, "invented_pyq": plant_invented_pyq,
           "convention_mismatch": lambda c, r: plant_convention_mismatch(c, r, conv),
           "figure_label": plant_figure_label, "long_answer": plant_long_answer,
           "unsupported_stat": plant_unsupported_stat, "cheatsheet_formula": plant_cheatsheet_formula}
    order = KINDS[:]
    rng.shuffle(order)
    planted, rounds = 0, 0
    while planted < n and rounds < 4:
        progress = False
        for k in order:
            if planted >= n:
                break
            if fns[k](c, rng):
                planted += 1
                progress = True
        rounds += 1
        if not progress:
            break
    c.save()
    key = []
    for k in c.key:
        ln = c.line(k["file"], k["_pos"])
        where = re.sub(r"^line \d+", f"line {ln}", k["where"])
        key.append({"file": k["file"], "where": where, "kind": k["kind"], "original": k["original"], "planted": k["planted"]})
    return key


def score(review: Path, keyf: Path):
    rv = json.loads(review.read_text("utf-8"))
    key = json.loads(keyf.read_text("utf-8"))
    # 06_review.md puts the worst findings under critical[] and the rest under fixes[]: both count
    fixes = (list(rv.get("critical", [])) + list(rv.get("fixes", []))) if isinstance(rv, dict) else rv
    hits = []
    for k in key:
        kl = int(re.match(r"line (\d+)", k["where"]).group(1)) if re.match(r"line (\d+)", k["where"]) else None
        tokens = [w for w in re.findall(r"[A-Za-z0-9@#.]{5,}", k["planted"] or k["original"])][:6]
        found = False
        for f in fixes:
            if Path(str(f.get("file", ""))).name != Path(k["file"]).name:
                continue
            blob = " ".join(str(f.get(x, "")) for x in ("where", "problem", "fix"))
            lines = [int(x) for x in re.findall(r"\b(?:line|l\.)\s*(\d+)", blob)]
            # a quoted planted string counts even when it has no long token and no line number
            # (real SVP r1: "\frac{2(L-1)}{1}" quoted verbatim was scored as missed)
            squash = lambda x: re.sub(r"\s+", "", str(x))
            pl = squash(k["planted"] or "")
            quoted = len(pl) >= 6 and pl in squash(blob)
            if (kl and any(abs(l - kl) <= 12 for l in lines)) or any(t in blob for t in tokens) or quoted:
                found = True
                break
        hits.append({"kind": k["kind"], "file": k["file"], "found": found})
    rec = sum(h["found"] for h in hits) / len(hits) if hits else 0.0
    return rec, hits


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="plant reviewer-calibration defects in a scratch copy")
    ap.add_argument("subject", nargs="?")
    ap.add_argument("--scope")
    ap.add_argument("--out")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--score", help="reviewer review.json to score against --key")
    ap.add_argument("--key")
    a = ap.parse_args()
    if a.score:
        if not a.key:
            ap.error("--score needs --key")
        rec, hits = score(Path(a.score), Path(a.key))
        for h in hits:
            print(f"{'FOUND ' if h['found'] else 'MISSED'} {h['kind']:20s} {h['file']}")
        print(f"RECALL {rec:.2f} ({sum(h['found'] for h in hits)}/{len(hits)})")
        return 0
    if not a.subject or not a.out:
        ap.error("usage: plant_defects.py <S> --scope <sc> --n 5 --seed K --out <dir>")
    _subj, _shared, work = resolve(a.subject, a.scope)
    out = Path(a.out).resolve()
    w = work.resolve()
    inside = w in out.parents
    if out == w or out in w.parents or (inside and (w / "reviews") not in out.parents):
        print("--out must be a separate folder (e.g. <S>/work/<sc>/reviews/copy_<k>), never the work folder itself", file=sys.stderr)
        return 2
    key = plant(work, out, a.n, a.seed)
    kdir = work / "reviews" / "_keys"
    kdir.mkdir(parents=True, exist_ok=True)
    kf = kdir / f"{out.name}.json"
    kf.write_text(json.dumps(key, indent=1, ensure_ascii=False), "utf-8")
    for k in key:
        print(f"PLANTED {k['kind']:20s} {k['file']}  {k['where'][:90]}")
    print(f"COPY   {out}\nKEY    {kf}")
    ok = len(key) >= a.n
    print("RESULT PASS" if ok else f"RESULT BLOCKED: only {len(key)} of {a.n} defects could be planted")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
