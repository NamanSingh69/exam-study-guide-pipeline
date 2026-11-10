"""assign.py: assignments.json from blueprint + bank + important_questions (00_orchestrator.md Phase C), lean writers.

Synthetic subject in tests/_tmp/assign/ (STUDYPREP_ROOT), no TeX:
  full papers        the 3 newest in-window ENDSEM papers (autumn after spring in a year), newest first; 700_ = newest
  older papers       the other in-window papers (endsem + midsem), newest first, continuing the 7NN numbering
  out of window      a 2019 paper gets no chapter and owns no solve
  solve owners       rule 1 newest full-paper question -> pyq-full; rule 2 older-only -> its older writer, chapter
                     62_older_ideas; rule 3 iq cluster with no in-window question -> pyq-full, chapter 60, anchor null;
                     rule 4 anything else -> no solve
  writers            notes-A / notes-B cover every in-scope topic once, contiguous units; out-of-scope units excluded
  figures            figure_plan owners, "atoms/" stripped
  kept keys          papers / transcribe / multi_set_papers already in assignments.json survive
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "assign"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({str(detail)[:400]})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
w = TMP / "TT" / "work" / "endsem"
w.mkdir(parents=True)
units = [{"id": f"U{u}", "title": f"Unit {u}", "in_scope": u <= 4, "chapter": f"3{u - 1}_unit{u}" if u <= 4 else "",
          "topics": [{"id": f"T{(u - 1) * 7 + k:02d}", "title": "t"} for k in range(1, 8)]} for u in range(1, 6)]
bp = {"units": units, "pyq_window": {"from": 2021, "to": 2025},
      "figure_plan": [{"fig": "fig:T02-x", "owner": "atoms/notes/T02", "used_by": ["T03"]}]}
papers = [  # id, year, session, exam
    ("ES2025", 2025, "autumn", "endsem"), ("ES2025SP", 2025, "spring", "endsem"), ("ES2024", 2024, "autumn", "endsem"),
    ("ES2023", 2023, "autumn", "endsem"), ("MS2025", 2025, "autumn", "midsem"), ("ES2019", 2019, "autumn", "endsem")]
bank = {"papers": [{"id": p, "year": y, "session": s, "exam": e, "weight": 1} for p, y, s, e in papers],
        "questions": [
            {"id": "ES2025-1a", "paper": "ES2025", "qno": "1(a)", "cluster": "C01", "topic": "T01", "in_scope": True},
            {"id": "ES2024-2a", "paper": "ES2024", "qno": "2(a)", "cluster": "C01", "topic": "T01", "in_scope": True},
            {"id": "ES2023-3a", "paper": "ES2023", "qno": "3(a)", "cluster": "C02", "topic": "T04", "in_scope": True},
            {"id": "MS2025-2a", "paper": "MS2025", "qno": "2(a)", "cluster": "C02", "topic": "T04", "in_scope": True},
            {"id": "ES2019-4a", "paper": "ES2019", "qno": "4(a)", "cluster": "C03", "topic": "T07", "in_scope": True},
            {"id": "ES2019-5a", "paper": "ES2019", "qno": "5(a)", "cluster": "C04", "topic": "T08", "in_scope": True}],
        "clusters": [{"id": f"C0{i}"} for i in range(1, 5)]}
iq = {"targets": {"iq_clusters": {"clusters": ["C01", "C03"]}}, "clusters": []}
(w / "blueprint.json").write_text(json.dumps(bp), "utf-8")
(w / "pyq_bank.json").write_text(json.dumps(bank), "utf-8")
(w / "important_questions.json").write_text(json.dumps(iq), "utf-8")
(w / "assignments.json").write_text(json.dumps({"papers": {"slug_x": "ES2025"}, "transcribe": [{"agent": "tx1"}],
                                                "multi_set_papers": {"s": {}}}), "utf-8")
env = dict(os.environ, STUDYPREP_ROOT=str(TMP), PYTHONIOENCODING="utf-8")
r = subprocess.run([sys.executable, str(PIPE / "tools" / "assign.py"), "TT", "--scope", "endsem"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
check("assign: exit 0", r.returncode == 0, r.stdout + r.stderr)
a = json.loads((w / "assignments.json").read_text("utf-8")) if r.returncode == 0 else {}
check("full papers: 3 newest in-window endsems, autumn after spring", a.get("full_papers") == ["ES2025", "ES2025SP", "ES2024"],
      a.get("full_papers"))
ch = {c["stem"]: c for c in a.get("chapters", [])}
check("700_ is the newest full paper", ch.get("700_pyq_es2025", {}).get("kind") == "pyq_full", list(ch))
check("older papers continue the numbering, newest first",
      ch.get("703_pyq_ms2025", {}).get("kind") == "pyq_older" and ch.get("704_pyq_es2023", {}).get("kind") == "pyq_older",
      list(ch))
check("out-of-window paper: no chapter", not any("es2019" in s for s in ch), list(ch))
so = a.get("solve_owners", {})
check("rule 1: C01 anchored at the newest full-paper question, owner pyq-full",
      so.get("C01") == {"owner": "pyq-full", "chapter": "700_pyq_es2025", "anchor": "ES2025-1a"}, so.get("C01"))
check("rule 2: C02 older-only -> older writer, 62_older_ideas, newest anchor",
      so.get("C02", {}).get("chapter") == "62_older_ideas" and so["C02"].get("anchor") == "MS2025-2a"
      and so["C02"].get("owner", "").startswith("pyq-older"), so.get("C02"))
check("rule 3: C03 (iq, only out-of-window) -> pyq-full, chapter 60, anchor null",
      so.get("C03") == {"owner": "pyq-full", "chapter": "60_important_questions", "anchor": None}, so.get("C03"))
check("rule 4: C04 gets no solve", "C04" not in so, so.get("C04"))
wr = a.get("writers", {})
alltopics = [t for ts in wr.values() for t in ts]
check("writers: notes-A and notes-B cover the 28 in-scope topics once (over 24 topics -> two writers)",
      set(wr) == {"notes-A", "notes-B"} and sorted(alltopics) == [f"T{i:02d}" for i in range(1, 29)], wr)
check("atoms owned by their notes writer", a.get("atoms", {}).get("notes/T01") in ("notes-A", "notes-B"), a.get("atoms"))
check("unit chapters owned by the writer of their topics",
      ch.get("30_unit1", {}).get("owner") == a.get("atoms", {}).get("notes/T01"), ch.get("30_unit1"))
check("figures: owner without atoms/", a.get("figures") == {"fig:T02-x": "notes/T02"}, a.get("figures"))
check("kept keys survive", a.get("papers") == {"slug_x": "ES2025"} and a.get("multi_set_papers") == {"s": {}}, a.get("papers"))
check("one_pdf true", a.get("one_pdf") is True)
check("fixed chapters present", all(s in ch for s in ("60_important_questions", "62_older_ideas", "65_q1_drill",
                                                      "80_mock_paper", "cheatsheet")), list(ch))

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
