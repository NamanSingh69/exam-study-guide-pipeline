"""pairs.py: blind X/Y pairs by label between a previous snapshot and the current chapters/atoms.

Fixture (tests/_tmp/pairs/, STUDYPREP_ROOT): self-contained chapters written below, in the shapes the real
CN chapters use (a \\section with its label on the same line; a question environment followed by its q: label,
solution, \\receipt and \\input{atoms/solve/..}; \\subsection*{..}\\phantomsection\\label{iq:..} and the older
\\subsection{..}\\label{iq:..}). A copy as prev/ has 8 units carrying a PREVMARK line; in the current version one
section moved into atoms/notes/. Tiers in a synthetic important_questions.json decide which surplus units are
left out. (The live CN chapters are regenerated and renamed between rounds, so the test does not copy them;
a final read-only smoke check runs pairs' extraction over them.)
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
REAL = PIPE.parent / "CN" / "work" / "midsem"
TMP = HERE / "_tmp" / "pairs"
TOOL = str(PIPE / "tools" / "pairs.py")
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
W = TMP / "CN" / "work" / "midsem"
(W / "chapters").mkdir(parents=True)


def section(tid, title, body):
    return (f"\\section{{{title}}}\\label{{sec:{tid}}}\n\\topicbadge{{{tid}}} \\asked{{MS2024 Q1}}\n\n{body}\n"
            f"\\begin{{formulabox}}{title}: the one formula.\\end{{formulabox}}\n"
            f"\\flashcard{{{title}?}}{{Answer for {tid}.}}\n\n% {'=' * 60}\n")


def pyq(qid, label, body):
    return (f"% {'-' * 64} {label}\n\\needspace{{8\\baselineskip}}\n"
            f"\\begin{{question}}{{2024 Midsem Q{label}}}{{1}}[\\clusterbadge{{C25}}]\n{body}\n\\end{{question}}\n"
            f"\\label{{q:{qid}}}\n\\receipt{{{qid}}}\n\\begin{{solution}}\nWorked answer for {qid}.\n\\end{{solution}}\n"
            f"\\input{{atoms/solve/C25}}\n\\begin{{examtip}}Tip for {qid}.\\end{{examtip}}\n\n")


(W / "chapters" / "32_transport_layer.tex").write_text(
    "\\chapter{Transport layer}\n\n"
    + section("T14", "Stop-and-wait protocol", "Sender waits for an ACK.")
    + section("T15", "Go-Back-N protocol", "Window of size $2^m-1$.")
    + section("T16", "Selective-Repeat protocol", "Window of size $2^{m-1}$.")
    + section("T17", "UDP", "Connectionless, 8-byte header.")
    + section("T19", "TCP segment format", "20 to 60 bytes.")
    + "\\section{Windows in TCP}\\label{sec:T22}\nrwnd and cwnd.\n", "utf-8")
(W / "chapters" / "702_pyq_ms2024.tex").write_text(
    "\\chapter{2024 Midsem paper: solutions}\n\\section{Question 1 (compulsory, 1 mark each)}\n\n"
    + pyq("MS2024-1b", "1(b)", "Decode the UDP header 0045 DF00 0058 0000.")
    + pyq("MS2024-1c", "1(c)", "In Stop and wait protocol every 4th packet is lost ...")
    + pyq("MS2024-1d", "1(d)", "Write the HTTP request ...")
    + "% " + "=" * 64 + "\n\\section{Question 5}\n\n"
    + pyq("MS2024-5a", "5(a)", "The initial sequence number is 2171 ...")
    + pyq("MS2024-5b", "5(b)", "Draw the TCP state transition diagram."), "utf-8")
(W / "chapters" / "60_important_questions.tex").write_text(
    "\\chapter{Important questions}\n\\section{Tier A}\n"
    "\\subsection*{Go-Back-N: count transmissions when every $k$-th packet is lost}\\phantomsection\\label{iq:C25}\n"
    "\\clusterbadge{C25}\\par\nFresh variant and answer plan.\n\n"
    "\\subsection{DNS names and records: FQDN vs PQDN}\\label{iq:C17}\n\\clusterbadge{C17}\\par\nFQDN ends at the root.\n\n"
    "\\subsection*{Delay types}\\phantomsection\\label{iq:C01}\n\\clusterbadge{C01}\\par\nd = L/R + m/s.\n", "utf-8")
(W / "pyq_bank.json").write_text(json.dumps({"papers": [{"id": "MS2024"}], "questions": [
    {"id": f"MS2024-{x}", "paper": "MS2024", "cluster": c} for x, c in
    (("1b", "C28"), ("1c", "C24"), ("1d", "C13"), ("5a", "C29"), ("5b", "C34"))]}), "utf-8")
(W / "important_questions.json").write_text(json.dumps({
    "clusters": [{"cluster": "C25", "tier": "A"}, {"cluster": "C01", "tier": "D"}],
    "topics": [{"topic": "T14", "tier": "A"}, {"topic": "T15", "tier": "B"}, {"topic": "T17", "tier": "A"},
               {"topic": "T19", "tier": "E"}]}), "utf-8")
PREV = W / "prev" / "2026-11-01"
shutil.copytree(W / "chapters", PREV / "chapters")
CHANGED = ["sec:T14", "sec:T15", "sec:T17", "sec:T19", "q:MS2024-1c", "q:MS2024-5b", "iq:C25", "iq:C01"]
for f in (PREV / "chapters").glob("*.tex"):
    t = f.read_text("utf-8")
    for lab in CHANGED:
        t = t.replace("\\label{%s}" % lab, "\\label{%s}\nPREVMARK %s" % (lab, lab))
    f.write_text(t, "utf-8")
# current: sec:T15 moves from the chapter into an atom
ch = (W / "chapters" / "32_transport_layer.tex").read_text("utf-8")
a, b = ch.index("\\section{Go-Back-N protocol}"), ch.index("\\section{Selective-Repeat")
assert a < b
(W / "atoms" / "notes").mkdir(parents=True)
(W / "atoms" / "notes" / "T15.tex").write_text(ch[a:b], "utf-8")
(W / "chapters" / "32_transport_layer.tex").write_text(ch[:a] + "\\input{atoms/notes/T15}\n\n" + ch[b:], "utf-8")
env = dict(os.environ, STUDYPREP_ROOT=str(TMP))


def run(*args, scope=True):
    cmd = [sys.executable, TOOL, "CN"] + (["--scope", "midsem"] if scope else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


OUT = W / "reviews" / "pairs" / "pairs.json"
KEY = W / "reviews" / "_keys" / "pairs_r4.json"
r = run("--prev", str(PREV), "--n", "6", "--seed", "3", "--round", "4")
check("runs", r.returncode == 0, r.stdout.strip().splitlines()[-1] if r.stdout else r.stderr[-300:])
out = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {"pairs": []}
key = json.loads(KEY.read_text("utf-8")) if KEY.exists() else {"pairs": {}}
labels = {p["label"] for p in out["pairs"]}
want = {"sec:T14", "sec:T15", "sec:T17", "q:MS2024-1c", "q:MS2024-5b", "iq:C25"}
check("3 sec + 2 q + 1 iq, tiers A/B first, only changed units", labels == want, str(sorted(labels)))
ok_map = True
for p in out["pairs"]:
    mark = f"PREVMARK {p['label']}"
    side = "X" if mark in p["X"] else "Y" if mark in p["Y"] else None
    other = "Y" if side == "X" else "X"
    m = key["pairs"].get(p["pair"], {})
    ok_map &= side is not None and mark not in p[other] and m.get(side) == "prev" and m.get(other) == "new" \
        and m.get("label") == p["label"]
check("key maps X/Y to prev/new correctly", ok_map)
by = {p["label"]: p for p in out["pairs"]}


def both(lab):
    return [by[lab]["X"], by[lab]["Y"]] if lab in by else ["", ""]


check("sec unit = its own section only",
      all(t.startswith("\\section{Stop-and-wait protocol}\\label{sec:T14}") and "\\section{Go-Back-N" not in t
          for t in both("sec:T14")))
check("sec unit found in an atom file (layout change)",
      all(t.startswith("\\section{Go-Back-N protocol}") and "\\section{Selective" not in t for t in both("sec:T15"))
      and key["pairs"].get(by.get("sec:T15", {}).get("pair"), {}).get("new_src", "").startswith("atoms/notes/T15.tex"))
check("q unit = question + solution, not its neighbours",
      all("\\begin{question}{2024 Midsem Q1(c)}" in t and "\\end{solution}" in t and "q:MS2024-1b" not in t
          and "q:MS2024-1d" not in t and "Q1(d)" not in t for t in both("q:MS2024-1c")))
check("iq unit = its own subsection only",
      all(t.startswith("\\subsection*{Go-Back-N") and "\\label{iq:C17}" not in t and "\\label{iq:C01}" not in t
          for t in both("iq:C25")))
check("pair files match the JSON", all(Path(p["x_file"]).read_text("utf-8") == p["X"]
                                        and Path(p["y_file"]).read_text("utf-8") == p["Y"] for p in out["pairs"]))
blob = OUT.read_text("utf-8")
check("reviewer JSON leaks nothing about which side is which",
      "prev_src" not in blob and "2026-11-01" not in blob and '"prev"' not in blob and '"new"' not in blob
      and not list(OUT.parent.glob("*key*")))
r2 = run("--prev", str(PREV), "--n", "6", "--seed", "3", "--round", "4")
check("same seed, same pairs", r2.returncode == 0 and OUT.read_text("utf-8") == blob)
sides = set()
for s in range(1, 9):
    run("--prev", str(PREV), "--n", "6", "--seed", str(s), "--key", str(TMP / f"k{s}.json"))
    sides |= {m["X"] for m in json.loads((TMP / f"k{s}.json").read_text("utf-8"))["pairs"].values()}
check("X is sometimes prev, sometimes new", sides == {"prev", "new"}, str(sides))
r = run("--prev", str(PREV), "--n", "12", "--seed", "1")
n12 = len(json.loads(OUT.read_text("utf-8"))["pairs"])
check("more pairs requested than changed units: all 8 + a warning", r.returncode == 0 and n12 == 8
      and "WARNING" in r.stdout, f"{n12}")
check("default key name without --round", (W / "reviews" / "_keys" / "pairs.json").exists())
same = TMP / "same"
shutil.copytree(W / "chapters", same / "chapters")
shutil.copytree(W / "atoms", same / "atoms")
r = run("--prev", str(same))
check("nothing changed -> exit 1", r.returncode == 1 and "RESULT BLOCKED" in r.stdout, f"rc={r.returncode}")
check("missing --prev dir is a usage error", run("--prev", str(TMP / "nope")).returncode == 2)
check("missing --scope is a usage error", run("--prev", str(PREV), scope=False).returncode == 2)

# read-only smoke check on the live CN chapters/atoms (whatever their current stems): every extracted unit
# carries its own label and none swallows a second unit of the same kind
if (REAL / "chapters").is_dir():
    sys.path.insert(0, str(PIPE / "tools"))
    import pairs as _pairs
    live = _pairs.collect(REAL)
    kinds = {k.split(":", 1)[0] for k in live}
    bad = [k for k, (body, _src) in live.items()
           if "\\label{%s}" % k not in body
           or len([m for m in _pairs.LABEL_RE.finditer(body) if m.group(2) == k.split(":", 1)[0]]) > 1]
    check("live CN chapters: every sec:/q:/iq: unit holds exactly its own label", kinds == {"sec", "q", "iq"} and not bad,
          f"{len(live)} units, kinds {sorted(kinds)}, bad {bad[:5]}")

shutil.rmtree(TMP, ignore_errors=True)
print("OK test_pairs" if not fails else f"FAIL test_pairs: {fails} check(s)")
sys.exit(1 if fails else 0)
