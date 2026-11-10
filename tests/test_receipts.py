"""receipts.py on a copy of CN midsem (tests/_tmp/receipts/, STUDYPREP_ROOT).

Checks: every banked question gets a crop; the match rate is reported and must stay >= 90 %; a crop's
height is that of a question (not the whole page); a question that runs over a page break is stacked
from two pages; the manual override wins; the real bank then passes verify_pyqs end to end; a question
edited after receipts.py ran is reported stale. KEEP=1 keeps the copy for looking at the PNGs.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
REAL_SUBJ = PIPE.parent / "CN"
TMP = HERE / "_tmp" / "receipts"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
S = TMP / "CN"
W = S / "work"
real = json.loads((REAL_SUBJ / "work" / "midsem" / "pyq_bank.json").read_text("utf-8"))
# A pinned set of papers, taken from the real bank (or, before the merge, from the transcribers' part files):
#   MS2022, MS2024, MS2025  the original trial papers
#   ES2024    22 manual rects (must be honoured as given)
#   ES2026SP  2-up booklet spreads; its manual rects are stripped so the automatic left/right split and the
#             paper's reading_order (p1-right, p2-left, p2-right, p1-left) are exercised
#   MS2026SP  garbled corpus lines: region re-OCR
#   MS2023, ES2022  short consecutive Q1 sub-parts whose crops used to swallow their neighbours
#   MS2020    4(a) has its own internal items 'a.' 'b.' (must not be mistaken for sub-part labels)
BASE, EXTRA_IDS = ("MS2022", "MS2024", "MS2025", "MS2023", "ES2022", "MS2020"), ("ES2024", "ES2026SP", "MS2026SP")
bank = {"papers": [], "questions": [], "clusters": real["clusters"], "imp_list": real.get("imp_list", [])}
EXTRA = {}
for pid in BASE + EXTRA_IDS:
    paper = next((p for p in real["papers"] if p["id"] == pid), None)
    qs = [q for q in real["questions"] if q.get("paper") == pid]
    f = REAL_SUBJ / "work" / "midsem" / f"pyq_bank.part_{pid}.json"
    if (paper is None or not qs) and f.exists():
        pb = json.loads(f.read_text("utf-8"))
        paper, qs = pb["paper"], pb["questions"]
    if paper is None:
        continue
    paper = dict(paper)
    for q in qs:
        q.setdefault("cluster", "C04"); q.setdefault("topic", "T01"); q.setdefault("type", "theory")
        if pid == "ES2026SP":
            q.pop("receipt", None)
    if pid == "ES2026SP":
        paper["reading_order"] = ["1R", "2L", "2R", "1L"]
    bank["papers"].append(paper)
    bank["questions"] += qs
    if pid in EXTRA_IDS:
        EXTRA[pid] = {"paper": paper, "questions": [q for q in qs]}
if "ES2024" in EXTRA:   # its manual rects, as the transcriber gave them
    EXTRA["ES2024"]["given"] = {q["id"]: q["receipt"] for q in EXTRA["ES2024"]["questions"] if q.get("receipt")}
manifest = json.loads((REAL_SUBJ / "work" / "manifest.json").read_text("utf-8"))
slugs = {p["source_slug"] for p in bank["papers"]}
(W / "corpus").mkdir(parents=True)
(W / "midsem").mkdir()
files = {}
for rel, m in manifest["files"].items():
    if m.get("slug") in slugs:
        (S / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REAL_SUBJ / rel, S / rel)
        shutil.copy2(REAL_SUBJ / "work" / "corpus" / f"{m['slug']}.md", W / "corpus" / f"{m['slug']}.md")
        files[rel] = m
(W / "manifest.json").write_text(json.dumps({"files": files}), "utf-8")
shutil.copy2(REAL_SUBJ / "work" / "midsem" / "blueprint.json", W / "midsem" / "blueprint.json")

# manual override on one question (rect deliberately elsewhere: it must be used as given)
MANUAL = "MS2025-1c"
for q in bank["questions"]:
    if q["id"] == MANUAL:
        q["receipt"] = {"page": 1, "rect": [30, 300, 560, 340]}
(W / "midsem" / "pyq_bank.json").write_text(json.dumps(bank, indent=1, ensure_ascii=False), "utf-8")
env = dict(os.environ, STUDYPREP_ROOT=str(TMP))


def tool(name, *args):
    return subprocess.run([sys.executable, str(PIPE / "tools" / name), "CN", "--scope", "midsem", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


r = tool("receipts.py")
print("\n".join("     | " + l for l in r.stdout.splitlines()[-48:]))
rj = W / "midsem" / "receipts" / "receipts.json"
rec = json.loads(rj.read_text("utf-8")) if rj.exists() else {}
ids = [q["id"] for q in bank["questions"]]
check("receipts.json has every question", set(rec) == set(ids), f"{len(rec)}/{len(ids)}")
check("a PNG for every question", all((W / "midsem" / "receipts" / f"{i}.png").exists() for i in ids))
# real CN 2026-11-06: 251 RGB receipts were 29 MB and made the archive PDF 13.7 MB. Receipts are scans of printed
# text: 16-level greyscale keeps them legible at a fraction of the size.
from PIL import Image as _Im
_modes = []
for i in ids:
    _p = W / "midsem" / "receipts" / f"{i}.png"
    if _p.exists():
        with _Im.open(_p) as _im:
            _cols = _im.getcolors(256)
            _modes.append((_im.mode in ("L", "P")) and _cols is not None and len(_cols) <= 16)
check("receipts are compact greyscale (<= 16 levels)", _modes and all(_modes), f"{sum(_modes)}/{len(_modes)}")
auto = [i for i in ids if i != MANUAL]
good = [i for i in auto if (rec.get(i, {}).get("match") or 0) >= 0.6]
rate = len(good) / len(auto)
check("automatic match rate >= 90 %", rate >= 0.9, f"{len(good)}/{len(auto)} = {rate:.0%}")
check("manual rect used as given", rec.get(MANUAL, {}).get("method") == "manual"
      and rec[MANUAL].get("rect") == [30, 300, 560, 340])
two = rec.get("MS2022-3b", {}).get("parts", [])
check("page-break question stacked from 2 pages", [p["page"] for p in two] == [1, 2], str(two))
heights = {i: rec[i]["rect"][3] - rec[i]["rect"][1] for i in auto if rec.get(i, {}).get("rect")}
check("one-line question crop is short (< 60 pt)", heights.get("MS2025-1d", 999) < 60,
      f"MS2025-1d {heights.get('MS2025-1d')}")
check("no crop is page-sized (< 400 pt)", all(h < 400 for h in heights.values()),
      f"max {max(heights.values()) if heights else '-'}")
for i in ("MS2025-1a", "MS2024-3a", "MS2022-4c"):
    print(f"     receipt {i}: {rec.get(i)}")

check("tx3 part files present (ES2024, ES2026SP, MS2026SP)", set(EXTRA) == {"ES2024", "ES2026SP", "MS2026SP"}, str(sorted(EXTRA)))
if "ES2024" in EXTRA:
    given = EXTRA["ES2024"]["given"]
    honoured = [i for i, r in given.items() if rec.get(i, {}).get("method") == "manual"
                and [{"page": p["page"], "rect": p["rect"]} for p in rec[i]["parts"]]
                == [{"page": int(x["page"]), "rect": [float(v) for v in x["rect"]]} for x in (r if isinstance(r, list) else [r])]
                and (W / "midsem" / "receipts" / f"{i}.png").exists()]
    check("ES2024: every manual rect honoured as given, with a PNG", len(given) >= 22 and len(honoured) == len(given),
          f"{len(honoured)}/{len(given)}")
if "ES2026SP" in EXTRA:
    import pymupdf
    pdf = next(S.rglob("6th*2026*end*.pdf"))
    pr = pymupdf.open(pdf)[0].rect
    mid = (pr.x0 + pr.x1) / 2
    sp = [q["id"] for q in EXTRA["ES2026SP"]["questions"]]
    in_half = [i for i in sp if rec.get(i, {}).get("parts") and all(p["rect"][2] <= mid + 1 or p["rect"][0] >= mid - 1
                                                                 for p in rec[i]["parts"])]
    good = [i for i in sp if (rec.get(i, {}).get("match") or 0) >= 0.6]
    check("ES2026SP spreads: every automatic crop lies inside one half-page", len(in_half) == len(sp),
          f"{len(in_half)}/{len(sp)}")
    check("ES2026SP spreads: automatic receipts match (left half, then right half)", len(good) == len(sp),
          f"{len(good)}/{len(sp)}; low: {[i for i in sp if i not in good]}")
    q4b = [(p["page"], "R" if p["rect"][0] >= mid - 1 else "L") for p in rec.get("ES2026SP-4b", {}).get("parts", [])]
    check("ES2026SP-4b follows the booklet reading order: p2-right then p1-left, stacked",
          q4b == [(2, "R"), (1, "L")] and (rec["ES2026SP-4b"].get("match") or 0) >= 0.9,
          f"{q4b} match {rec.get('ES2026SP-4b', {}).get('match')}")
if "MS2026SP" in EXTRA:
    r1c = rec.get("MS2026SP-1c", {})
    check("MS2026SP-1c: garbled page OCR -> region re-OCR reads the question", str(r1c.get("ocr_method", "")).startswith("region-ocr")
          and (r1c.get("match") or 0) >= 0.9 and "100%" in (r1c.get("ocr_text") or ""), f"{r1c.get('ocr_method')} {r1c.get('match')}")

# precision: a crop holds its own question and stops before its neighbours (writers' report on MS2023 1a-1e
# and ES2022-1g). Checked on the crop's own words (ocr_text = the words inside the crop rect(s)).
sys.path.insert(0, str(PIPE / "tools"))
import verify_pyqs as vp
qtext = {q["id"]: q["text"] for q in bank["questions"]}


def keys(s):
    return [t.fold for t in vp.tokenize(s, ocr=True)]


def has_run(hay, needle):
    return any(hay[i:i + len(needle)] == needle for i in range(len(hay) - len(needle) + 1))


NEIGHBOURS = [("MS2023-1a", "MS2023-1b"), ("MS2023-1b", "MS2023-1c"), ("MS2023-1c", "MS2023-1d"),
              ("MS2023-1d", "MS2023-1e"), ("MS2023-1e", "MS2023-2a"), ("ES2022-1e", "ES2022-1f"),
              ("ES2022-1f", "ES2022-1g"), ("ES2022-1g", "ES2022-1h"),
              ("MS2020-4a", "MS2020-4b")]   # 4(a) carries its own items a. b.: not its label line
leaks, own_ok = [], []
for a, b in NEIGHBOURS:
    if a not in rec or b not in rec:
        leaks.append(f"{a}/{b} missing"); continue
    ka, kb = keys(rec[a].get("ocr_text") or ""), keys(rec[b].get("ocr_text") or "")
    qa, qb = keys(qtext[a]), keys(qtext[b])
    if has_run(ka, qb[:3]):
        leaks.append(f"{a} holds the start of {b} ({' '.join(qb[:3])})")
    if has_run(kb, qa[-3:]):
        leaks.append(f"{b} holds the end of {a} ({' '.join(qa[-3:])})")
    if not has_run(ka, qa[-2:]):
        leaks.append(f"{a} lost its own last words ({' '.join(qa[-2:])})")
    tail = qa[-1]           # even a single distinctive word of the previous sub-part ('case?') is a leak
    if len(tail) >= 4 and tail not in qb and tail in kb:
        leaks.append(f"{b} holds '{tail}' from the end of {a}")
for i in {x for pair in NEIGHBOURS for x in pair}:
    rt = vp.tokenize(rec.get(i, {}).get("ocr_text") or "", ocr=True)
    qt = vp.tokenize(qtext[i])
    if rt and vp.assess(qt, rt, vp.align(qt, rt))["tok"] >= 0.6:
        own_ok.append(i)
n_q = len({x for pair in NEIGHBOURS for x in pair})
check("short consecutive sub-parts: each crop holds its own question", len(own_ok) == n_q, f"{len(own_ok)}/{n_q}")
check("short consecutive sub-parts: no crop holds a neighbour's first or last words", not leaks, "; ".join(leaks))

# data tables (ML): the automatic crop must hold the table that follows the prose, and stop at the next
# sub-part. The transcriber's manual rects (vision-checked) are the reference; they are stripped from the
# bank so the automatic crop is exercised.
MLW = PIPE.parent / "ML" / "work"
TAB = {"MS2023": ["MS2023-2a", "MS2023-3a"], "MS2023B": ["MS2023B-2b", "MS2023B-3b"], "MS2022": ["MS2022-4a", "MS2022-5a"]}
if all((MLW / "endsem" / f"pyq_bank.part_{p}.json").exists() for p in TAB):
    MS_ = TMP / "ML"
    (MS_ / "work" / "corpus").mkdir(parents=True)
    (MS_ / "work" / "endsem").mkdir(parents=True)
    (MS_ / "work" / "endsem" / "blueprint.json").write_text(json.dumps({"units": [{"id": "U1", "topics": [{"id": "T01"}]}]}), "utf-8")
    mlman = json.loads((MLW / "manifest.json").read_text("utf-8"))["files"]
    mb, ref, mfiles = {"papers": [], "questions": [], "clusters": [{"id": "C01", "topic": "T01"}]}, {}, {}
    for pid, qids in TAB.items():
        pb = json.loads((MLW / "endsem" / f"pyq_bank.part_{pid}.json").read_text("utf-8"))
        slug = pb["paper"]["source_slug"]
        shutil.copy2(MLW / "corpus" / f"{slug}.md", MS_ / "work" / "corpus" / f"{slug}.md")
        for rel, mm in mlman.items():
            if mm.get("slug") == slug:
                (MS_ / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(MLW.parent / rel, MS_ / rel)
                mfiles[rel] = mm
        mb["papers"].append(pb["paper"])
        for q in pb["questions"]:
            q.update(cluster="C01", topic="T01")
            if q["id"] in qids and q.get("receipt"):
                ref[q["id"]] = q.pop("receipt")
            mb["questions"].append(q)
    (MS_ / "work" / "manifest.json").write_text(json.dumps({"files": mfiles}), "utf-8")
    (MS_ / "work" / "endsem" / "pyq_bank.json").write_text(json.dumps(mb, ensure_ascii=False), "utf-8")
    envm = dict(os.environ, STUDYPREP_ROOT=str(TMP))
    rm = subprocess.run([sys.executable, str(PIPE / "tools" / "receipts.py"), "ML", "--scope", "endsem"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=envm)
    mrec_f = MS_ / "work" / "endsem" / "receipts" / "receipts.json"
    mrec = json.loads(mrec_f.read_text("utf-8")) if mrec_f.exists() else {}
    tq = [q for v_ in TAB.values() for q in v_]
    check("ML table questions: every one has a reference manual rect", set(ref) == set(tq), str(sorted(set(tq) - set(ref))))

    def covered(auto_parts, man):
        """share of the reference rect's height (inner part) covered by the automatic crop on that page"""
        mparts = man if isinstance(man, list) else [man]
        tot = got = 0.0
        for mp in mparts:
            y0, y1 = mp["rect"][1] + 6, mp["rect"][3] - 6
            tot += max(0.0, y1 - y0)
            for ap in auto_parts:
                if ap["page"] == mp["page"]:
                    got += max(0.0, min(y1, ap["rect"][3]) - max(y0, ap["rect"][1]))
        return got / tot if tot else 0.0

    cov = {i: round(covered(mrec.get(i, {}).get("parts", []), ref[i]), 2) for i in tq if i in ref}
    check("ML table questions: the automatic crop holds the whole table region (>= 90 % of the manual rect)",
          all(c >= 0.9 for c in cov.values()) and len(cov) == len(tq), str(cov))
    qtext_m = {q["id"]: q["text"] for q in mb["questions"]}
    nxt = {"MS2023-2a": "MS2023-2b", "MS2023-3a": "MS2023-3b", "MS2023B-2b": "MS2023B-3a", "MS2023B-3b": "MS2023B-4a",
           "MS2022-4a": "MS2022-4b", "MS2022-5a": "MS2022-5b"}
    leak = [i for i, j in nxt.items()
            if has_run(keys(mrec.get(i, {}).get("ocr_text") or ""), keys(vp.match_text({"text": qtext_m[j]}))[:3])]
    check("ML table questions: the crop stops before the next sub-part", not leak, str(leak))
    vm = subprocess.run([sys.executable, str(PIPE / "tools" / "verify_pyqs.py"), "ML", "--scope", "endsem"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=envm)
    print("\n".join("     | " + l for l in vm.stdout.splitlines() if l.split()[:1] and l.split()[0] in tq))
else:
    check("ML part files with tables present", False)

v = tool("verify_pyqs.py")
last = (v.stdout.strip().splitlines() or [""])[-1]
check("verify_pyqs passes with real receipts", v.returncode == 0 and last == "RESULT PASS", last)
if v.returncode:
    print("\n".join("     | " + l for l in v.stdout.splitlines()[-20:]))

# edit a question after receipts were made: the gate reports the receipt as stale
b2 = json.loads((W / "midsem" / "pyq_bank.json").read_text("utf-8"))
for q in b2["questions"]:
    if q["id"] == "MS2024-1c":
        q["text"] = q["text"].replace("total 15(fifteen)", "total 15 (fifteen)") + " "
(W / "midsem" / "pyq_bank.json").write_text(json.dumps(b2, ensure_ascii=False), "utf-8")
v = tool("verify_pyqs.py")
check("edited question -> stale receipt blocks", v.returncode == 1 and "stale" in v.stdout)
r2 = tool("receipts.py", "--only", "MS2024-1c")
v = tool("verify_pyqs.py")
check("re-crop of one question (--only) restores PASS", v.returncode == 0, (v.stdout.strip().splitlines() or [""])[-1])
check("--only kept the other receipts", len(json.loads(rj.read_text("utf-8"))) == len(ids))

r = subprocess.run([sys.executable, str(PIPE / "tools" / "receipts.py"), "CN"], capture_output=True, text=True, env=env)
check("missing --scope is a usage error", r.returncode == 2, f"rc={r.returncode}")

# ---- real ML (2026-11-06): one PDF holding 3 question sets ("pages": [a, b]). For an OCR'd question whose automatic
# match was < 0.999, receipts.py re-OCR'd the region into tmp/<slug> while the paper's crops live in
# tmp/<slug>_p<a>-<b>, so Tesseract found no region_0.png and the receipt went missing.
ML = PIPE.parent / "ML" / "work"
SLUG = "PYQE_2022_Endsem_2_Machine_Learning"
mlb = ML / "endsem" / "pyq_bank.json"
if mlb.exists() and (ML / "corpus" / f"{SLUG}.md").exists():
    R = TMP / "MLR" / "work"
    (R / "endsem").mkdir(parents=True, exist_ok=True)
    (R / "corpus").mkdir(exist_ok=True)
    (R / "pyq_pages").mkdir(exist_ok=True)
    shutil.copy2(ML / "corpus" / f"{SLUG}.md", R / "corpus" / f"{SLUG}.md")
    for png in (ML / "pyq_pages").glob(f"{SLUG}_p*.png"):
        shutil.copy2(png, R / "pyq_pages" / png.name)
    man = json.loads((ML / "manifest.json").read_text("utf-8"))
    files = man.get("files", man) if isinstance(man, dict) else man
    man2 = dict(man)
    if isinstance(man.get("files"), (list, dict)):
        man2["files"] = ([f for f in man["files"] if f.get("slug") == SLUG] if isinstance(man["files"], list)
                         else {k: v for k, v in man["files"].items() if (v or {}).get("slug") == SLUG})
    (R / "manifest.json").write_text(json.dumps(man2), "utf-8")
    src_pdf = PIPE.parent / "ML" / "Endsem PYQs"
    for f in src_pdf.glob("*2022*Endsem*2*"):
        (TMP / "MLR" / "Endsem PYQs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, TMP / "MLR" / "Endsem PYQs" / f.name)
    shutil.copy2(ML / "endsem" / "blueprint.json", R / "endsem" / "blueprint.json")
    full = json.loads(mlb.read_text("utf-8"))
    sets = {"ES2022B", "ES2022BS2", "ES2022BS3"}
    want = {"ES2022B-3", "ES2022BS3-4"}           # OCR'd prose questions with a sub-0.999 automatic match
    qs = [dict(q) for q in full["questions"] if q["id"] in want]
    for q in qs:
        q.pop("receipt", None)                      # force the automatic crop and the region re-OCR
    sub = {"papers": [p for p in full["papers"] if p["id"] in sets], "questions": qs,
           "clusters": [c for c in full["clusters"] if c["id"] in {q["cluster"] for q in qs}]}
    (R / "endsem" / "pyq_bank.json").write_text(json.dumps(sub, ensure_ascii=False), "utf-8")
    envr = dict(os.environ, STUDYPREP_ROOT=str(TMP))
    rr = subprocess.run([sys.executable, str(PIPE / "tools" / "receipts.py"), "MLR", "--scope", "endsem"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=envr)
    rjr = R / "endsem" / "receipts" / "receipts.json"
    recr = json.loads(rjr.read_text("utf-8")) if rjr.exists() else {}
    got = {q: (recr.get(q) or {}).get("file") for q in want}
    check("page-range papers: region re-OCR uses the set's own folder (receipts made)",
          all(got.values()) and "region_0.png" not in (rr.stdout + rr.stderr), (got, (rr.stdout + rr.stderr)[-400:]))
else:
    check("ML 3-set fixture present", False)

# --- pages scanned sideways (EE ES2023SP, pinned in fixtures/receipts_rotated) ---------------------------------
# Every page is rotated 90 deg (p1 and p2 opposite ways); the corpus OCR is noise and the manual rects are tall
# strips. The region re-OCR must read each strip turned upright, record the turn, and store the crop upright.
RF = HERE / "fixtures" / "receipts_rotated"
if (RF / "bank.json").exists():
    E = TMP / "EER" / "work"
    shutil.copytree(RF / "corpus", E / "corpus")
    (E / "endsem").mkdir(parents=True)
    shutil.copy2(RF / "manifest.json", E / "manifest.json")
    for rel in json.loads((RF / "manifest.json").read_text("utf-8"))["files"]:
        (TMP / "EER" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RF / rel, TMP / "EER" / rel)
    (E / "endsem" / "blueprint.json").write_text(json.dumps({"units": [{"id": "U1", "topics": [{"id": "T01"}]}]}), "utf-8")
    shutil.copy2(RF / "bank.json", E / "endsem" / "pyq_bank.json")
    re_ = subprocess.run([sys.executable, str(PIPE / "tools" / "receipts.py"), "EER", "--scope", "endsem"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         env=dict(os.environ, STUDYPREP_ROOT=str(TMP)))
    rje = E / "endsem" / "receipts" / "receipts.json"
    rece = json.loads(rje.read_text("utf-8")) if rje.exists() else {}
    import verify_pyqs as vpr
    ids = ("ES2023SP-1a", "ES2023SP-1b", "ES2023SP-1d")
    got = {q: ((rece.get(q) or {}).get("match"), (rece.get(q) or {}).get("rotate")) for q in ids}
    check("sideways scan: region OCR of each manual rect, turned upright, matches the question",
          all((m or 0) >= vpr.RECEIPT_MIN and r in (90, 180, 270) for m, r in got.values()),
          (got, (re_.stdout + re_.stderr)[-600:]))
    check("sideways scan: opposite-turned pages get opposite turns (p1 vs p2)",
          got["ES2023SP-1a"][1] is not None and got["ES2023SP-1d"][1] is not None
          and (got["ES2023SP-1a"][1] + 180) % 360 == got["ES2023SP-1d"][1], got)
    # 2(a) runs over p2 and p3, which are turned opposite ways: each part must be read with its own turn
    e2a = rece.get("ES2023SP-2a") or {}
    check("sideways scan: a 2-page receipt whose pages are turned opposite ways reads in full (per-part turns)",
          (e2a.get("match") or 0) >= vpr.RECEIPT_MIN and isinstance(e2a.get("rotate"), list)
          and len(set(e2a["rotate"])) == 2, {k: e2a.get(k) for k in ("match", "rotate", "ocr_method")})
    from PIL import Image
    sizes = {}
    for q in ids:
        f = (rece.get(q) or {}).get("file")
        if f and (E / "endsem" / f).exists():
            with Image.open(E / "endsem" / f) as im:
                sizes[q] = im.size
    check("sideways scan: stored receipt crops are upright (wider than tall for these 1-3 line questions)",
          len(sizes) == 3 and all(w > h for w, h in sizes.values()), sizes)
else:
    check("fixtures/receipts_rotated present", False)

if not os.environ.get("KEEP"):
    shutil.rmtree(TMP, ignore_errors=True)
print("OK test_receipts" if not fails else f"FAIL test_receipts: {fails} check(s)")
sys.exit(1 if fails else 0)
