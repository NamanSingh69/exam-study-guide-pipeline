"""Regression tests for tools/score.py (Round 4 planner). Standalone: prints OK lines, exits 0 on pass.

Runs score.py only against copies of the CN midsem inputs in tests/_tmp/score/ (STUDYPREP_ROOT), with
STUDYPREP_MODEL_PARAMS pointed at a temp file, so no real subject folder or the real model_params.json
is touched. Each check targets a Round 4 requirement or a bug listed in REVIEW_2026-11-05.md §2.2.
"""
import datetime, json, os, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
FIX = HERE / "fixtures" / "score_cn3"          # frozen round-3 CN midsem bank (3 papers, C01-C38)
LIVE = PIPE.parent / "CN" / "work" / "midsem"   # live bank: only the invariant smoke test reads it
# one folder per run: parallel run_all invocations (other workstreams) must not share files
TMP = HERE / "_tmp" / f"score_{os.getpid()}"
SCORE = Path(os.environ.get("SCORE_UNDER_TEST") or PIPE / "tools" / "score.py")  # mutation checks
fails = 0

# Minimal stand-in for studyguide.sty: only what score.py's chapters use, per ROUND4_SPEC "LaTeX macros".
STUB_STY = r"""\NeedsTeXFormat{LaTeX2e}\ProvidesPackage{studyguide}[stub]
\RequirePackage[T1]{fontenc}\RequirePackage{lmodern,microtype}
\RequirePackage[a4paper,left=20mm,right=20mm,top=22mm,bottom=22mm]{geometry}\RequirePackage{amsmath,amssymb,booktabs,array,tabularx,makecell}
\RequirePackage{xltabular}\RequirePackage[table]{xcolor}\RequirePackage{enumitem,etoolbox,tikz}\RequirePackage{hyperref}
\definecolor{sgteal}{RGB}{0,128,128}\definecolor{sgamber}{RGB}{217,119,6}\definecolor{sgred}{RGB}{185,28,28}
\definecolor{sgtint}{RGB}{240,244,250}\colorlet{muted}{gray}
\newcolumntype{Y}{>{\raggedright\arraybackslash}X}\newcommand{\zebra}{\rowcolors{2}{sgtint}{white}}
\newcommand{\sgpill}[1]{{\scriptsize\sffamily\bfseries #1}}
\newcommand{\tier}[1]{\sgpill{#1}}\newcommand{\prob}[1]{\sgpill{P #1\%}}
\newcommand{\sgdefbadge}[5]{\csgdef{sgb@#1}{\tier{#2}\,\sgpill{#3/#4}}}
\newcommand{\sgdeftopic}[3]{\csgdef{sgt@#1}{\sgpill{#2/#3}}}
\newcommand{\clusterbadge}[1]{\ifcsdef{sgb@#1}{\csuse{sgb@#1}}{\typeout{SG-BADGE-MISSING:#1}?#1}}
\newcommand{\topicbadge}[1]{\ifcsdef{sgt@#1}{\csuse{sgt@#1}}{\typeout{SG-BADGE-MISSING:#1}?#1}}
\AtBeginDocument{\IfFileExists{badges.tex}{\input{badges.tex}}{}}
"""


def check(cond, name, detail=""):
    global fails
    if cond:
        print(f"OK {name}")
    else:
        fails += 1
        print(f"FAIL {name} {detail}")


def setup(name, scope="midsem", bp_edit=None, bank_edit=None, signal=None):
    root = TMP / name
    if root.exists():
        shutil.rmtree(root)
    w = root / "CN" / "work" / scope
    w.mkdir(parents=True)
    bp = json.loads((FIX / "blueprint.json").read_text("utf-8"))
    bank = json.loads((FIX / "pyq_bank.json").read_text("utf-8"))
    if bp_edit:
        bp_edit(bp)
    if bank_edit:
        bank_edit(bank)
    (w / "blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
    (w / "pyq_bank.json").write_text(json.dumps(bank), encoding="utf-8")
    if signal is not None:
        (w / "class_signal.json").write_text(json.dumps(signal), encoding="utf-8")
    return root, w


def run(root, scope="midsem", params=None, extra=(), windows=None):
    # the live _pipeline/pyq_windows.json is lead-owned data: tests never read it unless they pass their own
    env = dict(os.environ, STUDYPREP_ROOT=str(root),
               STUDYPREP_MODEL_PARAMS=str(params or (root / "no_model_params.json")),
               STUDYPREP_PYQ_WINDOWS=str(windows or (root / "no_pyq_windows.json")))
    r = subprocess.run([sys.executable, str(SCORE), "CN", "--scope", scope, "--n-sim", "1500", *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return r


def iq(w):
    return json.loads((w / "important_questions.json").read_text("utf-8"))


# ------------------------------------------------------------------ 1. the real CN inputs
root, w = setup("base")
r = run(root)
check(r.returncode == 0 and r.stdout.strip().endswith("RESULT PASS"), "runs on CN midsem copy", r.stdout[-800:] + r.stderr[-800:])
d = iq(w)
for k in ("model", "clusters", "topics", "plans", "q1_drill", "must_draw", "skip_safety", "exam_hall", "backtest"):
    check(k in d, f"important_questions.json has key {k}")
P = d["plans"]
s3, s6, s12 = (set(P[h]["clusters"]) for h in ("3h", "6h", "12h"))
check(s3 <= s6 <= s12 and len(s3) < len(s12), "plans are nested 3h <= 6h <= 12h")
check(P["3h"]["minutes"] <= 180 and P["6h"]["minutes"] <= 360 and P["12h"]["minutes"] <= 720, "plans fit their budgets")
check(P["3h"]["expected_marks"] <= P["6h"]["expected_marks"] <= P["12h"]["expected_marks"], "expected marks grow with time")
check(all(0 <= P[h]["p_safe"] <= 1 for h in P) and P["12h"]["p_safe"] >= P["3h"]["p_safe"], "p_safe is a probability and grows")
tiers = {c["cluster"]: c["tier"] for c in d["clusters"]}
check({c for c, t in tiers.items() if t == "A"} == s3, "tier A == 3 h plan")
check({c for c, t in tiers.items() if t == "B"} == s6 - s3, "tier B == added by 6 h")
check({c for c, t in tiers.items() if t == "C"} == s12 - s6, "tier C == added by 12 h")
check(all(not x["asked_weighted"] and not x["plan"] for x in d["clusters"] if x["tier"] == "D"),
      "tier D ideas were never asked and are in no plan")
check(d["model"]["scope"] == "midsem" and d["model"]["p_display"] == "band", "3 papers -> P shown as a band")
pri = sum(t["prior"] for t in d["topics"])
check(abs(pri - 1) < 1e-3, "topic priors are normalised", f"sum={pri}")
check(abs(sum(t["share"] for t in d["topics"]) - 1) < 1e-3, "topic shares sum to 1")
badges = (w / "badges.tex").read_text("utf-8")
nb = len(re.findall(r"\\sgdefbadge\{C\d+\}\{[A-E]\}\{-\}\{(low|med|high)\}\{\d+\.\d\d\}", badges))
check(nb == len([c for c in d["clusters"] if not c["synthetic"]]), "badges.tex: one band-only \\sgdefbadge per cluster", f"{nb}")
check(len(re.findall(r"\\sgdeftopic\{T\d+\}\{-\}\{(low|med|high)\}", badges)) == len(d["topics"]), "badges.tex: one \\sgdeftopic per topic")
snap = w / "plan_snapshots" / f"{datetime.date.today().isoformat()}.json"
check(snap.exists() and json.loads(snap.read_text("utf-8"))["plans"]["6h"]["clusters"] == P["6h"]["clusters"],
      "plan snapshot written for today")
eh = d["exam_hall"]
check(eh["duration_min"] == 90 and abs(eh["min_per_mark"] - 4.0) < 1e-9 and eh["budgets"]["1"]["words"] == 80,
      "exam hall: 4 min per mark, 80 words for 1 mark", json.dumps(eh)[:300])
ss = d["skip_safety"]["U3"]["papers"]["MS2025"]
check(ss["answerable"] == 2 and ss["n"] == 4 and ss["need"] == 3, "skip-safety: skipping Transport leaves 2 of 4 in MS2025", str(ss))
check(d["skip_safety"]["U1"]["safe_papers"] == 3, "skip-safety: skipping Data Comm is safe in all 3 papers")
check("MS2024-1c" in d["q1_drill"]["question_ids"] and len(d["q1_drill"]["clusters"]) > 0, "q1_drill lists 1-mark PYQs and ideas")
check("MS2024-5b" in d["must_draw"]["question_ids"] and "C34" in d["must_draw"]["clusters"], "must_draw finds the TCP state diagram")
check(d["backtest"] is None, "no model_params -> backtest null")
radar = (w / "chapters" / "20_exam_radar.tex").read_text("utf-8")
how = (w / "chapters" / "05_how_to_use.tex").read_text("utf-8")
check("not yet backtested" in how and "not yet backtested" in radar, "backtest line says not yet backtested")
check("xltabular" in radar and r"\pageref{sec:" in radar and r"\pageref{iq:" in radar and r"\clusterbadge{" in radar,
      "radar uses xltabular, sec:/iq: page refs and \\clusterbadge")
check("How these plans are made." in radar, "model paragraph printed in the radar")
check("minutes per mark" in how and "Answer template" in how and "Q1 drill" in how, "how-to has exam-hall plan, templates, Q1 drill")
# plans in syllabus order: topic sec: refs of the 3 h block appear in blueprint order
block = radar.split(r"\subsection*{3 hours}")[1].split(r"\subsection*")[0]
order = [int(x) for x in re.findall(r"pageref\{sec:T(\d+)\}", block)]
check(order == sorted(order) and order, "3 h plan printed in syllabus order", str(order))
r2 = run(root)
check(iq(w)["plans"] == P, "deterministic: same plans on a second run")

# ------------------------------------------------------------------ 1b. wildcard: never asked, strong prior, no plan room
def wildcard(bank):
    for c in bank["clusters"]:
        if c["id"] == "C07":
            c["effort_min"] = 900            # cannot fit even the 12 h plan
    bank["imp_list"].append({"text": "Explain the OSI model", "source": "test", "cluster": "C07"})


root, w = setup("wild", bank_edit=wildcard)
r = run(root)
c07 = [c for c in iq(w)["clusters"] if c["cluster"] == "C07"][0]
check(r.returncode == 0 and c07["tier"] == "D" and c07["plan"] is None, "never-asked seniors'-list idea outside the plans is tier D",
      json.dumps(c07)[:200])

# ------------------------------------------------------------------ 2. scope from the folder, not blueprint.json
root, w = setup("scope", bp_edit=lambda bp: bp.update(scope="Endsem"))
r = run(root)
m = iq(w)["model"]
check(r.returncode == 0 and m["scope"] == "midsem" and abs(m["papers_used"]["MS2025"] - 1.0) < 1e-9 and
      abs(m["papers_used"]["MS2024"] - 0.8) < 1e-9, "scope comes from the folder name", json.dumps(m["papers_used"]))


# ------------------------------------------------------------------ 3. marks only from weighted papers
def add_endsem(bank):
    bank["papers"].append({"id": "ES2025", "year": 2025, "exam": "endsem", "full_marks": 50, "duration": "3 h"})
    bank["questions"].append({"id": "ES2025-2a", "paper": "ES2025", "qno": "2(a)", "marks": 10, "compulsory": False,
                              "text": "Explain QoS flow characteristics.", "topic": "T24", "cluster": "C38",
                              "type": "theory", "in_scope": True})


root, w = setup("weighted", bank_edit=add_endsem)
r = run(root)
d = iq(w)
c38 = [c for c in d["clusters"] if c["cluster"] == "C38"][0]
check(r.returncode == 0 and "ES2025" not in d["model"]["papers_used"] and c38["typical_marks"] != 10 and
      not c38["asked_weighted"], "endsem paper gets no weight and no marks in a midsem scope", json.dumps(c38)[:300])

# ------------------------------------------------------------------ 4. zero papers: honest, no crash
root, w = setup("zero", bank_edit=lambda b: (b.update(no_papers=True, papers=[], questions=[])))
r = run(root)
d = iq(w) if (w / "important_questions.json").exists() else {}
check(r.returncode == 0 and d and d["model"]["pattern_assumed"] and d["model"]["p_display"] == "band",
      "0 papers: runs, pattern assumed, bands only", r.stdout[-600:] + r.stderr[-600:])
if d:
    check("No relevant past paper" in d["model"]["note"] and
          "assumed pattern" in (w / "chapters" / "20_exam_radar.tex").read_text("utf-8"), "0 papers: output says so")
    pri = {t["topic"]: t["prior"] for t in d["topics"]}
    check(all(abs(t["share"] - pri[t["topic"]]) < 1e-3 for t in d["topics"]), "0 papers: shares equal the prior")
    # real SVP endsem (2026-11-06): no papers -> no one-mark clusters -> the drill target was 0 although the
    # (assumed) pattern has a compulsory Q1 of one-mark parts. Predict from the pattern instead.
    n_q1 = sum(1 for _ in range(int((d["exam_hall"] or {}).get("q1_parts") or 0))) if isinstance(d.get("exam_hall"), dict) else 0
    check(len(d["q1_drill"]["clusters"]) > 0, "0 papers: Q1 drill still predicts one-mark ideas from the pattern",
          d["q1_drill"])
    # real SVP review r1 (2026-11-06): paper-mode wording leaked into the zero-paper guide
    rad0 = (w / "chapters" / "20_exam_radar.tex").read_text("utf-8")
    how0 = (w / "chapters" / "05_how_to_use.tex").read_text("utf-8")
    leaks = [s for s in ("past papers in the window", "matching past question", "were asked", "For each past paper",
                         "Topic marks per paper", "of the window's marks", "recency-weighted",
                         "real paper structure") if s in rad0 + how0]
    # this fixture keeps its seniors' list, so naming it is correct; the SVP case (no list) is checked on real data
    check(not leaks, "0 papers: no wording that implies past papers exist", leaks)
    check("assumed pattern" in how0 and "simulated" in how0, "0 papers: plan numbers are labelled as simulated on the assumed pattern")
    nwild = rad0.split(r"\section{Wildcards}")[1].count(r"\pageref{iq:") if r"\section{Wildcards}" in rad0 else 0
    check(nwild <= 5, "radar wildcard list = the at most 5 wildcards the guide covers", nwild)
    # drill spread (SVP: 28 of 30 predicted items were video): every unit with ideas gets at least one item
    units_with = {t["unit"] for t in d["topics"]}
    c2u = {r["cluster"]: r["unit"] for r in d["clusters"]}
    got_units = {c2u.get(c) for c in d["q1_drill"]["clusters"]}
    check(units_with <= got_units, "0 papers: predicted Q1 drill covers every unit", (units_with, got_units))


# ------------------------------------------------------------------ 5. endsem: midsem papers only count for midsem units
def endsem_bp(bp):
    bp["scope"] = "Endsem"
    for u in bp["units"]:
        u["in_scope"] = True


def endsem_bank(with_mid):
    def f(bank):
        if not with_mid:
            bank["papers"], bank["questions"] = [], []
        bank["papers"].append({"id": "ES2025", "year": 2025, "session": "autumn", "exam": "endsem", "full_marks": 50, "duration": "3 h"})
        for i, (tp, cl, mk) in enumerate([("T28", "C28", 5), ("T14", "C23", 5), ("T08", "C11", 5), ("T38", "C28", 5)]):
            bank["questions"].append({"id": f"ES2025-{i + 2}a", "paper": "ES2025", "qno": f"{i + 2}(a)", "marks": mk,
                                      "compulsory": False, "text": "x", "topic": tp, "cluster": cl, "type": "theory",
                                      "in_scope": True})
    return f


def endsem_run(name, with_mid):
    root = TMP / name
    if root.exists():
        shutil.rmtree(root)
    mid = root / "CN" / "work" / "midsem"
    mid.mkdir(parents=True)
    shutil.copy(FIX / "blueprint.json", mid / "blueprint.json")
    end = root / "CN" / "work" / "endsem"
    end.mkdir()
    bp = json.loads((FIX / "blueprint.json").read_text("utf-8"))
    endsem_bp(bp)
    bank = json.loads((FIX / "pyq_bank.json").read_text("utf-8"))
    bank["clusters"] = [c for c in bank["clusters"]]
    endsem_bank(with_mid)(bank)
    (end / "blueprint.json").write_text(json.dumps(bp), encoding="utf-8")
    (end / "pyq_bank.json").write_text(json.dumps(bank), encoding="utf-8")
    r = run(root, "endsem")
    return r, iq(end) if (end / "important_questions.json").exists() else None


r1, e1 = endsem_run("endsem_mid", True)
r0, e0 = endsem_run("endsem_nomid", False)
ok = r1.returncode == 0 and r0.returncode == 0 and e1 and e0
check(ok, "endsem scope runs", (r1.stdout + r1.stderr)[-600:])
if ok:
    check(e1["model"]["papers_full_coverage"] == ["ES2025"] and abs(e1["model"]["papers_used"]["MS2025"] - 0.5) < 1e-9,
          "endsem: midsem papers are partial coverage at half weight", json.dumps(e1["model"]["papers_used"]))
    sh1 = {t["topic"]: t["share"] for t in e1["topics"]}
    sh0 = {t["topic"]: t["share"] for t in e0["topics"]}
    post = [t for t in sh1 if t >= "T25"]
    check(all(abs(sh1[t] - sh0[t]) < 1e-9 for t in post),
          "endsem: post-midsem topic shares do not depend on midsem papers (per-unit denominators)")


# ------------------------------------------------------------------ 5b. paper coverage list, weight 0, (year, session) recency
def cov_bank(bank):
    for p in bank["papers"]:
        p["session"] = "autumn"
        p["coverage"] = ["U1", "U2", "U3"]
    bank["papers"].append({"id": "MS2025S", "year": 2025, "session": "spring", "exam": "midsem", "full_marks": 20,
                           "duration": "1.5 h", "coverage": ["U2", "U3"], "weight": 0.5})
    bank["questions"].append({"id": "MS2025S-2a", "paper": "MS2025S", "qno": "2(a)", "marks": 5, "compulsory": False,
                              "text": "x", "topic": "T10", "cluster": "C18", "type": "theory", "in_scope": True})
    bank["papers"].append({"id": "REC2023", "year": 2023, "exam": "midsem", "full_marks": 20, "weight": 0})
    bank["questions"].append({"id": "REC2023-2a", "paper": "REC2023", "qno": "2(a)", "marks": 5, "compulsory": False,
                              "text": "x", "topic": "T24", "cluster": "C38", "type": "theory", "in_scope": True})


root, w = setup("coverage", bank_edit=cov_bank)
r = run(root)
d = iq(w)
pu = d["model"]["papers_used"]
check(r.returncode == 0 and "REC2023" not in pu and abs(pu["MS2025S"] - 0.5 * 0.8 ** 0.5) < 1e-3 and
      "MS2025S" not in d["model"]["papers_full_coverage"] and abs(pu["MS2025"] - 1.0) < 1e-9,
      "weight 0 = record only; spring sits half a year before autumn; partial coverage is not full", json.dumps(pu))

# ------------------------------------------------------------------ 6. class signal: stress / drop / pattern, never blocks
sig = {"source": "trigger message", "signals": [
    {"text": "teacher stressed QoS", "kind": "stress", "topics": ["T24"], "clusters": []},
    {"text": "selective repeat not coming", "kind": "drop", "topics": ["T16"], "clusters": []},
    {"text": "Q5 will be short notes", "kind": "pattern", "topics": [], "clusters": []},
    {"text": "typo", "kind": "stress", "topics": ["T99"], "clusters": []}]}
root, w = setup("signal", signal=sig)
r = run(root)
d = iq(w)
base = {t["topic"]: t["prior"] for t in json.loads((TMP / "base" / "CN" / "work" / "midsem" / "important_questions.json").read_text("utf-8"))["topics"]}
t24 = [t for t in d["topics"] if t["topic"] == "T24"][0]
t16 = [t for t in d["topics"] if t["topic"] == "T16"][0]
check(r.returncode == 0 and t24["prior"] > 1.5 * base["T24"] and t24["class_signal"], "stress signal boosts T24's prior",
      f"{t24['prior']} vs {base['T24']}")
inplan = {c for p in d["plans"].values() for c in p["clusters"]}
check(t16["prior"] < 1e-4 and t16["share"] == 0 and not ({"C26", "C27"} & inplan) and t16["dropped"],
      "drop signal: prior ~0 and the topic's ideas are in no plan")
radar = (w / "chapters" / "20_exam_radar.tex").read_text("utf-8")
check("Q5 will be short notes" in radar and "Class signal" in radar, "pattern signal printed in the radar")
check("Never asked in a past paper" not in radar, "wildcards are not described as never asked (CN review r1)")
check(any("T99" in x for x in d["model"]["class_signal"]["ignored"]) and "warning" in r.stdout, "unknown class-signal id is reported, not fatal")


# ------------------------------------------------------------------ 6b. source-confidence table from the blueprint
def conf(bp):
    for u in bp["units"]:
        u["source_confidence"] = {"level": "low" if u["id"] == "U1" else "high", "why": f"why-{u['id']}"}
    bp["coverage_gaps"] = [{"topic": "T02", "status": "unfillable", "book": "Forouzan ch. 3"},
                           {"topic": "T03", "status": "unfillable", "book": "Forouzan ch. 4"},
                           {"topic": "T24", "status": "filled"}]


root, w = setup("conf", bp_edit=conf)
r = run(root)
how = (w / "chapters" / "05_how_to_use.tex").read_text("utf-8")
row = [l for l in how.splitlines() if l.replace("\\hspace{0pt}", "").startswith("Data Communications &")]
check(r.returncode == 0 and row and "{low}" in row[0] and "& 2 &" in row[0] and "why-U1" in row[0] and
      "why-U3" in how, "source-confidence table: level, why and the not-from-notes count per unit", str(row))

# ------------------------------------------------------------------ 7. backtest line from model_params.json
root, w = setup("bt")
mp = root / "mp.json"
mp.write_text(json.dumps({"pooled": {"decay": 0.8, "alpha": 4.0, "lect_w": 0.5, "imp_boost": 0.5, "form_alpha": 4.0},
                          "subjects": {"CN/midsem": {"decay": 1.0, "alpha": 4.0, "lect_w": 0.5, "imp_boost": 0.5, "form_alpha": 4.0}},
                          "backtest": {"CN/midsem": {"n_folds": 3, "summary": {
                              "new": {"cover_6h": {"mean": 0.65, "min": 0.4, "max": 0.8}},
                              "lecture": {"cover_6h": {"mean": 0.68, "min": 0.5, "max": 0.8}},
                              "uniform": {"cover_6h": {"mean": 0.57, "min": 0.54, "max": 0.61}}}}}}), encoding="utf-8")
r = run(root, params=mp)
d = iq(w)
how = (w / "chapters" / "05_how_to_use.tex").read_text("utf-8")
check(r.returncode == 0 and "CN/midsem" in d["model"]["params_source"] and d["model"]["decay"] == 1.0,
      "subject-specific tuned parameters are used")
check(d["backtest"]["n_folds"] == 3 and "6\\,h plan covered 65\\%" in how and "indicative" in how,
      "backtest line printed with the 6 h cover", how[:0])

# ------------------------------------------------------------------ 8. the chapters compile with studyguide.sty
pdflatex = shutil.which("pdflatex")
w = TMP / "base" / "CN" / "work" / "midsem"
if not pdflatex:
    print("OK latex compile skipped (no pdflatex)")
else:
    def compile_(stem, body, texinputs, passes=2, opts="", wdir=None):
        global w
        w_saved, w = w, (wdir or w)
        try:
            return _compile(stem, body, texinputs, passes, opts)
        finally:
            w = w_saved

    def overfull(log):
        return max([0.0] + [float(x) for x in re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide", log)])

    def _compile(stem, body, texinputs, passes, opts):
        (w / f"{stem}.tex").write_text("\\documentclass[11pt]{report}\n\\usepackage" + (f"[{opts}]" if opts else "") +
                                       "{studyguide}\n\\begin{document}\n" + body + "\\end{document}\n", encoding="utf-8")
        env = dict(os.environ, TEXINPUTS=f"{texinputs};{w};")
        rc = 0
        for _ in range(passes):
            rr = subprocess.run([pdflatex, "-interaction=nonstopmode", "-halt-on-error", f"{stem}.tex"], cwd=w, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            rc = rc or rr.returncode
        return rc, (w / f"{stem}.log").read_text("utf-8", errors="replace")

    # The build workstream edits studyguide.sty in parallel. If the .sty cannot compile even an empty
    # document, that is its problem, not this chapter's: fall back to the stub (the spec's macros only).
    sty_dir = PIPE / "latex"
    rc0, _ = compile_("_empty", "x\n", sty_dir, passes=1)
    if rc0:
        sty_dir = TMP / "stubsty"
        sty_dir.mkdir(exist_ok=True)
        (sty_dir / "studyguide.sty").write_text(STUB_STY, encoding="utf-8")
        print("NOTE studyguide.sty does not compile an empty document right now; using the stub .sty")
    rc, log = compile_("_t", "\\input{chapters/05_how_to_use.tex}\n\\input{chapters/20_exam_radar.tex}\n", sty_dir)
    errs = [l for l in log.splitlines() if l.startswith("!")]
    check(rc == 0 and not errs, f"05 + 20 compile with {'studyguide.sty' if not rc0 else 'the stub .sty'}", "; ".join(errs[:3]))
    check("SG-BADGE-MISSING" not in log, "every \\clusterbadge/\\topicbadge is defined by badges.tex")
    check("Float too large" not in log and overfull(log) <= 4, "no float-too-large, no overfull box over 4 pt",
          f"max {overfull(log)} pt")

    # 8b. radar + how-to fit any line width: 12 papers, A4 and the [phone] page (105 x 187 mm)
    def many(bank):
        base_p, base_q = bank["papers"], bank["questions"]
        bank["papers"], bank["questions"] = [], []
        for k, y in enumerate(range(2014, 2026)):
            src = base_p[k % 3]
            pid = f"MS{y}"
            bank["papers"].append(dict(src, id=pid, year=y))
            for q in base_q:
                if q["paper"] == src["id"]:
                    bank["questions"].append(dict(q, id=q["id"].replace(src["id"], pid), paper=pid))

    root_m, w_m = setup("many", bank_edit=many,   # explicit window: all 12 papers are meant to count here
                        bp_edit=lambda bp: bp.update(pyq_window={"from": 2014, "to": 2025, "years": 12, "why": "test"}))
    r = run(root_m)
    radar = (w_m / "chapters" / "20_exam_radar.tex").read_text("utf-8")
    check(r.returncode == 0 and r"\thead{older\\(9)}" in radar and iq(w_m)["model"]["p_display"] == "percent",
          "12 papers: latest 3 as columns, 9 older summed; P as percent", r.stdout[-300:])
    body = "\\input{chapters/05_how_to_use.tex}\n\\input{chapters/20_exam_radar.tex}\n"
    if rc0:
        print("OK phone-layout check skipped (studyguide.sty not compilable right now)")
    else:
        for opts, name in (("", "A4"), ("phone", "phone")):
            rc, log = compile_(f"_fit_{name}", body, sty_dir, opts=opts, wdir=w_m)
            errs = [l for l in log.splitlines() if l.startswith("!")]
            check(rc == 0 and not errs and overfull(log) <= 4,
                  f"{name} layout: 05 + 20 with 12 papers compile with no overfull box over 4 pt",
                  f"max {overfull(log)} pt; " + "; ".join(errs[:2]))

# ------------------------------------------------------------------ 10. R4: the PYQ window
root, w = setup("window", bp_edit=lambda bp: bp.update(pyq_window={"from": 2024, "to": 2026, "years": 3, "why": "test"}))
r = run(root)
d = iq(w) if (w / "important_questions.json").exists() else {"model": {}}
m = d["model"]
radar = (w / "chapters" / "20_exam_radar.tex").read_text("utf-8") if r.returncode == 0 else ""
check(r.returncode == 0 and "MS2022" not in m.get("papers_used", {}) and
      m.get("papers_excluded", {}).get("MS2022") == "outside window", "window: MS2022 gets weight 0, reason 'outside window'",
      json.dumps(m.get("papers_excluded")))
check(r.returncode == 0 and not [q for q in d.get("q1_drill", {}).get("question_ids", ["MS2022-x"]) if q.startswith("MS2022")] and
      "MS2022" not in radar and "MS2022" not in json.dumps(d.get("skip_safety", {"MS2022": 1})),
      "window: MS2022 is out of the Q1 drill, the radar and skip-safety")
check(m.get("pyq_window", {}).get("from") == 2024 and not m.get("pyq_window", {}).get("defaulted"), "window: blueprint window recorded")


def with_paper(pid, year, like="MS2022"):
    def f(bank):
        src = [p for p in bank["papers"] if p["id"] == like][0]
        bank["papers"].append(dict(src, id=pid, year=year))
        bank["questions"] += [dict(q, id=q["id"].replace(like, pid), paper=pid) for q in bank["questions"] if q["paper"] == like]
    return f


# default rule: latest 5 calendar years with papers (2021-2025) -> a 2015 paper is outside
root, w = setup("window_default", bank_edit=with_paper("MS2015", 2015))
r = run(root)
d = iq(w) if (w / "important_questions.json").exists() else {"model": {}}
pw = d["model"].get("pyq_window", {})
check(r.returncode == 0 and pw.get("from") == 2021 and pw.get("to") == 2025 and pw.get("defaulted") and
      "pyq_window defaulted" in r.stdout and d["model"].get("papers_excluded", {}).get("MS2015") == "outside window",
      "default window: 2021-2025, printed as defaulted, 2015 paper excluded", json.dumps(pw) + r.stdout[-300:])


# default rule, extended: only 2 papers in 2021-2025, so it reaches back to the third (2018)
def two_recent(bank):
    for p in bank["papers"]:
        if p["id"] == "MS2022":
            p["year"] = 2018


root, w = setup("window_extend", bank_edit=two_recent)
r = run(root)
d = iq(w) if (w / "important_questions.json").exists() else {"model": {}}
pw = d["model"].get("pyq_window", {})
check(r.returncode == 0 and pw.get("from") == 2018 and "MS2022" in d["model"].get("papers_used", {}),
      "default window extends back to keep 3 relevant papers", json.dumps(pw))

# fallback order: blueprint.pyq_window > pyq_windows.json[<SUBJ>] > default rule
root, w = setup("window_json")
wj = root / "pyq_windows.json"
wj.write_text(json.dumps({"_note": "test", "CN": {"from": 2024, "to": 2026, "why": "json test window"}}), encoding="utf-8")
r = run(root, windows=wj)
d = iq(w) if (w / "important_questions.json").exists() else {"model": {}}
pw = d["model"].get("pyq_window", {})
check(r.returncode == 0 and pw.get("source") == "pyq_windows.json" and pw.get("from") == 2024 and
      d["model"].get("papers_excluded", {}).get("MS2022") == "outside window" and "from pyq_windows.json" in r.stdout,
      "no blueprint window: pyq_windows.json[CN] is used and printed", json.dumps(pw) + r.stdout[:200])
root, w = setup("window_json_bp", bp_edit=lambda bp: bp.update(pyq_window={"from": 2022, "to": 2026, "why": "bp"}))
wj = root / "pyq_windows.json"
wj.write_text(json.dumps({"CN": {"from": 2024, "to": 2026, "why": "json test window"}}), encoding="utf-8")
r = run(root, windows=wj)
d = iq(w)
check(r.returncode == 0 and d["model"]["pyq_window"]["source"] == "blueprint" and "MS2022" in d["model"]["papers_used"],
      "blueprint.pyq_window wins over pyq_windows.json")
root, w = setup("window_json_null")
wj = root / "pyq_windows.json"
wj.write_text(json.dumps({"CN": {"from": None, "to": None, "why": "no papers known"}}), encoding="utf-8")
r = run(root, windows=wj)
d = iq(w)
check(r.returncode == 0 and d["model"]["pyq_window"]["source"] == "pyq_windows.json" and len(d["model"]["papers_used"]) == 3 and
      "none (all papers)" in r.stdout, "null from/to in pyq_windows.json: no window, nothing excluded")

# a past paper on another scale (CN 2023 was 40 marks) is rescaled to today's full marks
def forty(bank):
    for p in bank["papers"]:
        if p["id"] == "MS2022":
            p["full_marks"] = 40
    for q in bank["questions"]:
        if q["paper"] == "MS2022":
            q["marks"] = q["marks"] * 2


root, w = setup("scale40", bank_edit=forty)
r = run(root)
d = iq(w)
check(r.returncode == 0 and d["model"]["full_marks"] == 20 and d["plans"]["12h"]["of_marks"] == 20 and
      d["exam_hall"]["min_per_mark"] == 4.0 and "10" not in d["exam_hall"]["budgets"],
      "a 40-mark past paper is rescaled to the 20-mark pattern", json.dumps(d["model"]["full_marks"]))

# ------------------------------------------------------------------ 11. R4: subject-scaled targets
root, w = setup("targets")
r = run(root)
d = iq(w)
T = d.get("targets", {})
bank = json.loads((FIX / "pyq_bank.json").read_text("utf-8"))
bp = json.loads((FIX / "blueprint.json").read_text("utf-8"))
unit_of = {t["id"]: u["id"] for u in bp["units"] if u.get("in_scope", True) for t in u["topics"]}
lect = {u["id"]: u["lectures"] for u in bp["units"] if u.get("in_scope", True)}
ctopic = {c["id"]: c["topic"] for c in bank["clusters"]}
qs = [q for q in bank["questions"] if q.get("in_scope", True) and ctopic.get(q["cluster"]) in unit_of]
tot = sum(q["marks"] for q in qs)
share = {u: sum(q["marks"] for q in qs if unit_of[ctopic[q["cluster"]]] == u) / tot for u in lect}
mean = sum(share.values()) / len(share)
want_np = {u: round(lect[u] * min(2.0, max(1.0, 1.0 + share[u] / mean)) + 1, 1) for u in lect}
got_np = {u: v["pages"] for u, v in T.get("notes_pages", {}).items()}
check(got_np == want_np and all(v.get("why") for v in T.get("notes_pages", {}).values()),
      "targets.notes_pages = lectures * clamp(1 + share/mean, 1, 2) + 1 per unit", f"{got_np} vs {want_np}")
num = sum(q["marks"] for q in qs if q["type"] == "numerical") / tot
want_cs = 2 + (len(unit_of) > 20) + (num > 0.40)
check(T.get("cheatsheet_pages", {}).get("pages") == want_cs and T["cheatsheet_pages"].get("why"),
      "targets.cheatsheet_pages = 2 + (topics > 20) + (numerical share > 40%)", f"{T.get('cheatsheet_pages')} vs {want_cs} (num {num:.2f})")
plan12 = d["plans"]["12h"]["clusters"]
dd = [c["cluster"] for c in d["clusters"] if c["tier"] == "D"]
ic = T.get("iq_clusters", {})
check(ic.get("clusters", [])[:len(plan12)] == plan12 and set(ic.get("clusters", [])[len(plan12):]) <= set(dd) and
      len(ic.get("clusters", [])) - len(plan12) == min(5, len(dd)) and ic.get("why"),
      "targets.iq_clusters = the 12 h plan + at most 5 tier-D wildcards")
# corrected expectation (real ML endsem, 2026-11-06): "every in-window 1-mark PYQ" gave a 177-item drill from 24 papers.
# The drill holds the NEWEST 1-mark PYQ of each one-mark idea (one per cluster) + the predicted items.
pyear = {p["id"]: (p.get("year") or 0, 1 if (p.get("session") or "autumn") == "autumn" else 0) for p in bank["papers"]}
newest = {}
for q in qs:
    if q["marks"] <= 1:
        c = q["cluster"]
        if c not in newest or pyear.get(q["paper"], (0, 0)) > pyear.get(newest[c]["paper"], (0, 0)):
            newest[c] = q
one = sorted(q["id"] for q in newest.values())
n1 = len(newest)
q1 = T.get("q1_drill", {})
check(sorted(q1.get("question_ids", [])) == one and len(q1.get("clusters", [])) == min(30, 2 * n1) and q1.get("why"),
      "targets.q1_drill = newest 1-mark PYQ per one-mark idea + min(30, 2 * one-mark clusters) predicted",
      (sorted(q1.get("question_ids", [])), one))
check(all(c["index_only"] == (c["tier"] == "E") for c in d["clusters"]), "tier E ideas are index_only, the rest are not")
how = (w / "chapters" / "05_how_to_use.tex").read_text("utf-8")
check("How big this guide is, and why" in how and f"{want_cs} landscape pages" in how, "05 prints the targets box")
# real CN 2026-11-06: a raw \fbox{\parbox{..}{..\par..}} box broke web.py's converter (2 render failures);
# the box must be a studyguide box environment that print, phone and web all understand
check("\\fbox" not in how and "\\begin{keyconceptbox}" in how, "05 targets box is a keyconceptbox, not a raw \\fbox")
# honesty (CN review r1, 2026-11-06): P must not be called a chance, and wildcards are "not asked in the window",
# not "never asked" (many were asked before the PYQ window)
check("chance the idea appears" not in how and "not a calibrated" in how, "05 does not present P as a calibrated chance")
# real SVP endsem (2026-11-06): an assumed-pattern source with a long corpus slug
# (PYQE_5th_Semester_B_Tech_Image_Processing_...) overflowed 05/20 by 72 pt (A4) and 155-174 pt (phone)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import importlib
_sc = importlib.import_module("score")
check(r"\_\allowbreak{}" in _sc.tex("PYQE_5th_Semester_B_Tech_Image_Processing"),
      "tex() lets long underscore slugs break after each underscore")


# a unit that carries more of the marks gets more notes pages, one that loses marks gets fewer.
# (Transport, U3, holds most marks and sits at the 2x cap, so the U2 -> U1 move is the informative one.)
def u2_to_u1(bank):
    for q in bank["questions"]:
        if q["topic"] in ("T07", "T08", "T09", "T10", "T11"):
            q["cluster"], q["topic"] = "C05", "T05"


root, w = setup("targets_shift", bank_edit=u2_to_u1)
r = run(root)
T2 = iq(w).get("targets", {}).get("notes_pages", {})
check(T2 and T2["U1"]["pages"] > got_np["U1"] and T2["U2"]["pages"] < got_np["U2"] and T2["U2"]["pages"] == 5 + 1,
      "moving U2's marks into U1: U1 gets more notes pages, U2 drops to lectures x 1 + 1",
      f"{T2.get('U1', {}).get('pages')} {T2.get('U2', {}).get('pages')} vs {got_np}")

# ------------------------------------------------------------------ 9. live-bank smoke test (invariants only)
# The live CN bank changes as the pipeline banks papers, so only properties that must hold for any bank are checked.
if (LIVE / "blueprint.json").exists() and (LIVE / "pyq_bank.json").exists():
    root_l = TMP / "live"
    if root_l.exists():
        shutil.rmtree(root_l)
    wl = root_l / "CN" / "work" / "midsem"
    wl.mkdir(parents=True)
    for f in ("blueprint.json", "pyq_bank.json"):
        shutil.copy(LIVE / f, wl / f)
    r = run(root_l)
    ok = r.returncode == 0 and (wl / "important_questions.json").exists()
    check(ok, "live bank: score.py runs", (r.stdout + r.stderr)[-500:])
    if ok:
        d = iq(wl)
        P = d["plans"]
        s3, s6, s12 = (set(P[h]["clusters"]) for h in ("3h", "6h", "12h"))
        tiers = {c["cluster"]: c["tier"] for c in d["clusters"]}
        check(s3 <= s6 <= s12, "live bank: plans nested")
        check(all(t in "ABCDE" for t in tiers.values()) and {c for c, t in tiers.items() if t == "A"} == s3 and
              {c for c, t in tiers.items() if t == "B"} == s6 - s3 and {c for c, t in tiers.items() if t == "C"} == s12 - s6,
              "live bank: tiers valid and equal to the plan stages")
        check(all(0 <= P[h]["p_safe"] <= 1 for h in P), "live bank: p_safe in [0, 1]")
else:
    print("OK live-bank smoke test skipped (no live CN midsem bank)")

# --- exam-hall plan uses the CURRENT pattern (DAA endsem 2026-11-08: the plan said "Optional question (8 marks)"
# from the oldest 3 h paper while the current 2.5 h paper has 10-mark optionals). Templates come in paper order
# (oldest first); the current one is the highest-weight (newest) template.
try:
    import score as scm
    def tpl(k, n, v):
        return {"groups": [{"compulsory": True, "value": 10.0, "parts": [{"marks": 1.0}] * 10}] +
                          [{"compulsory": False, "value": v, "parts": [{"marks": v / 2}] * 2} for _ in range(n)],
                "k": k, "n": n, "full_marks": 50.0}
    old, new = tpl(5, 7, 8.0), tpl(4, 5, 10.0)
    ctx_ = {"pattern": {"duration": "2.5 h", "full_marks": 50}, "papers": [], "scope": "endsem"}
    model_ = {"full_marks": 50.0, "templates": [(old, 0.4), (new, 1.0)]}
    eh = scm.exam_hall(ctx_, model_, [])
    opt = [p["step"] for p in eh["plan"] if p["step"].startswith("Optional")]
    check(len(opt) == 4 and all("(10 marks)" in s for s in opt),
          "exam-hall plan uses the current (highest-weight) template: any 4 of 10-mark questions", opt)
except Exception as e:  # noqa
    check(False, "exam-hall current-template test ran", repr(e))

print("ALL OK" if not fails else f"{fails} FAILED")
if not fails:
    shutil.rmtree(TMP, ignore_errors=True)   # keep the folder only when something failed
sys.exit(1 if fails else 0)
