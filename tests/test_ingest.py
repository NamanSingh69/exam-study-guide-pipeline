"""Regression test for tools/ingest.py (Round 4, REVIEW_2026-11-05 §2.4).

Builds a fake study root in tests/_tmp/ingest/ (never touches a real subject folder):

  _pipeline/tools/{ingest,workdir}.py, _pipeline/gapfill.json   copies of the tool under test
  DMDW/Notes/1. Intro.ppt                   real ML deck that is really a PDF (bytes %PDF-)
  DMDW/Notes/08Cluster Analysis.pptx        real DMDW deck: a notes slide has no text frame
  DMDW/Notes/Chap6-ClassificationBasic.pptx built here: group shapes, a notes slide without a body,
                                            a picture-only slide
  DMDW/Notes/Lecture 9 → λ-calculus          extensionless PDF with a non-cp1252 name and a
                                            text-less page
  DMDW/Midsem PYQs/2019 Midsem 1 ...pdf     real CN paper
  DMDW/Endsem PYQs/<two long names>.pdf     names whose 70-char slugs used to collide
  BAD/Notes/fake.pdf, broken.pptx           HTML saved as .pdf; a corrupt pptx

INGEST_TOOL=<path> runs another ingest.py (e.g. the pre-Round-4 one) against the same fixture.
Its copy sits at <root>/_pipeline/tools/, so even a version that ignores STUDYPREP_ROOT only sees the
fixture. Exit 0 and 'OK ...' lines when everything passes.
"""
import json, os, random, re, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
REAL = PIPE.parent
T = HERE / "_tmp" / "ingest"
TOOL_SRC = Path(os.environ.get("INGEST_TOOL") or PIPE / "tools" / "ingest.py")

fails = []


def check(cond, name, detail=""):
    if cond:
        print(f"OK {name}")
    else:
        print(f"FAIL {name} {detail}")
        fails.append(name)


def run(subject, **env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["STUDYPREP_ROOT"] = str(T)
    env.update(env_extra)
    # stdout is a pipe -> Python's default cp1252 on Windows; the tool must cope by itself
    r = subprocess.run([sys.executable, str(T / "_pipeline" / "tools" / "ingest.py"), subject],
                       capture_output=True, env=env, timeout=1200)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace").replace("\r", "")
    return r.returncode, out


def last_line(out):
    lines = [l for l in out.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""


def manifest(subject):
    p = T / subject / "work" / "manifest.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {"files": {}}


# ----------------------------------------------------------------------------- fixture
def make_png(path: Path, seed: int):
    from PIL import Image
    rnd = random.Random(seed)
    im = Image.new("RGB", (320, 240))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(320 * 240)])
    im.save(path)


def make_pptx(path: Path, png: Path):
    from pptx import Presentation
    from pptx.util import Inches
    from pptx.enum.shapes import PP_PLACEHOLDER
    prs = Presentation()
    blank = prs.slide_layouts[6]
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Decision tree induction"
    s1.placeholders[1].text = "Attribute selection measures: information gain, gain ratio, Gini index. " * 2
    s2 = prs.slides.add_slide(blank)          # text and a picture inside (nested) groups
    g = s2.shapes.add_group_shape()
    g.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text_frame.text = \
        "GROUPTOKEN naive Bayes assumes class-conditional independence of the attributes"
    inner = g.shapes.add_group_shape()
    inner.shapes.add_picture(str(png), Inches(1), Inches(3), Inches(3), Inches(2))
    s3 = prs.slides.add_slide(prs.slide_layouts[1])   # notes slide whose body placeholder is gone
    s3.shapes.title.text = "Rule-based classification"
    s3.placeholders[1].text = "IF age = youth AND student = yes THEN buys_computer = yes. Coverage and accuracy."
    ns = s3.notes_slide
    for ph in list(ns.placeholders):
        if ph.placeholder_format.type == PP_PLACEHOLDER.BODY:
            ph._element.getparent().remove(ph._element)
    s4 = prs.slides.add_slide(blank)          # picture only: must be rendered for agents to see
    s4.shapes.add_picture(str(png), Inches(1), Inches(1), Inches(6), Inches(4.5))
    prs.save(str(path))
    chk = Presentation(str(path)).slides[2]
    assert chk.has_notes_slide and chk.notes_slide.notes_text_frame is None, "fixture: notes body not removed"


def make_pdf(path: Path):
    import pymupdf as fitz
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "EXTLESSTOKEN Lecture 9: the lambda calculus, beta reduction and normal forms.")
    p.insert_text((72, 96), "Church numerals encode natural numbers as higher-order functions.")
    p2 = doc.new_page()                        # a diagram page with no text layer at all
    p2.draw_rect(fitz.Rect(100, 100, 400, 300), color=(0, 0, 1), width=3)
    p2.draw_circle((250, 500), 80, color=(1, 0, 0), width=3)
    doc.save(str(path))


def build_fixture():
    if T.exists():
        shutil.rmtree(T)
    tools = T / "_pipeline" / "tools"
    tools.mkdir(parents=True)
    shutil.copy2(TOOL_SRC, tools / "ingest.py")
    shutil.copy2(PIPE / "tools" / "workdir.py", tools / "workdir.py")
    if (PIPE / "gapfill.json").exists():
        shutil.copy2(PIPE / "gapfill.json", T / "_pipeline" / "gapfill.json")
    d = T / "DMDW"
    notes, mid, end = d / "Notes", d / "Midsem PYQs", d / "Endsem PYQs"
    for x in (notes, mid, end):
        x.mkdir(parents=True)
    shutil.copy2(REAL / "ML" / "Notes" / "1. Intro.ppt", notes / "1. Intro.ppt")
    shutil.copy2(REAL / "DMDW" / "Notes" / "08Cluster Analysis.pptx", notes / "08Cluster Analysis.pptx")
    png = T / "pic.png"
    make_png(png, 7)
    make_pptx(notes / "Chap6-ClassificationBasic.pptx", png)
    make_pdf(notes / "Lecture 9 → λ-calculus")
    paper = REAL / "CN" / "Midsem PYQs" / "2019 Midsem 1 Computer Networks.pdf"
    shutil.copy2(paper, mid / paper.name)
    for name in ("5th  Semester , B. Tech ,Computational Intelligence, CS 30011 CS 3031 ,(For 2023 and "
                 "Previous Admitted Batches), Autumn  End  Semester  Examination  2025.pdf",
                 "5th Semester, B.Tech , Computational Intelligence, CS 30011  CS 3031, (For 2023 (LE),2022 "
                 "& Previous Admitted Batches)  Autumn End Semester Examination 2024.pdf"):
        shutil.copy2(paper, end / name)
    b = T / "BAD" / "Notes"
    b.mkdir(parents=True)
    (b / "fake.pdf").write_bytes(b"<!DOCTYPE html><html><body>Sign in to continue</body></html>")
    import zipfile
    with zipfile.ZipFile(b / "broken.pptx", "w") as z:
        z.writestr("ppt/presentation.xml", "<not really a presentation")
    shutil.copy2(paper, b / "ok.pdf")


# ----------------------------------------------------------------------------- tests
def main():
    for s in (sys.stdout, sys.stderr):        # the test's own output quotes tool output (arrows, Greek)
        s.reconfigure(encoding="utf-8", errors="replace")
    build_fixture()
    work = T / "DMDW" / "work"

    # ---- run 1: OCR disabled (portability: the tool must still render low-text pages)
    rc, out = run("DMDW", TESSERACT_CMD="none")
    m = manifest("DMDW")
    files = m.get("files", {})
    check(rc == 0, "clean subject exits 0", f"rc={rc}\n{out[-2500:]}")
    check(re.match(r"INGEST: 0 errors", last_line(out)) is not None, "health line 'INGEST: 0 errors'", last_line(out))
    check(out.count("Tesseract not found") == 1, "exactly one Tesseract warning when OCR is off")
    check(not any("error" in v for v in files.values()), "no file errored",
          str({k: v.get("error") for k, v in files.items() if "error" in v}))

    intro = files.get("Notes/1. Intro.ppt", {})
    check(intro.get("kind_detected") == "pdf" and intro.get("mismatch") is True and intro.get("pages", 0) > 10
          and intro.get("text_pages", 0) > 10, "fake .ppt that is a PDF is read as PDF", str(intro)[:300])

    clu = files.get("Notes/08Cluster Analysis.pptx", {})
    check(clu.get("pages") == 152 and clu.get("text_pages", 0) >= 140,
          "real DMDW 08Cluster Analysis.pptx (notes slide without text frame) ingested", str(clu)[:300])
    check(str(clu.get("origin", "")).startswith("gapfill:"), "gap-fill deck has origin gapfill:<desc>",
          str(clu.get("origin")))
    check(intro.get("origin") == "instructor", "instructor deck has origin instructor", str(intro.get("origin")))

    c6 = files.get("Notes/Chap6-ClassificationBasic.pptx", {})
    slug6 = c6.get("slug", "?")
    md6 = (work / "corpus" / f"{slug6}.md").read_text("utf-8") if (work / "corpus" / f"{slug6}.md").exists() else ""
    check(c6.get("pages") == 4 and "error" not in c6, "built deck with a body-less notes slide ingested", str(c6)[:300])
    check("GROUPTOKEN" in md6, "text inside a group shape reaches the corpus")
    figs6 = work / "figures" / f"{slug6}.figs.json"
    check(figs6.exists() and any(f["page"] == 2 for f in json.loads(figs6.read_text("utf-8"))),
          "picture nested in groups is extracted as a figure")
    check((work / "note_pages" / f"{slug6}_p4.png").exists() and "[page image: work/note_pages/" in md6,
          "picture-only slide is rendered to note_pages/")
    check(str(c6.get("origin", "")).startswith("gapfill:"), "gapfill origin for Chap6 deck")

    ext = files.get("Notes/Lecture 9 → λ-calculus", {})
    slugx = ext.get("slug", "?")
    check(ext.get("kind_detected") == "pdf" and ext.get("ext_kind") is None and ext.get("mismatch") is False,
          "extensionless PDF with a non-cp1252 name detected from its bytes", str(ext)[:300])
    mdx = (work / "corpus" / f"{slugx}.md").read_text("utf-8") if (work / "corpus" / f"{slugx}.md").exists() else ""
    check("EXTLESSTOKEN" in mdx, "extensionless PDF text in corpus")
    check((work / "note_pages" / f"{slugx}_p2.png").exists() and not ext.get("lost_pages"),
          "text-less page rendered even without OCR")
    check("|ocr0|" in str(ext.get("stamp")) and ext.get("ocr_available") is False, "cache stamp records OCR off",
          str(ext.get("stamp")))

    pyq = files.get("Midsem PYQs/2019 Midsem 1 Computer Networks.pdf", {})
    check(pyq and (work / "pyq_pages" / f"{pyq.get('slug')}_p1.png").exists(), "PYQ page rendered to pyq_pages/")

    longs = [v for k, v in files.items() if k.startswith("Endsem PYQs/5th")]
    sl = [v.get("slug", "") for v in longs]
    check(len(sl) == 2 and len(set(sl)) == 2 and all(len(s) <= 75 for s in sl)
          and all(re.search(r"_[0-9a-f]{6}$", s) for s in sl), "long names get distinct hash-suffixed slugs", str(sl))

    idx = (work / "corpus" / "INDEX.md").read_text("utf-8") if (work / "corpus" / "INDEX.md").exists() else ""
    check("gapfill:" in idx and "| instructor |" in idx and "pdf (ext ppt)" in idx, "INDEX shows origin and kind")
    h = m.get("health", {})
    check(h.get("errors") == 0 and h.get("files_ok") == len(files), "manifest health block", str(h)[:300])

    # ---- run 2: unchanged inputs are cached; a manifest slug is kept
    files.setdefault("Notes/1. Intro.ppt", {})["slug"] = "N_kept_slug"
    files["Notes/1. Intro.ppt"]["stamp"] = "stale"
    m["files"] = files
    work.mkdir(parents=True, exist_ok=True)
    (work / "manifest.json").write_text(json.dumps(m, indent=1), "utf-8")
    rc2, out2 = run("DMDW", TESSERACT_CMD="none")
    f2 = manifest("DMDW").get("files", {})
    reingested = re.findall(r"^\[ingest\] (?:notes|syllabus|pyq_midsem|pyq_endsem|imp)\s+(.+?)\s*$",
                            out2.replace("\r", ""), flags=re.M)
    check(rc2 == 0 and reingested == ["Notes/1. Intro.ppt"], "second run re-ingests only the stale file",
          str(reingested)[:300])
    check(f2.get("Notes/1. Intro.ppt", {}).get("slug") == "N_kept_slug"
          and (work / "corpus" / "N_kept_slug.md").exists(), "existing manifest slug is kept")
    check(len(files) > 1 and all(f2.get(k, {}).get("slug") == files[k].get("slug") for k in files),
          "all other slugs stable across runs")

    # ---- run 3: Tesseract appears -> files with OCR-able pages are retried (stamp carries OCR availability)
    sys.path.insert(0, str(T / "_pipeline" / "tools"))
    try:
        import importlib
        ing = importlib.import_module("ingest")
        old = os.environ.pop("TESSERACT_CMD", None)
        tess = ing.find_tesseract() if hasattr(ing, "find_tesseract") else None
        os.environ["TESSERACT_CMD"] = "none"
        check(ing.find_tesseract() is None if hasattr(ing, "find_tesseract") else False,
              "TESSERACT_CMD=none disables OCR")
        if old is None:
            os.environ.pop("TESSERACT_CMD")
        else:
            os.environ["TESSERACT_CMD"] = old
    except Exception as e:
        tess = None
        check(False, "ingest module importable", repr(e))
    if tess:
        for p in (T / "DMDW" / "Notes").iterdir():     # keep run 3 short: OCR only the small files
            if p.name in ("08Cluster Analysis.pptx", "1. Intro.ppt"):
                p.unlink()
        rc3, out3 = run("DMDW", TESSERACT_CMD=tess)
        f3 = manifest("DMDW").get("files", {})
        e3 = f3.get("Notes/Lecture 9 → λ-calculus", {})
        check(rc3 == 0 and "|ocr1|" in str(e3.get("stamp")) and "Notes/Lecture 9 → λ-calculus" in out3,
              "installing Tesseract invalidates the cache", str(e3.get("stamp")))
        check("Notes/08Cluster Analysis.pptx" not in f3 and
              not (work / "corpus" / f"{clu.get('slug', '?')}.md").exists(), "removed input drops its stale outputs")
    else:
        print("OK (skipped OCR re-run: no Tesseract on this machine)")

    # ---- BAD subject: unresolved mismatch + corrupt file -> exit 1 with a summary
    rcb, outb = run("BAD", TESSERACT_CMD="none")
    mb = manifest("BAD").get("files", {})
    check(rcb == 1, "errors make ingest exit 1", f"rc={rcb}")
    check(re.match(r"INGEST: 2 errors \(1 files errored, 1 unresolved type mismatches, 0 pages", last_line(outb))
          is not None, "health summary line lists the errors", last_line(outb))
    check(mb.get("Notes/fake.pdf", {}).get("unresolved") is True, "HTML saved as .pdf is an unresolved mismatch")
    check("error" not in mb.get("Notes/ok.pdf", {"error": 1}), "good file in a bad subject still ingested")

    # ---- gapfill.json matches the real Notes folders (read-only check)
    gf = json.loads((PIPE / "gapfill.json").read_text("utf-8")) if (PIPE / "gapfill.json").exists() else {}
    missing = [f"{s}/{n}" for s, v in gf.items() if not s.startswith("_") for n in v
               if not (REAL / s / "Notes" / n).exists()]
    check(gf and not missing and sum(len(v) for s, v in gf.items() if not s.startswith("_")) == 25,
          "gapfill.json lists the 25 gap-fill notes from GATHERING_LOG.md", str(missing))

    if fails:
        print(f"FAIL test_ingest: {len(fails)} check(s) failed: {fails}")
        sys.exit(1)
    shutil.rmtree(T, ignore_errors=True)
    print("OK test_ingest")


if __name__ == "__main__":
    main()
