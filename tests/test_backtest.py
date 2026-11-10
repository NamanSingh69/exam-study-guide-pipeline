"""Regression tests for tools/backtest.py. Standalone: prints OK lines, exits 0 on pass.

Uses copies of the CN midsem inputs in tests/_tmp/backtest/ (STUDYPREP_ROOT) and writes model_params
only to a temp file (--out / STUDYPREP_MODEL_PARAMS); never touches a real subject folder or the real
_pipeline/model_params.json.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
FIX = HERE / "fixtures" / "score_cn3"          # frozen round-3 CN midsem bank (3 papers, C01-C38)
LIVE = PIPE.parent / "CN" / "work" / "midsem"   # live bank: only the invariant smoke test reads it
# one folder per run: parallel run_all invocations (other workstreams) must not share files
TMP = HERE / "_tmp" / f"backtest_{os.getpid()}"
BT = PIPE / "tools" / "backtest.py"
SCORE = PIPE / "tools" / "score.py"
fails = 0


def check(cond, name, detail=""):
    global fails
    if cond:
        print(f"OK {name}")
    else:
        fails += 1
        print(f"FAIL {name} {detail}")


def put(root, subj, bank_edit=None):
    w = root / subj / "work" / "midsem"
    w.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIX / "blueprint.json", w / "blueprint.json")
    bank = json.loads((FIX / "pyq_bank.json").read_text("utf-8"))
    if bank_edit:
        bank_edit(bank)
    (w / "pyq_bank.json").write_text(json.dumps(bank), encoding="utf-8")
    return w


def drop_paper(pid):
    def f(bank):
        bank["papers"] = [p for p in bank["papers"] if p["id"] != pid]
        bank["questions"] = [q for q in bank["questions"] if q["paper"] != pid]
    return f


def run(tool, args, root, mp):
    env = dict(os.environ, STUDYPREP_ROOT=str(root), STUDYPREP_MODEL_PARAMS=str(mp),
               STUDYPREP_PYQ_WINDOWS=str(root / "no_pyq_windows.json"))   # never the live pyq_windows.json
    return subprocess.run([sys.executable, str(tool), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=900)


if TMP.exists():
    shutil.rmtree(TMP)
root = TMP / "root"
put(root, "CN")
put(root, "XX", drop_paper("MS2022"))     # only 2 papers: must be skipped, not crash
mp = TMP / "mp.json"

# ------------------------------------------------------------------ 1. the backtest run
r = run(BT, ["--grid", "small", "--n-sim", "400", "--out", str(mp)], root, mp)
out = r.stdout + r.stderr
check(r.returncode == 0 and r.stdout.strip().endswith("RESULT PASS"), "backtest runs", out[-1500:])
check("skip XX/midsem: 2 relevant paper(s)" in out, "a bank with fewer than 3 papers is skipped and said so", out[:600])
d = json.loads(mp.read_text("utf-8")) if mp.exists() else {}
bt = d.get("backtest", {}).get("CN/midsem", {})
check(set(d.get("backtest", {})) == {"CN/midsem"}, "only eligible banks are backtested")
s = bt.get("summary", {})
check(all(m in s for m in ("new", "new_def", "old", "lecture", "uniform")), "every method is reported")
check(s.get("new", {}).get("cover_6h", {}).get("n") == 3 and bt.get("n_folds") == 3, "3 leave-one-year-out folds")
check(all(0 <= s[m]["cover_6h"]["min"] <= s[m]["cover_6h"]["mean"] <= s[m]["cover_6h"]["max"] <= 1
          for m in s if m in ("new", "old", "lecture", "uniform")), "coverage reported as mean with its range")
check(set(s.get("diff_new_minus", {})) >= {"old", "lecture", "uniform"}, "paired differences against each baseline")
check(set(d.get("pooled", {})) == {"decay", "alpha", "lect_w", "imp_boost", "form_alpha"} and "CN/midsem" in d.get("subjects", {}),
      "pooled and per-subject parameters written")
check(bt.get("forward_n_folds") == 2, "forward (past-only) folds reported too")
for f in bt.get("folds", []):
    if f["new"]["cover_6h"] is None:
        check(False, "fold has cover_6h")

# ------------------------------------------------------------------ 2. no leakage, folds, the old-model baseline
sys.path.insert(0, str(PIPE / "tools"))
os.environ["STUDYPREP_ROOT"] = str(root)
os.environ["STUDYPREP_PYQ_WINDOWS"] = str(root / "no_pyq_windows.json")
import importlib  # noqa: E402
import workdir  # noqa: E402
importlib.reload(workdir)
import score, backtest  # noqa: E402
ctx = score.load_ctx(root / "CN" / "work" / "midsem", "midsem")
fs = backtest.folds(ctx)
check(len(fs) == 3 and all(f["test"] not in f["train"] for f in fs), "test paper never in its own training set")
m = score.fit(ctx, dict(score.DEFAULTS), fs[0]["train"], fs[0]["year"])
check(fs[0]["test"] not in m["W"], "fit() ignores the held-out paper")
om = backtest.old_model(ctx, {"MS2022", "MS2024", "MS2025"}, 2025.5)  # (year, session) key of MS2025, autumn
check(om["plans"]["3h"] == ["C29", "C17", "C25", "C23", "C19", "C20", "C16", "C04", "C05", "C36"] and
      abs(om["P_c"]["C25"] - 0.788) < 1e-3, "old-model baseline reproduces the replaced score.py (3 h plan, P(C25)=0.788)")
sr = score.score_real(ctx, "MS2025", [c["id"] for c in ctx["clusters"]])
check(abs(sr["attain"] - 1) < 1e-9 and abs(sr["max"] - 20) < 1e-9, "studying everything attains the full 20 marks of MS2025")
sr = score.score_real(ctx, "MS2025", ["C18", "C11"])
check(abs(sr["marks"] - 5) < 1e-9, "Q2 alone (C18 + C11) attains exactly its 5 marks", str(sr))
sr = score.score_real(ctx, "MS2025", ["C05", "C16", "C36"])
check(abs(sr["marks"] - 5) < 1e-9, "Q5 short notes: any two of three cap the question at 5 marks", str(sr))

# ------------------------------------------------------------------ 2b. R4: papers outside the PYQ window never enter a fold
rootw = TMP / "window"
ww = put(rootw, "CN")
bpw = json.loads((ww / "blueprint.json").read_text("utf-8"))
bpw["pyq_window"] = {"from": 2024, "to": 2026, "years": 3, "why": "test"}
(ww / "blueprint.json").write_text(json.dumps(bpw), encoding="utf-8")
ctxw = score.load_ctx(ww, "midsem")
fw = backtest.folds(ctxw)
check(fw and all(f["test"] != "MS2022" and "MS2022" not in f["train"] for f in fw),
      "window: MS2022 is in no fold's test or training set", str([(f["test"], sorted(f["train"])) for f in fw]))
mpw = TMP / "mp_window.json"
r = run(BT, ["--grid", "small", "--n-sim", "300", "--out", str(mpw), "--subjects", "CN"], rootw, mpw)
check(r.returncode == 0 and "skip CN/midsem: 2 relevant paper(s)" in r.stdout,
      "window leaving 2 papers: the bank is skipped, not backtested", r.stdout[-400:])

# ------------------------------------------------------------------ 3. score.py picks up the tuned parameters
w = root / "CN" / "work" / "midsem"
r = run(SCORE, ["CN", "--scope", "midsem", "--n-sim", "800"], root, mp)
iq = json.loads((w / "important_questions.json").read_text("utf-8"))
check(r.returncode == 0 and "CN/midsem" in iq["model"]["params_source"] and iq["backtest"]["n_folds"] == 3,
      "score.py uses the tuned parameters and the backtest entry")
how = (w / "chapters" / "05_how_to_use.tex").read_text("utf-8")
check("Track record:" in how and "held-out" in how, "backtest line printed in How to use")

# ------------------------------------------------------------------ 4. --post-exam
root2 = TMP / "post"
w2 = put(root2, "CN", drop_paper("MS2025"))
mp2 = TMP / "mp_post.json"
r = run(SCORE, ["CN", "--scope", "midsem", "--n-sim", "800"], root2, mp2)
snap = sorted((w2 / "plan_snapshots").glob("*.json"))
check(r.returncode == 0 and snap, "snapshot written before the new paper is banked")
r = run(BT, ["--post-exam", "CN", "--scope", "midsem", "--paper", "MS2025", "--out", str(mp2)], root2, mp2)
check(r.returncode == 1 and "RESULT BLOCKED" in r.stdout, "post-exam blocks when the paper is not banked yet", r.stdout[-300:])
put(root2, "CN")   # the new paper arrives
r = run(BT, ["--post-exam", "CN", "--scope", "midsem", "--paper", "MS2025", "--out", str(mp2)], root2, mp2)
pe = w2 / "plan_snapshots" / "post_exam_MS2025.json"
res = json.loads(pe.read_text("utf-8")) if pe.exists() else {}
check(r.returncode == 0 and "headline: the 6-hour plan covered" in r.stdout and
      0 <= res.get("plans", {}).get("6h", {}).get("cover", -1) <= 1, "post-exam scores the saved plan", r.stdout[-500:])
mpj = json.loads(mp2.read_text("utf-8"))
check(len(mpj.get("post_exam", {}).get("CN/midsem", [])) == 1, "post-exam result recorded in model_params")
r = run(BT, ["--post-exam", "CN", "--scope", "midsem", "--paper", "MS2025", "--out", str(mp2)], root2, mp2)
check(len(json.loads(mp2.read_text("utf-8"))["post_exam"]["CN/midsem"]) == 1, "re-running post-exam replaces, not duplicates")

# ------------------------------------------------------------------ 5. nothing eligible: honest no-op
root3 = TMP / "none"
put(root3, "XX", drop_paper("MS2022"))
mp3 = TMP / "mp_none.json"
r = run(BT, ["--grid", "small", "--out", str(mp3)], root3, mp3)
check(r.returncode == 0 and "nothing to backtest" in r.stdout and not mp3.exists(), "no eligible bank: says so, writes nothing")

# ------------------------------------------------------------------ 6. live-bank smoke test (invariants only)
if (LIVE / "blueprint.json").exists() and (LIVE / "pyq_bank.json").exists():
    root4 = TMP / "live"
    wl = root4 / "CN" / "work" / "midsem"
    wl.mkdir(parents=True)
    for f in ("blueprint.json", "pyq_bank.json"):
        shutil.copy(LIVE / f, wl / f)
    mp4 = TMP / "mp_live.json"
    r = run(BT, ["--grid", "small", "--n-sim", "300", "--out", str(mp4)], root4, mp4)
    ok = r.returncode == 0 and r.stdout.strip().endswith("RESULT PASS")
    check(ok, "live bank: backtest runs", (r.stdout + r.stderr)[-600:])
    if ok and mp4.exists():
        b = json.loads(mp4.read_text("utf-8"))["backtest"].get("CN/midsem", {})
        vals = [f[m][k] for f in b.get("folds", []) for m in ("new", "old", "lecture", "uniform")
                for k in ("cover_3h", "cover_6h", "cover_12h") if f[m].get(k) is not None]
        check(b.get("n_folds", 0) >= 3 and vals and all(0 <= v <= 1 for v in vals),
              "live bank: >= 3 folds, every coverage in [0, 1]")
else:
    print("OK live-bank smoke test skipped (no live CN midsem bank)")

print("ALL OK" if not fails else f"{fails} FAILED")
if not fails:
    shutil.rmtree(TMP, ignore_errors=True)   # keep the folder only when something failed
sys.exit(1 if fails else 0)
