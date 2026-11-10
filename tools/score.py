"""
score.py: turn the verified PYQ bank into a topic-level marks model and nested study plans.

  py _pipeline/tools/score.py CN --scope midsem|endsem
     -> work/<scope>/important_questions.json, badges.tex, chapters/05_how_to_use.tex,
        chapters/20_exam_radar.tex, plan_snapshots/<date>.json

Model (Round 4; the same paragraph is printed in the guide, see explain()):
  * Relevant papers: a paper counts for a unit only if its coverage includes that unit. Papers of the
    scope's own exam type cover every in-scope unit; for an endsem scope a midsem paper covers only the
    midsem units, at CROSS_WEIGHT; for a midsem scope endsem papers do not count. Recency weight
    w = DECAY ** |ref_year - year|.
  * Topic prior pi_t (normalised to sum 1): LECT_W * lecture share + (1 - LECT_W) * uniform, times
    (1 + IMP_BOOST) for topics on a seniors' list and (1 + CLASS_BOOST) for topics the class signal
    stresses (work/<scope>/class_signal.json, optional).
  * Topic marks share (Dirichlet-smoothed, ALPHA pseudo-papers):
        unit share   u_U = (sum_full w_p m_Up/M_p + ALPHA pi_U) / (sum_full w_p + ALPHA)
        within unit  r_t = (sum_{p covers U} w_p m_tp/M_p + ALPHA pi_t) / (sum_{p covers U} w_p m_Up/M_p + ALPHA pi_U)
        share_t = u_U * r_t        (for papers that cover everything this is one weighted average)
  * Question forms (clusters) inside a topic get shares the same way (FORM_ALPHA pseudo-questions,
    prior uniform within the topic, boosted by seniors' lists and class signal).
  * Monte-Carlo papers: the structure (compulsory Q1, any k of n optional questions, sub-parts and
    sub-part choice) is drawn from the real relevant papers (recency weighted); each sub-part gets a
    unit, topic and form from the shares; later sub-parts of a question keep the first one's unit with
    probability rho (estimated from the bank).
  * Planner: greedy by marginal expected *attainable* marks per minute of study (best k optional
    questions, best sub-parts), first to 3 h, then 6 h, then 12 h, so the plans are nested.
    p_safe = share of simulated papers where the plan still lets you answer at least half the marks of
    k optional questions.
  * Tiers are study order: A = 3 h plan, B = added by 6 h, C = added by 12 h, D = wildcard (never asked
    in a weighted paper, strong prior), E = the rest. P is shown as a percent only with >= 4 relevant
    papers, otherwise as a band (low < 25% <= med < 50% <= high).
Parameters come from _pipeline/model_params.json (written by backtest.py) when present.
"""
import argparse, datetime, json, os, re, statistics, sys
from collections import OrderedDict, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import workdir  # noqa: E402

DEFAULTS = {"decay": 0.8, "alpha": 2.0, "lect_w": 0.5, "imp_boost": 0.5, "form_alpha": 4.0,
            "cross_weight": 0.5, "class_boost": 1.0}
TUNED_KEYS = ("decay", "alpha", "lect_w", "imp_boost", "form_alpha")
# tests point this at a temp file; the real one is written by backtest.py
PARAMS_FILE = Path(os.environ.get("STUDYPREP_MODEL_PARAMS") or (workdir.PIPE / "model_params.json"))
# suggested per-subject PYQ windows (lead-owned); tests point this at a temp file
WINDOWS_FILE = Path(os.environ.get("STUDYPREP_PYQ_WINDOWS") or (workdir.PIPE / "pyq_windows.json"))
N_SIM, SEED = 3000, 20261105
BUDGETS = (("3h", 180), ("6h", 360), ("12h", 720))
SAFE_FRAC = 0.5          # an optional question is "answerable" if you can earn >= half its marks
WORDS_PER_MIN = 20
BANDS = ((0.50, "high"), (0.25, "med"), (0.0, "low"))
MIN_PAPERS_FOR_PERCENT = 4
MAX_PAPER_COLS = 3       # radar tables show the latest 3 papers as columns (4 if exactly 4), older ones summed: fits a phone page
DIAGRAM_RE = re.compile(r"\b(draw|diagram|sketch|timeline|flow ?chart|state transition|header format)\b", re.I)


# ----------------------------------------------------------------------------- small helpers
def tex(s):
    s = str(s)
    s = re.sub(r"\^\(([^)]*)\)", lambda m: "\x00SUP" + m.group(1) + "\x00END", s)
    s = re.sub(r"\^(\w+)", lambda m: "\x00SUP" + m.group(1) + "\x00END", s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")):
        s = s.replace(a, b)
    s = s.replace("/", r"\slash{}")          # lets long "A/B/C/D" runs break at the slash
    s = s.replace(r"\_", r"\_\allowbreak{}")  # long corpus slugs (PYQE_5th_Semester_...) break at underscores
    return s.replace("\x00SUP", r"\textsuperscript{").replace("\x00END", "}")


def band(p):
    for lo, name in BANDS:
        if p >= lo:
            return name
    return "low"


def paper_kind(p):
    return "midsem" if str(p.get("exam", "")).lower().startswith("mid") else "endsem"


def qkey(qno):
    """Main question of a sub-part: '3(a) [2nd Q3]' -> '3#2nd Q3', '1(c)' -> '1'."""
    s = str(qno)
    m = re.match(r"\s*Q?\s*(\d+)", s, re.I)
    k = m.group(1) if m else s.strip()
    b = re.search(r"\[(.*?)\]", s)
    return k + ("#" + b.group(1) if b else "")


def parse_minutes(s, scope):
    m = re.search(r"([\d.]+)\s*(h|hr|hrs|hour|hours|min|mins|minutes|m)\b", str(s or ""), re.I)
    if not m:
        return 90 if scope == "midsem" else 180
    v = float(m.group(1))
    return int(round(v * 60 if m.group(2).lower().startswith("h") else v))


def fmt(x):
    return f"{x:g}" if abs(x - round(x, 1)) < 1e-9 else f"{x:.1f}"


def load_params(subject, scope):
    """(params, source): subject-specific tuned > pooled > defaults."""
    p = dict(DEFAULTS)
    f = PARAMS_FILE
    if not f.exists():
        return p, "defaults (no model_params.json)"
    try:
        mp = json.loads(f.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"warning: model_params.json unreadable ({e}); using defaults", file=sys.stderr)
        return p, "defaults (model_params.json unreadable)"
    key = f"{subject}/{scope}"
    if key in mp.get("subjects", {}):
        p.update({k: v for k, v in mp["subjects"][key].items() if k in DEFAULTS})
        return p, f"model_params.json: {key} (shrunk toward the pooled mean)"
    if mp.get("pooled"):
        p.update({k: v for k, v in mp["pooled"].items() if k in DEFAULTS})
        return p, "model_params.json: pooled across subjects"
    return p, "defaults"


def backtest_entry(subject, scope):
    f = PARAMS_FILE
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text("utf-8")).get("backtest", {}).get(f"{subject}/{scope}")
    except (OSError, json.JSONDecodeError):
        return None


# ----------------------------------------------------------------------------- context
def load_ctx(work, scope):
    """Everything the model needs from blueprint.json, pyq_bank.json and class_signal.json."""
    work = Path(work)
    bp = json.loads((work / "blueprint.json").read_text("utf-8"))
    bank = json.loads((work / "pyq_bank.json").read_text("utf-8"))
    units, topics, torder = [], OrderedDict(), []
    for u in bp.get("units", []):
        if not u.get("in_scope", True):
            continue
        units.append({"id": u["id"], "title": u.get("title", ""), "midsem": u.get("midsem"),
                      "lectures": u.get("lectures") or sum(float(t.get("lectures") or 0) for t in u.get("topics", []))})
        for t in u.get("topics", []):
            topics[t["id"]] = dict(t, unit=u["id"], unit_title=u.get("title", ""))
            torder.append(t["id"])
    if not topics:
        raise ValueError("blueprint has no in-scope topics")
    uid = [u["id"] for u in units]
    imp = defaultdict(int)
    for i in bank.get("imp_list", []) or []:
        if i.get("cluster"):
            imp[i["cluster"]] += 1
    clusters = []
    for c in bank.get("clusters", []):
        if c.get("topic") in topics:
            clusters.append(dict(c, synthetic=False, imp=imp.get(c["id"], 0)))
    have = {c["topic"] for c in clusters}
    for tid in torder:  # a topic without any recorded form still needs something to study
        if tid not in have:
            clusters.append({"id": f"{tid}-any", "topic": tid, "label": f"Any question on: {topics[tid]['title']}",
                             "type": "theory", "effort_min": 30, "synthetic": True, "imp": 0})
    clusters.sort(key=lambda c: (torder.index(c["topic"]), c["id"]))
    cidx = {c["id"]: i for i, c in enumerate(clusters)}
    ctop = {c["id"]: c["topic"] for c in clusters}
    allq = list(bank.get("questions", []))
    qs = []
    for q in allq:
        if q.get("in_scope", True) and q.get("cluster") in cidx:
            qs.append(dict(q, topic=ctop[q["cluster"]], unit=topics[ctop[q["cluster"]]]["unit"]))
    sig = load_signal(work, topics, cidx)
    mid_units = None
    if scope == "endsem":
        sib = work.parent / "midsem" / "blueprint.json"
        if sib.exists():
            try:
                mb = json.loads(sib.read_text("utf-8"))
                mid_units = {u["id"] for u in mb.get("units", []) if u.get("in_scope", True)} & set(uid)
            except (OSError, json.JSONDecodeError, KeyError):
                mid_units = None
        if not mid_units:
            flagged = {u["id"] for u in units if u.get("midsem")}
            mid_units = flagged or None
    pat = bp.get("exam_pattern", {}) or {}
    papers = sorted(bank.get("papers", []), key=lambda p: (tkey(p), p["id"]))
    window = resolve_window(bp.get("pyq_window"), papers, scope, work.parent.parent.name)
    inwin = {p["id"] for p in papers if in_window(window, p)}
    return {"work": work, "scope": scope, "bp": bp, "bank": bank, "units": units, "uid": uid,
            "topics": topics, "torder": torder, "clusters": clusters, "cidx": cidx, "allq": allq,
            "qs": [q for q in qs if q["paper"] in inwin],     # papers outside the PYQ window are record only
            "papers": papers, "window": window, "pattern": pat, "signal": sig, "mid_units": mid_units}


def suggested_window(subject):
    """_pipeline/pyq_windows.json -> <SUBJ> (the lead's suggested windows), or None."""
    try:
        d = json.loads(WINDOWS_FILE.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    w = d.get(subject)
    return w if isinstance(w, dict) and "from" in w else None


def resolve_window(pw, papers, scope, subject=None):
    """The PYQ window (ROUND4_SPEC R4), inclusive years. Sources, in order:
    1. blueprint.pyq_window {from, to}
    2. _pipeline/pyq_windows.json -> <SUBJ> (from/to may be null: no window, e.g. a subject with no papers)
    3. the default rule: the latest 5 calendar years that have papers, extended back (by at most 5 more
       years) until the scope's own exam type has at least 3 relevant papers."""
    if isinstance(pw, dict) and pw.get("from") is not None:
        return {"from": int(pw["from"]), "to": int(pw.get("to") or 9999), "defaulted": False, "source": "blueprint",
                "why": pw.get("why", "blueprint.pyq_window")}
    sw = suggested_window(subject) if subject else None
    if sw is not None:
        frm, to = sw.get("from"), sw.get("to")
        return {"from": int(frm) if frm is not None else None, "to": int(to) if to is not None else 9999,
                "defaulted": False, "source": "pyq_windows.json", "why": sw.get("why", "pyq_windows.json")}
    years = [int(p["year"]) for p in papers if p.get("year") and float(p.get("weight", 1)) > 0]
    if not years:
        return {"from": None, "to": None, "defaulted": True, "source": "default", "why": "no papers: nothing to window"}
    to = max(years)
    frm = to - 4
    rel = sorted((int(p["year"]) for p in papers if p.get("year") and float(p.get("weight", 1)) > 0
                  and paper_kind(p) == scope), reverse=True)
    why = f"default: latest 5 calendar years with papers ({frm}-{to})"
    if sum(1 for y in rel if frm <= y <= to) < 3 and len(rel) >= 3 and rel[2] < frm:
        frm = max(to - 9, rel[2])
        why += f", extended back to {frm} to keep 3 relevant {scope} papers"
    return {"from": frm, "to": to, "defaulted": True, "source": "default", "why": why}


def in_window(window, p):
    if not window or window.get("from") is None:
        return True
    y = int(p.get("year") or 0)
    return window["from"] <= y <= window["to"]


def exclusion_reason(ctx, p):
    """Why a paper carries no weight (None if it counts)."""
    if not in_window(ctx["window"], p):
        return "outside window"
    if float(p.get("weight", 1.0)) <= 0:
        return "record only (weight 0)"
    if ctx["scope"] == "midsem" and paper_kind(p) != "midsem":
        return "endsem paper: does not define midsem odds"
    if not coverage(ctx, p):
        return "covers no in-scope unit"
    return None


def load_signal(work, topics, cidx):
    """class_signal.json (schemas.md): {"source", "signals": [{"text", "kind": stress|drop|pattern,
    "topics": [], "clusters": []}]}. stress boosts the prior of the listed topics/clusters; drop sets the
    topic (or idea) prior to ~0 and keeps it out of every plan; pattern is informational (printed in the
    radar). Unknown ids are reported and ignored; this file never blocks a run."""
    out = {"boost_t": set(), "boost_c": set(), "drop_t": set(), "drop_c": set(), "patterns": [], "notes": [],
           "source": None, "ignored": []}
    f = Path(work) / "class_signal.json"
    if not f.exists():
        return out
    try:
        d = json.loads(f.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        out["ignored"].append(f"class_signal.json unreadable: {e}")
        return out
    out["source"] = d.get("source", "class signal")
    for s in d.get("signals", []) or []:
        if not isinstance(s, dict):
            out["ignored"].append(f"signal is not an object: {s!r}")
            continue
        kind = str(s.get("kind", "stress")).lower()
        text = str(s.get("text", "")).strip()
        if kind == "pattern":
            out["patterns"].append(text)
            out["notes"].append(f"pattern: {text}")
            continue
        if kind not in ("stress", "drop"):
            out["ignored"].append(f"unknown signal kind {kind!r} ({text})")
            continue
        tids = [t for t in s.get("topics", []) or [] if t in topics]
        cids = [c for c in s.get("clusters", []) or [] if c in cidx]
        for x in [t for t in s.get("topics", []) or [] if t not in topics] + \
                 [c for c in s.get("clusters", []) or [] if c not in cidx]:
            out["ignored"].append(f"{kind}: unknown id {x}")
        out["boost_t" if kind == "stress" else "drop_t"].update(tids)
        out["boost_c" if kind == "stress" else "drop_c"].update(cids)
        if tids or cids:
            out["notes"].append(f"{kind} {', '.join(tids + cids)}: {text}")
    return out


def tkey(p):
    """Recency key (year, session) as a number: spring = year, autumn = year + 0.5."""
    y = float(p.get("year") or 0)
    return y + (0.5 if str(p.get("session", "")).lower().startswith("aut") else 0.0)


def coverage(ctx, p):
    """Set of in-scope unit ids this paper can tell us about.
    - a paper of the scope's own exam type: its `coverage` list if given, else every in-scope unit
    - midsem scope: an endsem paper never counts (endsem papers do not define midsem odds)
    - endsem scope: a midsem paper counts only for the units it examines (its `coverage`, else the
      sibling midsem blueprint's units, else the units its questions hit) and never for post-midsem units"""
    allu = set(ctx["uid"])
    if not in_window(ctx.get("window"), p):
        return set()          # outside the PYQ window: weight 0 everywhere, backtest folds included
    cov = p.get("coverage") or p.get("covers")
    kind = paper_kind(p)
    if kind == ctx["scope"]:
        return (set(cov) & allu) if cov else allu
    if ctx["scope"] == "midsem":
        return set()
    mid = ctx["mid_units"]
    if mid is None:
        mid = {q["unit"] for q in ctx["qs"] if q["paper"] == p["id"]}
    return (set(cov) & set(mid) & allu) if cov else (set(mid) & allu)


def paper_weights(ctx, prm, train=None, ref_year=None):
    """{pid: {"w", "cov", "full", "year"}} for papers with weight > 0. `year` is the recency key.
    w = DECAY ** |ref - key| * source relevance (paper `weight`: 1 same course, 0.5 similar, 0 record
    only) * CROSS_WEIGHT for a midsem paper in an endsem scope."""
    cand = []
    for p in ctx["papers"]:
        if train is not None and p["id"] not in train:
            continue
        cov = coverage(ctx, p)
        if cov:
            cand.append((p, cov))
    if not cand:
        return {}
    ref = ref_year if ref_year is not None else max(tkey(p) for p, _ in cand)
    out = {}
    for p, cov in cand:
        w = prm["decay"] ** abs(ref - tkey(p))
        w *= 1.0 if paper_kind(p) == ctx["scope"] else prm["cross_weight"]
        w *= float(p.get("weight", 1.0))
        if w > 0:
            out[p["id"]] = {"w": w, "cov": cov, "full": cov == set(ctx["uid"]) and paper_kind(p) == ctx["scope"],
                            "year": tkey(p)}
    return out


def topic_prior(ctx, prm):
    T = ctx["torder"]
    lec = {t: float(ctx["topics"][t].get("lectures") or 0) for t in T}
    known = [v for v in lec.values() if v > 0]
    fill = statistics.median(known) if known else 1.0
    lec = {t: (v if v > 0 else fill) for t, v in lec.items()}
    L = sum(lec.values())
    sig = ctx["signal"]
    boost_c_topics = {ctx["clusters"][ctx["cidx"][c]]["topic"] for c in sig["boost_c"]}
    raw = {}
    for t in T:
        v = prm["lect_w"] * lec[t] / L + (1 - prm["lect_w"]) / len(T)
        v *= 1 + prm["imp_boost"] * bool(ctx["topics"][t].get("senior_imp"))
        if t in sig["boost_t"]:
            v *= 1 + prm["class_boost"]
        elif t in boost_c_topics:
            v *= 1 + prm["class_boost"] / 2
        if t in sig["drop_t"]:
            v *= 1e-6
        raw[t] = v
    s = sum(raw.values())
    return {t: v / s for t, v in raw.items()}


# ----------------------------------------------------------------------------- the model
def fit(ctx, prm, train=None, ref_year=None, evidence=True):
    """Fit the topic marks model. evidence=False keeps the paper structure but ignores which topics
    were asked (the lecture-time-only baseline)."""
    W = paper_weights(ctx, prm, train, ref_year)
    T, U = ctx["torder"], ctx["uid"]
    unit_of = {t: ctx["topics"][t]["unit"] for t in T}
    pi = topic_prior(ctx, prm)
    piU = defaultdict(float)
    for t in T:
        piU[unit_of[t]] += pi[t]
    m_t = defaultdict(lambda: defaultdict(float))   # pid -> topic -> marks
    n_c = defaultdict(lambda: defaultdict(float))   # pid -> cluster -> count
    for q in ctx["qs"]:
        if q["paper"] in W and q["unit"] in W[q["paper"]]["cov"]:
            m_t[q["paper"]][q["topic"]] += float(q["marks"])
            n_c[q["paper"]][q["cluster"]] += 1
    M = {pid: sum(m_t[pid].values()) for pid in W}
    use = {pid: v for pid, v in W.items() if M[pid] > 0} if evidence else {}
    a = max(prm["alpha"], 1e-3)
    uS = {}
    num = {u: a * piU[u] for u in U}
    den = a
    for pid, v in use.items():
        if v["full"]:
            den += v["w"]
            for t, mk in m_t[pid].items():
                num[unit_of[t]] += v["w"] * mk / M[pid]
    for u in U:
        uS[u] = num[u] / den
    zs = sum(uS.values())
    uS = {u: x / zs for u, x in uS.items()}
    share = {}
    for t in T:
        u = unit_of[t]
        nt, dt = a * pi[t], a * piU[u]
        for pid, v in use.items():
            if u in v["cov"]:
                nt += v["w"] * m_t[pid].get(t, 0) / M[pid]
                dt += v["w"] * sum(mk for tt, mk in m_t[pid].items() if unit_of[tt] == u) / M[pid]
        share[t] = uS[u] * nt / dt
    for t in ctx["signal"]["drop_t"]:
        share[t] = 0.0
    z = sum(share.values()) or 1.0
    share = {t: s / z for t, s in share.items()}
    # forms within topics
    fa = max(prm["form_alpha"], 1e-3)
    form = {}
    by_topic = defaultdict(list)
    for c in ctx["clusters"]:
        by_topic[c["topic"]].append(c)
    for t, cl in by_topic.items():
        raw = {}
        for c in cl:
            v = 1 + prm["imp_boost"] * bool(c.get("imp"))
            if c["id"] in ctx["signal"]["drop_c"]:
                v *= 1e-6
            if c["id"] in ctx["signal"]["boost_c"]:
                v *= 1 + prm["class_boost"]
            raw[c["id"]] = v
        zr = sum(raw.values())
        num = {cid: fa * v / zr for cid, v in raw.items()}
        den = fa
        for pid, v in use.items():
            if unit_of[t] in v["cov"]:
                for cid in raw:
                    k = n_c[pid].get(cid, 0)
                    num[cid] += v["w"] * k
                    den += v["w"] * k
        form[t] = {cid: x / den for cid, x in num.items()}
    # structure templates and typical marks come only from weighted papers
    full = [pid for pid, v in W.items() if v["full"]]
    same = [p["id"] for p in ctx["papers"] if p["id"] in W and paper_kind(p) == ctx["scope"]]
    templates = [(structure(ctx, pid), W[pid]["w"]) for pid in same]
    templates = [(rescale(s, ctx["pattern"].get("full_marks")), w) for s, w in templates if s["groups"]]
    assumed = None
    if not templates:
        s, assumed = assumed_structure(ctx)
        templates = [(s, 1.0)]
    rho = estimate_rho(ctx, W if evidence else {}, uS)
    return {"prm": dict(prm), "W": W, "pi": pi, "unit_share": uS, "share": share, "form": form,
            "templates": templates, "assumed": assumed, "rho": rho, "n_full": len(full),
            "n_full_years": len({W[p]["year"] for p in full}), "unit_of": unit_of,
            "evidence": evidence}


def structure(ctx, pid):
    """Groups (main questions) of a real paper with choice rules: value, k_sub, compulsory."""
    paper = next(p for p in ctx["papers"] if p["id"] == pid)
    cmap = {q["id"]: q for q in ctx["qs"]}
    groups = OrderedDict()
    for q in ctx["allq"]:
        if q.get("paper") != pid:
            continue
        try:
            mk = float(q["marks"])
        except (TypeError, ValueError, KeyError):
            continue
        g = groups.setdefault(qkey(q.get("qno", q["id"])), {"compulsory": False, "parts": []})
        g["compulsory"] = g["compulsory"] or bool(q.get("compulsory"))
        iq = cmap.get(q["id"])
        g["parts"].append({"qid": q["id"], "cluster": iq["cluster"] if iq else None,
                           "topic": iq["topic"] if iq else None, "unit": iq["unit"] if iq else None,
                           "marks": mk})
    gl = list(groups.values())
    comp_total = sum(p["marks"] for g in gl if g["compulsory"] for p in g["parts"])
    opt = [g for g in gl if not g["compulsory"]]
    ch = paper.get("choose") or ctx["pattern"].get("choose") or {}
    k = int(ch.get("answer") or 0) or len(opt)
    k = min(k, len(opt))
    F = paper.get("full_marks") or ctx["pattern"].get("full_marks")
    val = (float(F) - comp_total) / k if (F and k) else None
    for g in gl:
        s = sum(p["marks"] for p in g["parts"])
        if g["compulsory"] or val is None or val <= 0:
            g["value"], g["k_sub"] = s, len(g["parts"])
            continue
        v = min(val, s)
        ms = [p["marks"] for p in g["parts"]]
        if s > v + 1e-6 and max(ms) - min(ms) < 1e-6:
            g["k_sub"] = max(1, int(round(v / ms[0])))
        else:
            g["k_sub"] = len(ms)
        g["value"] = v
    return {"pid": pid, "groups": gl, "k": k, "n": len(opt),
            "full_marks": float(F) if F else sum(g["value"] for g in gl if g["compulsory"]) + k * (val or 0)}


def rescale(struct, F):
    """Scale a past paper's structure to the current full marks (e.g. a 40-mark 2023 paper -> 20), so that
    simulated papers, expected marks and the exam-hall plan are on today's scale. Shape is kept."""
    try:
        F = float(F)
    except (TypeError, ValueError):
        return struct
    if not F or not struct.get("full_marks") or abs(struct["full_marks"] - F) < 1e-9:
        return struct
    f = F / struct["full_marks"]
    groups = [dict(g, value=g["value"] * f, parts=[dict(p, marks=p["marks"] * f) for p in g["parts"]])
              for g in struct["groups"]]
    return dict(struct, groups=groups, full_marks=F, scaled_from=struct["full_marks"])


def assumed_structure(ctx):
    """0 relevant papers: a pattern from the blueprint (or the KIIT default), labelled as assumed."""
    pat = ctx["pattern"]
    F = float(pat.get("full_marks") or (20 if ctx["scope"] == "midsem" else 50))
    ch = pat.get("choose") or {}
    n = len(ch.get("from") or []) or (4 if F <= 30 else 6)
    k = int(ch.get("answer") or 0) or (3 if F <= 30 else 4)
    c = 5 if F <= 30 else 10
    val = (F - c) / k
    gl = [{"compulsory": True, "value": float(c), "k_sub": c,
           "parts": [{"qid": None, "cluster": None, "topic": None, "unit": None, "marks": 1.0}] * c}]
    for _ in range(n):
        gl.append({"compulsory": False, "value": val, "k_sub": 2,
                   "parts": [{"qid": None, "cluster": None, "topic": None, "unit": None, "marks": val / 2}] * 2})
    src = (f"blueprint exam_pattern, assumed from {pat.get('source')}" if pat.get("choose") else
           f"KIIT default {ctx['scope']} pattern (no paper and no pattern in the blueprint)")
    return {"pid": None, "groups": gl, "k": k, "n": n, "full_marks": F}, src


def estimate_rho(ctx, W, uS):
    """P(a later sub-part keeps the first sub-part's unit), from optional questions of weighted papers."""
    same = pairs = 0
    for pid, v in W.items():
        if not v["full"]:
            continue
        for g in structure(ctx, pid)["groups"]:
            if g["compulsory"]:
                continue
            us = [p["unit"] for p in g["parts"] if p["unit"]]
            for x in us[1:]:
                pairs += 1
                same += x == us[0]
    ps = (same + 1.0) / (pairs + 2.0)
    B = sum(x * x for x in uS.values())
    if B >= 1 - 1e-9:
        return 0.5
    return float(min(0.95, max(0.0, (ps - B) / (1 - B))))


# ----------------------------------------------------------------------------- simulation
def pack(structs, C):
    """Padded arrays for a list of structures (each a dict from structure())."""
    G = max(len(s["groups"]) for s in structs)
    S = max(len(g["parts"]) for s in structs for g in s["groups"])
    N = len(structs)
    a = {"marks": np.zeros((N, G, S)), "clus": np.full((N, G, S), C, dtype=np.int64),
         "gval": np.zeros((N, G)), "gk": np.zeros((N, G), dtype=np.int64),
         "gcomp": np.zeros((N, G), dtype=bool), "gopt": np.zeros((N, G), dtype=bool),
         "kopt": np.zeros(N, dtype=np.int64), "nopt": np.zeros(N, dtype=np.int64),
         "valid": np.zeros((N, G, S), dtype=bool)}
    return a, G, S


def real_arrays(ctx, struct):
    C = len(ctx["clusters"])
    a, G, S = pack([struct], C)
    fill_struct(a, 0, struct)
    for gi, g in enumerate(struct["groups"]):
        for si, p in enumerate(g["parts"]):
            if p["cluster"] in ctx["cidx"]:
                a["clus"][0, gi, si] = ctx["cidx"][p["cluster"]]
    return a


def fill_struct(a, i, s):
    for gi, g in enumerate(s["groups"]):
        a["gval"][i, gi] = g["value"]
        a["gk"][i, gi] = g["k_sub"]
        a["gcomp"][i, gi] = g["compulsory"]
        a["gopt"][i, gi] = not g["compulsory"]
        for si, p in enumerate(g["parts"]):
            a["marks"][i, gi, si] = p["marks"]
            a["valid"][i, gi, si] = True
    a["kopt"][i] = s["k"]
    a["nopt"][i] = s["n"]


def simulate(ctx, model, n=N_SIM, seed=SEED):
    rng = np.random.default_rng(seed)
    C = len(ctx["clusters"])
    tw = np.array([w for _, w in model["templates"]], dtype=float)
    tw /= tw.sum()
    tidx = rng.choice(len(tw), size=n, p=tw)
    structs = [s for s, _ in model["templates"]]
    a, G, S = pack(structs, C)
    T = {k: v.copy() for k, v in a.items()}
    for i, s in enumerate(structs):
        fill_struct(T, i, s)
    sim = {k: v[tidx] for k, v in T.items()}
    U = ctx["uid"]
    us = np.array([model["unit_share"][u] for u in U])
    if us.sum() <= 0:
        us = np.ones(len(U))
    us = us / us.sum()
    unit = rng.choice(len(U), size=(n, G, S), p=us)
    keep = rng.random((n, G, S)) < model["rho"]
    for s_ in range(1, S):
        m = keep[:, :, s_] & ~sim["gcomp"]
        unit[:, :, s_] = np.where(m, unit[:, :, 0], unit[:, :, s_])
    topic = np.full((n, G, S), -1, dtype=np.int64)
    torder = ctx["torder"]
    tix = {t: i for i, t in enumerate(torder)}
    clus = np.full((n, G, S), C, dtype=np.int64)
    for ui, u in enumerate(U):
        ts = [t for t in torder if model["unit_of"][t] == u]
        ps = np.array([model["share"][t] for t in ts], dtype=float)
        mask = (unit == ui) & sim["valid"]
        k = int(mask.sum())
        if not k:
            continue
        if ps.sum() <= 0:   # every topic of the unit dropped: move those slots to other units' topics
            ts = torder
            ps = np.array([model["share"][t] for t in ts], dtype=float)
        ps = ps / ps.sum()
        topic[mask] = np.array([tix[t] for t in ts])[rng.choice(len(ts), size=k, p=ps)]
    for t in torder:
        mask = topic == tix[t]
        k = int(mask.sum())
        if not k:
            continue
        f = model["form"][t]
        cids = list(f)
        ps = np.array([f[c] for c in cids], dtype=float)
        ps /= ps.sum()
        clus[mask] = np.array([ctx["cidx"][c] for c in cids])[rng.choice(len(cids), size=k, p=ps)]
    sim["clus"] = np.where(sim["valid"], clus, C)
    sim["topic"] = np.where(sim["valid"], topic, -1)
    return sim


def attain(a, credit, rows=None, detail=False):
    """Attainable marks per paper (array) and the 'can still answer k optional questions' flags
    (plus the number of answerable optional questions per paper when detail=True)."""
    if rows is not None:
        a = {k: v[rows] for k, v in a.items()}
    cr = np.append(credit, 0.0)
    got = a["marks"] * cr[a["clus"]]
    srt = -np.sort(-got, axis=2)
    S = got.shape[2]
    take = np.arange(S)[None, None, :] < a["gk"][:, :, None]
    g = np.minimum((srt * take).sum(2), a["gval"])
    comp = (g * a["gcomp"]).sum(1)
    opt = np.where(a["gopt"], g, -1.0)
    so = -np.sort(-opt, axis=1)
    G = got.shape[1]
    takeo = np.arange(G)[None, :] < a["kopt"][:, None]
    tot = comp + (np.clip(so, 0, None) * takeo).sum(1)
    ans = ((g >= SAFE_FRAC * a["gval"] - 1e-9) & a["gopt"] & (a["gval"] > 0)).sum(1)
    if detail:
        return tot, ans >= a["kopt"], ans
    return tot, ans >= a["kopt"]


def greedy_plan(ctx, sim, budgets=BUDGETS):
    """Nested greedy plans: maximise expected attainable marks per minute, stage by stage."""
    C = len(ctx["clusters"])
    N = sim["marks"].shape[0]
    eff = np.array([float(c.get("effort_min") or 30) for c in ctx["clusters"]])
    rows = [np.nonzero((sim["clus"] == i).any(axis=(1, 2)))[0] for i in range(C)]
    sig = ctx["signal"]
    blocked = [c["id"] in sig["drop_c"] or c["topic"] in sig["drop_t"] for c in ctx["clusters"]]
    credit = np.zeros(C)
    cur, _ = attain(sim, credit)
    chosen, steps, used = [], [], 0.0
    plans = OrderedDict()
    for name, B in budgets:
        while True:
            best = None
            for i in range(C):
                if credit[i] or blocked[i] or eff[i] > B - used + 1e-9 or not len(rows[i]):
                    continue
                cr = credit.copy()
                cr[i] = 1.0
                new, _ = attain(sim, cr, rows[i])
                gain = float((new - cur[rows[i]]).sum()) / N
                r = gain / eff[i]
                if gain > 1e-4 and (best is None or r > best[0] + 1e-12):
                    best = (r, i, gain, new)
            if best is None:
                break
            _, i, gain, new = best
            credit[i] = 1.0
            cur[rows[i]] = new
            used += eff[i]
            chosen.append(i)
            steps.append({"cluster": ctx["clusters"][i]["id"], "gain": round(gain, 3), "stage": name})
        tot, safe = attain(sim, credit)
        plans[name] = {"idx": list(chosen), "minutes": int(round(used)),
                       "expected_marks": round(float(tot.mean()), 2), "p_safe": round(float(safe.mean()), 3)}
    return plans, steps


def plan_credit(ctx, cids):
    cr = np.zeros(len(ctx["clusters"]))
    for c in cids:
        if c in ctx["cidx"]:
            cr[ctx["cidx"][c]] = 1.0
    return cr


def score_real(ctx, pid, cids, topic_level=False):
    """Fraction of a real paper's attainable marks a plan covers, plus the share of printed marks."""
    st = structure(ctx, pid)
    a = real_arrays(ctx, st)
    C = len(ctx["clusters"])
    if topic_level:
        tops = {ctx["clusters"][ctx["cidx"][c]]["topic"] for c in cids if c in ctx["cidx"]}
        cids = [c["id"] for c in ctx["clusters"] if c["topic"] in tops]
    cr = plan_credit(ctx, cids)
    got, safe = attain(a, cr)
    mx, _ = attain(a, np.ones(C))
    printed = sum(p["marks"] for g in st["groups"] for p in g["parts"])
    pc = sum(p["marks"] for g in st["groups"] for p in g["parts"] if p["cluster"] in set(cids))
    return {"attain": float(got[0] / mx[0]) if mx[0] else 0.0, "printed": pc / printed if printed else 0.0,
            "safe": bool(safe[0]), "marks": float(got[0]), "max": float(mx[0])}


# ----------------------------------------------------------------------------- run
def run_model(ctx, prm, n_sim=N_SIM, seed=SEED, train=None, ref_year=None, evidence=True):
    model = fit(ctx, prm, train, ref_year, evidence)
    sim = simulate(ctx, model, n_sim, seed)
    plans, steps = greedy_plan(ctx, sim)
    C = len(ctx["clusters"])
    present = np.stack([(sim["clus"] == i).any(axis=(1, 2)) for i in range(C)], 1)
    compmask = sim["gcomp"][:, :, None] & sim["valid"]
    present_q1 = np.stack([((sim["clus"] == i) & compmask).any(axis=(1, 2)) for i in range(C)], 1)
    fac = np.where(sim["gcomp"], 1.0, sim["kopt"][:, None] / np.maximum(sim["nopt"][:, None], 1))
    ev = np.stack([((sim["clus"] == i) * sim["marks"] * fac[:, :, None]).sum((1, 2)) for i in range(C)], 1)
    T = ctx["torder"]
    tpres = np.stack([(sim["topic"] == j).any(axis=(1, 2)) for j in range(len(T))], 1)
    tmarks = np.stack([((sim["topic"] == j) * sim["marks"]).sum((1, 2)) for j in range(len(T))], 1)
    allc, _ = attain(sim, np.ones(C))
    model.update({"P_c": present.mean(0), "P_q1": present_q1.mean(0), "EV_c": ev.mean(0),
                  "P_t": tpres.mean(0), "marks_t": tmarks.mean(0), "plans": plans, "steps": steps,
                  "max_marks": float(allc.mean()), "n_sim": n_sim, "seed": seed,
                  "full_marks": float(np.mean([s["full_marks"] for s, _ in model["templates"]]))})
    return model


def explain(prm, n_sim, n_papers, show_percent, rho):
    """The one paragraph printed in the guide."""
    pct = ("Chances are shown as percentages." if show_percent else
           f"With only {n_papers} relevant past paper{'s' if n_papers != 1 else ''} the chance a topic or idea "
           "appears is shown as a band (low under 25\\%, med 25--49\\%, high 50\\% or more), not a percentage.")
    if n_papers == 0:   # zero-paper subject (real SVP, 2026-11-06): say only what the model really used
        return (r"\textbf{How these plans are made.} No past paper exists, so each topic's share of the marks comes "
                r"from its lecture time alone. Inside each topic every question idea gets an equal share. From these "
                rf"shares we draw {n_sim} plausible papers with the \emph{{assumed}} pattern's structure (compulsory "
                r"Q1, any $k$ of $n$ optional questions). The plans are built greedily: each step adds the idea that "
                r"most raises your expected \emph{attainable} marks per minute of study, first up to 3 hours, then 6, "
                r"then 12, so every plan contains the shorter one. $p_{\mathrm{safe}}$ is the share of simulated papers "
                r"on which the plan still lets you earn at least half the marks of $k$ optional questions. Tiers are "
                r"study order: A is the 3 h plan, B is added by 6 h, C by 12 h, D are wildcards (heavily taught, "
                r"outside the 12 h plan), E the rest. " + pct)
    return (r"\textbf{How these plans are made.} Each topic's share of the paper's marks is the recency-weighted "
            rf"average of its share in the past papers that covered its unit (a paper $y$ years older counts "
            rf"${prm['decay']:.2g}^y$ as much), blended with a prior worth {prm['alpha']:.2g} papers that comes "
            r"from lecture time and the seniors' lists. Inside each topic, each question form (idea) gets a "
            rf"share the same way. From these shares we draw {n_sim} plausible papers with the real paper "
            r"structure (compulsory Q1, any $k$ of $n$ optional questions, sub-part choices; later sub-parts of "
            rf"a question stay in the first one's unit {round(100 * rho)}\% of the time). The plans are built "
            r"greedily: each step adds the idea that most raises your expected \emph{attainable} marks (what "
            r"you could score answering the best $k$ optional questions with what you have studied) per minute "
            r"of study, first up to 3 hours, then 6, then 12, so every plan contains the shorter one. "
            r"$p_{\mathrm{safe}}$ is the share of simulated papers on which the plan still lets you earn at "
            r"least half the marks of $k$ optional questions. Tiers are study order: A is the 3 h plan, B is "
            r"added by 6 h, C by 12 h, D are wildcards (never asked, heavily taught), E the rest. " + pct)


def main():
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("subject")
    ap.add_argument("--scope")
    ap.add_argument("--n-sim", type=int, default=N_SIM)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    subj, _shared, work = workdir.resolve(a.subject, a.scope)
    scope = work.name                     # never from blueprint.json
    errs = [f"missing {work / f}" for f in ("blueprint.json", "pyq_bank.json") if not (work / f).exists()]
    if errs:
        print("RESULT BLOCKED: " + "; ".join(errs))
        return 1
    try:
        ctx = load_ctx(work, scope)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"RESULT BLOCKED: cannot read inputs ({e})")
        return 1
    win = ctx["window"]
    span = f"{win['from']}-{win['to']}" if win["from"] is not None else "none (all papers)"
    if win["defaulted"]:
        print(f"pyq_window defaulted: {span} ({win['why']}); set blueprint.pyq_window to override")
    else:
        print(f"pyq_window {span} from {win['source']} ({win['why']})")
    prm, psrc = load_params(subj.name, scope)
    model = run_model(ctx, prm, a.n_sim, a.seed)
    out = build_outputs(ctx, model, subj.name, scope, psrc)
    write_outputs(ctx, model, out, subj.name, scope)
    for w in ctx["signal"]["ignored"]:
        print("warning:", w)
    print_summary(ctx, model, out)
    print("RESULT PASS")
    return 0


# ----------------------------------------------------------------------------- outputs
def build_outputs(ctx, model, subject, scope, psrc):
    cl, T = ctx["clusters"], ctx["torder"]
    W = model["W"]
    n_rel = model["n_full_years"]
    show_pct = n_rel >= MIN_PAPERS_FOR_PERCENT
    plans = model["plans"]
    stage_of = {}
    prev = set()
    for name, _ in BUDGETS:
        for i in plans[name]["idx"]:
            if i not in prev:
                stage_of[i] = name
        prev = set(plans[name]["idx"])
    tier_of_stage = {"3h": "A", "6h": "B", "12h": "C"}
    weighted_q = [q for q in ctx["qs"] if q["paper"] in W and q["unit"] in W[q["paper"]]["cov"]]
    by_c = defaultdict(list)
    for q in weighted_q:
        by_c[q["cluster"]].append(q)
    opt_marks = [float(q["marks"]) for q in weighted_q if not q.get("compulsory")]
    if not opt_marks:
        s0 = current_template(model)
        opt_marks = [p["marks"] for g in s0["groups"] if not g["compulsory"] for p in g["parts"]]
    default_m = statistics.mode(opt_marks) if opt_marks else 2.5
    pi = model["pi"]
    strong = statistics.median(pi.values()) if pi else 0
    gain_of = {s["cluster"]: s["gain"] for s in model["steps"]}
    sig = ctx["signal"]

    def dropped(c):
        return c["id"] in sig["drop_c"] or c["topic"] in sig["drop_t"]
    rows = []
    for i, c in enumerate(cl):
        cq = by_c.get(c["id"], [])
        per = defaultdict(float)
        for q in cq:
            per[q["paper"]] += float(q["marks"])
        m = statistics.median(per.values()) if per else default_m
        P = float(model["P_c"][i])
        if i in stage_of:
            tier = tier_of_stage[stage_of[i]]
        elif dropped(c):
            tier = "E"
        elif not cq and not c["synthetic"] and (pi[c["topic"]] >= strong or c.get("imp") or
                                                c["id"] in sig["boost_c"] or c["topic"] in sig["boost_t"]):
            tier = "D"
        else:
            tier = "E"
        ev = float(model["EV_c"][i])
        eff = float(c.get("effort_min") or 30)
        allq = [q for q in ctx["qs"] if q["cluster"] == c["id"]]
        asked = defaultdict(list)
        for q in allq:
            asked[q["paper"]].append(f"Q{q.get('qno', '')}")
        t = ctx["topics"][c["topic"]]
        rows.append({
            "cluster": c["id"], "label": c["label"], "topic": c["topic"], "topic_title": t.get("title", ""),
            "unit": t["unit"], "type": c.get("type", ""), "P": round(P, 3), "band": band(P),
            "P_display": f"{round(100 * P)}%" if show_pct else band(P),
            "P_q1": round(float(model["P_q1"][i]), 3),
            "prior": round(pi[c["topic"]] * model["form"][c["topic"]].get(c["id"], 0), 4),
            "form_share": round(model["form"][c["topic"]].get(c["id"], 0), 3),
            "typical_marks": m, "compulsory": any(q.get("compulsory") for q in cq),
            "EV": round(ev, 2), "effort_min": int(eff), "yield_per_30min": round(ev / (eff / 30), 2),
            "tier": tier, "plan": stage_of.get(i), "plan_gain": gain_of.get(c["id"]),
            "asked": [f"{pid} " + ", ".join(v) for pid, v in sorted(asked.items())],
            "asked_weighted": sorted(per), "question_ids": [q["id"] for q in allq],
            "in_imp_list": bool(c.get("imp")), "class_signal": c["id"] in sig["boost_c"], "dropped": dropped(c),
            "synthetic": c["synthetic"], "index_only": tier == "E"})
    trows = []
    tier_rank = "ABCDE"
    for j, tid in enumerate(T):
        t = ctx["topics"][tid]
        mk = defaultdict(float)
        for q in weighted_q:
            if q["topic"] == tid:
                mk[q["paper"]] += float(q["marks"])
        P = float(model["P_t"][j])
        ts = [r["tier"] for r in rows if r["topic"] == tid]
        trows.append({"topic": tid, "title": t.get("title", ""), "unit": t["unit"], "P": round(P, 3),
                      "band": band(P), "P_display": f"{round(100 * P)}%" if show_pct else band(P),
                      "share": round(model["share"][tid], 4), "expected_marks": round(float(model["marks_t"][j]), 2),
                      "prior": round(pi[tid], 4), "papers": sorted(mk), "marks_by_paper": dict(mk),
                      "tier": min(ts, key=tier_rank.index) if ts else "E",
                      "class_signal": tid in sig["boost_t"], "dropped": tid in sig["drop_t"]})
    plans_out = OrderedDict()
    for name, _ in BUDGETS:
        p = plans[name]
        cids = [cl[i]["id"] for i in p["idx"]]
        plans_out[name] = {"clusters": cids, "topics": [t for t in T if any(cl[i]["topic"] == t for i in p["idx"])],
                           "minutes": p["minutes"], "expected_marks": p["expected_marks"],
                           "of_marks": round(model["full_marks"], 1), "p_safe": p["p_safe"]}
    pat = ctx["pattern"]
    out = OrderedDict()
    k = current_template(model)["k"]
    n = current_template(model)["n"]
    out["model"] = {
        "version": "r4-planner", "scope": scope, **{k_: model["prm"][k_] for k_ in DEFAULTS},
        "params_source": psrc, "n_sim": model["n_sim"], "seed": model["seed"], "same_unit_rho": round(model["rho"], 3),
        "papers_used": {pid: round(v["w"], 4) for pid, v in W.items()},
        "papers_full_coverage": sorted(pid for pid, v in W.items() if v["full"]),
        "papers_excluded": {p["id"]: exclusion_reason(ctx, p) for p in ctx["papers"] if p["id"] not in W},
        "pyq_window": dict(ctx["window"]),
        "n_relevant_papers": n_rel, "p_display": "percent" if show_pct else "band",
        "pattern_assumed": bool(model["assumed"]), "pattern_source": model["assumed"] or pat.get("source", ""),
        "choice": {"answer": k, "from": n}, "safe_rule": f"answer >= {SAFE_FRAC:g} of the marks of k optional questions",
        "max_attainable": round(model["max_marks"], 2), "full_marks": round(model["full_marks"], 1),
        "unit_share": {u: round(v, 4) for u, v in model["unit_share"].items()},
        "class_signal": {"source": sig["source"], "notes": sig["notes"], "patterns": sig["patterns"],
                         "ignored": sig["ignored"]},
        "explanation": explain(model["prm"], model["n_sim"], n_rel, show_pct, model["rho"]),
        "note": ("No relevant past paper: P is the prior only and the paper pattern is assumed."
                 if not W else f"{n_rel} relevant paper year(s); treat P as indicative."),
    }
    out["clusters"] = rows
    out["topics"] = trows
    out["plans"] = plans_out
    out["units"] = [{"unit": u["id"], "title": u["title"], "share": round(model["unit_share"][u["id"]], 4),
                     "expected_marks": round(sum(r["expected_marks"] for r in trows if r["unit"] == u["id"]), 2)}
                    for u in ctx["units"]]
    # Q1 drill: every in-window 1-mark PYQ (of a relevant source) + min(30, 2 x one-mark clusters) predicted ideas
    usable = {p["id"] for p in ctx["papers"] if in_window(ctx["window"], p) and float(p.get("weight", 1.0)) > 0}
    uq = [q for q in ctx["qs"] if q["paper"] in usable]
    oneq = [q for q in uq if float(q["marks"]) <= 1]
    # the newest 1-mark PYQ of each one-mark idea (real ML endsem: every 1-mark PYQ of 24 papers made a 177-item drill)
    pkey = {p["id"]: (p.get("year") or 0, 1 if (p.get("session") or "autumn") == "autumn" else 0) for p in ctx["papers"]}
    newest = {}
    for q in oneq:
        c = q["cluster"]
        if c not in newest or pkey.get(q["paper"], (0, 0)) > pkey.get(newest[c]["paper"], (0, 0)):
            newest[c] = q
    one = sorted(q["id"] for q in newest.values())
    n_pred = min(30, 2 * len({q["cluster"] for q in oneq}))
    order = np.argsort(-model["P_q1"], kind="stable")
    pred = [cl[i]["id"] for i in order if model["P_q1"][i] > 0 and not cl[i]["synthetic"]][:n_pred]
    if not oneq:
        # No one-mark past question in the window (e.g. 0 papers): the (assumed) pattern still has a compulsory
        # Q1 of one-mark parts, so predict 3 ideas per part from the overall P (real SVP endsem, 2026-11-06).
        q1_parts = sum(1 for g in assumed_structure(ctx)[0]["groups"] if g["compulsory"]
                       for p in g["parts"] if float(p["marks"]) <= 1)
        n_pred = min(30, 3 * q1_parts)
        order = np.argsort(-model["P_c"], kind="stable")
        ranked = [i for i in order if not cl[i]["synthetic"]]
        # spread over units by the model's unit share, at least one item per unit (real SVP: the top-30 by P were
        # 28 video ideas and no Module II item)
        t2u = {t: ctx["topics"][t]["unit"] for t in ctx["topics"]}
        units = [u["id"] for u in ctx["units"] if any(t2u.get(cl[i]["topic"]) == u["id"] for i in ranked)]
        share = {u: float(model["unit_share"].get(u, 0)) for u in units}
        tot = sum(share.values()) or 1.0
        quota = {u: max(1, int(round(n_pred * share[u] / tot))) for u in units}
        while sum(quota.values()) > n_pred and any(q > 1 for q in quota.values()):
            quota[max(quota, key=lambda u: quota[u])] -= 1
        pred, taken = [], {u: 0 for u in units}
        for i in ranked:
            u = t2u.get(cl[i]["topic"])
            if u in taken and taken[u] < quota[u]:
                pred.append(cl[i]["id"]); taken[u] += 1
        for i in ranked:                      # top up to n_pred if a unit ran out of ideas
            if len(pred) >= n_pred:
                break
            if cl[i]["id"] not in pred:
                pred.append(cl[i]["id"])
        pred = pred[:n_pred]
    out["q1_drill"] = {"question_ids": one, "clusters": pred}
    # must draw
    md_q = [q["id"] for q in uq if q.get("type") == "diagram" or DIAGRAM_RE.search(q.get("text", ""))]
    md_c = [c["id"] for c in cl if c.get("type") == "diagram" or
            any(q["cluster"] == c["id"] for q in uq if q["id"] in md_q)]
    out["must_draw"] = {"question_ids": md_q, "clusters": md_c}
    out["skip_safety"] = skip_safety(ctx, model)
    out["exam_hall"] = exam_hall(ctx, model, weighted_q)
    out["targets"] = targets(ctx, model, out, weighted_q, n_pred)
    out["backtest"] = backtest_entry(subject, scope)
    return out


def targets(ctx, model, out, weighted_q, n_pred):
    """Subject-scaled sizes (ROUND4_SPEC R4 section 2), each with a `why`."""
    plan12 = out["plans"]["12h"]["clusters"]
    wild = sorted((r for r in out["clusters"] if r["tier"] == "D"), key=lambda r: -r["EV"])[:5]
    iqc = plan12 + [r["cluster"] for r in wild]
    tot = sum(float(q["marks"]) for q in weighted_q)
    if tot > 0:
        share = {u["id"]: sum(float(q["marks"]) for q in weighted_q if q["unit"] == u["id"]) / tot for u in ctx["units"]}
        src = "of the window's in-scope PYQ marks"
    else:
        share = dict(model["unit_share"])
        src = "of the expected marks (prior only: no paper in the window)"
    mean = sum(share.values()) / max(len(share), 1)
    notes = OrderedDict()
    for u in ctx["units"]:
        f = min(2.0, max(1.0, 1.0 + share[u["id"]] / mean)) if mean > 0 else 1.0
        pages = round(float(u["lectures"]) * f + 1, 1)
        notes[u["id"]] = {"title": u["title"], "pages": pages, "lectures": u["lectures"], "share": round(share[u["id"]], 4),
                          "why": (f"{fmt(float(u['lectures']))} lectures x {f:.2f} (this unit holds {round(100 * share[u['id']])}% "
                                  f"{src}; the mean unit holds {round(100 * mean)}%) + 1")}
    n_topics = len(ctx["torder"])
    num = (sum(float(q["marks"]) for q in weighted_q if q.get("type") == "numerical") / tot) if tot > 0 else 0.0
    cs = 2 + (n_topics > 20) + (num > 0.40)
    one = out["q1_drill"]["question_ids"]
    return {
        "iq_clusters": {"count": len(iqc), "clusters": iqc,
                        "why": f"the 12 h plan's {len(plan12)} ideas plus {len(wild)} tier-D wildcard(s) (at most 5); "
                               f"tier E ideas get a one-line index entry only"},
        "notes_pages": notes,
        "cheatsheet_pages": {"pages": cs, "topics": n_topics, "numerical_share": round(num, 3),
                             "why": f"2 + {int(n_topics > 20)} ({n_topics} in-scope topics, more than 20?) + {int(num > 0.40)} "
                                    + (f"(numericals are {round(100 * num)}% of the window's marks, more than 40%?); "
                                       if one or ctx["qs"] else "(no past paper, so no numerical share); ") +
                                    f"landscape pages, not counting the night-before sheet"},
        "q1_drill": {"question_ids": one, "clusters": out["q1_drill"]["clusters"], "count": len(one) + len(out["q1_drill"]["clusters"]),
                     "why": (f"the newest in-window 1-mark past question of each one-mark idea ({len(one)}) plus min(30, 2 x "
                             f"{len({q['cluster'] for q in ctx['qs'] if q['id'] in set(one)})} one-mark ideas) = "
                             f"{n_pred} predicted items") if one else
                            (f"no one-mark past question in the window: 3 predicted ideas per compulsory one-mark Q1 "
                             f"part of the (assumed) pattern, at most 30 = {len(out['q1_drill']['clusters'])} items")},
    }


def skip_safety(ctx, model):
    W = model["W"]
    C = len(ctx["clusters"])
    full = [pid for pid, v in W.items() if v["full"]]
    sim = simulate(ctx, model, min(model["n_sim"], 2000), model["seed"] + 1)
    out = OrderedDict()
    for u in ctx["units"]:
        cr = np.array([0.0 if ctx["topics"][c["topic"]]["unit"] == u["id"] else 1.0 for c in ctx["clusters"]])
        per = OrderedDict()
        for pid in full:
            st = structure(ctx, pid)
            a = real_arrays(ctx, st)
            got, _, ok = attain(a, cr, detail=True)
            per[pid] = {"answerable": int(ok[0]), "n": st["n"], "need": st["k"], "marks_left": round(float(got[0]), 2),
                        "max": round(float(attain(a, np.ones(C))[0][0]), 2)}
        _, safe = attain(sim, cr)
        n_ok = sum(1 for v in per.values() if v["answerable"] >= v["need"])
        txt = "; ".join(f"{pid}: {v['answerable']} of {v['n']} (need {v['need']})" for pid, v in per.items())
        out[u["id"]] = {"title": u["title"], "papers": per, "safe_papers": n_ok, "total_papers": len(per),
                        "p_safe_mc": round(float(safe.mean()), 3),
                        "text": (f"If you skip {u['title']}, you could still answer: {txt}." if per else
                                 f"If you skip {u['title']}: no past paper to check; simulated p_safe "
                                 f"{round(100 * float(safe.mean()))}%.")}
    return out


def current_template(model):
    """The current exam structure: the highest-weight template (recency-weighted, so the newest paper; ties
    go to the later paper). Templates come in paper order, oldest first, so templates[0] was the OLDEST
    paper's pattern (DAA endsem 2026-11-08: 8-mark optionals from a 3 h paper; the current one has 10)."""
    t = model["templates"]
    best = max(range(len(t)), key=lambda i: (t[i][1], i))
    return t[best][0]


def exam_hall(ctx, model, weighted_q):
    pat = ctx["pattern"]
    dur = parse_minutes(pat.get("duration") or (ctx["papers"][-1].get("duration") if ctx["papers"] else None),
                        ctx["scope"])
    F = model["full_marks"] or 20
    reserve = 10 if dur <= 120 else 15
    mpm = round((dur - reserve) / F, 1)
    fm = {p["id"]: p.get("full_marks") for p in ctx["papers"]}
    vals = sorted({float(q["marks"]) for q in weighted_q          # marks values of papers on today's scale only
                   if not fm.get(q["paper"]) or abs(float(fm[q["paper"]]) - F) < 1e-9})
    s0 = current_template(model)
    vals = sorted(set(vals) | {p["marks"] for g in s0["groups"] for p in g["parts"]} |
                  {round(g["value"], 2) for g in s0["groups"] if not g["compulsory"]})
    budgets = OrderedDict()
    for v in vals:
        budgets[fmt(v)] = {"minutes": round(v * mpm, 1), "words": int(round(v * mpm * WORDS_PER_MIN, -1)),
                           "template": answer_template(v)}
    comp = sum(g["value"] for g in s0["groups"] if g["compulsory"])
    optv = [g["value"] for g in s0["groups"] if not g["compulsory"]]
    ov = statistics.median(optv) if optv else 0
    plan = [{"step": "Read the whole paper; pick the optional questions your plan covers", "minutes": 5}]
    if comp:
        plan.append({"step": f"Q1 / compulsory part ({fmt(comp)} marks)", "minutes": round(comp * mpm)})
    for i in range(s0["k"]):
        plan.append({"step": f"Optional question {i + 1} ({fmt(ov)} marks)", "minutes": round(ov * mpm)})
    plan.append({"step": "Check numbers, units, diagram labels; fill blanks", "minutes": max(0, reserve - 5)})
    return {"duration_min": dur, "full_marks": F, "reserve_min": reserve, "min_per_mark": mpm,
            "words_per_min": WORDS_PER_MIN, "budgets": budgets, "plan": plan,
            "numerical_template": "Given (with units) -> formula -> substitution -> boxed answer with unit -> one-line meaning"}


def answer_template(m):
    if m <= 1:
        return "One crisp sentence that answers exactly what is asked, plus one supporting fact, formula or example. No introduction."
    if m <= 2.5:
        return "Definition line; 3-4 points or the formula with a worked substitution; a small labelled sketch if the topic has one."
    if m <= 3.5:
        return "Definition; labelled diagram or timeline; 4-5 points or full working with units; boxed answer."
    if m <= 5:
        return "Intro line; labelled diagram; 5-6 points under sub-headings (or full working); example or comparison table; one-line conclusion."
    return "Headings; diagram; 6-8 points; worked example; comparison or table; conclusion."


def write_outputs(ctx, model, out, subject, scope):
    work = ctx["work"]
    (work / "important_questions.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    show = out["model"]["p_display"] == "percent"
    B = ["% generated by score.py on every run: do not edit",
         "% \\sgdefbadge{cluster}{tier}{P% or -}{band}{EV}   \\sgdeftopic{topic}{P% or -}{band}"]
    for r in out["clusters"]:
        if r["synthetic"]:
            continue
        B.append(rf"\sgdefbadge{{{r['cluster']}}}{{{r['tier']}}}{{{round(100 * r['P']) if show else '-'}}}"
                 rf"{{{r['band']}}}{{{r['EV']:.2f}}}")
    for t in out["topics"]:
        B.append(rf"\sgdeftopic{{{t['topic']}}}{{{round(100 * t['P']) if show else '-'}}}{{{t['band']}}}")
    (work / "badges.tex").write_text("\n".join(B) + "\n", encoding="utf-8")
    (work / "chapters").mkdir(parents=True, exist_ok=True)
    (work / "chapters" / "20_exam_radar.tex").write_text(radar_tex(ctx, model, out), encoding="utf-8")
    (work / "chapters" / "05_how_to_use.tex").write_text(howto_tex(ctx, model, out), encoding="utf-8")
    snap = work / "plan_snapshots"
    snap.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    s = {"date": today, "subject": subject, "scope": scope, "model": {k: out["model"][k] for k in
         ("version", "params_source", "papers_used", "n_relevant_papers", "same_unit_rho", *DEFAULTS)},
         "plans": out["plans"], "clusters": {r["cluster"]: {"P": r["P"], "tier": r["tier"]} for r in out["clusters"]},
         "topics": {t["topic"]: {"P": t["P"], "share": t["share"]} for t in out["topics"]}}
    (snap / f"{today}.json").write_text(json.dumps(s, indent=1), encoding="utf-8")


def backtest_line(out):
    bt = out.get("backtest")
    if not bt or not bt.get("summary"):
        return r"\textbf{Track record:} not yet backtested (needs at least 3 past papers of this exam)."
    s = bt["summary"]
    def g(m, key="cover_6h"):
        v = s.get(m, {}).get(key)
        return v if v else None
    new, lec, uni = g("new"), g("lecture"), g("uniform")
    txt = (rf"\textbf{{Track record:}} tested on {bt.get('n_folds', '?')} held-out past papers (each predicted from "
           rf"the others): the 6\,h plan covered {round(100 * new['mean'])}\% of the attainable marks "
           rf"(range {round(100 * new['min'])}--{round(100 * new['max'])}\%)")
    extra = []
    if lec:
        extra.append(rf"{round(100 * lec['mean'])}\% for a plan from lecture time alone")
    if uni:
        extra.append(rf"{round(100 * uni['mean'])}\% for random ideas")
    if extra:
        txt += ", against " + " and ".join(extra)
    txt += "."
    if bt.get("n_folds", 0) < 6:
        txt += r" With this few papers the numbers are indicative only."
    return txt


def paper_cols(pids):
    """Paper columns that fit any page width: the latest MAX_PAPER_COLS papers, older ones summed."""
    if len(pids) <= MAX_PAPER_COLS + 1:
        return list(pids), []
    return list(pids[-MAX_PAPER_COLS:]), list(pids[:-MAX_PAPER_COLS])


def phead(pid):
    """Two-line header for a paper id ('MS2024' -> MS over 2024) so numeric columns stay narrow."""
    m = re.match(r"^([A-Za-z_-]+?)(\d{2,4}.*)$", pid)
    if m:
        return rf"\thead{{{tex(m.group(1))}\\{tex(m.group(2))}}}"
    return rf"\thead{{{tex(pid)}}}"


def heat_cells(mk):
    if mk:
        return rf"\cellcolor{{sgamber!{min(70, int(15 + 12 * mk))}}}{mk:g}"
    return r"\textcolor{muted}{--}"


def radar_tex(ctx, model, out):
    W = model["W"]
    pids = [p["id"] for p in ctx["papers"] if p["id"] in W]
    shown, older = paper_cols(pids)
    F = out["model"]["full_marks"]
    L = [r"\chapter{Exam Radar: where the marks are}", r"\label{ch:radar}"]
    has_imp = bool(ctx.get("bank", {}).get("imp_list")) if isinstance(ctx.get("bank"), dict) else False
    if not pids:
        L.append(r"\textbf{No past paper of this exam is in the bank.} Everything below comes from the prior "
                 r"(lecture time" + (r" and seniors' lists" if has_imp else "") + r") and an \textbf{assumed pattern} (" +
                 tex(out["model"]["pattern_source"]) + r"). Use it as a reading order, not a forecast.\par")
    else:
        L.append(rf"Built from {len(pids)} past paper{'s' if len(pids) != 1 else ''} "
                 rf"({', '.join(tex(p) for p in pids)}).\par")
    L += [out["model"]["explanation"] + r"\par", backtest_line(out) + r"\par"]
    cs = out["model"]["class_signal"]
    if cs["notes"]:
        L.append(rf"\textbf{{Class signal}} ({tex(cs['source'] or 'class signal')}): " +
                 "; ".join(tex(n) for n in cs["notes"]) +
                 r". Stressed topics get a larger prior; dropped ones are left out of every plan; pattern notes "
                 r"are shown as given.\par")
    L.append("")
    # heatmap (with no papers: the prior's topic weights only; nothing implies a paper exists)
    L += ([r"\section{Topic marks per paper}",
           r"Marks each topic carried in each paper (all printed sub-parts, before choice), the model's expected "
           r"marks per paper, the chance it appears at all, and the plan that first covers it."] if pids else
          [r"\section{Topic weights (from lecture time, assumed pattern)}",
           r"With no past paper, each topic's weight comes from its lecture time; expected marks are simulated on the "
           r"assumed pattern. The last column is the plan that first covers the topic."]) + [
          r"{\footnotesize\setlength{\tabcolsep}{2.5pt}\zebra",
          r"\begin{xltabular}{\linewidth}{@{}Y" + "c" * (len(shown) + bool(older)) + "ccc@{}}",
          r"\toprule \thead{Topic} & " + "".join(phead(p) + " & " for p in shown) +
          (rf"\thead{{older\\({len(older)})}} & " if older else "") +
          r"\thead{Exp.\\marks} & \thead{Chance} & \thead{Plan}\\\midrule\endhead",
          r"\bottomrule\endfoot"]
    plan_of_topic = {}
    for name, _ in BUDGETS:
        for t in out["plans"][name]["topics"]:
            plan_of_topic.setdefault(t, name)
    for tr in out["topics"]:
        cells = [heat_cells(tr["marks_by_paper"].get(p)) for p in shown]
        if older:
            cells.append(heat_cells(sum(tr["marks_by_paper"].get(p, 0) for p in older)))
        pl = plan_of_topic.get(tr["topic"])
        L.append(r"\hspace{0pt}" + rf"{tex(tr['title'])} & " + "".join(c + " & " for c in cells) +
                 rf"{tr['expected_marks']:.1f} & \topicbadge{{{tr['topic']}}} & "
                 rf"{tex(pl.replace('h', ' h')) if pl else r'\textcolor{muted}{--}'}\\")
    L += [r"\end{xltabular}}", ""]
    # plans
    byc = {r["cluster"]: r for r in out["clusters"]}
    L += [r"\section{Study plans, in syllabus order}",
          r"Each plan contains the shorter one: study the 3\,h list first, then the 6\,h additions, then the "
          r"12\,h additions. Within a plan, topics follow the syllabus; the page numbers point to the notes "
          r"(topic) and to the important-question entry (idea).",
          "", r"{\small\begin{tabular}{@{}lcccc@{}}\toprule",
          r"\thead{Plan} & \thead{Ideas} & \thead{Minutes} & \thead{Expected marks\\(model)} & "
          r"\thead{$p_{\mathrm{safe}}$}\\\midrule"]
    for name, _ in BUDGETS:
        p = out["plans"][name]
        L.append(rf"{name.replace('h', ' h')} & {len(p['clusters'])} & {p['minutes']} & "
                 rf"{p['expected_marks']:.1f} of {F:g} & {round(100 * p['p_safe'])}\%\\")
    L += [r"\bottomrule\end{tabular}}", ""]
    prev = []
    for name, _ in BUDGETS:
        p = out["plans"][name]
        add = [c for c in p["clusters"] if c not in prev]
        head = {"3h": "3 hours", "6h": "6 hours: add these", "12h": "12 hours: add these"}[name]
        L.append(rf"\subsection*{{{head}}}")
        if not add:
            L.append(r"(nothing more is worth adding at this budget)")
            prev = p["clusters"]
            continue
        L.append(r"\begin{itemize}[leftmargin=1.2em,itemsep=1pt,topsep=2pt]")
        for u in ctx["units"]:
            ts = [t for t in ctx["torder"] if ctx["topics"][t]["unit"] == u["id"] and
                  any(byc[c]["topic"] == t for c in add)]
            if not ts:
                continue
            L.append(rf"\item[] \textbf{{{tex(u['title'])}}}")
            for t in ts:
                ideas = []
                for c in add:
                    r = byc[c]
                    if r["topic"] != t:
                        continue
                    ref = "" if r["synthetic"] else rf", p.\,\pageref{{iq:{c}}}"
                    badge = "" if r["synthetic"] else rf"\clusterbadge{{{c}}}\ "
                    ideas.append(rf"{badge}{tex(r['label'])} {{\scriptsize\color{{muted}}({r['effort_min']} min{ref})}}")
                L.append(rf"\item {tex(ctx['topics'][t]['title'])} {{\scriptsize\color{{muted}}(notes p.\,\pageref{{sec:{t}}})}}"
                         r"\newline " + r"; ".join(ideas))
        L.append(r"\end{itemize}")
        prev = p["clusters"]
    # must draw
    md = [c for c in out["must_draw"]["clusters"] if c in byc]
    L += ["", r"\section{Must-draw diagrams}",
          (r"These ideas were asked (or are taught) as diagrams" if pids else r"These ideas are taught as diagrams") +
          r"; practise drawing each one from memory with every label."]
    if md:
        items = []
        for c in md:
            r = byc[c]
            ref = rf" p.\,\pageref{{iq:{c}}}" if r["tier"] in "ABCD" and not r["synthetic"] else ""
            items.append(tex(r["label"]) + ref)
        L.append(r"\begin{itemize}[leftmargin=1.2em,itemsep=0pt,topsep=2pt]" +
                 "".join(r"\item " + x for x in items) + r"\end{itemize}")
    else:
        L.append(r"(none recorded)")
    # skip safety
    ss = out["skip_safety"]
    L += ["", r"\section{If you skip a unit}",
          (r"For each past paper: how many optional questions you could still answer (earn at least half their "
           r"marks) if you skipped the unit but knew everything else, and the same on simulated papers." if pids else
           r"On papers simulated from the assumed pattern: how often you could still answer enough optional "
           r"questions (earn at least half their marks) if you skipped the unit but knew everything else.")]
    L += [r"{\small\setlength{\tabcolsep}{2.5pt}\begin{xltabular}{\linewidth}{@{}Y" + "c" * len(shown) + "c@{}}",
          r"\toprule \thead{Skip} & " + "".join(phead(p) + " & " for p in shown) +
          r"\thead{Simulated\\$p_{\mathrm{safe}}$}\\\midrule\endhead", r"\bottomrule\endfoot"]
    for uid_, v in ss.items():
        cells = []
        for p in shown:
            x = v["papers"].get(p)
            if not x:
                cells.append(r"\textcolor{muted}{--}")
            else:
                col = "sgred" if x["answerable"] < x["need"] else "black"
                cells.append(rf"\textcolor{{{col}}}{{{x['answerable']}/{x['n']}}}")
        L.append(r"\hspace{0pt}" + tex(v["title"]) + " & " + "".join(c + " & " for c in cells) + rf"{round(100 * v['p_safe_mc'])}\%\\")
    L += [r"\end{xltabular}}"]
    need = out["model"]["choice"]["answer"]
    L.append(rf"{{\footnotesize Red: fewer than the {need} optional questions you must answer.}}")
    # wildcards
    # only the wildcards the guide covers (targets.iq_clusters); the rest are index lines (real SVP: 48 tier-D ideas)
    tgt = set((out.get("targets", {}).get("iq_clusters") or {}).get("clusters") or [])
    wild = [r for r in out["clusters"] if r["tier"] == "D" and (not tgt or r["cluster"] in tgt)]
    if wild:
        L += ["", r"\section{Wildcards}",
              (r"Not asked in the past papers this guide uses, but heavily taught or on the seniors' list. " if pids else
               r"Heavily taught but outside the 12-hour plan. ") +
              r"Read them once if you have time left: " +
              "; ".join(tex(r["label"]) + rf" (p.\,\pageref{{iq:{r['cluster']}}})" for r in wild) + "."]
    return "\n".join(L) + "\n"


def howto_tex(ctx, model, out):
    pat = ctx["pattern"]
    eh = out["exam_hall"]
    F = out["model"]["full_marks"]
    L = [r"\chapter{How to use this guide}"]
    if out["model"]["pattern_assumed"]:
        L.append(r"\textbf{Exam pattern (assumed: no past paper in the bank)} (" + tex(out["model"]["pattern_source"]) +
                 r"): " + tex(pat.get("structure", "")) + r".\par")
    else:
        L.append(rf"\textbf{{Exam pattern}} ({tex(pat.get('source', 'latest paper'))}): {tex(pat.get('structure', ''))}. "
                 rf"Full marks {tex(pat.get('full_marks', fmt(F)))}, {tex(pat.get('duration', ''))}.\par")
    L += [r"\paragraph{Pick a plan.} The Exam Radar (p.\,\pageref{ch:radar}) gives three nested study plans. "
          r"Tiers are study order, not a promise: \tier{A} ideas make the 3\,h plan, \tier{B} are added for 6\,h, "
          r"\tier{C} for 12\,h, \tier{D} are wildcards and \tier{E} the rest. Next to each tier the badge shows the " +
          (r"model's estimate P of how likely the idea is to appear, from the past papers in the window. "
           if not out["model"]["pattern_assumed"] else
           r"model's estimate P of how likely the idea is to appear, from lecture time only (no past paper exists). ") +
          r"It is a rough guide, not a calibrated chance (see the track record in the Exam Radar)" +
          ("." if out["model"]["p_display"] == "percent" else
           r"; it is shown as a band (low, med, high) because there are too few past papers for percentages."),
          "", r"{\small\begin{tabular}{@{}lcccc@{}}\toprule",
          r"\thead{If you have} & \thead{Ideas} & \thead{Minutes} & \thead{Expected marks\\(model)} & "
          r"\thead{$p_{\mathrm{safe}}$}\\\midrule"]
    for name, _ in BUDGETS:
        p = out["plans"][name]
        L.append(rf"{name.replace('h', ' hours')} & {len(p['clusters'])} & {p['minutes']} & {p['expected_marks']:.1f} of {F:g} & "
                 rf"{round(100 * p['p_safe'])}\%\\")
    sim_note = (r" Expected marks and $p_{\mathrm{safe}}$ are simulated on the assumed pattern, not on real papers."
                if out["model"]["pattern_assumed"] else "")
    L += [r"\bottomrule\end{tabular}}\par",
          r"{\footnotesize $p_{\mathrm{safe}}$: share of simulated papers on which the plan still lets you earn at "
          rf"least half the marks of the {out['model']['choice']['answer']} optional questions you must answer."
          + sim_note + r"}\par",
          backtest_line(out) + r"\par",
          r"\paragraph{Suggested method.} (1) Pick the plan that fits your time. (2) For each idea in it, read the "
          + (r"notes section, then solve the matching past question on paper \emph{before} reading the solution. "
             if not out["model"]["pattern_assumed"] else
             r"notes section, then try the idea's Expected question on paper \emph{before} reading the solution. ") +
          r"(3) Do the Q1 rapid-fire drill. (4) Attempt the mock paper under exam time. (5) Revise from the cheatsheet.",
          ""]
    # exam hall
    L += [r"\section*{In the exam hall}",
          rf"You have {eh['duration_min']} minutes for {fmt(eh['full_marks'])} marks. Keep {eh['reserve_min']} minutes "
          rf"for reading and checking, which leaves \textbf{{{eh['min_per_mark']:g} minutes per mark}}.\par\smallskip\noindent",
          r"{\small\begin{xltabular}{\linewidth}{@{}Yr@{}}\toprule \thead{Step} & \thead{Minutes}\\\midrule\endhead"]
    for s in eh["plan"]:
        L.append(rf"{tex(s['step'])} & {s['minutes']}\\")
    L += [r"\bottomrule\end{xltabular}}", "",
          r"\textbf{Word budget and answer shape per marks value} (at most about "
          rf"{eh['words_per_min']} written words per minute):",
          r"{\small\begin{xltabular}{\linewidth}{@{}ccc>{\raggedright\arraybackslash}X@{}}",
          r"\toprule \thead{Marks} & \thead{Minutes} & \thead{Words} & \thead{Answer template}\\\midrule\endhead",
          r"\bottomrule\endfoot"]
    for m, b in eh["budgets"].items():
        L.append(rf"{m} & {b['minutes']:g} & {b['words']} & {tex(b['template'])}\\")
    L += [r"\end{xltabular}}",
          r"\textbf{Numericals:} " + tex(eh["numerical_template"]).replace("->", r"$\rightarrow$") + r".\par"]
    q1 = out["q1_drill"]
    L.append(rf"\paragraph{{Q1 drill.}} {len(q1['question_ids'])} one-mark past questions and the "
             rf"{len(q1['clusters'])} ideas most likely in Q1 are collected in the Q1 rapid-fire drill chapter"
             r"\ifcsname r@ch:q1drill\endcsname{} (p.\,\pageref{ch:q1drill})\fi"
             r". Answer each in one or two lines, out loud, before checking.")
    L += sizes_box(ctx, out)
    # source confidence
    L += source_confidence(ctx, out)
    L.append(r"\paragraph{Storyboards.} Step-by-step figures print as numbered frames; in Adobe Acrobat, Okular or Foxit "
             r"the interactive edition also plays them as animations.")
    return "\n".join(L) + "\n"


def source_confidence(ctx, out):
    """Per-unit source confidence from blueprint units[].source_confidence {level, why}, plus the
    number of topics written from a book (coverage_gaps with status unfillable -> \\notfromnotes)."""
    bpu = {u["id"]: u for u in ctx["bp"].get("units", [])}
    gaps = defaultdict(int)
    for g in ctx["bp"].get("coverage_gaps", []) or []:
        if str(g.get("status", "")).lower() == "unfillable" and g.get("topic") in ctx["topics"]:
            gaps[ctx["topics"][g["topic"]]["unit"]] += 1
    L = [r"\paragraph{How far to trust each unit's notes.}\mbox{}\par\noindent",
         r"{\small\setlength{\tabcolsep}{3pt}\begin{xltabular}{\linewidth}"
         r"{@{}>{\raggedright\arraybackslash\hsize=0.8\hsize}Xcc>{\raggedright\arraybackslash\hsize=1.2\hsize}X@{}}",
         r"\toprule \thead{Unit} & \thead{Confidence} & \thead{Not from\\your notes} & \thead{Why}\\\midrule\endhead",
         r"\bottomrule\endfoot"]
    for u in ctx["units"]:
        sc = bpu.get(u["id"], {}).get("source_confidence") or {}
        lvl = str(sc.get("level", "")).lower()
        col = {"high": "sgteal", "medium": "sgamber", "low": "sgred"}.get(lvl, "muted")
        L.append(r"\hspace{0pt}" + rf"{tex(u['title'])} & \textcolor{{{col}}}{{{tex(lvl or 'not rated')}}} & {gaps.get(u['id'], 0)} & "
                 rf"{tex(sc.get('why', ''))}\\")
    L.append(r"\end{xltabular}}")
    L.append(r"{\footnotesize Topics not from your notes carry a red banner naming the book they were written "
             r"from; check them against class material.}\par")
    return L


def sizes_box(ctx, out):
    """'How big this guide is, and why': the targets in a keyconceptbox (studyguide.sty)."""
    T = out["targets"]
    w = out["model"]["pyq_window"]
    win = (f"{w['from']}--{w['to']}" if w.get("from") is not None else "all papers")
    units = "; ".join(rf"{tex(v['title'])} {fmt(v['pages'])} pp." for v in T["notes_pages"].values())
    tot = sum(v["pages"] for v in T["notes_pages"].values())
    body = [rf"\textbf{{Past papers used:}} {win}" +
            {"default": r" (default rule)", "pyq_windows.json": r" (suggested per-subject window)"}.get(w.get("source"), "") +
            rf". {tex(w.get('why', ''))}.\par",
            rf"\textbf{{Important questions:}} {T['iq_clusters']['count']} ideas: {tex(T['iq_clusters']['why'])}.\par",
            rf"\textbf{{Notes:}} about {fmt(round(tot))} pages ({units}). Each unit gets lectures $\times$ "
            r"(1 + its share of the past-paper marks over the average unit's share, between 1 and 2) + 1 pages, so "
            r"units that carry more marks get more room.\par",
            rf"\textbf{{Cheatsheet:}} {T['cheatsheet_pages']['pages']} landscape pages: "
            rf"{tex(T['cheatsheet_pages']['why'])}.\par",
            rf"\textbf{{Q1 drill:}} {T['q1_drill']['count']} items: {tex(T['q1_drill']['why'])}."]
    # a studyguide box environment (not a raw \fbox{\parbox}): print, phone and web.py all render it
    return ["", r"\begin{keyconceptbox}[How big this guide is, and why]\small", *body, r"\end{keyconceptbox}", ""]


def print_summary(ctx, model, out):
    print(f"model: {out['model']['params_source']}; papers {out['model']['papers_used']}; "
          f"rho {model['rho']:.2f}; display {out['model']['p_display']}")
    for name, p in out["plans"].items():
        print(f"plan {name:>3s}: {len(p['clusters']):2d} ideas, {p['minutes']:3d} min, expected "
              f"{p['expected_marks']:.1f}/{p['of_marks']:g}, p_safe {p['p_safe']:.2f}")
    print(f"{'tier':4s} {'P':>5s} {'EV':>5s}  cluster  label")
    for r in sorted(out["clusters"], key=lambda r: ("ABCDE".index(r["tier"]), -r["EV"]))[:25]:
        print(f"{r['tier']:4s} {r['P']:5.2f} {r['EV']:5.2f}  {r['cluster']:7s}  {r['label'][:64]}")
    print(f"wrote {ctx['work'] / 'important_questions.json'}, badges.tex, chapters/05_how_to_use.tex, "
          f"chapters/20_exam_radar.tex, plan_snapshots/")


if __name__ == "__main__":
    sys.exit(main())
