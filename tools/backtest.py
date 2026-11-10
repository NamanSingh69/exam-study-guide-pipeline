"""
backtest.py: test the score.py planner on held-out past papers, tune its few parameters pooled across
subjects, and score saved plans against newly banked papers.

  py _pipeline/tools/backtest.py                       every <SUBJ>/work/<scope>/ bank with >= 3 relevant
                                                       papers; writes _pipeline/model_params.json
  py _pipeline/tools/backtest.py --subjects CN ML      only these subjects
  py _pipeline/tools/backtest.py --no-write            report only
  py _pipeline/tools/backtest.py --post-exam CN --scope midsem --paper MS2026 [--snapshot 2026-11-05]
                                                       score a saved plan snapshot against a new paper

Folds: leave-one-year-out (one exam session = (year, session) at a time). Each session's paper(s) is predicted from every other relevant
paper (recency measured from the held-out year).

Methods compared on every fold:
  new        score.py model + planner, with the tuned parameters
  new_def    the same with score.py's default parameters (the tuned run is tuned on these same folds,
             so it is optimistic; the defaults run is not)
  old        the pre-Round-4 model: Beta-smoothed recency-weighted P per idea, plans greedy by yield
  lecture    lecture time only: same planner, but the topic shares ignore every past paper
  uniform    random ideas until the time budget is used (mean of 200 random orders)

Metrics:
  cover_3h/6h/12h  share of the held-out paper's attainable marks (choice rules applied) that the plan covers
  printed_6h       share of the paper's printed marks whose idea is in the 6 h plan
  topic_xent       cross-entropy of the held-out topic marks shares (nats; lower is better)
  brier_c/logloss_c, brier_t/logloss_t   P(idea asked) and P(topic asked)

Tuning (few parameters, heavily shrunk): DECAY, ALPHA, LECT_W, IMP_BOOST on a coarse grid. The
pooled mean minimises the mean fold topic_xent over every bank plus a penalty pulling it toward the
defaults; each bank's own parameters minimise its own fold loss plus a penalty pulling them toward
the pooled mean, which shrinks harder when the bank has fewer folds.
"""
import argparse, datetime, itertools, json, statistics, sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import workdir  # noqa: E402
import score  # noqa: E402

MIN_PAPERS = 3
GRID = {"decay": [0.5, 0.8, 1.0], "alpha": [0.5, 1.0, 2.0, 4.0, 8.0, 16.0],
        "lect_w": [0.0, 0.5, 1.0], "imp_boost": [0.0, 0.5, 1.0], "form_alpha": [1.0, 4.0, 16.0]}
GRID_SMALL = {"decay": [0.8, 1.0], "alpha": [2.0, 8.0], "lect_w": [0.5], "imp_boost": [0.5], "form_alpha": [4.0]}
RANGE = {"decay": 0.5, "alpha": 15.5, "lect_w": 1.0, "imp_boost": 1.0, "form_alpha": 15.0}
LAMBDA_DEFAULT = 0.5     # pooled mean: penalty per (range-normalised distance)^2, divided by total folds
LAMBDA_POOLED = 0.5      # per bank: penalty toward the pooled mean, divided by the bank's folds
UNIFORM_REPS = 200
OLD_DECAY, OLD_ALPHA = 0.8, 1.5
EPS = 1e-3


# ----------------------------------------------------------------------------- banks and folds
def discover(subjects=None):
    out = []
    for subj in sorted(p for p in workdir.ROOT.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        if subjects and subj.name not in subjects:
            continue
        for sc in workdir.SCOPES:
            w = subj / "work" / sc
            if (w / "blueprint.json").exists() and (w / "pyq_bank.json").exists():
                try:
                    ctx = score.load_ctx(w, sc)
                except (ValueError, KeyError, json.JSONDecodeError) as e:
                    print(f"skip {subj.name}/{sc}: {e}")
                    continue
                full = full_papers(ctx)
                yrs = sorted({score.tkey(p) for p in full})
                tag = f"{subj.name}/{sc}"
                if len(full) >= MIN_PAPERS and len(yrs) >= 2:
                    out.append((tag, ctx))
                else:
                    print(f"skip {tag}: {len(full)} relevant paper(s) (need {MIN_PAPERS})")
    return out


def full_papers(ctx):
    allu = set(ctx["uid"])
    return [p for p in ctx["papers"] if score.coverage(ctx, p) == allu and
            any(q["paper"] == p["id"] for q in ctx["qs"])]


def folds(ctx, forward=False):
    full = full_papers(ctx)
    years = sorted({score.tkey(p) for p in full})
    rel = [p for p in ctx["papers"] if score.coverage(ctx, p)]
    out = []
    for y in years:
        test = [p["id"] for p in full if score.tkey(p) == y]
        if forward:
            train = {p["id"] for p in rel if score.tkey(p) < y}
        else:
            train = {p["id"] for p in rel if score.tkey(p) != y}
        if not any(p["id"] in train for p in full):
            continue
        for t in test:
            out.append({"test": t, "year": y, "train": train})
    return out


# ----------------------------------------------------------------------------- truth of a held-out paper
def truth(ctx, pid):
    qs = [q for q in ctx["qs"] if q["paper"] == pid]
    tm = defaultdict(float)
    for q in qs:
        tm[q["topic"]] += float(q["marks"])
    M = sum(tm.values()) or 1.0
    return {"topic_share": {t: v / M for t, v in tm.items()}, "clusters": {q["cluster"] for q in qs},
            "topics": set(tm)}


def xent(share, tr):
    return -sum(s * np.log(max(share.get(t, 0.0), EPS)) for t, s in tr["topic_share"].items())


def form_xent(ctx, model, pid):
    """Mean -log P(form | topic) over the held-out paper's questions."""
    qs = [q for q in ctx["qs"] if q["paper"] == pid]
    if not qs:
        return 0.0
    return float(-np.mean([np.log(max(model["form"][q["topic"]].get(q["cluster"], 0.0), EPS)) for q in qs]))


def joint_loss(ctx, model, pid, tr):
    """Tuning objective: topic-marks cross-entropy + form cross-entropy (both held out, in nats)."""
    return xent(model["share"], tr) + form_xent(ctx, model, pid)


def binary(P, y):
    P = np.clip(np.asarray(P, float), 0.01, 0.99)
    y = np.asarray(y, float)
    return float(((P - y) ** 2).mean()), float(-(y * np.log(P) + (1 - y) * np.log(1 - P)).mean())


# ----------------------------------------------------------------------------- the old (pre-Round-4) model
def old_model(ctx, train, ref_year):
    """Faithful to the replaced score.py, with weights restricted to the training papers."""
    T = ctx["topics"]
    maxlec = max([float(t.get("lectures") or 0) for u in ctx["bp"].get("units", [])
                  for t in u.get("topics", [])] + [1])   # the old code used every unit, in scope or not
    W = {}
    for p in ctx["papers"]:
        if p["id"] not in train:
            continue
        same = score.paper_kind(p) == ctx["scope"]
        if not same and ctx["scope"] == "midsem":
            continue
        W[p["id"]] = OLD_DECAY ** abs(ref_year - score.tkey(p)) * (1.0 if same else 0.5)
    Wsum = sum(W.values()) or 1.0
    imp = {c["id"] for c in ctx["clusters"] if c.get("imp")}

    def tprior(t):
        return min(0.70, max(0.05, 0.10 + 0.35 * float(t.get("lectures") or 0) / maxlec + 0.15 * bool(t.get("senior_imp"))))
    qs = [q for q in ctx["qs"] if q["paper"] in W]
    opt = [float(q["marks"]) for q in qs if not q.get("compulsory")]
    dm = statistics.mode(opt) if opt else 2.5
    ch = ctx["pattern"].get("choose") or {}
    copt = (ch.get("answer", 1) / max(1, len(ch.get("from", [1])))) if ch else 1.0
    rows = []
    for c in ctx["clusters"]:
        if c["synthetic"]:
            continue
        t = T[c["topic"]]
        cq = [q for q in qs if q["cluster"] == c["id"]]
        asked = defaultdict(float)
        for q in cq:
            asked[q["paper"]] += float(q["marks"])
        prior = min(0.8, max(0.03, 0.6 * tprior(t) + (0.10 if c["id"] in imp else 0)))
        P = (sum(W[p] for p in asked) + OLD_ALPHA * prior) / (Wsum + OLD_ALPHA)
        m = statistics.median(asked.values()) if asked else dm
        ev = P * m * (1.0 if any(q.get("compulsory") for q in cq) else copt)
        eff = float(c.get("effort_min") or 30)
        Pd = round(100 * P) / 100
        n_asked = len(asked)
        tier = ("A" if Pd >= 0.60 else "B" if Pd >= 0.35 else "C" if Pd >= 0.15 and n_asked else
                "D" if not n_asked and prior >= 0.18 else "C" if Pd >= 0.15 else "E")
        rows.append({"id": c["id"], "P": P, "EV": round(ev, 2), "yield": round(ev / (eff / 30), 2), "eff": eff,
                     "tier": tier})
    rows.sort(key=lambda r: (-r["EV"], -r["P"]))
    plans = {}
    for name, B in score.BUDGETS:
        out, used = [], 0
        for r in sorted(rows, key=lambda r: -r["yield"]):
            if r["tier"] in "ABCD" and used + r["eff"] <= B:
                out.append(r["id"])
                used += r["eff"]
        plans[name] = out
    Pt = {}
    for tid, t in T.items():
        tp = {q["paper"] for q in qs if q["topic"] == tid}
        Pt[tid] = (sum(W[p] for p in tp) + OLD_ALPHA * tprior(t)) / (Wsum + OLD_ALPHA)
    return {"P_c": {r["id"]: r["P"] for r in rows}, "P_t": Pt, "plans": plans}


def random_plans(ctx, rng):
    eff = {c["id"]: float(c.get("effort_min") or 30) for c in ctx["clusters"]}
    order = [ctx["clusters"][i]["id"] for i in rng.permutation(len(ctx["clusters"]))]
    chosen, used, plans = [], 0.0, {}
    for name, B in score.BUDGETS:
        for c in order:
            if c not in chosen and used + eff[c] <= B:
                chosen.append(c)
                used += eff[c]
        plans[name] = list(chosen)
    return plans


# ----------------------------------------------------------------------------- evaluation of one fold
def eval_fold(ctx, f, prm, n_sim, seed):
    tr = truth(ctx, f["test"])
    C = [c["id"] for c in ctx["clusters"]]
    T = ctx["torder"]
    yc = [c in tr["clusters"] for c in C]
    yt = [t in tr["topics"] for t in T]
    res = {"test": f["test"], "year": f["year"], "n_train": len(f["train"])}
    lecture_prm = dict(prm, lect_w=1.0, imp_boost=0.0)
    for name, p, ev in (("new", prm, True), ("new_def", dict(score.DEFAULTS), True), ("lecture", lecture_prm, False)):
        m = score.run_model(ctx, p, n_sim, seed, f["train"], f["year"], evidence=ev)
        r = {"topic_xent": xent(m["share"], tr), "form_xent": form_xent(ctx, m, f["test"])}
        r["brier_c"], r["logloss_c"] = binary(m["P_c"], yc)
        r["brier_t"], r["logloss_t"] = binary(m["P_t"], yt)
        for pn in m["plans"]:
            cids = [ctx["clusters"][i]["id"] for i in m["plans"][pn]["idx"]]
            sr = score.score_real(ctx, f["test"], cids)
            r[f"cover_{pn}"] = sr["attain"]
            r[f"printed_{pn}"] = sr["printed"]
            r[f"cover_topic_{pn}"] = score.score_real(ctx, f["test"], cids, topic_level=True)["attain"]
            r[f"psafe_pred_{pn}"] = m["plans"][pn]["p_safe"]
            r[f"safe_{pn}"] = float(sr["safe"])
        res[name] = r
    om = old_model(ctx, f["train"], f["year"])
    r = {"topic_xent": None, "form_xent": None}
    r["brier_c"], r["logloss_c"] = binary([om["P_c"].get(c, 0.03) for c in C], yc)
    r["brier_t"], r["logloss_t"] = binary([om["P_t"][t] for t in T], yt)
    for pn, cids in om["plans"].items():
        sr = score.score_real(ctx, f["test"], cids)
        r[f"cover_{pn}"], r[f"printed_{pn}"], r[f"safe_{pn}"] = sr["attain"], sr["printed"], float(sr["safe"])
        r[f"cover_topic_{pn}"] = score.score_real(ctx, f["test"], cids, topic_level=True)["attain"]
    res["old"] = r
    # uniform: base-rate P from the training papers, random plans
    tr_full = [p["id"] for p in full_papers(ctx) if p["id"] in f["train"]]
    if tr_full:
        rc = np.mean([len(truth(ctx, p)["clusters"]) / len(C) for p in tr_full])
        rt = np.mean([len(truth(ctx, p)["topics"]) / len(T) for p in tr_full])
    else:
        rc = rt = 0.3
    r = {"topic_xent": xent({t: 1 / len(T) for t in T}, tr)}
    r["brier_c"], r["logloss_c"] = binary([rc] * len(C), yc)
    r["brier_t"], r["logloss_t"] = binary([rt] * len(T), yt)
    rng = np.random.default_rng(seed)
    acc = defaultdict(list)
    for _ in range(UNIFORM_REPS):
        for pn, cids in random_plans(ctx, rng).items():
            sr = score.score_real(ctx, f["test"], cids)
            acc[f"cover_{pn}"].append(sr["attain"])
            acc[f"printed_{pn}"].append(sr["printed"])
            acc[f"safe_{pn}"].append(float(sr["safe"]))
    r.update({k: float(np.mean(v)) for k, v in acc.items()})
    res["uniform"] = r
    return res


METHODS = ("new", "new_def", "old", "lecture", "uniform")
KEYS = ("cover_3h", "cover_6h", "cover_12h", "printed_6h", "cover_topic_6h", "safe_6h", "psafe_pred_6h",
        "topic_xent", "form_xent", "brier_c", "logloss_c", "brier_t", "logloss_t")


def summarise(fres, seed=1):
    out = {}
    for m in METHODS:
        out[m] = {}
        for k in KEYS:
            v = [f[m].get(k) for f in fres if f[m].get(k) is not None]
            if v:
                out[m][k] = interval(v, seed)
    # paired differences: the honest comparison with this few folds
    out["diff_new_minus"] = {}
    for b in ("old", "lecture", "uniform", "new_def"):
        d = [f["new"]["cover_6h"] - f[b]["cover_6h"] for f in fres if "cover_6h" in f[b]]
        if d:
            out["diff_new_minus"][b] = interval(d, seed)
    return out


def interval(v, seed=1):
    v = [float(x) for x in v]
    r = {"mean": round(float(np.mean(v)), 4), "min": round(min(v), 4), "max": round(max(v), 4), "n": len(v)}
    if len(v) >= 5:
        rng = np.random.default_rng(seed)
        bs = [np.mean(rng.choice(v, len(v))) for _ in range(2000)]
        r["ci90"] = [round(float(np.percentile(bs, 5)), 4), round(float(np.percentile(bs, 95)), 4)]
    return r


# ----------------------------------------------------------------------------- tuning
def dist2(a, b):
    return sum(((a[k] - b[k]) / RANGE[k]) ** 2 for k in score.TUNED_KEYS)


def fold_losses(banks, grid):
    """loss[tag][combo] = mean topic_xent over that bank's folds (fit only; no simulation)."""
    combos = [dict(zip(grid, vals)) for vals in itertools.product(*grid.values())]
    L = {}
    for tag, ctx in banks:
        fs = folds(ctx)
        trs = [truth(ctx, f["test"]) for f in fs]
        L[tag] = {"n": len(fs), "loss": []}
        for cb in combos:
            prm = dict(score.DEFAULTS, **cb)
            ls = [joint_loss(ctx, score.fit(ctx, prm, f["train"], f["year"]), f["test"], t) for f, t in zip(fs, trs)]
            L[tag]["loss"].append(float(np.mean(ls)))
    return combos, L


def tune(banks, grid):
    combos, L = fold_losses(banks, grid)
    tot = sum(v["n"] for v in L.values()) or 1
    d0 = {k: score.DEFAULTS[k] for k in score.TUNED_KEYS}

    def pooled_obj(i):
        fit_ = sum(v["n"] * v["loss"][i] for v in L.values()) / tot
        return fit_ + LAMBDA_DEFAULT / tot * dist2(combos[i], d0)
    ip = min(range(len(combos)), key=pooled_obj)
    pooled = {k: combos[ip][k] for k in score.TUNED_KEYS}
    subjects = {}
    for tag, v in L.items():
        def obj(i, v=v):
            return v["loss"][i] + LAMBDA_POOLED / max(v["n"], 1) * dist2(combos[i], pooled)
        i_s = min(range(len(combos)), key=obj)
        subjects[tag] = {k: combos[i_s][k] for k in score.TUNED_KEYS}
        subjects[tag]["fold_xent"] = round(v["loss"][i_s], 4)
        subjects[tag]["fold_xent_defaults"] = round(v["loss"][combos.index(min(combos, key=lambda c: dist2(c, d0)))], 4)
    return pooled, subjects, {"pooled_fold_xent": round(sum(v["n"] * v["loss"][ip] for v in L.values()) / tot, 4)}


# ----------------------------------------------------------------------------- report
def table(tag, s, how="leave-one-year-out"):
    lines = [f"\n{tag}: {how}, {s['new']['cover_6h']['n']} folds (mean [min..max])",
             f"{'method':9s} {'cover3h':>17s} {'cover6h':>17s} {'cover12h':>17s} {'printed6h':>17s} "
             f"{'topic_xent':>17s} {'form_xent':>17s} {'brier_c':>17s} {'brier_t':>17s}"]
    for m in METHODS:
        row = f"{m:9s}"
        for k in ("cover_3h", "cover_6h", "cover_12h", "printed_6h", "topic_xent", "form_xent", "brier_c", "brier_t"):
            v = s[m].get(k)
            row += f" {v['mean']:5.3f} [{v['min']:.2f}..{v['max']:.2f}]" if v else f" {'n/a':>17s}"
        lines.append(row)
    for b, v in s["diff_new_minus"].items():
        lines.append(f"6 h cover, new minus {b:8s}: {v['mean']:+.3f} [{v['min']:+.2f}..{v['max']:+.2f}]")
    return "\n".join(lines)


def run_backtest(a):
    banks = discover(a.subjects)
    if not banks:
        print(f"no bank with >= {MIN_PAPERS} relevant papers: nothing to backtest; model_params.json unchanged")
        print("RESULT PASS")
        return 0
    grid = GRID_SMALL if a.grid == "small" else GRID
    pooled, subjects, info = tune(banks, grid) if not a.no_tune else (
        {k: score.DEFAULTS[k] for k in score.TUNED_KEYS}, {}, {"note": "tuning skipped"})
    print(f"pooled parameters: {pooled}  {info}")
    bt = {}
    for tag, ctx in banks:
        prm = dict(score.DEFAULTS, **{k: v for k, v in subjects.get(tag, pooled).items() if k in score.DEFAULTS})
        fs = folds(ctx)
        fres = [eval_fold(ctx, f, prm, a.n_sim, a.seed) for f in fs]
        s = summarise(fres)
        ff = folds(ctx, forward=True)
        fwd = [eval_fold(ctx, f, prm, a.n_sim, a.seed) for f in ff]
        bt[tag] = {"date": datetime.date.today().isoformat(), "method": "leave-one-year-out", "n_folds": len(fres),
                   "params": {k: prm[k] for k in score.TUNED_KEYS}, "summary": s,
                   "forward": summarise(fwd) if fwd else None, "forward_n_folds": len(fwd),
                   "folds": [{"test": f["test"], **{m: {k: (round(v, 4) if isinstance(v, float) else v)
                                                         for k, v in f[m].items()} for m in METHODS}} for f in fres]}
        print(table(tag, s))
        if fwd:
            print(table(tag, bt[tag]["forward"], "forward (each paper from the earlier ones only)"))
    if a.no_write:
        print("RESULT PASS (not written)")
        return 0
    out = Path(a.out) if a.out else score.PARAMS_FILE
    old = {}
    if out.exists():
        try:
            old = json.loads(out.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            old = {}
    mp = {"version": "r4", "generated": datetime.date.today().isoformat(),
          "about": "Written by tools/backtest.py. score.py uses subjects[<SUBJ>/<scope>] if present, else pooled, "
                   "else its defaults.",
          "defaults": score.DEFAULTS, "grid": grid,
          "shrinkage": {"to_defaults": LAMBDA_DEFAULT, "to_pooled": LAMBDA_POOLED, "distance": "range-normalised",
                        "objective": "mean held-out topic-marks cross-entropy + form cross-entropy"},
          "pooled": pooled, "tuning": info, "subjects": subjects,
          "banks": {tag: {"folds": bt[tag]["n_folds"], "papers": len(full_papers(ctx))} for tag, ctx in banks},
          "backtest": bt, "post_exam": old.get("post_exam", {})}
    out.write_text(json.dumps(mp, indent=1), encoding="utf-8")
    print(f"wrote {out}")
    print("RESULT PASS")
    return 0


# ----------------------------------------------------------------------------- post-exam
def post_exam(a):
    subj, _shared, work = workdir.resolve(a.post_exam, a.scope)
    scope = work.name
    ctx = score.load_ctx(work, scope)
    if not any(p["id"] == a.paper for p in ctx["papers"]):
        print(f"RESULT BLOCKED: paper {a.paper} is not in {work / 'pyq_bank.json'} (bank and verify it first)")
        return 1
    if not any(q["paper"] == a.paper for q in ctx["qs"]):
        print(f"RESULT BLOCKED: paper {a.paper} has no in-scope questions")
        return 1
    snaps = sorted((work / "plan_snapshots").glob("[0-9]*.json"))
    if a.snapshot:
        snaps = [s for s in snaps if s.stem == a.snapshot]
    else:
        snaps = [s for s in snaps if a.paper not in json.loads(s.read_text("utf-8")).get("model", {}).get("papers_used", {})]
    if not snaps:
        print("RESULT BLOCKED: no plan snapshot made before this paper was banked")
        return 1
    snap = json.loads(snaps[-1].read_text("utf-8"))
    res = {"paper": a.paper, "snapshot": snaps[-1].stem, "plans": {}}
    for pn, p in snap["plans"].items():
        sr = score.score_real(ctx, a.paper, p["clusters"])
        res["plans"][pn] = {"cover": round(sr["attain"], 4), "printed": round(sr["printed"], 4),
                            "marks": sr["marks"], "max": sr["max"], "safe": sr["safe"],
                            "predicted_expected": p.get("expected_marks"), "predicted_p_safe": p.get("p_safe")}
        print(f"{pn:>3s} plan (snapshot {snaps[-1].stem}): covered {100 * sr['attain']:.0f}% of the attainable marks "
              f"({sr['marks']:g}/{sr['max']:g}; predicted {p.get('expected_marks')}/{p.get('of_marks')}), "
              f"{100 * sr['printed']:.0f}% of printed marks, safe={sr['safe']}")
    six = res["plans"].get("6h")
    if six:
        print(f"headline: the 6-hour plan covered {100 * six['cover']:.0f}% of {a.paper}")
    (work / "plan_snapshots" / f"post_exam_{a.paper}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    out = Path(a.out) if a.out else score.PARAMS_FILE
    mp = json.loads(out.read_text("utf-8")) if out.exists() else {}
    mp.setdefault("post_exam", {}).setdefault(f"{subj.name}/{scope}", [])
    mp["post_exam"][f"{subj.name}/{scope}"] = [r for r in mp["post_exam"][f"{subj.name}/{scope}"]
                                               if r.get("paper") != a.paper] + [res]
    out.write_text(json.dumps(mp, indent=1), encoding="utf-8")
    print("RESULT PASS")
    return 0


def main():
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subjects", nargs="*")
    ap.add_argument("--n-sim", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=score.SEED)
    ap.add_argument("--grid", choices=("full", "small"), default="full")
    ap.add_argument("--no-tune", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--out", help="model_params.json path (default: _pipeline/model_params.json)")
    ap.add_argument("--post-exam", metavar="SUBJ")
    ap.add_argument("--scope")
    ap.add_argument("--paper")
    ap.add_argument("--snapshot")
    a = ap.parse_args()
    if a.post_exam:
        if not a.paper:
            print("--post-exam needs --paper <id>", file=sys.stderr)
            return 2
        return post_exam(a)
    return run_backtest(a)


if __name__ == "__main__":
    sys.exit(main())
