"""Regression tests for metrics.py (hard gates) and plant_defects.py (Round 4, workstream T4).

Uses test_build.make_subject() in tests/_tmp/metrics/ and a copy of the CN midsem trial chapters in
tests/_tmp/plant/ (STUDYPREP_ROOT); never writes into a real subject. T4_PIPE=<other _pipeline> runs the
suite against other tools (RED check). Prints 'OK <name>' per test; exit 0 only if all pass.
"""
import hashlib, importlib, json, os, re, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_build as tb  # noqa: E402  (fixture + runner; its tests run only under __main__)

PIPE, TOOLS = tb.PIPE, tb.TOOLS
REAL_CN = PIPE.parent / "CN" / "work" if (PIPE.parent / "CN").exists() else HERE.parent.parent / "CN" / "work"
fails = passed = 0


def check(name, cond, detail=""):
    global fails, passed
    if cond:
        passed += 1
        print(f"OK   {name}")
    else:
        fails += 1
        print(f"FAIL {name}\n     {str(detail)[-1500:]}")


def last_metrics(work):
    lines = (work / "metrics.jsonl").read_text("utf-8").strip().splitlines()
    return json.loads(lines[-1]), len(lines)


def result_line(out):
    return next((l for l in reversed(out.strip().splitlines()) if l.startswith("RESULT")), "")


def test_metrics():
    root = HERE / "_tmp" / "metrics"
    work = tb.make_subject(root, dangling=True)
    os.environ["STUDYPREP_ROOT"] = str(root)

    # --- CLI on a failed build: exit 1 with the counts
    rc, out, _ = tb.run(["build.py", "TT", "--scope", "midsem"], root)
    rc, out, _ = tb.run(["metrics.py", "TT", "--scope", "midsem"], root, timeout=600)
    m, n1 = last_metrics(work) if (work / "metrics.jsonl").exists() else ({}, 0)
    check("metrics exits 1 when a hard gate fails", rc == 1, out[-800:])
    check("final line RESULT BLOCKED names undefined_refs and stale_pdf",
          result_line(out).startswith("RESULT BLOCKED") and "undefined_refs=1" in result_line(out)
          and "stale_pdf=1" in result_line(out), result_line(out))
    check("undefined_refs / undefined_text counted from the full-build log",
          m.get("undefined_refs") == 1 and m.get("undefined_text") == 1 and m.get("undefined_labels") == ["q:P2022-9z"], m)

    # --- fixed build: every hard gate except the (fixture-less) PYQ gate passes end to end
    tb.make_subject(root, dangling=False)
    rc, out, _ = tb.run(["build.py", "TT", "--scope", "midsem"], root)
    check("fixture builds cleanly", rc == 0, out[-800:])
    rc, out, _ = tb.run(["metrics.py", "TT", "--scope", "midsem"], root, timeout=600)
    m, n2 = last_metrics(work)
    check("metrics appends one line per run to metrics.jsonl", n2 == 1, n2)
    gl = result_line(out)
    check("clean guide: only pyq_gate (no real corpus in the fixture) blocks", gl == "RESULT BLOCKED: pyq_gate=0", gl)
    for k, v in (("tex_errors", 0), ("float_too_large", 0), ("missing_chapters", []), ("missing_receipts", []),
                 ("checks_failed", []), ("stale_pdf", 0), ("ingest_errors", 0), ("dup_solves", []),
                 ("missing_badges", []), ("numericals_without_check", []), ("backtest_6h_cover", 0.62),
                 ("storyboards_per_process_topic", 1.0)):
        check(f"clean guide: {k} = {v!r}", m.get(k) == v, m.get(k))
    check("pages_per_exam_mark from the PYQ chapter pages", isinstance(m.get("pages_per_exam_mark"), float)
          and 0 < m["pages_per_exam_mark"] < 1, m.get("pages_per_exam_mark"))

    # --- in-process mutations (pyq gate stubbed; everything else real)
    sys.path.insert(0, str(TOOLS))
    metrics = importlib.import_module("metrics")
    comp = lambda: metrics.compute("TT", "midsem", gate_fn=lambda: 1)
    m = comp()
    check("compute(): all gates pass with the PYQ gate stubbed", metrics.gates(m) == [], metrics.gates(m))

    # checks are executed (exit code and timeout)
    tb.write(work / "checks" / "bad.py", "import sys\nprint('wrong')\nsys.exit(3)\n")
    tb.write(work / "checks" / "slow.py", "import time\ntime.sleep(8)\n")
    tb.write(work / "checks" / "_helper.py", "raise SystemExit(5)  # helpers are imported, not run\n")
    old_t = metrics.CHECK_TIMEOUT
    metrics.CHECK_TIMEOUT = 2
    m = comp()
    metrics.CHECK_TIMEOUT = old_t
    names = " ".join(m["checks_failed"])
    check("checks_failed: a failing check is listed", "bad.py" in names, names)
    check("checks_failed: a check over the timeout is listed", "slow.py" in names and "timeout" in names, names)
    check("checks_failed: _helper modules are not run", "_helper" not in names, names)
    check("checks_failed is a hard gate", any(g.startswith("checks_failed=") for g in metrics.gates(m)), metrics.gates(m))
    for f in ("bad.py", "slow.py", "_helper.py"):
        (work / "checks" / f).unlink()

    # numericals from the bank, not from labels
    bank = json.loads((work / "pyq_bank.json").read_text("utf-8"))
    bank["questions"].append(dict(bank["questions"][0], id="P2024-1b", qno="1(b)", cluster="C02"))
    (work / "pyq_bank.json").write_text(json.dumps(bank), "utf-8")
    m = comp()
    check("numericals_without_check counts a bank numerical with no \\label and no check",
          m["numericals_without_check"] == ["P2024-1b"], m["numericals_without_check"])
    check("missing_receipts counts a banked question without receipts/<qid>.png", m["missing_receipts"] == ["P2024-1b"],
          m["missing_receipts"])
    (work / "pyq_bank.json").write_text(json.dumps(tb.BANK), "utf-8")
    rj = work / "receipts" / "receipts.json"
    good = rj.read_text("utf-8")
    rj.write_text(json.dumps({"P2024-1a": {"file": None, "match": 0.0}}), "utf-8")
    m = comp()
    check("missing_receipts counts a receipts.json entry with file: null", m["missing_receipts"] == ["P2024-1a"], m["missing_receipts"])
    rj.write_text(good, "utf-8")

    # missing chapters: blueprint units + papers, then assignments.json
    unit = work / "chapters" / "30_unit_one.tex"
    keep = unit.read_text("utf-8")
    unit.unlink()
    m = comp()
    check("missing_chapters: a blueprint unit chapter", any(x.startswith("30_unit_one") for x in m["missing_chapters"]), m["missing_chapters"])
    unit.write_text(keep, "utf-8")
    p700 = work / "chapters" / "700_pyq_p2024.tex"
    p700.rename(work / "chapters" / "70_pyq_p2024_old.tex")
    m = comp()
    check("missing_chapters: one 7NN_pyq_<paper> per paper (3-digit stems)", any("pyq_p2024" in x for x in m["missing_chapters"]),
          m["missing_chapters"])
    (work / "chapters" / "70_pyq_p2024_old.tex").rename(p700)
    tb.write(work / "assignments.json", json.dumps({"chapters": [{"stem": s, "kind": "x"} for s in
                                                    list(tb.CH) + ["65_q1_drill"]]}))
    m = comp()
    check("missing_chapters: assignments.json chapters[].stem wins", m["missing_chapters"] == ["65_q1_drill (x)"], m["missing_chapters"])
    (work / "assignments.json").unlink()

    # badges, duplicate solves
    iqf = work / "chapters" / "60_important_questions.tex"
    iqt = iqf.read_text("utf-8")
    iqf.write_text(iqt + "\\clusterbadge{C77}\n\\begin{solvedidea}{C01}{Again}x\\end{solvedidea}\n", "utf-8")
    m = comp()
    check("missing_badges: an id not in badges.tex", "C77" in m["missing_badges"], m["missing_badges"])
    check("dup_solves: a second solvedidea for the same cluster", m["dup_solves"] == ["C01"], m["dup_solves"])
    iqf.write_text(iqt + "\\input{atoms/solve/C01}\n", "utf-8")
    m = comp()
    check("dup_solves: atoms/solve/C01 \\input twice", m["dup_solves"] == ["C01"], m["dup_solves"])
    iqf.write_text(iqt, "utf-8")

    # staleness
    t = time.time() + 120
    os.utime(work / "atoms" / "notes" / "T01.tex", (t, t))
    m = comp()
    check("stale_pdf: an atom newer than the delivered guide", m["stale_pdf"] == 1 and "T01" in m.get("stale_detail", ""), m.get("stale_detail"))
    # real SVP (2026-11-06): a failed phone build left the old phone PDF; it must count as stale too
    gdst = tb.deliverable(work, "_Guide.pdf")
    pdst = gdst.with_name(gdst.name.replace("_Guide.pdf", "_Guide_Phone.pdf"))
    if gdst.exists():
        shutil.copyfile(gdst, pdst)
        old = time.time() - 7200
        os.utime(pdst, (old, old))
        os.utime(gdst, (t + 60, t + 60))      # print guide fresh, phone PDF two hours old
        m = comp()
        check("stale_pdf: a delivered phone PDF older than its sources is stale",
              m["stale_pdf"] == 1 and "Phone" in m.get("stale_detail", ""), m.get("stale_detail"))
        pdst.unlink()
    os.utime(work / "atoms" / "notes" / "T01.tex", None)
    for f in (work / "chapters").glob("*.tex"):
        os.utime(f, (time.time() - 3600, time.time() - 3600))
    for f in (work / "atoms").rglob("*.tex"):
        os.utime(f, (time.time() - 3600, time.time() - 3600))
    os.utime(work / "badges.tex", (time.time() - 3600, time.time() - 3600))

    # ingest errors from the manifest health block (and the old-manifest fallback)
    man = work.parent / "manifest.json"
    man.write_text(json.dumps({"files": {}, "health": {"errors": 2}}), "utf-8")
    m = comp()
    check("ingest_errors = manifest.health.errors", m["ingest_errors"] == 2 and "ingest_errors=2" in metrics.gates(m), m["ingest_errors"])
    man.write_text(json.dumps({"files": {"Notes/a.ppt": {"slug": "N_a", "error": "boom"}, "Notes/b.pdf": {"slug": "N_b"}}}), "utf-8")
    m = comp()
    check("ingest_errors fallback: entries with an 'error' key", m["ingest_errors"] == 1, m["ingest_errors"])
    man.write_text(json.dumps({"files": {}, "health": {"errors": 0}}), "utf-8")

    # log-derived gates
    log = work / "build" / "guide" / "guide.log"
    orig = log.read_text("latin-1")
    log.write_text(orig + "\nLaTeX Warning: Float too large for page by 10.0pt on input line 3.\n"
                   "./chapters/80_mock_paper.tex:5: Undefined control sequence.\n", "latin-1")
    m = comp()
    check("float_too_large and tex_errors gate from the log",
          m["float_too_large"] == 1 and m["tex_errors"] >= 1
          and {"float_too_large=1"} <= set(metrics.gates(m)) and any(g.startswith("tex_errors=") for g in metrics.gates(m)),
          (m["float_too_large"], m["tex_errors"]))
    log.write_text(orig, "latin-1")
    check("compute(): clean again after restoring", metrics.gates(comp()) == [], metrics.gates(comp()))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_plant():
    root = HERE / "_tmp" / "plant"
    if root.exists():
        shutil.rmtree(root)
    w = root / "CN" / "work" / "midsem"
    shutil.copytree(REAL_CN / "midsem" / "chapters", w / "chapters")
    if (REAL_CN / "midsem" / "atoms").exists():   # Round 4 layout: notes and full solutions live in atoms/
        shutil.copytree(REAL_CN / "midsem" / "atoms", w / "atoms")
    for f in (REAL_CN / "midsem").glob("*.json"):
        shutil.copy2(f, w / f.name)
    shutil.copy2(REAL_CN / "conventions.json", w.parent / "conventions.json")
    before = {p.name: sha(p) for p in (w / "chapters").glob("*.tex")}
    out = w / "reviews" / "copy_3"
    rc, txt, _ = tb.run(["plant_defects.py", "CN", "--scope", "midsem", "--n", "7", "--seed", "3", "--out", str(out)], root)
    check("plant_defects: plants 7 defects (exit 0)", rc == 0 and "RESULT PASS" in txt, txt[-800:])
    keyf = w / "reviews" / "_keys" / "copy_3.json"
    check("plant_defects: answer key in reviews/_keys/, never inside --out",
          keyf.exists() and not any(out.rglob("*key*")), list(out.rglob("*"))[:5])
    key = json.loads(keyf.read_text("utf-8")) if keyf.exists() else []
    check("plant_defects: key shape [{file, where, kind, original, planted}]",
          key and all(set(k) == {"file", "where", "kind", "original", "planted"} for k in key), key[:1])
    kinds = {k["kind"] for k in key}
    want = {"wrong_number", "invented_pyq", "convention_mismatch", "figure_label", "long_answer", "unsupported_stat",
            "cheatsheet_formula"}
    check("plant_defects: all 7 kinds planted on the CN trial", kinds == want, sorted(kinds))
    okp = True
    for k in key:
        f = out / k["file"]
        t = f.read_text("utf-8") if f.exists() else ""
        ln = int(re.match(r"line (\d+)", k["where"]).group(1))
        if not k["planted"] or k["planted"].splitlines()[0] not in "\n".join(t.splitlines()[ln - 3: ln + 3]):
            okp = False
            print("     planted text not found near", k["file"], k["where"][:60])
    check("plant_defects: every planted text sits at the line the key names", okp)
    check("plant_defects: copy holds chapters/ + JSON with relative paths",
          (out / "chapters" / "cheatsheet.tex").exists() and (out / "pyq_bank.json").exists())
    check("plant_defects: originals untouched", before == {p.name: sha(p) for p in (w / "chapters").glob("*.tex")})
    sys.path.insert(0, str(TOOLS))
    build = importlib.import_module("build")
    struct = re.compile(r"unbalanced|unclosed|\\begin\{.*\} x\d+ vs")
    bad = [i for f in {k["file"] for k in key}
           for i in build.lint_file(out / f) if struct.search(i)
           and i not in [j for j in build.lint_file(w / f) if struct.search(j)]]
    check("plant_defects: planted files stay structurally valid LaTeX", not bad, bad)

    # seeds differ; --out may not be the work folder; recall scoring
    rc, _, _ = tb.run(["plant_defects.py", "CN", "--scope", "midsem", "--n", "5", "--seed", "1", "--out", str(w / "reviews" / "copy_1")], root)
    rc2, _, _ = tb.run(["plant_defects.py", "CN", "--scope", "midsem", "--n", "5", "--seed", "2", "--out", str(w / "reviews" / "copy_2")], root)
    k1 = json.loads((w / "reviews" / "_keys" / "copy_1.json").read_text("utf-8"))
    k2 = json.loads((w / "reviews" / "_keys" / "copy_2.json").read_text("utf-8"))
    check("plant_defects: --n 5 gives 5 defects; seeds differ",
          rc == 0 and rc2 == 0 and len(k1) == 5 and len(k2) == 5 and
          [(k["kind"], k["where"]) for k in k1] != [(k["kind"], k["where"]) for k in k2])
    rc, txt, _ = tb.run(["plant_defects.py", "CN", "--scope", "midsem", "--n", "5", "--seed", "1", "--out", str(w)], root)
    check("plant_defects: refuses --out = the work folder (exit 2)", rc == 2 and (w / "chapters").exists(), txt[-300:])
    review = {"fixes": [{"file": k["file"], "where": k["where"].split(":")[0], "problem": "x", "fix": "y"} for k in k1[:3]]
              + [{"file": "chapters/nowhere.tex", "where": "line 1", "problem": "x"}]}
    rv = root / "review.json"
    rv.write_text(json.dumps(review), "utf-8")
    rc, txt, _ = tb.run(["plant_defects.py", "--score", str(rv), "--key", str(w / "reviews" / "_keys" / "copy_1.json")], root)
    check("plant_defects --score: recall 3/5", rc == 0 and "RECALL 0.60 (3/5)" in txt, txt[-400:])
    # real CN round 1 (2026-11-06): reviewer B reported the invented PYQ sentence and the made-up statistic under
    # critical[], and the scorer (fixes[] only) counted them as missed: 2/5 instead of 4/5
    k4 = k1[3]
    review["critical"] = [{"file": k4["file"], "where": k4["where"].split(":")[0], "problem": "x", "fix": "y"}]
    rv.write_text(json.dumps(review), "utf-8")
    rc, txt, _ = tb.run(["plant_defects.py", "--score", str(rv), "--key", str(w / "reviews" / "_keys" / "copy_1.json")], root)
    check("plant_defects --score: findings under critical[] count too (4/5)", rc == 0 and "RECALL 0.80 (4/5)" in txt,
          txt[-400:])
    # real SVP round 1 (2026-11-06): the reviewer quoted the planted short formula exactly ("\frac{2(L-1)}{1}") but gave
    # no line number; tokens >= 5 chars do not exist in it, so the scorer missed it. A quoted planted string counts.
    import re as _re
    quotable = [k for k in k1 if len(_re.sub(r"\s+", "", k["planted"] or "")) >= 6]
    rq = {"fixes": [{"file": k["file"], "where": "box", "problem": "prints " + k["planted"] + " here", "fix": "z"}
                    for k in quotable]}
    rv.write_text(json.dumps(rq), "utf-8")
    rc, txt, _ = tb.run(["plant_defects.py", "--score", str(rv), "--key", str(w / "reviews" / "_keys" / "copy_1.json")], root)
    want = f"RECALL {len(quotable) / 5:.2f} ({len(quotable)}/5)"
    check("plant_defects --score: findings that only quote the planted text count",
          quotable and rc == 0 and want in txt, (want, txt[-300:]))
    # discriminating case: a planted formula with no token of >= 5 letters and no line number in the review
    kf = root / "key_formula.json"
    kf.write_text(json.dumps([{"file": "chapters/cheatsheet.tex", "where": "formula box", "kind": "cheatsheet_formula",
                               "original": r"\frac{1}{2(L-1)}", "planted": r"\frac{2(L-1)}{1}"}]), "utf-8")
    rv.write_text(json.dumps({"fixes": [{"file": "chapters/cheatsheet.tex", "where": "ZCR box",
                                         "problem": r"ZCR = \frac{2(L-1)}{1} is upside down", "fix": "invert"}]}), "utf-8")
    rc, txt, _ = tb.run(["plant_defects.py", "--score", str(rv), "--key", str(kf)], root)
    check("plant_defects --score: a quoted short planted formula counts (real SVP r1 ZCR case)",
          rc == 0 and "RECALL 1.00 (1/1)" in txt, txt[-300:])


def test_archive_metrics():
    """Guide + PYQ archive: the archive build counts in the gates; cross refs; staleness; page measures."""
    root = HERE / "_tmp" / "metrics_archive"
    work = tb.make_archive_subject(root)
    sys.path.insert(0, str(TOOLS))
    workdir = importlib.import_module("workdir")
    metrics = importlib.import_module("metrics")
    old_root, workdir.ROOT = workdir.ROOT, root
    try:
        for args in (["build.py", "TT", "--scope", "midsem"], ["build.py", "TT", "--scope", "midsem", "--archive"],
                     ["build.py", "TT", "--scope", "midsem"]):
            rc, out, _ = tb.run(args, root)
            check(f"archive metrics: {' '.join(args[3:]) or 'guide'} builds", rc == 0, out[-600:])
        comp = lambda: metrics.compute("TT", "midsem", gate_fn=lambda: 1)
        m = comp()
        check("archive metrics: guide -> archive -> guide passes every gate", metrics.gates(m) == [], (metrics.gates(m), m.get("stale_detail")))
        check("archive metrics: cross_refs_unresolved = [] and none pending",
              m.get("cross_refs_unresolved") == [] and m.get("cross_refs_pending") == 0, (m.get("cross_refs_unresolved"), m.get("cross_refs_pending")))
        check("archive metrics: archive_pages reported separately", isinstance(m.get("archive_pages"), int) and m["archive_pages"] >= 2,
              m.get("archive_pages"))
        pages = metrics.chapter_pages(work)
        check("archive metrics: pages_per_exam_mark measured on the main guide only",
              "701_pyq_p2019" not in pages and m["pages_per_exam_mark"] == round(pages.get("700_pyq_p2024", 0) / 20, 3),
              (pages, m["pages_per_exam_mark"]))
        # staleness of the archive deliverable
        arch_ch = work / "chapters" / "701_pyq_p2019.tex"
        t = time.time() + 120
        os.utime(arch_ch, (t, t))
        m = comp()
        check("archive metrics: an archive chapter newer than the archive PDF is stale_pdf",
              m["stale_pdf"] == 1 and "PYQ_Archive" in m.get("stale_detail", ""), m.get("stale_detail"))
        os.utime(arch_ch, (time.time() - 3600, time.time() - 3600))
        adst = tb.deliverable(work, "_PYQ_Archive.pdf")
        keep = adst.read_bytes()
        adst.unlink()
        m = comp()
        check("archive metrics: a missing archive deliverable is stale_pdf",
              m["stale_pdf"] == 1 and "no delivered Test_Subject_Midsem_PYQ_Archive.pdf" in m.get("stale_detail", ""), m.get("stale_detail"))
        adst.write_bytes(keep)
        # the guide's archive pointers go stale when the archive's pages change
        res = work / "build" / "guide" / "result.json"
        r = json.loads(res.read_text("utf-8"))
        r["xref_sig"] = "0000"
        res.write_text(json.dumps(r), "utf-8")
        m = comp()
        check("archive metrics: guide built against an older archive is stale", m["stale_pdf"] == 1
              and "guide was built against an older PYQ archive" in m.get("stale_detail", ""), m.get("stale_detail"))
        # missing_chapters covers the archive chapters
        keep_t = arch_ch.read_text("utf-8")
        arch_ch.unlink()
        m = comp()
        check("archive metrics: a missing archive chapter is in missing_chapters",
              any(x.startswith("701_pyq_p2019") for x in m["missing_chapters"]), m["missing_chapters"])
        arch_ch.write_text(keep_t, "utf-8")
        # a cross target missing from the archive: the guide build fails and the gate names it
        work = tb.make_archive_subject(root, missing="archive")
        rc, out, _ = tb.run(["build.py", "TT", "--scope", "midsem"], root)
        m = comp()
        check("archive metrics: cross_refs_unresolved names the missing archive target and gates",
              rc == 1 and m.get("cross_refs_unresolved") == ["q:P2019-9z"]
              and "cross_refs_unresolved=1" in metrics.gates(m), (rc, m.get("cross_refs_unresolved"), metrics.gates(m)))
        # ... and a log error in the archive build counts in the shared tex_errors gate
        tb.make_archive_subject(root)
        tb.run(["build.py", "TT", "--scope", "midsem"], root)
        tb.run(["build.py", "TT", "--scope", "midsem", "--archive"], root)
        alog = root / "TT" / "work" / "midsem" / "build" / "archive" / "archive.log"
        alog.write_text(alog.read_text("latin-1") + "\n./chapters/701_pyq_p2019.tex:3: Undefined control sequence.\n", "latin-1")
        m = comp()
        check("archive metrics: an error in the archive build log counts in tex_errors", m["tex_errors"] >= 1, m["tex_errors"])
    finally:
        workdir.ROOT = old_root


def test_window_targets():
    """R4: blueprint.pyq_window and important_questions.json targets (subject-scaled sizes)."""
    root = HERE / "_tmp" / "metrics_window"
    work = tb.make_subject(root, dangling=False)
    sys.path.insert(0, str(TOOLS))
    workdir = importlib.import_module("workdir")
    metrics = importlib.import_module("metrics")
    old_root, workdir.ROOT = workdir.ROOT, root
    try:
        rc, out, _ = tb.run(["build.py", "TT", "--scope", "midsem"], root)
        check("window: fixture guide builds", rc == 0, out[-600:])
        comp = lambda: metrics.compute("TT", "midsem", gate_fn=lambda: 1)
        bpf, iqf, bankf = work / "blueprint.json", work / "important_questions.json", work / "pyq_bank.json"
        bp, iq, bank = (json.loads(f.read_text("utf-8")) for f in (bpf, iqf, bankf))
        bp["pyq_window"] = {"from": 2022, "to": 2026, "years": 5, "why": "test"}
        bpf.write_text(json.dumps(bp), "utf-8")
        bank["papers"] += [{"id": "P2019", "year": 2019, "exam": "midsem", "full_marks": 20},
                           {"id": "P2018", "year": 2018, "exam": "midsem", "full_marks": 20}]
        bank["questions"] += [dict(tb.BANK["questions"][0], id="P2019-2b", paper="P2019", qno="2(b)"),
                              dict(tb.BANK["questions"][0], id="P2018-1a", paper="P2018", qno="1(a)")]
        bankf.write_text(json.dumps(bank), "utf-8")
        m = comp()
        check("window: in-window q: labels only -> out_of_window_in_chapters = 0", m.get("out_of_window_in_chapters") == 0,
              m.get("out_of_window_in_chapters"))
        tb.write(work / "chapters" / "709_pyq_p2019.tex", "\\chapter{2019}\n\\begin{question}{2019 Q2(b)}{1}x\\end{question}\\label{q:P2019-2b}\n")
        tb.write(work / "atoms" / "notes" / "T99.tex", "\\section{Old}\\label{q:P2018-1a}\n")
        m = comp()
        check("window: q: labels of papers outside blueprint.pyq_window are counted (chapters and atoms)",
              m.get("out_of_window_in_chapters") == 2, m.get("out_of_window_in_chapters"))
        check("window: out_of_window_in_chapters is a hard gate", "out_of_window_in_chapters=2" in metrics.gates(m), metrics.gates(m))
        (work / "chapters" / "709_pyq_p2019.tex").unlink()
        (work / "atoms" / "notes" / "T99.tex").unlink()
        # real CN 2026-11-06: numericals of out-of-window papers were listed as "without check"
        nb = json.loads((work / "pyq_bank.json").read_text("utf-8"))
        old_years = {p["id"]: p.get("year") for p in nb.get("papers", [])}
        out_q = [q["id"] for q in nb.get("questions", []) if q.get("type") == "numerical" and q.get("in_scope", True)
                 and isinstance(old_years.get(q.get("paper")), int)
                 and not int(bp["pyq_window"]["from"]) <= old_years[q["paper"]] <= int(bp["pyq_window"]["to"])]
        m = comp()
        check("window: numericals of out-of-window papers are not counted as missing checks",
              not set(out_q) & set(m.get("numericals_without_check") or []), (out_q, m.get("numericals_without_check")))

        # targets: important questions, notes pages, cheatsheet pages
        iq["targets"] = {"iq_clusters": ["C01", "C02"], "notes_pages": {"U1": 0}, "cheatsheet_pages": 2,
                         "why": {"iq_clusters": "test"}}
        iqf.write_text(json.dumps(iq), "utf-8")
        m = comp()
        v = m.get("iq_count_vs_target")
        check("targets: iq_count_vs_target compares iq: labels in 60_important_questions with targets.iq_clusters",
              isinstance(v, dict) and v.get("count") == 1 and v.get("target") == 2 and v.get("missing") == ["C02"]
              and v.get("extra") == [], v)
        unit_pages = metrics.chapter_pages(work).get("30_unit_one")
        check("targets: over_budget_pages uses targets.notes_pages[unit]",
              unit_pages and m.get("over_budget_pages") == unit_pages, (unit_pages, m.get("over_budget_pages")))
        iq["targets"]["notes_pages"] = {"U1": unit_pages}
        iqf.write_text(json.dumps(iq), "utf-8")
        check("targets: a unit within its notes_pages target is not over budget", comp().get("over_budget_pages") == 0)
        c = m.get("cheatsheet_pages_vs_target")
        check("targets: cheatsheet_pages_vs_target from the built cheatsheet", isinstance(c, dict) and c.get("target") == 2
              and c.get("pages") == tb.pdf_info(work / "build" / "cheatsheet" / "cheatsheet.pdf")["pages"], c)
        check("targets: iq/cheatsheet targets are tracked, not gates",
              not any(g.startswith(("iq_count", "cheatsheet_pages")) for g in metrics.gates(m)), metrics.gates(m))
        # the shapes score.py really writes (real CN, 2026-11-06): dicts with a 'why', not bare values
        iq["targets"] = {"iq_clusters": {"clusters": ["C01", "C02"], "count": 2, "why": "12 h plan + wildcards"},
                         "notes_pages": {"U1": {"title": "One", "pages": float(unit_pages), "lectures": 4, "why": "x"}},
                         "cheatsheet_pages": {"pages": 2, "why": "2 + 0 + 0"}}
        iqf.write_text(json.dumps(iq), "utf-8")
        m = comp()
        v = m.get("iq_count_vs_target")
        check("targets (real score.py shape): iq_clusters as {clusters, count, why}",
              isinstance(v, dict) and v.get("target") == 2 and v.get("missing") == ["C02"] and v.get("extra") == [], v)
        check("targets (real shape): notes_pages[unit].pages is the budget", m.get("over_budget_pages") == 0,
              m.get("over_budget_pages"))
        # discriminating case (SVP U5, 2026-11-06): a dict target smaller than the old 1.5/lecture rule must be used
        iq["targets"]["notes_pages"]["U1"]["pages"] = 0.0
        iqf.write_text(json.dumps(iq), "utf-8")
        check("targets (real shape): a dict target below the old rule is honoured",
              comp().get("over_budget_pages") == unit_pages, (unit_pages, comp().get("over_budget_pages")))
        c = m.get("cheatsheet_pages_vs_target")
        check("targets (real shape): cheatsheet target is the integer page count",
              isinstance(c, dict) and c.get("target") == 2, c)
        iq.pop("targets")
        iqf.write_text(json.dumps(iq), "utf-8")
        m = comp()
        check("targets: without targets the old notes rule applies and the targets metrics are None",
              m.get("over_budget_pages") == max(0, unit_pages - round(1.5 * 4 + 1))
              and m.get("iq_count_vs_target") is None and m.get("cheatsheet_pages_vs_target") is None,
              (m.get("over_budget_pages"), m.get("iq_count_vs_target")))
    finally:
        workdir.ROOT = old_root


def main():
    test_metrics()
    test_archive_metrics()
    test_window_targets()
    test_plant()
    print(f"{passed}/{passed + fails} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
