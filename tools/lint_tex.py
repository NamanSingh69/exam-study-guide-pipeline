r"""lint_tex.py: fast pre-build lint for the LaTeX traps that otherwise surface after a 5-minute full build.

    py tools/lint_tex.py <SUBJ> --scope midsem|endsem [--files a.tex,b.tex]
    from lint_tex import lint_files      # lint_files(paths) -> [(path, line, code, msg)]

Lints <SUBJ>/work/<scope>/atoms/**/*.tex and chapters/*.tex (or only --files). Prints
`LINT <relpath>:<line> <code> <msg>` and `RESULT PASS|FAIL`; exit 1 on any error, 0 otherwise.

Errors
  answer_in_caption  \\answer{..} inside \\caption{..}: breaks the web edition and the full build (tcbox in a moving argument)
  dup_newcommand     same macro \\newcommand'ed in two different files of the subject: fatal in the full build
                     ("command already defined"; also breaks the web edition); \\providecommand / \\renewcommand never count
  long_cell_word     a word with no break opportunity wider than its fixed-width column on the PHONE page
  banned             [H] float placement and \\tiny (writer contract)
Warning
  printed_id         raw convention-style id (\\texttt{ack\\_number}, conv\\_..) in running text; the metrics
                     internal_leaks gate is the authority, this only warns early

long_cell_word model (PRINT edition only; the phone edition is dropped): A4 text width ~160 mm, 11 pt body. L{w}
and p/m/b{w} columns keep their written width; l/c/r/X/Y columns are never checked. A cell is the text with math,
\ref-like arguments, URLs, \texttt, \label and comments removed; break opportunities are spaces, hyphens, dashes,
\- and \allowbreak ('/' is NOT one: "Eigenvalues/eigenvectors" is the trap). Estimated word width = chars x 0.5 em
at the table font (11 pt, or the last \small/\footnotesize/\scriptsize in the 400 chars before the table or in
it). Usable width = column - 2 x \tabcolsep (6 pt, or the last \setlength{\tabcolsep} above; +1 tabcolsep at an
@{} edge). Only tokens of 8+ characters are checked. Joined slugs (contain a non-letter) are flagged when
estimate > 1.2 x usable (TOL_JOINED 1.2); plain words only when estimate > 1.6 x usable (TOL_PLAIN). Example: L{42mm} =
119 pt, usable 107 pt: "eigenvectors" passes, "Eigenvalues/eigenvectors" (137 pt) is flagged. \multicolumn
advances the column index by its span.
"""
import re, sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

EM_PER_CHAR = 0.5
MIN_WORD = 8        # shorter tokens (numbers, 'Marks', 'viii') are never reported: tiny columns are tuned by hand
TOL_JOINED = 1.2    # slugs with '/', ':', '_', digits: no break opportunity, 0.5 em/char is about right
TOL_PLAIN = 1.6     # plain alphabetic words: 0.5 em/char overestimates (~0.43 em) and hand-tuned columns hold them
FONT_PT = {"scriptsize": 8.0, "footnotesize": 9.0, "small": 10.0, "normalsize": 11.0}   # 11 pt class
UNIT_PT = {"mm": 2.8453, "cm": 28.453, "pt": 1.0, "in": 72.27, "em": 10.5, "ex": 4.5}
ERRORS = {"answer_in_caption", "dup_newcommand", "long_cell_word", "banned"}


def _mask_comments(s):
    """Blank out %-comments (keeps offsets and line numbers)."""
    return re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m.group(0)), s)


def _line(s, pos):
    return s.count("\n", 0, pos) + 1


def _group(s, i):
    """s[i] == '{': return index after the matching '}' (or len(s))."""
    d = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                return i + 1
        i += 1
    return len(s)


def _to_pt(txt):
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(mm|cm|pt|in|em|ex)\s*", txt)
    return float(m.group(1)) * UNIT_PT[m.group(2)] if m else None


def parse_spec(spec):
    """Column spec -> list of column widths in pt (None = not fixed / not checked)."""
    cols, i = [], 0
    while i < len(spec):
        c = spec[i]
        if c in "><@!":
            i += 1
            if i < len(spec) and spec[i] == "{":
                i = _group(spec, i)
            continue
        if c == "*":
            j = _group(spec, i + 1)
            n = re.sub(r"[{}\s]", "", spec[i + 1:j])
            k = _group(spec, j)
            sub = parse_spec(spec[j + 1:k - 1])
            cols += sub * (int(n) if n.isdigit() else 1)
            i = k
            continue
        if c in "pmbL":
            if i + 1 < len(spec) and spec[i + 1] == "{":
                j = _group(spec, i + 1)
                w = _to_pt(spec[i + 2:j - 1])
                cols.append(None if w is None else w)
                i = j
                continue
            cols.append(None)
        elif c in "lcrXY":
            cols.append(None)
        i += 1
    return cols


_STRIP_ARGS = re.compile(r"\\(?:ref|pageref|cref|Cref|eqref|autoref|nameref|url|href|texttt|label|cite|"
                         r"hyperref|path|lstinline|verb|mks|clusterbadge|topicbadge)\*?(?:\[[^\]]*\])?\{[^{}]*\}")


def _clean_cell(t):
    t = re.sub(r"\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)", " ", t, flags=re.S)
    t = _STRIP_ARGS.sub(" ", t)
    t = re.sub(r"\\(?:-|allowbreak|slash|linebreak|newline)(?![A-Za-z])", " ", t)
    t = re.sub(r"\\(?:&|_|%|#|\$)", lambda m: m.group(0)[1], t)
    t = re.sub(r"\\[A-Za-z]+\*?", " ", t)
    t = re.sub(r"[{}\\~]", " ", t)
    return t


def _words(cell):
    for w in re.split(r"[\s\-\u2013\u2014]+", _clean_cell(cell)):
        w = w.strip(".,;:()[]?!'\"")
        if w:
            yield w


def _check_tables(src, path, out):
    for m in re.finditer(r"\\begin\{(tabularx|tabular|xltabular|longtable)\*?\}", src):
        env, i = m.group(1), m.end()
        if env in ("tabularx", "xltabular"):
            while i < len(src) and src[i].isspace():
                i += 1
            if i < len(src) and src[i] == "{":
                i = _group(src, i)
        while i < len(src) and (src[i].isspace() or src[i] == "["):
            i = src.index("]", i) + 1 if src[i] == "[" else i + 1
        if i >= len(src) or src[i] != "{":
            continue
        j = _group(src, i)
        cols = parse_spec(src[i + 1:j - 1])
        if not any(c is not None for c in cols):
            continue
        end = re.compile(r"\\end\{" + env + r"\*?\}").search(src, j)
        body_end = end.start() if end else len(src)
        ctx = src[max(0, m.start() - 400):body_end]
        sizes = re.findall(r"\\(scriptsize|footnotesize|small|normalsize)(?![A-Za-z])", ctx)
        font = FONT_PT[sizes[-1]] if sizes else 11.0
        per_char = EM_PER_CHAR * font
        seps = re.findall(r"\\setlength\s*\{\\tabcolsep\}\s*\{([^}]*)\}", src[:body_end])
        sep = (_to_pt(seps[-1]) if seps else None) or 6.0
        raw = src[i + 1:j - 1].strip()
        edge = [raw.startswith("@{}"), raw.endswith("@{}")]
        pos, col = j, 0
        for sm in re.finditer(r"(?<!\\)&|\\\\", src[j:body_end] + r"\\\\"):
            seg_end = j + sm.start()
            seg = src[pos:seg_end]
            if col < len(cols) and cols[col] is not None and "\\multicolumn" not in seg:
                usable = (cols[col] - 2 * sep + (sep if (col == 0 and edge[0]) else 0)
                          + (sep if (col == len(cols) - 1 and edge[1]) else 0))
                for w in _words(seg):
                    if len(w) >= MIN_WORD and len(w) * per_char > usable * (TOL_PLAIN if w.isalpha() else TOL_JOINED):
                        out.append((path, _line(src, pos + max(0, seg.find(w))), "long_cell_word",
                                    f"'{w}' (~{len(w) * per_char:.0f} pt) cannot break in a column of ~{usable:.0f} pt "
                                    f"on the printed page; add a space or \\-"))
            span = re.search(r"\\multicolumn\s*\{\s*(\d+)\s*\}", seg)
            if sm.group(0) == "&":
                col += int(span.group(1)) if span else 1
            else:
                col = 0
            pos = j + sm.end()


def _check_captions(src, path, out):
    for m in re.finditer(r"\\caption\*?(?:\[[^\]]*\])?\s*\{", src):
        k = m.end() - 1
        e = _group(src, k)
        a = re.search(r"\\answer(?![A-Za-z])", src[k:e])
        if a:
            out.append((path, _line(src, k + a.start()), "answer_in_caption",
                        "\\answer inside \\caption breaks the phone/web/full builds; put it in the running text"))


def _check_banned(src, path, out):
    for m in re.finditer(r"\[H\]", src):
        out.append((path, _line(src, m.start()), "banned", "[H] float placement is forbidden (use [htbp])"))
    for m in re.finditer(r"\\tiny(?![A-Za-z])", src):
        out.append((path, _line(src, m.start()), "banned", "\\tiny is forbidden (smallest size is \\scriptsize)"))


def _check_ids(src, path, out):
    plain = re.sub(r"\$\$.*?\$\$|\$[^$\n]*\$", lambda m: " " * len(m.group(0)), src, flags=re.S)
    for m in re.finditer(r"\\texttt\{[A-Za-z0-9]+\\_[^{}]*\}|\bconv\\_", plain):
        out.append((path, _line(src, m.start()), "printed_id",
                    "raw convention-style id in running text (internal_leaks gate will fail if printed)"))


def lint_files(paths):
    """Lint .tex files. Returns [(path, line, code, msg)] sorted by path and line."""
    out, defs = [], {}
    for p in paths:
        p = Path(p)
        try:
            src = _mask_comments(p.read_text("utf-8", errors="replace"))
        except OSError as e:
            out.append((p, 0, "unreadable", str(e)))
            continue
        _check_captions(src, p, out)
        _check_banned(src, p, out)
        _check_tables(src, p, out)
        _check_ids(src, p, out)
        for m in re.finditer(r"\\newcommand\*?\s*\{?\s*(\\[A-Za-z@]+)", src):
            defs.setdefault(m.group(1), []).append((p, _line(src, m.start())))
    for name, locs in defs.items():
        if len({str(q) for q, _ in locs}) > 1:
            first = locs[0][0]
            for q, ln in locs[1:]:
                if q != first:
                    out.append((q, ln, "dup_newcommand",
                                f"{name} already \\newcommand'ed in {first.name}; use \\providecommand"))
    out.sort(key=lambda r: (str(r[0]), r[1]))
    return out


def subject_files(scoped):
    return sorted(list((scoped / "atoms").rglob("*.tex")) + list((scoped / "chapters").glob("*.tex")))


def main(argv=None):
    import argparse
    import workdir
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("subject")
    ap.add_argument("--scope", required=False)
    ap.add_argument("--files", help="comma-separated .tex files (default: all atoms and chapters)")
    a = ap.parse_args(argv)
    subj, _, scoped = workdir.resolve(a.subject, a.scope)
    allf = subject_files(scoped)
    if a.files:
        want = []
        for f in a.files.split(","):
            f = f.strip()
            if f:
                q = Path(f)
                want.append(q if q.is_absolute() else (scoped / f if (scoped / f).exists() else Path.cwd() / f))
        known = {x.resolve() for x in allf}
        res = lint_files(allf + [w for w in want if w.resolve() not in known])
        keep = {w.resolve() for w in want}
        # duplicates are judged across the whole subject, but only reported for the files asked about
        res = [r for r in res if Path(r[0]).resolve() in keep]
    else:
        res = lint_files(allf)
    for p, ln, code, msg in res:
        try:
            rel = Path(p).resolve().relative_to(subj.resolve()).as_posix()
        except ValueError:
            rel = str(p)
        print(f"LINT {rel}:{ln} {code} {msg}" + ("" if code in ERRORS else "  [warning]"))
    errs = sum(1 for r in res if r[2] in ERRORS or r[2] == "unreadable")
    print(f"{errs} error(s), {len(res) - errs} warning(s) in {len(allf)} file(s)")
    print("RESULT " + ("FAIL" if errs else "PASS"))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
