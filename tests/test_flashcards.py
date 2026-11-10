"""Regression tests for tools/flashcards.py (\\flashcard -> Anki CSV + web self-test page).

  py _pipeline/tests/test_flashcards.py

The CN trial has no \\flashcard yet, so this builds a fixture subject FC in tests/_tmp/flashcards/:
cards in a chapter (topic from the enclosing \\label{sec:..}), in atoms/notes/T02.tex (topic from the
file name, and \\input by the chapter: must not be counted twice) and in atoms/solve/C05.tex (topic via
the bank's cluster). Fronts/backs hold nested braces, maths, a semicolon, quotes and a newline.
A second fixture has a malformed card and must BLOCK (exit 1).
"""
import csv, io, json, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "flashcards"
TOOL = PIPE / "tools" / "flashcards.py"
fails = 0


def ok(cond, name, extra=""):
    global fails
    if cond:
        print(f"OK {name}")
    else:
        fails += 1
        print(f"FAIL {name} {extra}")


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def run(subject, scope="midsem"):
    env = dict(os.environ, STUDYPREP_ROOT=str(TMP))
    r = subprocess.run([sys.executable, str(TOOL), subject, "--scope", scope], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=300)
    return r.returncode, r.stdout + r.stderr


shutil.rmtree(TMP, ignore_errors=True)
w = TMP / "FC" / "work" / "midsem"
write(w / "blueprint.json", json.dumps({"subject": "Flash Course", "code": "FC 1", "units": [
    {"id": "U1", "title": "One", "in_scope": True, "chapter": "30_one",
     "topics": [{"id": "T01", "title": "First"}, {"id": "T02", "title": "Second"}, {"id": "T03", "title": "Third"}]}]}))
write(w / "pyq_bank.json", json.dumps({"papers": [], "questions": [],
                                       "clusters": [{"id": "C05", "topic": "T03", "label": "x"}]}))
write(w / "chapters" / "30_one.tex", r"""\chapter{One}
\section{First}\label{sec:T01}
Text. \flashcard{What is $a^{2}$ for $a=3$?}{It is \textbf{9}; {nested {braces}} stay.}
% \flashcard{commented}{out: never collected}
\flashcard
  {Define ``ARQ''}
  {Automatic Repeat
   reQuest: resend on timeout.}
\input{atoms/notes/T02}
""")
write(w / "atoms" / "notes" / "T02.tex", r"""\section{Second}\label{sec:T02}
\flashcard{Window limit in GBN}{$W\le 2^m-1$}
""")
write(w / "atoms" / "solve" / "C05.tex", r"""\begin{solvedidea}{C05}{x}
\flashcard{Loss count rule}{$T-\lfloor T/k\rfloor \ge N$}
\end{solvedidea}
""")
code, out = run("FC")
ok(code == 0 and "RESULT PASS (4 cards)" in out, "flashcards.py collects 4 cards and passes", out[-600:])
lines = (w / "flashcards.csv").read_text(encoding="utf-8").splitlines()
ok(lines[:2] == ["#separator:semicolon", "#html:true"], "Anki header lines", str(lines[:4]))
rows = list(csv.reader(io.StringIO("\n".join(l for l in lines if not l.startswith("#"))), delimiter=";"))
ok(len(rows) == 4 and all(len(r) == 3 for r in rows), "4 rows of front;back;tags", str(rows))
if len(rows) == 4:
    f0, b0, t0 = rows[0]
    ok(r"\(a^{2}\)" in f0 and r"\(a=3\)" in f0, "maths exported as \\( .. \\)", f0)
    ok("<strong>9</strong>" in b0 and "nested braces" in b0 and ";" in b0, "balanced braces, HTML, semicolon kept", b0)
    ok(t0 == "FC midsem T01", "tags: subject scope topic (from \\label{sec:..})", t0)
    ok(rows[1][0] == "Define “ARQ”" and "\n" not in rows[1][1] and rows[1][1].startswith("Automatic Repeat reQuest"),
       "multi-line card flattened, TeX quotes -> typographic", str(rows[1]))
    ok(rows[2][2] == "FC midsem T02" and r"\(W\le 2^m-1\)" in rows[2][1], "atom card tagged with the atom's topic", str(rows[2]))
    ok(rows[3][2] == "FC midsem T03", "solve-atom card tagged via its cluster's topic", str(rows[3]))
ok(not any("commented" in r[0] for r in rows), "commented-out cards are ignored")
ok(re.search(r"T01: 2\s+T02: 1\s+T03: 1", out) is not None, "per-topic counts printed", out)
h = (w / "web" / "flashcards.html").read_text(encoding="utf-8")
ok("4 cards" in h and '<script type="application/json" id="cards">' in h and "assets/site.js" in h,
   "flashcards.html self-test page written")
ok((w / "web" / "assets" / "site.css").exists(), "web assets present next to flashcards.html")
data = json.loads(re.search(r'id="cards">(.*?)</script>', h, re.S).group(1))
ok(len(data) == 4 and '<span class="m">' in data[0]["f"], "page cards carry KaTeX spans")

# Real build order (orchestrator Phase E): flashcards.py creates web/, then web.py must still be able to
# rebuild it. Found on real CN 2026-11-06: web.py exit 2 "refusing to wipe ... (no .sgweb)".
WEB = PIPE / "tools" / "web.py"
env = dict(os.environ, STUDYPREP_ROOT=str(TMP))
r = subprocess.run([sys.executable, str(WEB), "FC", "--scope", "midsem", "--no-render"], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", env=env, timeout=600)
ok(r.returncode == 0, "web.py runs after flashcards.py created web/ (marker written)",
   (r.stdout + r.stderr)[-400:])
# a foreign folder that flashcards.py did NOT create stays protected
foreign = TMP / "FC" / "work" / "midsem" / "foreign_out"
write(foreign / "keep.txt", "user file")
r = subprocess.run([sys.executable, str(TOOL), "FC", "--scope", "midsem", "--out-html", str(foreign)],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=300)
ok(not (foreign / ".sgweb").exists() and (foreign / "keep.txt").exists(),
   "flashcards.py never marks a pre-existing non-web folder as wipeable")

# malformed card -> BLOCKED
w2 = TMP / "BAD" / "work" / "midsem"
write(w2 / "blueprint.json", json.dumps({"subject": "Bad", "units": []}))
write(w2 / "chapters" / "30_bad.tex", "\\chapter{Bad}\n\\flashcard{front only, never closed\n")
code, out = run("BAD")
ok(code == 1 and "RESULT BLOCKED" in out, "a malformed \\flashcard blocks (exit 1)", out[-300:])
code, out = run("FC", scope="")
ok(code == 2, "--scope is required (exit 2)")

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
