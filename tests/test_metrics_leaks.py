"""metrics.py: internal_leaks (hard gate) and answers_vs_checks (tracked), on synthetic data (no TeX).

internal_leaks     convention ids that contain an underscore (conventions.json) printed in the guide PDF text,
                   e.g. "(convention ack_number)" (CN, SE, DAA endsem 2026-11-10); plain-word ids such as
                   "fragmentation" are ordinary text and never count; a hyphenated line break inside an id counts
answers_vs_checks  a checks/<qid>.py whose printed number appears in none of the \\answer{} boxes printed under
                   \\label{q:<qid>} (the CN "ACK 2052 vs 2051" class of bug); a question whose answer is elsewhere
                   (no \\answer under its label) is not counted; numbers compare with a small tolerance
"""
import json, shutil, sys
from pathlib import Path

import pymupdf as fitz

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
sys.path.insert(0, str(PIPE / "tools"))
TMP = HERE / "_tmp" / "metrics_leaks"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import metrics  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
work = TMP / "TT" / "work" / "endsem"
(work / "build" / "guide").mkdir(parents=True)
(work / "conventions.json").write_text(json.dumps([{"id": "ack_number", "decision": "x"},
                                                   {"id": "fragmentation", "decision": "y"},
                                                   {"id": "crc_division_rule", "decision": "z"}]), "utf-8")
doc = fitz.open()
p1 = doc.new_page()
p1.insert_text((72, 100), "Acknowledgment number = next byte expected (convention ack_number).", fontsize=10)
p1.insert_text((72, 120), "IP fragmentation splits a datagram.", fontsize=10)
p2 = doc.new_page()
p2.insert_text((72, 100), "Clean page about routing.", fontsize=10)
p3 = doc.new_page()
p3.insert_text((72, 100), "Divide as in convention crc_divi-", fontsize=10)
p3.insert_text((72, 112), "sion_rule and keep the remainder.", fontsize=10)
doc.save(work / "build" / "guide" / "guide.pdf")

leaks = metrics.internal_leaks(work)
check("leaks: the underscore id on p1 is found", any(l.startswith("p1 ") and "ack_number" in l for l in leaks), leaks)
check("leaks: a plain-word id is not a leak", not any("fragmentation" in l for l in leaks), leaks)
check("leaks: a hyphen-broken id is found", any(l.startswith("p3 ") and "crc_division_rule" in l for l in leaks), leaks)
check("leaks: exactly those two", len(leaks) == 2, leaks)
check("leaks: hard gate", "internal_leaks" in metrics.HARD_GATES)
(work / "build" / "guide" / "guide.pdf").unlink()
check("leaks: no PDF -> None (not measured)", metrics.internal_leaks(work) is None)

# answers vs checks
(work / "chapters").mkdir()
(work / "atoms" / "solve").mkdir(parents=True)
(work / "chapters" / "700_pyq_ms2022.tex").write_text(
    "\\begin{question}{2022 Q3(b)}{5}\nACK number?\n\\end{question}\\label{q:MS2022-3b}\n"
    "\\begin{solution}The ACK is \\answer{2052}.\\end{solution}\n"
    "\\begin{question}{2022 Q4(a)}{2}\nUtilisation?\n\\end{question}\\label{q:MS2022-4a}\n"
    "\\begin{solution}$U=\\answer{0.0476}$, i.e. 4.76\\%.\\end{solution}\n"
    "\\begin{question}{2022 Q5(a)}{2}\nWindow?\n\\end{question}\\label{q:MS2022-5a}\n\\seesolved{C07}\n", "utf-8")
outs = {"MS2022-3b": "ack = 2051\n", "MS2022-4a": "U = 0.047619\n", "MS2022-5a": "7\n", "C07": "7\n"}
bad = metrics.answers_vs_checks(work, outs)
check("answers: 2052 printed vs check 2051 is flagged", any("MS2022-3b" in b and "2051" in b for b in bad), bad)
check("answers: 0.0476 vs 0.047619 agrees within tolerance", not any("MS2022-4a" in b for b in bad), bad)
check("answers: no \\answer under the label -> not counted", not any("MS2022-5a" in b for b in bad), bad)
check("answers: tracked, not a hard gate", "answers_vs_checks" not in metrics.HARD_GATES)

# real CN shapes (2026-11-10): multi-line check output, thousands separators, LaTeX thin spaces
(work / "chapters" / "701_pyq_es2022.tex").write_text(
    "\\begin{question}{2022 Q1(e)}{1}\nRTTs?\n\\end{question}\\label{q:ES2022-1e}\n"
    "\\begin{solution}Non-persistent: \\answer{10 RTT}.\\end{solution}\n"
    "\\begin{question}{2022 Q1(g)}{1}\nWindow?\n\\end{question}\\label{q:ES2022-1g}\n"
    "\\begin{solution}\\answer{75,000 bytes}\\end{solution}\n"
    "\\begin{question}{2023 Q2(a)}{2}\nCodeword?\n\\end{question}\\label{q:ES2023-2a}\n"
    "\\begin{solution}\\answer{1001\\,1100\\,101}\\end{solution}\n", "utf-8")
outs = {"ES2022-1e": "non-persistent = 10 RTT\npersistent with pipelining = 2 + 1 = 3 RTT\n",
        "ES2022-1g": "window = 2000000 x 0.3 = 600,000 bits = 75,000 B\n",
        "ES2023-2a": "corrected codeword = 10011100101\n"}
bad = metrics.answers_vs_checks(work, outs)
check("answers: the match may be on any output line", not any("ES2022-1e" in b for b in bad), bad)
check("answers: thousands separators", not any("ES2022-1g" in b for b in bad), bad)
check("answers: LaTeX thin spaces inside a number", not any("ES2023-2a" in b for b in bad), bad)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
