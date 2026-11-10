"""pack.py: one compact context file per writer instead of "read the contract + 6 JSONs + the corpus".

Synthetic subject in tests/_tmp/pack/ (STUDYPREP_ROOT). Checks:
  --writer unit-U1   only U1's topics; each topic's title, visual, P, blueprint notes; the unit's page target
                     with its why; conventions; the writer card; corpus excerpts of exactly the cited pages,
                     each under its [slug pN] tag; a vision transcription replaces the OCR text of its page
  --role pyq         every solve owner that is not reused: Cid, anchor, chapter, and the anchor question's
                     verbatim bank text with its marks; the in-window paper list
  size cap           --max-kb truncates excerpts (never ids) and says so
  CLI                prints one PACK line with the path and size; exit 0; unknown writer exits 2
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "pack"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({str(detail)[:400]})" if detail else ""))
    fails += not ok


def w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=1), encoding="utf-8")


if TMP.exists():
    shutil.rmtree(TMP)
shared = TMP / "TT" / "work"
work = shared / "endsem"
w(shared / "corpus" / "N_Notes.md", "# SOURCE: Notes/notes.pdf\n\n"
  + "".join(f"## [N_Notes p{p}]\nOCR text of page {p} about {'sliding windows' if p < 4 else 'routing'}.\n\n"
            for p in range(1, 8)))
w(shared / "corpus" / "N_Notes__vision_p1-3.md", "## [N_Notes p2]\nVISION transcription of page 2: the window diagram.\n")
w(work / "blueprint.json", {"subject": "Test Subject", "units": [
    {"id": "U1", "title": "Transport", "topics": [
        {"id": "T01", "title": "Sliding window", "visual": "storyboard", "sources": ["N_Notes p1-2"],
         "notes": "Window size rule from p2."},
        {"id": "T02", "title": "Go-Back-N", "visual": "block", "sources": ["N_Notes p3"], "notes": ""}]},
    {"id": "U2", "title": "Network", "topics": [
        {"id": "T03", "title": "Routing", "visual": "table", "sources": ["N_Notes p5, p7"], "notes": "OTHER-UNIT"}]}]})
w(work / "assignments.json", {
    "writers": {"unit-U1": ["T01", "T02"], "unit-U2": ["T03"]},
    "atoms": {"notes/T01": "unit-U1", "notes/T02": "unit-U1", "notes/T03": "unit-U2"},
    "chapters": [{"stem": "30_transport", "kind": "unit", "unit": "U1", "owner": "unit-U1"},
                 {"stem": "31_network", "kind": "unit", "unit": "U2", "owner": "unit-U2"},
                 {"stem": "700_pyq_es2025", "kind": "pyq_full", "paper": "ES2025", "owner": "pyq-1"}],
    "solve_owners": {"C01": {"owner": "pyq-1", "chapter": "700_pyq_es2025", "anchor": "ES2025-1a"},
                     "C02": {"owner": "pyq-1", "chapter": "700_pyq_es2025", "anchor": "ES2025-2b"},
                     "C09": {"owner": "pyq-older-1", "chapter": "62_older_ideas", "anchor": "MS2024-3a",
                             "reused_from_midsem": True}},
    "figures": {"fig:T01-window": "notes/T01", "fig:T03-table": "notes/T03"},
    "reused_solves": ["C09"], "full_papers": ["ES2025"]})
w(work / "important_questions.json", {
    "topics": [{"topic": "T01", "P": 0.8, "P_display": "80%"}, {"topic": "T02", "P": 0.4, "P_display": "40%"},
               {"topic": "T03", "P": 0.2, "P_display": "20%"}],
    "clusters": [{"cluster": "C01", "topic": "T01", "tier": "A"}, {"cluster": "C02", "topic": "T02", "tier": "B"}],
    "targets": {"notes_pages": {"U1": {"title": "Transport", "pages": 6.5, "why": "WHY-U1 4 lectures x 1.3"},
                                "U2": {"title": "Network", "pages": 3, "why": "WHY-U2"}},
                "q1_drill": {"count": 10, "why": "x"}, "cheatsheet_pages": {"count": 3, "why": "y"}}})
w(work / "conventions.json", [{"id": "window_bits", "decision": "CONV-DECISION window <= 2^m - 1 for GBN"}])
w(work / "pyq_bank.json", {"papers": [{"id": "ES2025", "year": 2025}], "questions": [
    {"id": "ES2025-1a", "paper": "ES2025", "qno": "1(a)", "marks": 2, "text": "VERBATIM-1a Define a sliding window.",
     "cluster": "C01"},
    {"id": "ES2025-2b", "paper": "ES2025", "qno": "2(b)", "marks": 5, "text": "VERBATIM-2b Compute GBN throughput.",
     "cluster": "C02"}]})

env = dict(os.environ, STUDYPREP_ROOT=str(TMP), PYTHONIOENCODING="utf-8")


def run(*args):
    r = subprocess.run([sys.executable, str(PIPE / "tools" / "pack.py"), "TT", "--scope", "endsem", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, r.stdout + r.stderr


rc, out = run("--writer", "unit-U1")
p = work / "packs" / "unit-U1.md"
txt = p.read_text("utf-8") if p.exists() else ""
check("notes: exit 0 and PACK line", rc == 0 and "PACK " in out and "unit-U1.md" in out, out)
check("notes: own topics, not the other unit's", "T01" in txt and "T02" in txt and "T03" not in txt
      and "OTHER-UNIT" not in txt, txt[:600])
check("notes: titles, visual, P, blueprint notes", all(s in txt for s in ("Sliding window", "storyboard", "80%",
                                                                           "Window size rule from p2")))
check("notes: unit page target with its why", "6.5" in txt and "WHY-U1" in txt)
check("notes: figures owned", "fig:T01-window" in txt and "fig:T03-table" not in txt)
check("notes: conventions", "CONV-DECISION" in txt)
card = (PIPE / "prompts" / "_writer_card.md")
check("notes: the writer card is embedded", card.exists() and card.read_text("utf-8").strip()[:200] in txt)
check("notes: cited pages under their tags", "[N_Notes p1]" in txt and "[N_Notes p3]" in txt and "[N_Notes p5]" not in txt)
check("notes: vision text replaces OCR for its page", "VISION transcription of page 2" in txt
      and "OCR text of page 2" not in txt)

rc, out = run("--role", "pyq")
p = work / "packs" / "pyq.md"
txt = p.read_text("utf-8") if p.exists() else ""
check("pyq: exit 0", rc == 0, out)
check("pyq: own solves with anchors and chapters", all(s in txt for s in ("C01", "ES2025-1a", "C02", "ES2025-2b",
                                                                           "700_pyq_es2025")))
check("pyq: reused solves left out", "C09" not in txt and "MS2024-3a" not in txt)
check("pyq: verbatim question text and marks", "VERBATIM-1a Define a sliding window." in txt and "[5 marks]" in txt)
check("pyq: in-window full papers", "ES2025" in txt)

w(shared / "corpus" / "N_Notes.md", "# SOURCE\n\n" + "".join(f"## [N_Notes p{p}]\n" + ("long text " * 900) + "\n\n"
                                                           for p in range(1, 8)))
(shared / "corpus" / "N_Notes__vision_p1-3.md").unlink()
rc, out = run("--writer", "unit-U1", "--max-kb", "12")
txt = (work / "packs" / "unit-U1.md").read_text("utf-8")
check("cap: pack stays under the cap", len(txt.encode("utf-8")) <= 13 * 1024, len(txt.encode("utf-8")))
check("cap: ids kept and truncation announced", "T01" in txt and "T02" in txt and "truncated" in txt.lower())

# many topics x many cited pages (SE endsem: 75 topics, 640 pages) must still respect the cap
many = [{"id": f"T{i:02d}", "title": f"Topic {i}", "visual": "block", "sources": [f"N_Notes p1-7"]} for i in range(1, 41)]
bp = json.loads((work / "blueprint.json").read_text("utf-8"))
bp["units"][0]["topics"] = many
w(work / "blueprint.json", bp)
a = json.loads((work / "assignments.json").read_text("utf-8"))
a["writers"]["unit-U1"] = [t["id"] for t in many]
w(work / "assignments.json", a)
rc, out = run("--writer", "unit-U1", "--max-kb", "40")
txt = (work / "packs" / "unit-U1.md").read_text("utf-8")
check("many: cap respected with 40 topics x 7 pages", len(txt.encode("utf-8")) <= 41 * 1024, len(txt.encode("utf-8")))
check("many: every topic id kept", all(f"T{i:02d}" in txt for i in range(1, 41)))
check("many: pages left out are listed by tag", "also cited" in txt.lower(), txt[-400:])

# dedupe: a page cited by two topics is quoted once; a deck's repeated header/footer is quoted at most once
import subprocess as _sp
shared2 = TMP / "T2" / "work"
work2 = shared2 / "endsem"
w(shared2 / "corpus" / "D_Deck.md", "# SOURCE\n\n" + "".join(
    f"## [D_Deck p{p}]\nACME UNIVERSITY HEADER\nbody line unique-{p}   with  spaces\n" + f"filler{p} " * 400 + "\n\n\n\n\nlecture footer slide\n\n"
    for p in range(1, 7)))
w(work2 / "blueprint.json", {"units": [{"id": "U1", "title": "X", "topics": [
    {"id": "T01", "title": "Alpha", "visual": "block", "sources": ["D_Deck p1-2"]},
    {"id": "T02", "title": "Beta", "visual": "block", "sources": ["D_Deck p2-3"]}]}]})
w(work2 / "assignments.json", {"writers": {"w1": ["T01", "T02"]}, "atoms": {}, "chapters": []})
w(work2 / "important_questions.json", {})


def run2(*args):
    return _sp.run([sys.executable, str(PIPE / "tools" / "pack.py"), "T2", "--scope", "endsem", "--writer", "w1", *args],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", env=env).returncode


run2()
t2 = (work2 / "packs" / "w1.md").read_text("utf-8")
check("dedupe: shared page quoted once with both topic ids", t2.count("## [D_Deck p2]") == 1
      and "(for T01, T02)" in t2, t2[-900:])
check("dedupe: every cited page tag present", all(f"[D_Deck p{n}]" in t2 for n in (1, 2, 3)))
check("dedupe: repeated header quoted at most once, flagged", t2.count("ACME UNIVERSITY HEADER") == 1
      and "repeated header" in t2.lower(), t2.count("ACME UNIVERSITY HEADER"))
check("dedupe: unique body kept, whitespace collapsed", "unique-1 with spaces" in t2
      and "\n\n\n" not in t2.split("## Cited pages")[-1])
rc3 = run2("--max-kb", "9")
t3 = (work2 / "packs" / "w1.md").read_text("utf-8")
check("dedupe: cap still holds, ids kept", rc3 == 0 and len(t3.encode("utf-8")) <= 9.5 * 1024 and "T01" in t3 and "T02" in t3,
      len(t3.encode("utf-8")))

rc, out = run("--writer", "unit-U9")
check("unknown writer: exit 2", rc == 2, out)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
