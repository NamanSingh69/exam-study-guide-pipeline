"""score.py sizes_box: the student-facing 'How big this guide is' box states sizes in plain words (2026-11-11).

Reviewers of ML, DMDW and IPA flagged the box as leaked planner reasoning: it printed the targets' internal "why"
formulas, e.g. "2 + 1 (57 in-scope topics, more than 20?) + 1 (numericals are 48% ..., more than 40%?)" and
"the 12 h plan's 41 ideas plus 0 tier-D wildcard(s)". The formulas stay in important_questions.json for the writer
packs; the printed box says what the student gets. No TeX.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import score  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


out = {"model": {"pyq_window": {"from": 2022, "to": 2026, "source": "default", "why": "the last 5 years"}},
       "targets": {
           "iq_clusters": {"count": 41, "clusters": [], "why": "the 12 h plan's 41 ideas plus 0 tier-D wildcard(s) "
                                                               "(at most 5); tier E ideas get a one-line index entry only"},
           "notes_pages": {"U1": {"title": "Intro", "pages": 8.5, "why": "4 lectures x 1.50 (...) + 1"},
                           "U2": {"title": "Search", "pages": 12.0, "why": "5 lectures x 2.00 (...) + 1"}},
           "cheatsheet_pages": {"pages": 4, "topics": 57, "numerical_share": 0.48,
                                "why": "2 + 1 (57 in-scope topics, more than 20?) + 1 (numericals are 48% of the "
                                       "window's marks, more than 40%?); landscape pages, not counting the night-before sheet"},
           "q1_drill": {"question_ids": ["a", "b", "c"], "clusters": ["C1", "C2"], "count": 33,
                        "why": "the newest in-window 1-mark past question of each one-mark idea (3) plus min(30, 2 x 3 "
                               "one-mark ideas) = 6 predicted items"}}}
text = "\n".join(score.sizes_box(None, out))
for bad in ("?", "tier", "min(30", "2 + 1", "x 2.00", "wildcard"):
    check(f"no planner formula text: {bad!r}", bad not in text, text[:400] if bad in text else "")
check("states the cheatsheet pages", "4 landscape pages" in text, text)
check("states the important-question count", "41" in text, text)
check("states the drill size", "33" in text, text)
check("states the notes pages per unit", "8.5" in text and "12" in text, text)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
