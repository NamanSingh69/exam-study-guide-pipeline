"""verify_pyqs.check_marks: '[alt k of N]' alternative pools (IPA ES2021SP, Spring 2021 online paper, 2026-11-10).

Every question of that paper offers N alternatives of equal marks (qno '<n> [alt k of N]'); the student answers one.
  pool of N equal alternatives        one slot worth one alternative: Q1-Q7 (4 alts x 2) + any 3 of Q8-Q11 (12) = 50
  alternatives with unequal marks     a problem (sub-part missing or extra)
  a pool with fewer than N banked     a problem (an alternative is missing)
  either-or pairs ('Qn OR')           unchanged
No TeX, no files: calls check_marks directly.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import verify_pyqs  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


def pool_paper(q9_marks=12, drop=None):
    qs = []
    for n in range(1, 8):
        for k in range(1, 5):
            qs.append({"id": f"P-{n}v{k}", "qno": f"{n} [alt {k} of 4]", "marks": 2, "compulsory": True})
    for n, alts in ((8, 2), (9, 3), (10, 3), (11, 3)):
        for k in range(1, alts + 1):
            m = q9_marks if (n == 9 and k == 2) else 12
            qs.append({"id": f"P-{n}v{k}", "qno": f"{n} [alt {k} of {alts}]", "marks": m, "compulsory": False})
    if drop:
        qs = [q for q in qs if q["id"] != drop]
    return qs


paper = {"full_marks": 50, "pattern": "Q1-Q7 compulsory, 2 marks each (one alternative of each); any 3 of Q8-Q11"}
probs, summary = verify_pyqs.check_marks("ES2021SP", paper, pool_paper())
check("alt pools: no problems", probs == [], probs)
check("alt pools: 14 compulsory + 3 of 4 x 12 = 50", summary.startswith("14 compulsory + 3 of 4 x 12 = 50"), summary)

probs, _ = verify_pyqs.check_marks("ES2021SP", paper, pool_paper(q9_marks=10))
check("alt pools: unequal alternatives are a problem", any("Q9" in p for p in probs), probs)

probs, _ = verify_pyqs.check_marks("ES2021SP", paper, pool_paper(drop="P-10v3"))
check("alt pools: a missing alternative is a problem", any("Q10" in p for p in probs), probs)

orp = {"full_marks": 20, "pattern": "Q1 compulsory 5x1; any 3 of Q2-Q5"}
qs = [{"id": f"M-1{c}", "qno": f"1({c})", "marks": 1, "compulsory": True} for c in "abcde"]
qs += [{"id": f"M-{n}", "qno": f"{n}", "marks": 5, "compulsory": False} for n in range(2, 6)]
qs += [{"id": "M-5OR", "qno": "5 OR", "marks": 5, "compulsory": False}]
probs, summary = verify_pyqs.check_marks("MS2025", orp, qs)
check("either-or pairs unchanged", probs == [] and "either-or pair" in summary, (probs, summary))

# a question printed incomplete on the paper (AI MS2023: Q5 headed [5+5=10], only 5(a) printed): the paper entry
# names the gap explicitly ("printed_gaps"); the slot counts its header marks and the summary says so. Without the
# entry the unequal marks stay a problem.
gq = [{"id": f"G-1{c}", "qno": f"1({c})", "marks": 2, "compulsory": True} for c in "abcde"]
gq += [{"id": f"G-{n}{c}", "qno": f"{n}({c})", "marks": 5, "compulsory": False} for n in (2, 3, 4) for c in "ab"]
gq += [{"id": "G-5a", "qno": "5(a)", "marks": 5, "compulsory": False}]
gp = {"full_marks": 40, "pattern": "Q1 compulsory 5x2; any 3 of Q2-Q5"}
probs, _ = verify_pyqs.check_marks("MS2023", gp, gq)
check("printed gap: without printed_gaps the unequal Q5 is a problem", any("unequal" in p for p in probs), probs)
gp2 = dict(gp, printed_gaps={"5": {"header_marks": 10, "note": "headed [5+5=10]; only 5(a) is printed"}})
probs, summary = verify_pyqs.check_marks("MS2023", gp2, gq)
check("printed gap: with printed_gaps the paper adds up", probs == [] and "10 compulsory + 3 of 4 x 10 = 40" in summary,
      (probs, summary))
check("printed gap: the summary names the gap", "printed gap Q5" in summary, summary)
gp3 = dict(gp, printed_gaps={"5": {"header_marks": 10}})
probs, _ = verify_pyqs.check_marks("MS2023", gp3, gq)
check("printed gap: an entry without a note is a problem", any("note" in p for p in probs), probs)

# "any one of the following approaches" inside a LATER sub-part is that sub-part's own content (AI ES2023 5(b)):
# a choice across sub-parts is stated in the question's first banked part (the stem)
cq = [{"id": f"C-1{c}", "qno": f"1({c})", "marks": 1, "compulsory": True} for c in "abcdefghij"]
for n in range(2, 9):
    cq += [{"id": f"C-{n}a", "qno": f"{n}(a)", "marks": 4, "compulsory": False, "text": "Explain the idea."},
           {"id": f"C-{n}b", "qno": f"{n}(b)", "marks": 4, "compulsory": False,
            "text": ("Explain any one of the following approaches to the problem with an example." if n == 5
                     else "Solve it.")}]
cp = {"full_marks": 50, "pattern": "Q1 compulsory 10x1; any 5 of Q2-Q8"}
probs, summary = verify_pyqs.check_marks("ES2023", cp, cq)
check("later sub-part 'any one of the following' is not a group choice", probs == [], (probs, summary))
# the first sub-part's own numbered list "any one of the following planning problems: 1. .. 2. .. 3. .." (AI ES2026SP 6(a))
dq = [{"id": f"D-1{c}", "qno": f"1({c})", "marks": 1, "compulsory": True} for c in "abcdefghij"]
for n in range(2, 7):
    dq += [{"id": f"D-{n}a", "qno": f"{n}(a)", "marks": 5, "compulsory": False,
            "text": ("Solve any one of the following planning problems: 1. blocks world 2. spare tyre 3. cargo."
                     if n == 6 else "Explain.")},
           {"id": f"D-{n}b", "qno": f"{n}(b)", "marks": 5, "compulsory": False, "text": "Solve."}]
probs, summary = verify_pyqs.check_marks("ES2026SP", {"full_marks": 50, "pattern": "Q1 compulsory 10x1; any 4 of Q2-Q6"}, dq)
check("a sub-part's own digit-numbered list is not a group choice", probs == [], (probs, summary))

# OCR letter/digit look-alikes are not swaps (DOS MS2025B-5a: the paper prints "M5", OCR reads "MS");
# a real digit swap stays a swap (CN "ACK 2052 vs 2051")
T = verify_pyqs.tokenize
def tok(s):
    return T(s)[0]
check("look-alike: M5 vs OCR MS is not a swap", not verify_pyqs.is_swap(tok("M5"), tok("MS")))
check("look-alike: 2052 vs 2051 is still a swap", verify_pyqs.is_swap(tok("2052"), tok("2051")))
check("OCR punctuation only: 23921285 vs OCR 2392128.5 is not a swap", not verify_pyqs.is_swap(tok("23921285"), tok("2392128.5")))
check("look-alike: 15 vs OCR 16 is still a swap", verify_pyqs.is_swap(tok("15"), tok("16")))

# a printed spaced digit string equals its run-together OCR form (AI ES2023 7(b) chromosome "5 4 3 1 6 7 8 2")
check("digit run: '5 4 3 1 6 7 8 2' tokenizes as '54316782'",
      [t.raw for t in T("x1 = 5 4 3 1 6 7 8 2")][-1] == "54316782", [t.raw for t in T("x1 = 5 4 3 1 6 7 8 2")])
check("digit run: a short pair '3 4' is left alone", [t.raw for t in T("between 3 4")][-2:] == ["3", "4"],
      [t.raw for t in T("between 3 4")])

# prose after a long table stays inside the matched window (DMDW ES2023 7(b): 76 garbled table tokens in between)
pre = "Give a brief description of the classifier. The data set is as follows:"
post = "Predict the class label of the second instance. Mention advantage and disadvantage over other techniques."
rows = [["sunny", "working", "go-out", "sunny", "working", "go-out"]] * 6
page = "## [P p1] (OCR)\n" + " ".join(["filler words of another question"] * 30) + "\n" + pre + "\n" + \
       "\n".join("| " + " 1 | ".join(r) + " |" for r in rows) + "\n" + post + "\n" + " ".join(["more filler text"] * 20)
c = verify_pyqs.corpus_tokens(page, marks={4.0}, pages=None)
q = {"id": "P-7b", "text": pre + " [table] " + post, "table": {"header": ["Weather", "Car", "Class", "Weather", "Car", "Class"], "rows": rows}}
met, reasons, _n = verify_pyqs.check_question(q, c, "k-table-test")
check("table in the middle: prose after it is matched", met.get("tok", 0) >= 0.95, (met.get("tok"), reasons))

# receipt rescue: a vision-checked crop's fresh OCR has speck noise between words (AI MS2025SP-4a "me ef", "ce me");
# word order is judged on the matched tokens only in that path, while the corpus check keeps its full window
q = {"id": "R-4a", "text": "Provide the state space representation of the following problems:- (i) 8-Puzzle. (ii) N-Queen.",
     "verified": "vision"}
rt = verify_pyqs.tokenize("4, (a) Provide the state space representation of the 1 following problems: me ef! - | (i) "
                          "8-Puzzle. ce me (ii) N-Queen.", ocr=True)
met, reasons, _n = verify_pyqs.check_question(q, rt, "dbg-rescue", True, rescue=True)
check("receipt rescue: speck noise does not break word order", reasons == [], (met.get("tri"), reasons))
met, reasons, _n = verify_pyqs.check_question(q, rt, "dbg-corpus", True)
check("corpus check keeps its full-window trigram", any("trigram" in r for r in reasons), reasons)

# nested sub-part labels (AI MS2022 2b(i)/2b(ii)/5a(I), MS2023B 3b(i), 5I): all belong to their question
for qno, want in (("2b(i)", "2"), ("2(b)(ii)", "2"), ("5a(I)", "5"), ("5I", "5"), ("3 (b) (i)", "3"),
                  ("1(j)", "1"), ("3(a) [2nd Q3]", "3 [2nd Q3]"), ("1(b) OR", "1 OR"), ("4 [alt 2 of 3]", "4 [alt 2 of 3]")):
    got = verify_pyqs.group_key(qno)
    check(f"group_key {qno!r} -> {want!r}", got == want, got)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
