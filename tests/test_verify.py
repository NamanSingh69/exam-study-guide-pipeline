"""Attack suite for verify_pyqs.py (REVIEW_2026-11-05 section 2.1 plus Round 4 additions).

Runs the gate CLI against a copy of the CN midsem bank in tests/_tmp/verify/ (STUDYPREP_ROOT).
The untouched bank (with stand-in receipts) must PASS; every attack must end in RESULT BLOCKED with
exit code 1 and, where the attack targets one question, a failure row for that question naming the
expected reason. Set T1_VERIFY_SCRIPT to run the suite against another copy of the gate (RED check).
"""
import copy, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
REAL = PIPE.parent / "CN" / "work"
TMP = HERE / "_tmp" / "verify"
SCRIPT = os.environ.get("T1_VERIFY_SCRIPT") or str(PIPE / "tools" / "verify_pyqs.py")
sys.path.insert(0, str(PIPE / "tools"))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

SLUGS = ["PYQM_2022_Midsem_1_Computer_Networks", "PYQM_2024_Midsem_1_Computer_Networks_1",
         "PYQM_2025_Midsem_1_Computer_Networks_1"]
fails = 0


def setup():
    if TMP.exists():
        shutil.rmtree(TMP)
    w = TMP / "CN" / "work"
    (w / "corpus").mkdir(parents=True)
    (w / "midsem" / "receipts").mkdir(parents=True)
    for s in SLUGS:
        shutil.copy2(REAL / "corpus" / f"{s}.md", w / "corpus" / f"{s}.md")
    for f in ("pyq_bank.json", "blueprint.json"):
        shutil.copy2(REAL / "midsem" / f, w / "midsem" / f)
    return w / "midsem"


WORK = setup()
BANK = WORK / "pyq_bank.json"
REAL_BANK = json.loads(BANK.read_text("utf-8"))
# the attack suite is pinned to the three original trial papers, whatever else the real bank grows to hold
TRIAL = ("MS2022", "MS2024", "MS2025")
ORIG = {"papers": [p for p in REAL_BANK["papers"] if p["id"] in TRIAL],
        "questions": [q for q in REAL_BANK["questions"] if q.get("paper") in TRIAL],
        "clusters": REAL_BANK["clusters"], "imp_list": REAL_BANK.get("imp_list", [])}
BANK.write_text(json.dumps(ORIG, ensure_ascii=False), "utf-8")


def write_receipts(bank, match=1.0):
    """Stand-in receipts (receipts.py itself is tested in test_receipts.py)."""
    try:
        from verify_pyqs import text_sha
    except ImportError:          # old gate: no receipts at all
        return
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")
    rec = {}
    for q in bank.get("questions", []):
        (WORK / "receipts" / f"{q['id']}.png").write_bytes(png)
        rec[q["id"]] = {"page": 1, "rect": [0, 0, 100, 20], "match": match, "method": "test",
                        "file": f"receipts/{q['id']}.png", "text_sha": text_sha(q.get("text") or "")}
    (WORK / "receipts" / "receipts.json").write_text(json.dumps(rec), "utf-8")


def run(bank, receipts=True, args=("CN", "--scope", "midsem")):
    BANK.write_text(json.dumps(bank, ensure_ascii=False), "utf-8")
    if receipts:
        write_receipts(ORIG)       # receipts made from the ORIGINAL bank, as a real run would have
    else:
        shutil.rmtree(WORK / "receipts", ignore_errors=True)
        (WORK / "receipts").mkdir()
    env = dict(os.environ, STUDYPREP_ROOT=str(TMP))
    r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    return r.returncode, lines


def expect(name, bank, rc=1, qid=None, reason=None, receipts=True, last=None):
    global fails
    code, lines = run(bank, receipts)
    final = lines[-1] if lines else ""
    ok = code == rc and final.startswith(last or ("RESULT BLOCKED" if rc == 1 else "RESULT PASS"))
    if ok and qid:
        rows = [l for l in lines if l.split()[:1] == [qid]]
        ok = bool(rows) and (reason is None or any(reason in l for l in rows))
    if ok and reason and not qid:
        ok = any(reason in l for l in lines)
    print(("OK   " if ok else "FAIL ") + f"{name}  (rc={code}; {final[:110]})")
    if not ok:
        fails += 1
        print("\n".join("     | " + l for l in lines[-25:]))


def mod(qid, **kw):
    b = copy.deepcopy(ORIG)
    for q in b["questions"]:
        if q["id"] == qid:
            for k, v in kw.items():
                q[k] = v(q) if callable(v) else v
    return b


def drop(*qids):
    b = copy.deepcopy(ORIG)
    b["questions"] = [q for q in b["questions"] if q["id"] not in qids]
    return b


def text_of(qid):
    return next(q["text"] for q in ORIG["questions"] if q["id"] == qid)


# --- baseline: the real bank passes ------------------------------------------------------------
expect("real CN midsem bank passes", copy.deepcopy(ORIG), rc=0)

# --- the reviewer's attack script (attack_verify.py) --------------------------------------------
expect("empty bank", {"papers": [], "questions": [], "clusters": []}, reason="empty bank")
b = copy.deepcopy(ORIG); b["questions"] = []
expect("papers, zero questions", b, reason="empty bank")
b = copy.deepcopy(ORIG); seen = set(); keep = []
for q in b["questions"]:
    if q["paper"] not in seen:
        seen.add(q["paper"]); keep.append(q)
b["questions"] = keep
expect("1 question per paper (rest dropped)", b, reason="full marks")
expect("question text ''", mod("MS2024-1c", text=""), qid="MS2024-1c", reason="empty question text")
expect("numbers changed 4th->7th, 15->12",
       mod("MS2024-1c", text=lambda q: q["text"].replace("4th", "7th").replace("15(fifteen)", "12(twelve)")),
       qid="MS2024-1c", reason="number '7th'")
expect("numbers changed 1 Mbps->100 Mbps, 20 ms->2 ms",
       mod("MS2025-4a", text=lambda q: q["text"].replace("1 Mbps", "100 Mbps").replace("20 milliseconds", "2 milliseconds")),
       qid="MS2025-4a", reason="number '100'")
expect("ISN 2171 -> 2117, 1000 bytes -> 100 bytes",
       mod("MS2024-5a", text=lambda q: q["text"].replace("2171", "2117").replace("1000 bytes", "100 bytes")),
       qid="MS2024-5a", reason="number '2117'")
expect("UDP->TCP swap", mod("MS2022-1c", text=lambda q: q["text"].replace("UDP", "TCP")),
       qid="MS2022-1c", reason="acronym 'TCP'")
expect("FQDN/PQDN -> DNS/ARP", mod("MS2025-1e", text="What are DNS and ARP?"),
       qid="MS2025-1e", reason="acronym 'ARP'")
expect("fabricated: sliding window protocol",
       mod("MS2024-1c", text="Explain the sliding window protocol with packets and transmission."),
       qid="MS2024-1c", reason="containment")
expect("fabricated: 'Define TCP.'", mod("MS2024-1c", text="Define TCP."), qid="MS2024-1c", reason="tokens found")
expect("fabricated: 'Define TCP.' not vision-verified", mod("MS2024-1c", text="Define TCP.", verified="ocr"),
       qid="MS2024-1c", reason="not vision-verified")
expect("fabricated: 'What is ARP? Why is it used?'", mod("MS2024-1c", text="What is ARP? Why is it used?"),
       qid="MS2024-1c", reason="acronym 'ARP'")
expect("topic T99 not in blueprint", mod("MS2024-1c", topic="T99"), qid="MS2024-1c", reason="T99 not in blueprint")
b = copy.deepcopy(ORIG); b["papers"][0]["source_slug"] = "nope"
expect("paper corpus missing", b, reason="corpus file nope.md not found")
expect("marks '2.5 M'", mod("MS2024-1c", marks="2.5 M"), qid="MS2024-1c", reason="not a positive number")
expect("marks '1' (string)", mod("MS2024-1c", marks="1"), qid="MS2024-1c", reason="not a positive number")

# --- Round 4 additions ----------------------------------------------------------------------------
expect("question copied from a different paper (MS2022 caching Q as MS2024-5b)",
       mod("MS2024-5b", text=text_of("MS2022-2b")), qid="MS2024-5b", reason="containment")
expect("near-duplicate copied from a different paper (MS2022 GBN Q as MS2024-4b)",
       mod("MS2024-4b", text=text_of("MS2022-1a")), qid="MS2024-4b", reason="unexplained edit")
expect("question moved to another paper (MS2022-2b filed under MS2024)",
       mod("MS2022-2b", paper="MS2024"), qid="MS2022-2b", reason="containment")
expect("sub-part dropped (MS2024-5b): marks don't add up", drop("MS2024-5b"), reason="unequal marks")
expect("sub-part dropped from compulsory Q1 (MS2024-1e)", drop("MS2024-1e"), reason="pattern says Q1 is 5 x 1")
expect("whole optional question dropped (MS2024 Q5)", drop("MS2024-5a", "MS2024-5b"),
       reason="pattern lists 4 optional questions")
expect("short-note sub-part dropped (MS2025-5iii)", drop("MS2025-5iii"), reason="says 'any 2' but only 2 part(s)")
expect("two short-note sub-parts dropped (MS2025-5ii, 5iii)", drop("MS2025-5ii", "MS2025-5iii"), reason="unequal marks")
expect("two words substituted (MS2025-3a termination->teardown, server->host)",
       mod("MS2025-3a", text=lambda q: q["text"].replace("connection termination", "connection teardown")
           .replace("a server", "a host")),
       qid="MS2025-3a", reason="unexplained edit")
expect("acronyms swapped GBN<->SR (MS2024-4a)",
       mod("MS2024-4a", text=lambda q: q["text"].replace("(GBN)", "(@@)").replace("(SR)", "(GBN)").replace("(@@)", "(SR)")),
       qid="MS2024-4a", reason="out of place")
expect("acronyms swapped TCP<->UDP (MS2025-1b)",
       mod("MS2025-1b", text="Why UDP/IP protocol is preferable over TCP/IP protocol for data transfer?"),
       qid="MS2025-1b", reason="out of place")
expect("acronyms swapped SYN<->FIN (MS2022-3b)",
       mod("MS2022-3b", text=lambda q: q["text"].replace("SYN, ACK and FIN", "FIN, ACK and SYN")),
       qid="MS2022-3b", reason="out of place")
expect("numbers swapped ISN 50<->81 (MS2022-3b)",
       mod("MS2022-3b", text=lambda q: q["text"].replace("Client is 50 and for Server is 81", "Client is 81 and for Server is 50")),
       qid="MS2022-3b", reason="out of place")
expect("sub-part duplicated over another (MS2024-5b := 5a)", mod("MS2024-5b", text=text_of("MS2024-5a")),
       qid="MS2024-5b", reason="duplicates another question")
b = copy.deepcopy(ORIG); b["questions"].append(dict(b["questions"][0]))
expect("duplicate question id", b, qid=b["questions"][0]["id"], reason="duplicate question id")
BOGUS_C = "CX_NOT_A_CLUSTER"     # (C99 became a real cluster when the bank grew)
assert BOGUS_C not in {c["id"] for c in ORIG["clusters"]}
expect("unknown cluster", mod("MS2024-1c", cluster=BOGUS_C), qid="MS2024-1c", reason=f"unknown cluster {BOGUS_C}")
expect("ocr_fixes cannot excuse a missing acronym",
       mod("MS2024-2a", text=lambda q: q["text"].replace("non-persistence HTTP", "non-persistence FTP")),
       qid="MS2024-2a", reason="acronym 'FTP'")

# --- zero papers (weak-input mode, lead resolution R3) ----------------------------------------------
MAN = WORK.parent / "manifest.json"


def manifest(*cats):
    files = {"Notes/n.pdf": {"slug": "N_n", "category": "notes"}, "Syllabus/s.pdf": {"slug": "SYL_s", "category": "syllabus"}}
    for i, c in enumerate(cats):
        files[f"PYQs/p{i}.pdf"] = {"slug": f"P{i}", "category": c}
    MAN.write_text(json.dumps({"files": files}), "utf-8")


weak = {"no_papers": True, "papers": [], "questions": [], "clusters": copy.deepcopy(ORIG["clusters"]),
        "imp_list": copy.deepcopy(ORIG["imp_list"])}
manifest()
expect("no_papers with no PYQ files passes", copy.deepcopy(weak), rc=0, receipts=False,
       last="RESULT PASS (no papers: weak-input mode)")
manifest("pyq_midsem")
expect("no_papers while a midsem PYQ file exists blocks", copy.deepcopy(weak), receipts=False, reason="past-paper file")
manifest("pyq_endsem")
expect("no_papers while an endsem PYQ file exists blocks", copy.deepcopy(weak), receipts=False, reason="past-paper file")
manifest()
w = copy.deepcopy(weak); w["clusters"][0]["topic"] = "T99"
expect("no_papers still checks cluster topics", w, receipts=False, reason="topic T99 not in blueprint")
w = copy.deepcopy(weak); w["clusters"] = []
expect("no_papers with no clusters blocks", w, receipts=False, reason="no clusters")
w = copy.deepcopy(weak); w["questions"] = copy.deepcopy(ORIG["questions"][:2])
expect("no_papers with questions in the bank blocks", w, receipts=False, reason="no_papers is true but the bank has")
w = copy.deepcopy(weak); w["no_papers"] = "yes"
expect("no_papers must be a boolean", w, receipts=False, reason="no_papers must be true or false")
w = copy.deepcopy(weak); del w["no_papers"]
expect("empty bank without the flag still blocks (no PYQ files)", w, receipts=False, reason="empty bank")
MAN.unlink()
expect("no_papers without a manifest blocks", copy.deepcopy(weak), receipts=False, reason="manifest.json missing")

# --- receipts --------------------------------------------------------------------------------------
expect("no receipts at all", copy.deepcopy(ORIG), receipts=False, qid="MS2024-1c", reason="no receipt")
b = copy.deepcopy(ORIG)
BANK.write_text(json.dumps(b), "utf-8")


def run_with_receipts(bank, match, name, rc, qid=None, reason=None, alter=None):
    global fails
    write_receipts(ORIG, match=match)
    if alter:
        alter()
    BANK.write_text(json.dumps(bank, ensure_ascii=False), "utf-8")
    env = dict(os.environ, STUDYPREP_ROOT=str(TMP))
    r = subprocess.run([sys.executable, SCRIPT, "CN", "--scope", "midsem"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    ok = r.returncode == rc and lines and lines[-1].startswith("RESULT PASS" if rc == 0 else "RESULT BLOCKED")
    if ok and qid:
        ok = any(l.split()[:1] == [qid] and (reason or "") in l for l in lines)
    print(("OK   " if ok else "FAIL ") + f"{name}  (rc={r.returncode}; {lines[-1][:110] if lines else ''})")
    if not ok:
        fails += 1
        print("\n".join("     | " + l for l in lines[-20:]))


run_with_receipts(copy.deepcopy(ORIG), 0.3, "low-match receipts block", 1, "MS2024-1c", "low-match receipt")
manual = copy.deepcopy(ORIG)
for q in manual["questions"]:
    q["receipt"] = {"page": 1, "rect": [20, 100, 570, 160]}
run_with_receipts(manual, 0.3, "low match + vision + manual rect passes", 0)
nov = copy.deepcopy(manual)
for q in nov["questions"]:
    if q["id"] == "MS2024-1c":
        q["verified"] = "ocr"
run_with_receipts(nov, 0.3, "low match + manual rect but not vision blocks", 1, "MS2024-1c", "low-match receipt")
run_with_receipts(copy.deepcopy(ORIG), 1.0, "receipt image missing blocks", 1, "MS2024-1c", "receipt image missing",
                  alter=lambda: (WORK / "receipts" / "MS2024-1c.png").unlink())
# a text edit that keeps the paper check happy (OCR-typo-level) still invalidates the receipt
expect("stale receipt after a text edit",
       mod("MS2024-1c", text=lambda q: q["text"].replace("total 15(fifteen)", "total 15 (fifteen)") + " "),
       qid="MS2024-1c", reason="stale")

# --- transcribers' real papers: OCR damage the gate must accept, and the limits of that -----------
# The 11 papers of tx1/tx2/tx3 (from the real bank, or their part files before the merge) plus the trial
# papers, in subject folder CNX. Stand-in receipts carry no fresh OCR text, except for the questions whose
# corpus OCR is garbage (tx3: MS2026SP 1a-1e; ES2026SP spreads 3b, 4a, 4b, 5b OR): there the stand-in
# fresh OCR is the paper's own wording (test_receipts.py checks real fresh OCR end to end).
PART_IDS = ("ES2018", "ES2019", "ES2022", "ES2023", "MS2019", "MS2020", "MS2023",
            "ES2024", "ES2025", "MS2026SP", "ES2026SP")
GARBLED = ("MS2026SP-1a", "MS2026SP-1b", "MS2026SP-1c", "MS2026SP-1d", "MS2026SP-1e",
           "ES2026SP-3b", "ES2026SP-4a", "ES2026SP-4b", "ES2026SP-5bOR")
X = TMP / "CNX" / "work"
(X / "corpus").mkdir(parents=True)
(X / "midsem" / "receipts").mkdir(parents=True)
shutil.copy2(REAL / "midsem" / "blueprint.json", X / "midsem" / "blueprint.json")
for f in (REAL / "corpus").glob("PYQ*.md"):
    shutil.copy2(f, X / "corpus" / f.name)
XB = copy.deepcopy(ORIG)
PARTS = []
for pid in PART_IDS:
    paper = next((p for p in REAL_BANK["papers"] if p["id"] == pid), None)
    qs = [q for q in REAL_BANK["questions"] if q.get("paper") == pid]
    f = REAL / "midsem" / f"pyq_bank.part_{pid}.json"
    if (paper is None or not qs) and f.exists():
        shutil.copy2(f, X / "midsem" / f.name)
        pb = json.loads(f.read_text("utf-8"))
        paper, qs = pb["paper"], pb["questions"]
    if paper is None:
        continue
    PARTS.append(pid)
    XB["papers"].append(paper)
    for q in copy.deepcopy(qs):
        q.setdefault("cluster", "C04"); q.setdefault("topic", "T01"); q.setdefault("type", "theory")
        XB["questions"].append(q)
XIDS = {q["id"] for q in XB["questions"]}
PAPER_WORDS = {q["id"]: q["text"] for q in XB["questions"]}      # what the paper itself says
# the PDFs and manifest too: the gate tells a scanner's OCR text layer (MS2023, ES2024) from a clean one
_cn_man = json.loads((REAL / "manifest.json").read_text("utf-8"))["files"]      # REAL = CN/work
_slugs = {p["source_slug"] for p in XB["papers"]}
_files = {rel: m for rel, m in _cn_man.items() if m.get("slug") in _slugs}
for rel in _files:
    (TMP / "CNX" / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REAL.parent / rel, TMP / "CNX" / rel)
(X / "manifest.json").write_text(json.dumps({"files": _files}), "utf-8")


def runx(name, bank, rc=1, qid=None, reason=None, receipts_bank=None, matches=None, drop_png=(), want=None,
         fresh=GARBLED):
    """Run the gate on CNX; receipts are made from receipts_bank (default: the merged original). Questions in
    `fresh` get a stand-in fresh OCR text: always the PAPER's wording, never an edited question's."""
    global fails
    from verify_pyqs import text_sha
    rec = {}
    for q in (receipts_bank or XB)["questions"]:
        png = X / "midsem" / "receipts" / f"{q['id']}.png"
        png.write_bytes(b"\x89PNG")
        rec[q["id"]] = {"page": 1, "rect": [0, 0, 100, 20], "match": (matches or {}).get(q["id"], 1.0),
                        "method": "test", "file": f"receipts/{q['id']}.png", "text_sha": text_sha(q.get("text") or "")}
        if q["id"] in fresh:
            rec[q["id"]].update(ocr_text=PAPER_WORDS[q["id"]], ocr_method="test", ocr_is_ocr=True)
    for qd in drop_png:
        (X / "midsem" / "receipts" / f"{qd}.png").unlink()
    (X / "midsem" / "receipts" / "receipts.json").write_text(json.dumps(rec), "utf-8")
    (X / "midsem" / "pyq_bank.json").write_text(json.dumps(bank, ensure_ascii=False), "utf-8")
    r = subprocess.run([sys.executable, SCRIPT, "CNX", "--scope", "midsem"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=dict(os.environ, STUDYPREP_ROOT=str(TMP)))
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    final = lines[-1] if lines else ""
    ok = r.returncode == rc and final.startswith("RESULT PASS" if rc == 0 else "RESULT BLOCKED")
    if ok and qid:
        ok = any(l.split()[:1] == [qid] and (reason or "") in l for l in lines)
    if ok and want:
        ok = any(want in l for l in lines)
    print(("OK   " if ok else "FAIL ") + f"{name}  (rc={r.returncode}; {final[:110]})")
    if not ok:
        fails += 1
        print("\n".join("     | " + l for l in lines[-25:]))


def xmod(qid, **kw):
    b = copy.deepcopy(XB)
    for q in b["questions"]:
        if q["id"] == qid:
            for k, v in kw.items():
                q[k] = v(q) if callable(v) else v
    return b


if {"ES2018-1j", "MS2020-3b", "ES2019-3b", "MS2023-2a", "ES2022-8b"} <= XIDS:
    runx(f"real transcriber parts ({len(PARTS)} papers) pass with their ocr_fixes", copy.deepcopy(XB), rc=0)
    runx("endsem Q1 runs a-j: 1(j) is grouped with Q1 (ES2018 10 x 2)", copy.deepcopy(XB), rc=0,
         want="paper ES2018 [PYQE_2018_Endsem_1_Computer_Networks]: 25 question(s); marks 20 compulsory + 5 of 7 x 8 = 60")
    runx("internal choice inside one sub-part (ES2022 8(b) 'any two of the following')", copy.deepcopy(XB), rc=0,
         want="paper ES2022 [PYQE_2022_Endsem_1_Computer_Networks]: 24 question(s); marks 10 compulsory + 5 of 7 x 8 = 50")
    runx("pipe fold: ES2019-3b '| MSS' matches '1 MSS' with no excuse needed", xmod("ES2019-3b", ocr_fixes=""), rc=0)
    runx("0/O fold: MS2023-2a 'RTTO' matches 'RTT0' with no excuse needed", xmod("MS2023-2a", ocr_fixes=""), rc=0)
    runx("lost superscript without ocr_fixes blocks (MS2020-3b)", xmod("MS2020-3b", ocr_fixes=""),
         qid="MS2020-3b", reason="number '2' not in the matched paper text")
    runx("lost superscript without vision blocks (MS2020-3b)", xmod("MS2020-3b", verified="ocr"),
         qid="MS2020-3b", reason="number '2' not in the matched paper text")
    runx("lost superscript with a low-match receipt blocks (MS2020-3b)", copy.deepcopy(XB),
         matches={"MS2020-3b": 0.3}, qid="MS2020-3b", reason="number '2' not in the matched paper text")
    runx("lost superscript with no receipt image blocks (MS2020-3b)", copy.deepcopy(XB), drop_png=("MS2020-3b",),
         qid="MS2020-3b", reason="number '2' not in the matched paper text")
    runx("lost acronym without ocr_fixes blocks (MS2023-4a 'III')", xmod("MS2023-4a", ocr_fixes=""),
         qid="MS2023-4a", reason="acronym 'III'")
    b = xmod("ES2019-3b", text=lambda q: q["text"].replace("1 MSS", "2 MSS"))
    runx("number swap on an OCR'd page without vision + ocr_fixes blocks (ES2019-3b 1->2 MSS)",
         b, receipts_bank=b, qid="ES2019-3b", reason="number '2'")
    b = xmod("MS2024-1c", text=lambda q: q["text"].replace("4th", "7th"), ocr_fixes="'7th' was 'Ath' in OCR")
    runx("swap to a different clean number blocks even with vision + ocr_fixes + fresh receipt",
         b, receipts_bank=b, qid="MS2024-1c", reason="paper has '4th' there")
    b = xmod("MS2024-4a", text=lambda q: q["text"].replace("(GBN)", "(@@)").replace("(SR)", "(GBN)").replace("(@@)", "(SR)"),
             ocr_fixes="'GBN' and 'SR' misread in OCR")
    runx("acronym swap blocks even with vision + ocr_fixes + fresh receipt", b, receipts_bank=b,
         qid="MS2024-4a", reason="out of place")
    # the same lost number: excused on an OCR'd page, strict on a text-layer page
    cf = X / "corpus" / "PYQM_2025_Midsem_1_Computer_Networks_1.md"
    orig_c = cf.read_text("utf-8")
    lost = orig_c.replace("up to 15 packets", "up to packets")
    b = xmod("MS2025-4a", ocr_fixes="'15' is lost in the paper text")
    cf.write_text(lost, "utf-8")
    runx("number lost on an OCR'd page: excused with vision + ocr_fixes + receipt", b, rc=0, receipts_bank=b)
    cf.write_text(lost.replace("] (OCR)", "]"), "utf-8")
    runx("number lost in a text layer: no excuse", b, receipts_bank=b, qid="MS2025-4a",
         reason="number '15' not in the matched paper text")
    cf.write_text(orig_c, "utf-8")
else:
    print("FAIL tx1/tx2 papers not found (real bank or CN/work/midsem/pyq_bank.part_*.json)")
    fails += 1

if {"ES2026SP-1bOR", "ES2025-5a", "MS2026SP-1c", "MS2026SP-Q5", "ES2024-1j"} <= XIDS:
    # either-or pairs (ES2026SP: Q1-Q5 each "Qn ... OR ...", 5 x 10 = 50)
    runx("either-or pairs: Qn and Qn OR are one choice slot (ES2026SP 5 x 10)", copy.deepcopy(XB), rc=0,
         want="paper ES2026SP [PYQE_6th_Sem_2026_end_Computer_Networks_CS30003]: 20 question(s); "
              "marks 0 compulsory + 5 of 5 x 10 = 50 (5 either-or pair(s))")
    b = copy.deepcopy(XB); b["questions"] = [q for q in b["questions"] if q["id"] != "ES2026SP-3bOR"]
    runx("a sub-part dropped from one OR alternative blocks", b, want="its OR alternative (5) carry different marks")
    b = copy.deepcopy(XB); b["questions"] = [q for q in b["questions"] if q["id"] not in ("ES2026SP-3a", "ES2026SP-3b")]
    runx("an OR alternative without its first alternative blocks", b, want="Q3 OR is banked but its first alternative")
    b = xmod("ES2026SP-1b", text=PAPER_WORDS["ES2026SP-1a"])
    runx("a real duplicate within one alternative still blocks (1(b) := 1(a))", b, qid="ES2026SP-1b",
         reason="duplicates another question")
    # OCR near-misses are excusable, but only with vision + ocr_fixes + receipt
    runx("'$00,000' for '800,000' without ocr_fixes blocks (ES2025-5a)", xmod("ES2025-5a", ocr_fixes=""),
         qid="ES2025-5a", reason="number '800,000'")
    runx("'EPRAME' for 'FRAME' without ocr_fixes blocks (MS2026SP-Q5)", xmod("MS2026SP-Q5", ocr_fixes=""),
         qid="MS2026SP-Q5", reason="acronym 'FRAME'")
    # garbage corpus OCR: the receipt's fresh OCR decides, and only when it passes every check
    runx("garbled corpus without a fresh-OCR receipt blocks (MS2026SP-1c)", copy.deepcopy(XB),
         fresh=tuple(g for g in GARBLED if g != "MS2026SP-1c"), qid="MS2026SP-1c", reason="of its tokens found")
    b = xmod("MS2026SP-1c", text=lambda q: q["text"].replace("100%", "90%"), ocr_fixes="'90%' was garbled in OCR")
    runx("edited number on a garbled line blocks against the fresh OCR too (100% -> 90%)", b, receipts_bank=b,
         qid="MS2026SP-1c", reason="number '90'")
    b = xmod("MS2026SP-1c", text=lambda q: q["text"].replace("Justify your", "Justify  your"))
    runx("fresh OCR of a stale receipt is not used (MS2026SP-1c edited after receipts.py)", b,
         qid="MS2026SP-1c", reason="receipt is stale")
else:
    print("FAIL tx3 papers not found (real bank or CN/work/midsem/pyq_bank.part_*.json)")
    fails += 1


# --- data tables (ML endsem transcription: KNN / least-squares datasets) -------------------------------
# Copies of ML/work/endsem/pyq_bank.part_{MS2023,MS2023B,MS2022}.json. The transcribers typed each table
# inline as 'a | b | c' lines; here they are converted to the schema form: prose in `text` with a [table]
# placeholder, the cells in `table`. Subject folder MLX, synthetic blueprint (the part files have no clusters).
ML = PIPE.parent / "ML" / "work"
TABLE_QS = ("MS2023-2a", "MS2023-3a", "MS2023B-2b", "MS2023B-3b", "MS2022-4a", "MS2022-5a")


def to_table(q):
    lines = q["text"].split("\n")
    rows = [l for l in lines if " | " in l]
    if not rows:
        return q
    prose, placed = [], False
    for l in lines:
        if " | " in l:
            if not placed:
                prose.append("[table]"); placed = True
        else:
            prose.append(l)
    q["text"] = "\n".join(prose)
    q["table"] = {"header": [c.strip() for c in rows[0].split("|")],
                  "rows": [[c.strip() for c in r.split("|")] for r in rows[1:]]}
    return q


# Also from the ML transcription: MS2023-3a (garbled *text layer* of a scanned PDF), ES2023B-5a ("any two" that
# is not a choice over sub-parts), ES2022B / BS2 / BS3 (3 question sets in one PDF), ES2026SP-5a and ES2025B-5a
# (margin marks '[5]' interleaved), ES2025D-4b (maths), MS2025B (a clean digital text layer: stays strict).
ML_IDS = ("MS2023", "MS2023B", "MS2022", "ES2023B", "ES2022B", "ES2022BS2", "ES2022BS3", "ES2026SP", "ES2025B",
          "ES2025D", "MS2025B")
SETS = {"ES2022B": [1, 4], "ES2022BS2": [5, 8], "ES2022BS3": [9, 12]}
MLP = [ML / "endsem" / f"pyq_bank.part_{p}.json" for p in ML_IDS]
if all(f.exists() for f in MLP):
    M = TMP / "MLX" / "work"
    (M / "corpus").mkdir(parents=True)
    (M / "endsem" / "receipts").mkdir(parents=True)
    (M / "endsem" / "blueprint.json").write_text(json.dumps(
        {"units": [{"id": "U1", "topics": [{"id": "T01"}]}]}), "utf-8")
    MB = {"papers": [], "questions": [], "clusters": [{"id": "C01", "topic": "T01"}]}
    INLINE = {}
    ml_man = json.loads((ML / "manifest.json").read_text("utf-8"))["files"]
    files = {}
    for f in MLP:
        shutil.copy2(f, M / "endsem" / f.name)
        pb = json.loads(f.read_text("utf-8"))
        slug = pb["paper"]["source_slug"]
        shutil.copy2(ML / "corpus" / f"{slug}.md", M / "corpus" / f"{slug}.md")
        for rel, mm in ml_man.items():                 # the PDF too: the gate checks scanner-OCR text layers
            if mm.get("slug") == slug and rel not in files:
                (TMP / "MLX" / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ML.parent / rel, TMP / "MLX" / rel)
                files[rel] = mm
        paper = dict(pb["paper"])
        if paper["id"] in SETS:
            paper["pages"] = SETS[paper["id"]]
        MB["papers"].append(paper)
        for q in pb["questions"]:
            q.update(cluster="C01", topic="T01")
            INLINE[q["id"]] = q["text"]
            if q["id"] == "ES2025D-4b":          # the transcriber's formula, written as $...$ maths
                t = q["text"]
                a0 = t.index("J(a,b)")
                a1 = t.index(", and the following dataset")
                q["text"] = t[:a0] + "$" + t[a0:a1] + "$" + t[a1:]
            if q["id"] == "ES2022BS2-3":         # printed fraction glyphs (OCR loses them), written as maths
                q["text"] = q["text"].replace("½", "$1/2$").replace("¼", "$1/4$").replace("¾", "$3/4$")
            MB["questions"].append(to_table(q) if q["id"] in TABLE_QS else q)
    (M / "manifest.json").write_text(json.dumps({"files": files}), "utf-8")
    MLQ = {q["id"]: q for q in MB["questions"]}

    def runm(name, bank, rc=1, qid=None, reason=None, receipts_bank=None, matches=None, drop_png=(), want_line=None):
        global fails
        import verify_pyqs as vpm
        rsha = getattr(vpm, "receipt_sha", None) or (lambda q: vpm.text_sha(q.get("text") or ""))
        rec = {}
        for q in (receipts_bank or MB)["questions"]:
            (M / "endsem" / "receipts" / f"{q['id']}.png").write_bytes(b"\x89PNG")
            rec[q["id"]] = {"page": 1, "rect": [0, 0, 100, 20], "match": (matches or {}).get(q["id"], 1.0),
                            "method": "manual" if q.get("receipt") else "test", "file": f"receipts/{q['id']}.png",
                            "text_sha": rsha(q)}
        for qd in drop_png:
            (M / "endsem" / "receipts" / f"{qd}.png").unlink()
        (M / "endsem" / "receipts" / "receipts.json").write_text(json.dumps(rec), "utf-8")
        (M / "endsem" / "pyq_bank.json").write_text(json.dumps(bank, ensure_ascii=False), "utf-8")
        r = subprocess.run([sys.executable, SCRIPT, "MLX", "--scope", "endsem"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=dict(os.environ, STUDYPREP_ROOT=str(TMP)))
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        final = lines[-1] if lines else ""
        ok = r.returncode == rc and final.startswith("RESULT PASS" if rc == 0 else "RESULT BLOCKED")
        if ok and qid:
            ok = any(l.split()[:1] == [qid] and (reason or "") in l for l in lines)
        if ok and want_line:
            ok = any(want_line in l for l in lines)
        print(("OK   " if ok else "FAIL ") + f"{name}  (rc={r.returncode}; {final[:110]})")
        if not ok:
            fails += 1
            print("\n".join("     | " + l for l in lines[-25:]))

    def mmod(qid, **kw):
        b = copy.deepcopy(MB)
        for q in b["questions"]:
            if q["id"] == qid:
                for k, v in kw.items():
                    q[k] = v(q) if callable(v) else v
        return b

    runm(f"data tables: {len(TABLE_QS)} real ML table questions pass (prose matched, table via vision + receipt)",
         copy.deepcopy(MB), rc=0)
    def inline(q):                       # the old transcription: table rows typed into the text, no table field
        tab = q.pop("table")
        rows = "\n".join(" | ".join(str(c) for c in r) for r in [tab["header"]] + tab["rows"])
        return q["text"].replace("[table]", rows)

    b = copy.deepcopy(MB)
    for q in b["questions"]:
        if q["id"] == "MS2022-4a":
            q["text"] = inline(q)
    runm("inline table typed into the text blocks (MS2022-4a): the OCR of a table is garbage", b, receipts_bank=b,
         qid="MS2022-4a")
    b = mmod("MS2023-3a", verified="ocr")
    runm("a table without vision verification blocks", b, receipts_bank=b, qid="MS2023-3a", reason="table")
    runm("a table without a receipt image blocks", copy.deepcopy(MB), drop_png=("MS2023-3a",),
         qid="MS2023-3a", reason="table")
    b = mmod("MS2022-4a", receipt=None)
    b["questions"] = [dict(q, **({} if q["id"] != "MS2022-4a" else {})) for q in b["questions"]]
    for q in b["questions"]:
        if q["id"] == "MS2022-4a":
            q.pop("receipt", None)
    runm("a table whose automatic receipt matches badly blocks (no manual rect)", b, receipts_bank=b,
         matches={"MS2022-4a": 0.3}, qid="MS2022-4a", reason="table")
    b = mmod("MS2023-3a", table=lambda q: {"header": q["table"]["header"], "rows": q["table"]["rows"][:1] + [q["table"]["rows"][1][:3]] + q["table"]["rows"][2:]})
    runm("a ragged table row blocks", b, receipts_bank=b, qid="MS2023-3a", reason="row 2 has 3 cell(s), header has 4")
    b = mmod("MS2022-4a", table=lambda q: {"header": q["table"]["header"], "rows": [q["table"]["rows"][0][:2] + [""]] + q["table"]["rows"][1:]})
    runm("an empty table cell blocks", b, receipts_bank=b, qid="MS2022-4a", reason="empty cell")
    b = mmod("MS2022-4a", table=lambda q: {"header": q["table"]["header"], "rows": [q["table"]["rows"][0][:2] + ["-"]] + q["table"]["rows"][1:]})
    runm("a '-' table cell is allowed", b, rc=0, receipts_bank=b)
    b = mmod("MS2023-3a", text=lambda q: q["text"].replace("[table]", ""))
    runm("a table without its [table] placeholder in the text blocks", b, receipts_bank=b, qid="MS2023-3a",
         reason="[table]")
    b = mmod("MS2023-3a", table={"header": "X1 X2", "rows": []})
    runm("a malformed table (header not a list, no rows) blocks", b, receipts_bank=b, qid="MS2023-3a", reason="table")
    b = mmod("MS2023-3a", table=lambda q: {"header": q["table"]["header"], "rows": [["I1", "7", "7", "1"]] + q["table"]["rows"][1:]})
    runm("a table edited after receipts.py ran makes the receipt stale", b, qid="MS2023-3a", reason="stale")
    b = mmod("MS2023-3a", text=lambda q: q["text"].replace("K=3", "K=5"))
    runm("the prose is still matched in full: K=3 -> K=5 blocks despite the table", b, receipts_bank=b,
         qid="MS2023-3a", reason="number '5'")

    # a scanner's OCR text layer (invisible text over the page image) is OCR quality: MS2023-3a 't1' read
    # 'tr-{3,7)' passes above with vision + ocr_fixes + receipt; without that evidence the text layer is strict
    man_full = (M / "manifest.json").read_text("utf-8")
    (M / "manifest.json").write_text(json.dumps({"files": {k: v for k, v in json.loads(man_full)["files"].items()
                                                           if v["slug"] != "PYQM_2023_Midsem_1_Machine_Learning"}}), "utf-8")
    runm("no scanner-OCR evidence for the PDF: its text layer is strict (MS2023-3a 't1')", copy.deepcopy(MB),
         qid="MS2023-3a", reason="'t1'")
    (M / "manifest.json").write_text(man_full, "utf-8")
    # a clean digital text layer stays strict, even where ingest's OCR copy of the page could be matched
    cfm = M / "corpus" / "PYQM_2025_Midsem_2_Machine_Learning.md"
    cm_orig = cfm.read_text("utf-8")
    cfm.write_text(cm_orig.replace("instances, where 6 belong", "instances, where belong"), "utf-8")
    b = mmod("MS2025B-1e", ocr_fixes="'6' was lost in the text", verified="vision")
    runm("clean digital page: a number missing from the text layer blocks even with vision + ocr_fixes",
         b, receipts_bank=b, qid="MS2025B-1e", reason="number '6'")
    cfm.write_text(cm_orig, "utf-8")

    # "any two" ranging over concepts is not a choice over sub-parts (ES2023B 5(a)); a stated choice still is
    b = mmod("ES2023B-5a", text="Answer any two of the following: (a) distance measures (b) K-means clustering")
    runm("'answer any two of the following' over two banked parts still blocks", b, receipts_bank=b,
         want_line="says 'any 2' but only 2 part(s)")

    # question sets sharing one PDF (ES2022B, BS2, BS3): each matched against its own pages only
    b = copy.deepcopy(MB)
    for p in b["papers"]:
        p.pop("pages", None) if p["id"] == "ES2022BS2" else None
    runm("papers sharing a source_slug without their own page ranges block", b,
         want_line="share source_slug")
    b = copy.deepcopy(MB)
    for p in b["papers"]:
        if p["id"] == "ES2022BS3":
            p["pages"] = [8, 12]
    runm("overlapping page ranges block", b, want_line="overlap")
    b = mmod("ES2022B-5", text=MLQ["ES2022BS2-5"]["text"])
    runm("a question of set 2 filed under set 1 blocks (only set 1's pages are searched)", b, receipts_bank=b,
         qid="ES2022B-5")

    # margin marks '[5]' interleaved by OCR are dropped (ES2026SP-5a, ES2025B-5a pass above); real numbers stay
    b = mmod("ES2026SP-5a", text=lambda q: q["text"].replace("X3 = 1", "X3 = 5"))
    runm("a number equal to the marks is still checked: X3 = 1 -> X3 = 5 blocks", b, receipts_bank=b,
         qid="ES2026SP-5a", reason="'5'")
    b = mmod("MS2023B-4b", text=lambda q: q["text"].replace("C1(2)", "C1(4)"))
    runm("'C1(2)' is not a marks annotation: C1(2) -> C1(4) blocks", b, receipts_bank=b,
         qid="MS2023B-4b", reason="'4'")

    # $...$ maths: confirmed only by vision + receipt; prose outside stays strict; no hiding prose in maths
    b = mmod("ES2025D-4b", verified="ocr")
    runm("$...$ maths without vision blocks (ES2025D-4b)", b, receipts_bank=b, qid="ES2025D-4b", reason="maths")
    runm("$...$ maths without a receipt image blocks", copy.deepcopy(MB), drop_png=("ES2025D-4b",),
         qid="ES2025D-4b", reason="maths")
    b = mmod("ES2025D-4b", text=lambda q: q["text"].replace("a = 1.0", "a = 2.0"))
    runm("a number outside $...$ is still checked: a = 1.0 -> 2.0 blocks", b, receipts_bank=b,
         qid="ES2025D-4b", reason="'2.0'")
    b = mmod("ES2025D-4b", text=lambda q: "$" + q["text"].replace("$", "") + "$")
    runm("attack: the whole question hidden inside $...$ blocks (share cap)", b, receipts_bank=b,
         qid="ES2025D-4b", reason="inside $...$")
    b = mmod("ES2025D-4b", text=lambda q: q["text"].replace("Use Gradient descent", "$Use Gradient descent"))
    runm("an unbalanced $ blocks", b, receipts_bank=b, qid="ES2025D-4b", reason="unbalanced $")
    b = mmod("MS2025B-4", text=lambda q: q["text"].replace("$17,000", "$18,000"))
    runm("currency '$17,000' is text, not maths: $17,000 -> $18,000 blocks", b, receipts_bank=b,
         qid="MS2025B-4", reason="18,000")
else:
    print("FAIL ML part files not found (ML/work/endsem/pyq_bank.part_*.json)")
    fails += 1

# --- receipt-rescued questions in the duplicate check (CI endsem, pinned in fixtures/verify_ci_rescue) ------
# MS2024B-1a/1b/1c and MS2025-1c: the corpus OCR of these lines is garbage, the receipt's fresh region OCR
# matches in full. The corpus alignment that failed leaves stray positions; the duplicate check must not use
# them (it blocked all four as "duplicates another question (owns 0)"). A real copy must still block.
CIF = HERE / "fixtures" / "verify_ci_rescue"
if (CIF / "bank.json").exists():
    C = TMP / "CIX" / "work"
    shutil.copytree(CIF / "corpus", C / "corpus")
    (C / "endsem" / "receipts").mkdir(parents=True)
    shutil.copy2(CIF / "manifest.json", C / "manifest.json")
    for rel in json.loads((CIF / "manifest.json").read_text("utf-8"))["files"]:
        (TMP / "CIX" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CIF / rel, TMP / "CIX" / rel)
    (C / "endsem" / "blueprint.json").write_text(json.dumps(
        {"units": [{"id": "U1", "topics": [{"id": "T01"}]}]}), "utf-8")
    CB = json.loads((CIF / "bank.json").read_text("utf-8"))
    CREC = json.loads((CIF / "receipts.json").read_text("utf-8"))
    RESCUED = ("MS2024B-1a", "MS2024B-1b", "MS2024B-1c", "MS2025-1c")

    def runc(name, bank, rc=1, qid=None, reason=None, rec_over=None):
        global fails
        import verify_pyqs as vpm
        rsha = getattr(vpm, "receipt_sha", None) or (lambda q: vpm.text_sha(q.get("text") or ""))
        rec = {}
        for q in bank["questions"]:
            (C / "endsem" / "receipts" / f"{q['id']}.png").write_bytes(b"\x89PNG")
            rec[q["id"]] = dict(CREC[q["id"]], file=f"receipts/{q['id']}.png", text_sha=rsha(q))
            rec[q["id"]].update((rec_over or {}).get(q["id"], {}))
        (C / "endsem" / "receipts" / "receipts.json").write_text(json.dumps(rec), "utf-8")
        (C / "endsem" / "pyq_bank.json").write_text(json.dumps(bank, ensure_ascii=False), "utf-8")
        r = subprocess.run([sys.executable, SCRIPT, "CIX", "--scope", "endsem"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=dict(os.environ, STUDYPREP_ROOT=str(TMP)))
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        final = lines[-1] if lines else ""
        ok = r.returncode == rc and final.startswith("RESULT PASS" if rc == 0 else "RESULT BLOCKED")
        if ok and qid:
            ok = any(l.split()[:1] == [qid] and (reason or "") in l for l in lines)
        print(("OK   " if ok else "FAIL ") + f"{name}  (rc={r.returncode}; {final[:110]})")
        if not ok:
            fails += 1
            print("\n".join("     | " + l for l in lines[-25:]))

    runc("receipt-rescued questions are not 'duplicates' of their neighbours (CI MS2024B-1a/1b/1c, MS2025-1c)",
         copy.deepcopy(CB), rc=0)
    # a real copy among rescued questions: 1(b) := 1(a), with the same receipt region and fresh OCR
    b = copy.deepcopy(CB)
    qa = next(q for q in b["questions"] if q["id"] == "MS2024B-1a")
    for q in b["questions"]:
        if q["id"] == "MS2024B-1b":
            q["text"], q["ocr_fixes"] = qa["text"], qa.get("ocr_fixes", "")
            if "receipt" in qa:
                q["receipt"] = qa["receipt"]
    runc("a rescued question that copies another still blocks (MS2024B 1(b) := 1(a))", b, qid="MS2024B-1b",
         reason="duplicates another question",
         rec_over={"MS2024B-1b": {k: CREC["MS2024B-1a"][k] for k in ("rect", "parts", "ocr_text") if k in CREC["MS2024B-1a"]}})
else:
    print("FAIL fixtures/verify_ci_rescue missing")
    fails += 1

# --- 'any two' over exactly the two items one sub-part lists (HPC ES2024 Q7(b), 2026-11-08) -------------------
# "Write short note on any two: (i) Vector ... (ii) VLIW ..." is 7(b)'s own wording over its own two items:
# both are answered for 7(b)'s 5 marks. It is not a choice over Q7's banked sub-parts. A real group-level
# "Answer any two of the following" over two banked sub-parts must still block (a sub-part is missing).
try:
    from verify_pyqs import check_marks
    pap = {"full_marks": 20, "pattern": "Q1 compulsory 10x1; any 1 of Q2-Q3"}
    q1 = [{"id": f"P-1{c}", "qno": f"1({c})", "marks": 1, "compulsory": True, "text": "x"} for c in "abcdefghij"]
    def q7(n, t):
        return [{"id": f"P-{n}a", "qno": f"{n}(a)", "marks": 5, "compulsory": False, "text": "Compute the AMAT."},
                {"id": f"P-{n}b", "qno": f"{n}(b)", "marks": 5, "compulsory": False, "text": t}]
    notes = "Write short note on any two:\n(i) Vector processor Architecture\n(ii) VLIW processor Architecture"
    pr_ok, _s = check_marks("P", pap, q1 + q7(2, notes) + q7(3, "Explain pipelining."))
    group = "Answer any two of the following. (a) Explain RAW hazards."
    pr_bad, _s = check_marks("P", pap, q1 + [dict(q, text=group) if q["qno"] == "2(a)" else q
                                             for q in q7(2, "Explain WAR hazards.")] + q7(3, "Explain pipelining."))
    ok = not pr_ok and any("a sub-part is missing" in p for p in pr_bad)
    print(("OK   " if ok else "FAIL ") + f"'any two' over a sub-part's own two items is its own choice; a group "
          f"'any two of the following' over 2 banked parts still blocks  (ok-case {pr_ok}; group-case {pr_bad})")
    fails += not ok
except ImportError as e:
    print(f"FAIL check_marks import: {e}"); fails += 1

try:
    from verify_pyqs import group_key
    gk = {s: group_key(s) for s in ("1(a)", "1(h)", "1(j)", "1(z)", "2(iv)", "5(iii)", "2(A)", "1.(c)",
                                    "3(a) [2nd Q3]", "3(b) [2nd Q3]", "7", "Q2", "1(b) OR", "1(b)OR", "1 OR (b)")}
    ok = (gk["1(a)"] == gk["1(h)"] == gk["1(j)"] == gk["1(z)"] == "1" and gk["2(iv)"] == gk["2(A)"] == "2"
          and gk["5(iii)"] == "5" and gk["1.(c)"] == "1" and gk["3(a) [2nd Q3]"] == gk["3(b) [2nd Q3]"] == "3 [2nd Q3]"
          and gk["7"] == "7" and gk["Q2"] == "2" and gk["1(b) OR"] == gk["1(b)OR"] == gk["1 OR (b)"] == "1 OR")
except ImportError:
    ok, gk = False, "group_key missing"
print(("OK   " if ok else "FAIL ") + f"group_key: any letter a-z or roman numeral; '[2nd Q3]' kept  ({gk})")
fails += not ok

# --- CLI contract --------------------------------------------------------------------------------
write_receipts(ORIG)
BANK.write_text(json.dumps(ORIG, ensure_ascii=False), "utf-8")
env = dict(os.environ, STUDYPREP_ROOT=str(TMP))
r = subprocess.run([sys.executable, SCRIPT, "CN"], capture_output=True, text=True, env=env)
ok = r.returncode == 2
print(("OK   " if ok else "FAIL ") + f"missing --scope is a usage error (rc={r.returncode})")
fails += not ok
r = subprocess.run([sys.executable, SCRIPT, "CN", "--scope", "endsem"], capture_output=True, text=True, env=env)
ok = r.returncode == 1 and (r.stdout.strip().splitlines() or [""])[-1].startswith("RESULT BLOCKED")
print(("OK   " if ok else "FAIL ") + f"endsem scope without a bank blocks (rc={r.returncode})")
fails += not ok

shutil.rmtree(TMP, ignore_errors=True)
print("OK test_verify" if not fails else f"FAIL test_verify: {fails} case(s)")
sys.exit(1 if fails else 0)
