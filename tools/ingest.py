"""
ingest.py — Stage 0 of the study-guide pipeline.

Turns every raw input of a subject folder into agent-friendly material:

  <SUBJ>/work/corpus/<slug>.md         page-tagged text ("## [<slug> p12]"), OCR fallback
  <SUBJ>/work/pyq_pages/<slug>_pN.png  every PYQ page rendered at 170 dpi (for vision verification)
  <SUBJ>/work/note_pages/<slug>_pN.png every low-text notes/syllabus page or slide, rendered
  <SUBJ>/work/figures/src/...          embedded figures from notes (size-filtered)
  <SUBJ>/work/manifest.json            per file: slug, category, origin, kind_detected, mismatch, page
                                       counts, OCR/quality flags; plus a top-level "health" summary
  <SUBJ>/work/corpus/INDEX.md          one-screen overview for agents (start here)

Usage:
  py _pipeline/tools/ingest.py CN            # subject folder name (relative to workdir.ROOT)
  py _pipeline/tools/ingest.py CN --force    # re-ingest everything (slugs are still kept)
  py _pipeline/tools/ingest.py CN --no-figures

Input folders recognised (case-insensitive, any that exist):
  Syllabus/  Notes/  Midsem PYQs/  Endsem PYQs/  Important Questions/  Extra/

File types come from the bytes (PDF, PPTX/DOCX zip, legacy OLE .ppt/.doc, images, plain text); the
extension is only a fallback. A file whose extension disagrees with its bytes is read as what the bytes
say (`mismatch: true`); one whose extension claims a type the bytes do not show is an error.

OCR: Tesseract from $TESSERACT_CMD, else PATH, else the default Windows install path. It is optional:
without it low-text pages are still rendered to images (one warning). TESSERACT_CMD=none disables it.
OCR availability is part of every cache stamp, so installing Tesseract later re-ingests the files.

Origin: `gapfill:<description>` for files listed in _pipeline/gapfill.json, otherwise `instructor`.

Exit codes: 0 = all inputs ingested; 1 = some file errored, an extension/bytes mismatch could not be
resolved, or a page ended up with neither text nor an image (the last line is `INGEST: N errors (...)`);
2 = usage error.
"""
import argparse, hashlib, io, json, os, re, shutil, subprocess, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workdir  # noqa: E402

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # pragma: no cover
    import fitz

ROOT = workdir.ROOT
PIPE = workdir.PIPE
INGEST_VERSION = 4          # bump to invalidate every cache entry
DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

CATEGORIES = {
    "syllabus": "syllabus",
    "notes": "notes",
    "midsem pyqs": "pyq_midsem",
    "endsem pyqs": "pyq_endsem",
    "important questions": "imp",
    "extra": "notes",
}
PREFIX = {"syllabus": "SYL", "notes": "N", "pyq_midsem": "PYQM", "pyq_endsem": "PYQE", "imp": "IMP"}
MIN_FIG_PX = 220        # ignore icons/logos smaller than this on both sides
MIN_FIG_BYTES = 6_000
OCR_DPI = 300
PYQ_RENDER_DPI = 170
NOTE_RENDER_DPI = 110
SLIDE_RENDER_W = 1280   # px width of rendered slides
LOW_TEXT = 60           # a page/slide with fewer text characters than this is rendered (and OCR'd)
TEXT_PAGE_MIN = 20      # "page with text" for the stats: at least this many non-blank characters
POOR_OCR_CONF = 70      # mean Tesseract word confidence below this => read the page images
SLUG_MAX = 70

# extension -> kind; the bytes decide first (see detect_kind)
EXT_KIND = {".pdf": "pdf", ".pptx": "pptx", ".docx": "docx", ".ppt": "ppt", ".doc": "doc",
            ".png": "image", ".jpg": "image", ".jpeg": "image", ".tif": "image", ".tiff": "image",
            ".bmp": "image", ".gif": "image", ".webp": "image", ".txt": "text", ".md": "text"}
SUPPORTED = {"pdf", "pptx", "docx", "ppt", "doc", "image", "text"}

TESSERACT = None        # resolved in main()
OCR_CONF = []           # per-page mean word confidence of the file being ingested (0-100)


# ----------------------------------------------------------------------------- helpers
def find_tesseract():
    """$TESSERACT_CMD, then PATH, then the default install path. None when unavailable."""
    env = os.environ.get("TESSERACT_CMD")
    if env is not None and env.strip().lower() in ("none", "off", "0", "-"):
        return None
    for c in (env, shutil.which("tesseract"), DEFAULT_TESSERACT):
        if c and Path(c).is_file():
            return str(c)
    return None


def slugify(s: str, key: str | None = None) -> str:
    """File name -> slug. Names longer than SLUG_MAX get a short hash of `key` (default: the name)."""
    s0 = s
    s = re.sub(r"\.(pdf|pptx?|docx?)$", "", s, flags=re.I)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "file"
    if len(s) > SLUG_MAX:
        h = hashlib.sha1((key or s0).encode("utf-8")).hexdigest()[:6]
        s = s[:SLUG_MAX - 7].rstrip("_") + "_" + h
    return s


def garble_ratio(text: str) -> float:
    """Fraction of 'words' that look like OCR garbage. 0 = clean."""
    words = re.findall(r"\S+", text)
    if not words:
        return 1.0
    bad = sum(1 for w in words if not re.fullmatch(r"[\w\-\.,;:()\[\]{}'\"/%+=*<>^|&!?#$@~`\\]+", w)
              or (len(w) > 3 and not re.search(r"[aeiouAEIOU0-9]", w)))
    return round(bad / len(words), 3)


def ocr_png(png: Path, psm: str = "6") -> str:
    """OCR one page image. Rebuilds text from Tesseract TSV so we also get word confidence.

    psm 6 (one text block) suits scanned pages; slides with mixed layout read better with psm 3 (auto)."""
    if not TESSERACT:
        return ""
    try:
        out = subprocess.run([TESSERACT, str(png), "stdout", "--psm", psm, "tsv"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:  # noqa
        return f"[OCR FAILED: {e}]"
    lines, confs, key = [], [], None
    for row in out.stdout.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or c[0] != "5":
            continue
        k = (c[2], c[3], c[4])  # block, paragraph, line
        if k != key:
            lines.append([]); key = k
        if c[11].strip():
            lines[-1].append(c[11])
            try:
                confs.append(float(c[10]))
            except ValueError:
                pass
    if confs:
        OCR_CONF.append(sum(confs) / len(confs))
    return "\n".join(" ".join(l) for l in lines if l)


def blob_to_png(blob: bytes, dest: Path) -> bool:
    """Save an embedded image (any format PIL/MuPDF can decode) as PNG."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(blob))
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.save(dest, "PNG")
        return True
    except Exception:
        pass
    try:
        pm = fitz.Pixmap(blob)
        if pm.n - pm.alpha >= 4:
            pm = fitz.Pixmap(fitz.csRGB, pm)
        pm.save(dest)
        return True
    except Exception:
        return False


def page_rec(i, text, used_ocr=False, image=None, blank=False):
    """One corpus page. image: path relative to work/ or None. blank: the source page is truly empty."""
    return {"i": i, "text": text or "", "ocr": used_ocr, "image": image, "blank": blank}


# ----------------------------------------------------------------------------- type detection
def _ole_kind(f: Path):
    """Legacy OLE container: look for the stream names in the directory (UTF-16)."""
    try:
        blob = f.read_bytes()
    except OSError:
        return None
    u16 = lambda s: s.encode("utf-16-le")
    if u16("PowerPoint Document") in blob:
        return "ppt"
    if u16("WordDocument") in blob:
        return "doc"
    if u16("Workbook") in blob or u16("Book") in blob:
        return "xls"
    if b"PowerPoint" in blob:
        return "ppt"
    return "ole"


def sniff_bytes(f: Path):
    """Real type of a file from its bytes, or None when unrecognised."""
    try:
        with f.open("rb") as fh:
            head = fh.read(1024)
    except OSError:
        return None
    if head.startswith(b"%PDF") or b"%PDF-" in head:
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(f) as z:
                names = z.namelist()
        except Exception:
            return None
        if any(n.startswith("ppt/") for n in names):
            return "pptx"
        if any(n.startswith("word/") for n in names):
            return "docx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        return "zip"
    if head.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return _ole_kind(f)
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff") or head[:4] in (b"GIF8", b"II*\x00", b"MM\x00*") \
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
        return "image"
    return None


def detect_kind(f: Path):
    """-> (kind, ext_kind, mismatch, unresolved). kind=None means unrecognised.

    mismatch:   the extension names a type and the bytes show a different one (read as the bytes say)
    unresolved: the extension names a type and the bytes show nothing recognisable (an error)
    """
    ext_kind = EXT_KIND.get(f.suffix.lower())
    sniffed = sniff_bytes(f)
    if ext_kind == "text" and sniffed is None:
        return "text", ext_kind, False, False
    if ext_kind == "image" and f.suffix.lower() == ".bmp" and sniffed is None:
        try:
            if f.open("rb").read(2) == b"BM":
                sniffed = "image"
        except OSError:
            pass
    if sniffed in ("ppt", "doc", "ole") and ext_kind in ("ppt", "doc"):
        return ext_kind, ext_kind, False, False      # OLE sub-type heuristics are weak: trust the extension
    kind = sniffed or None
    mismatch = bool(ext_kind and sniffed and sniffed != ext_kind)
    unresolved = bool(ext_kind and not sniffed)
    return kind, ext_kind, mismatch, unresolved


# ----------------------------------------------------------------------------- PDF (and images)
def ingest_pdf(doc, slug: str, cat: str, work: Path, figures: bool, tmp: Path):
    """doc: an open fitz document. Every low-text page is rendered; every PYQ page is rendered."""
    if doc.needs_pass and not doc.authenticate(""):
        raise RuntimeError("password-protected PDF")
    pages_out, ocr_pages, figs = [], 0, []
    seen = set()
    is_pyq = cat.startswith("pyq") or cat == "imp"
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        used_ocr, image = False, None
        low = len(text.strip()) < LOW_TEXT
        if is_pyq:
            d = work / "pyq_pages"
            d.mkdir(parents=True, exist_ok=True)
            try:
                page.get_pixmap(dpi=PYQ_RENDER_DPI).save(d / f"{slug}_p{i}.png")
                image = f"pyq_pages/{slug}_p{i}.png"
            except Exception as e:  # noqa
                print(f"   !! p{i}: could not render: {e!r}")
        elif low:   # scanned/handwritten/diagram page: agents must be able to SEE it
            d = work / "note_pages"
            d.mkdir(parents=True, exist_ok=True)
            try:
                page.get_pixmap(dpi=NOTE_RENDER_DPI).save(d / f"{slug}_p{i}.png")
                image = f"note_pages/{slug}_p{i}.png"
            except Exception as e:  # noqa
                print(f"   !! p{i}: could not render: {e!r}")
        if TESSERACT and low:
            png = tmp / f"{slug}_p{i}.png"
            try:
                page.get_pixmap(dpi=OCR_DPI).save(png)
                t = ocr_png(png)
            except Exception as e:  # noqa
                t = ""
            if t.strip() and not t.startswith("[OCR FAILED"):
                text, used_ocr = t, True
                ocr_pages += 1
        elif TESSERACT and is_pyq:  # text layer present: keep it, but add OCR of the image as a cross-check
            png = tmp / f"{slug}_p{i}_alt.png"
            try:
                page.get_pixmap(dpi=OCR_DPI).save(png)
                alt = ocr_png(png)
            except Exception:
                alt = ""
            if alt.strip():
                text = text + "\n\n[OCR of the page image - use if the text layer above is garbled]\n" + alt
        pages_out.append(page_rec(i, text, used_ocr, image))

        if figures and cat == "notes":
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                if not info or info.get("width", 0) < MIN_FIG_PX or info.get("height", 0) < MIN_FIG_PX:
                    continue
                data = info["image"]
                if len(data) < MIN_FIG_BYTES:
                    continue
                h = hashlib.md5(data).hexdigest()[:10]
                if h in seen:
                    continue
                seen.add(h)
                ext = info.get("ext", "png")
                if ext not in ("png", "jpg", "jpeg"):
                    # convert exotic formats (jpx, jb2...) to png
                    try:
                        pm = fitz.Pixmap(doc, xref)
                        if pm.n - pm.alpha >= 4:
                            pm = fitz.Pixmap(fitz.csRGB, pm)
                        data, ext = pm.tobytes("png"), "png"
                    except Exception:
                        continue
                fd = work / "figures" / "src"
                fd.mkdir(parents=True, exist_ok=True)
                name = f"{slug}_p{i}_{h}.{ext}"
                (fd / name).write_bytes(data)
                figs.append({"file": f"figures/src/{name}", "page": i,
                             "w": info["width"], "h": info["height"]})
    return pages_out, ocr_pages, figs, len(doc)


def open_image_as_pdf(path: Path):
    img = fitz.open(str(path))
    pdf = img.convert_to_pdf()
    img.close()
    return fitz.open("pdf", pdf)


# ----------------------------------------------------------------------------- PowerPoint COM (Windows)
_COM = {"ok": os.name == "nt", "warned": False}


def _psq(p) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def export_slides_com(src: Path, indices, outdir: Path, w: int, h: int) -> dict:
    """Render the given 1-based slides with PowerPoint (COM). Returns {index: png path}."""
    if not _COM["ok"] or not indices:
        return {}
    outdir.mkdir(parents=True, exist_ok=True)
    lst = ",".join(str(i) for i in indices)
    ps = ("$ErrorActionPreference='Stop';"
          "$p=New-Object -ComObject PowerPoint.Application;"
          f"$d=$p.Presentations.Open({_psq(src.resolve())},$true,$false,$false);"
          f"try{{foreach($i in @({lst})){{$d.Slides.Item($i).Export({_psq(outdir.resolve())}+'\\s'+$i+'.png','PNG',{w},{h})}}}}"
          "finally{$d.Close();if($p.Presentations.Count -eq 0){$p.Quit()}}")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=min(900, 90 + 4 * len(indices)))
        err = (r.stderr or "")
    except Exception as e:  # noqa
        err = repr(e)
    got = {i: outdir / f"s{i}.png" for i in indices if (outdir / f"s{i}.png").exists()}
    if not got and ("ComObject" in err or "80040154" in err or "New-Object" in err):
        _COM["ok"] = False
        if not _COM["warned"]:
            print("[ingest] WARNING: PowerPoint (COM) is not available; low-text slides fall back to their largest picture")
            _COM["warned"] = True
    return got


# ----------------------------------------------------------------------------- PPTX
def iter_shapes(shapes):
    """All shapes of a slide, recursing into group shapes."""
    from pptx.shapes.group import GroupShape
    for shp in shapes:
        if isinstance(shp, GroupShape):
            yield from iter_shapes(shp.shapes)
        else:
            yield shp


def ingest_pptx(path: Path, slug: str, cat: str, work: Path, figures: bool, tmp: Path):
    from pptx import Presentation
    from pptx.shapes.picture import Picture
    prs = Presentation(str(path))
    pages, figs, problems = [], [], 0
    low_slides, pics_of, has_content = [], {}, {}
    for i, slide in enumerate(prs.slides, start=1):
        chunks, pics, content = [], [], False
        for shp in iter_shapes(slide.shapes):
            try:
                if shp.has_text_frame:
                    t = shp.text_frame.text
                    if t.strip():
                        chunks.append(t); content = True
                if getattr(shp, "has_table", False) and shp.has_table:
                    for row in shp.table.rows:
                        chunks.append(" | ".join(c.text for c in row.cells))
                    content = True
                if getattr(shp, "has_chart", False) and shp.has_chart:
                    content = True
                    ch = shp.chart
                    if ch.has_title and ch.chart_title.has_text_frame:
                        chunks.append("[chart] " + ch.chart_title.text_frame.text)
                if isinstance(shp, Picture):
                    blob, ext = shp.image.blob, shp.image.ext
                    content = True
                    try:
                        area = int(shp.width or 0) * int(shp.height or 0)
                    except Exception:
                        area = 0
                    pics.append((area, blob))
                    if figures and len(blob) >= MIN_FIG_BYTES:
                        h = hashlib.md5(blob).hexdigest()[:10]
                        fd = work / "figures" / "src"
                        fd.mkdir(parents=True, exist_ok=True)
                        name = f"{slug}_s{i}_{h}.{ext}"
                        (fd / name).write_bytes(blob)
                        figs.append({"file": f"figures/src/{name}", "page": i})
                elif not shp.is_placeholder:
                    # drawn shapes, connectors, SmartArt/OLE frames: something to see even without text
                    content = True
            except Exception:
                problems += 1
        slide_text = "\n".join(chunks)      # speaker notes don't count: they are not on the slide
        try:
            if slide.has_notes_slide:
                tf = slide.notes_slide.notes_text_frame   # None when the notes slide has no body placeholder
                n = tf.text.strip() if tf is not None else ""
                if n:
                    chunks.append(f"[speaker notes] {n}")
        except Exception:
            problems += 1
        text = "\n".join(chunks)
        pages.append(page_rec(i, text))
        pics_of[i], has_content[i] = pics, content
        if len(slide_text.strip()) < LOW_TEXT:
            low_slides.append(i)

    nocr = 0
    if low_slides:
        sub = "pyq_pages" if (cat.startswith("pyq") or cat == "imp") else "note_pages"
        d = work / sub
        d.mkdir(parents=True, exist_ok=True)
        try:
            sw, sh = int(prs.slide_width or 9144000), int(prs.slide_height or 6858000)
        except Exception:
            sw, sh = 9144000, 6858000
        hpx = max(1, round(SLIDE_RENDER_W * sh / sw))
        rendered = export_slides_com(path, low_slides, tmp / f"{slug}_slides", SLIDE_RENDER_W, hpx)
        for i in low_slides:
            rec = pages[i - 1]
            dest = d / f"{slug}_p{i}.png"
            ok = False
            if i in rendered:
                try:
                    shutil.copyfile(rendered[i], dest); ok = True
                except OSError:
                    pass
            if not ok and pics_of[i]:   # no renderer: the slide's largest picture is what there is to see
                ok = blob_to_png(max(pics_of[i], key=lambda p: (p[0], len(p[1])))[1], dest)
            if ok:
                rec["image"] = f"{sub}/{dest.name}"
                if TESSERACT:
                    t = ocr_png(dest, psm="3")
                    if t.strip() and not t.startswith("[OCR FAILED"):
                        rec["text"] = (rec["text"] + "\n\n[OCR of the slide image]\n" + t).strip()
                        rec["ocr"] = True
                        nocr += 1
            elif not has_content[i] and not rec["text"].strip():
                rec["blank"] = True     # nothing on the slide: no content lost
    if problems:
        print(f"   .. {problems} shape(s) could not be read (skipped)")
    return pages, nocr, figs, len(prs.slides)


# ----------------------------------------------------------------------------- DOCX
def ingest_docx(path: Path, slug: str, work: Path, figures: bool):
    import docx
    d = docx.Document(str(path))
    lines = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            lines.append(" | ".join(c.text.strip() for c in row.cells))
    figs, media = [], []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.startswith("word/media/"):
                data = z.read(n)
                media.append(data)
                if not figures or len(data) < MIN_FIG_BYTES:
                    continue
                fd = work / "figures" / "src"
                fd.mkdir(parents=True, exist_ok=True)
                name = f"{slug}_{Path(n).name}"
                (fd / name).write_bytes(data)
                figs.append({"file": f"figures/src/{name}", "page": 0})
    text = "\n".join(lines)
    rec = page_rec(1, text)
    nocr = 0
    if len(text.strip()) < LOW_TEXT:
        if media:
            dest = work / "note_pages" / f"{slug}_p1.png"
            if blob_to_png(max(media, key=len), dest):
                rec["image"] = f"note_pages/{dest.name}"
                if TESSERACT:
                    t = ocr_png(dest)
                    if t.strip() and not t.startswith("[OCR FAILED"):
                        rec["text"] = (text + "\n\n[OCR of the embedded image]\n" + t).strip()
                        rec["ocr"] = True; nocr = 1
        elif not text.strip():
            rec["blank"] = True
    return [rec], nocr, figs, 1


# ----------------------------------------------------------------------------- legacy .doc/.ppt
def convert_legacy(path: Path, kind: str, out: Path):
    """MS Office COM (Windows): .doc/.ppt -> .pdf. Returns the pdf path or None."""
    src = _psq(path.resolve())
    dst = _psq(out.resolve())
    if kind == "doc":
        ps = (f"$w=New-Object -ComObject Word.Application;$w.Visible=$false;"
              f"$d=$w.Documents.Open({src},$false,$true);$d.SaveAs([ref]{dst},[ref]17);$d.Close();"
              f"if($w.Documents.Count -eq 0){{$w.Quit()}}")
    elif kind == "ppt":
        ps = (f"$p=New-Object -ComObject PowerPoint.Application;"
              f"$d=$p.Presentations.Open({src},$true,$false,$false);$d.SaveAs({dst},32);$d.Close();"
              f"if($p.Presentations.Count -eq 0){{$p.Quit()}}")
    else:
        return None
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, timeout=300)
    except Exception:
        return None
    return out if out.exists() else None


# ----------------------------------------------------------------------------- outputs bookkeeping
def clean_outputs(work: Path, slug: str):
    """Remove everything a previous ingest of `slug` wrote (page images, figures, corpus file)."""
    pat = re.compile(rf"^{re.escape(slug)}_p\d+\.png$")
    for sub in ("pyq_pages", "note_pages"):
        d = work / sub
        if d.is_dir():
            for p in d.iterdir():
                if pat.match(p.name):
                    p.unlink(missing_ok=True)
    fj = work / "figures" / f"{slug}.figs.json"
    if fj.exists():
        try:
            for fig in json.loads(fj.read_text("utf-8")):
                (work / fig["file"]).unlink(missing_ok=True)
        except Exception:
            pass
        fj.unlink(missing_ok=True)
    (work / "corpus" / f"{slug}.md").unlink(missing_ok=True)


def load_gapfill(subject: str) -> dict:
    p = PIPE / "gapfill.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception as e:
        print(f"[ingest] WARNING: cannot read {p}: {e!r}")
        return {}
    for k, v in data.items():
        if k.lower() == subject.lower() and isinstance(v, dict):
            return {name: desc for name, desc in v.items() if not name.startswith("_")}
    return {}


def origin_of(f: Path, rel: str, gap: dict) -> str:
    for key in (f.name, rel, rel.split("/", 1)[-1]):
        if key in gap:
            return f"gapfill:{gap[key]}"
    return "instructor"


def file_stamp(f: Path, ocr: bool) -> str:
    st = f.stat()
    return f"{st.st_size}-{int(st.st_mtime)}|ocr{int(ocr)}|v{INGEST_VERSION}"


# ----------------------------------------------------------------------------- main
def ingest_one(f: Path, kind: str, slug: str, cat: str, work: Path, tmp: Path, figures: bool):
    """-> (pages, nocr, figs, npages)."""
    src = f
    if kind in ("pdf", "pptx", "docx") and f.suffix.lower() != "." + kind:
        src = tmp / f"{slug}.{kind}"           # readers (and PowerPoint) want the right suffix
        shutil.copy2(f, src)
    if kind in ("ppt", "doc"):
        conv = convert_legacy(f, kind, tmp / f"{slug}_conv.pdf")
        if not conv:
            raise RuntimeError(f"legacy .{kind}: could not convert to PDF (needs MS Office COM); convert it manually")
        with fitz.open(str(conv)) as doc:
            return ingest_pdf(doc, slug, cat, work, figures, tmp)
    if kind == "pdf":
        with fitz.open(str(src), filetype="pdf") as doc:
            return ingest_pdf(doc, slug, cat, work, figures, tmp)
    if kind == "image":
        with open_image_as_pdf(src) as doc:
            return ingest_pdf(doc, slug, cat, work, False, tmp)
    if kind == "pptx":
        return ingest_pptx(src, slug, cat, work, figures, tmp)
    if kind == "docx":
        return ingest_docx(src, slug, work, figures)
    if kind == "text":
        t = f.read_text("utf-8", errors="replace")
        return [page_rec(1, t, blank=not t.strip())], 0, [], 1
    raise RuntimeError(f"unsupported kind {kind}")


def main():
    global TESSERACT
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description="Stage 0: ingest a subject's raw inputs into work/")
    ap.add_argument("subject")
    ap.add_argument("--force", action="store_true", help="re-ingest every file (existing slugs are kept)")
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args()

    subj = (ROOT / a.subject).resolve()
    if not subj.is_dir():
        print(f"No such subject folder: {subj}", file=sys.stderr)
        sys.exit(2)
    work = subj / "work"
    corpus = work / "corpus"
    tmp = work / "_tmp"
    for d in (corpus, tmp):
        d.mkdir(parents=True, exist_ok=True)
    man_path = work / "manifest.json"
    old = {"files": {}}
    if man_path.exists():
        try:
            old = json.loads(man_path.read_text("utf-8"))
        except Exception as e:
            print(f"[ingest] WARNING: unreadable manifest ({e!r}); starting fresh")
    old_files = old.get("files", {})
    cache = {} if a.force else old_files

    TESSERACT = find_tesseract()
    ocr_ok = TESSERACT is not None
    if not ocr_ok:
        print("[ingest] WARNING: Tesseract not found (set TESSERACT_CMD or put tesseract on PATH): "
              "low-text pages are rendered to images but get no OCR text")
    gap = load_gapfill(subj.name)

    # ---- discover inputs
    inputs, skipped = [], {}
    for child in sorted(subj.iterdir()):
        if child.is_dir() and child.name.lower() in CATEGORIES:
            cat = CATEGORIES[child.name.lower()]
            for f in sorted(child.rglob("*")):
                if not f.is_file() or f.name.startswith(("~$", ".")) or f.name.lower() in ("desktop.ini", "thumbs.db"):
                    continue
                rel = str(f.relative_to(subj)).replace("\\", "/")
                kind, ext_kind, mismatch, unresolved = detect_kind(f)
                if kind is None and not unresolved:
                    skipped[rel] = "unrecognised file type (not PDF/PPTX/DOCX/PPT/DOC/image/text)"
                    continue
                if kind is not None and kind not in SUPPORTED and not mismatch:
                    skipped[rel] = f"unsupported file type: {kind}"
                    continue
                inputs.append((cat, f, rel, kind, ext_kind, mismatch, unresolved))
    known = {gk for gk in gap}
    present_names = {f.name for _, f, *_ in inputs}
    for gk in sorted(known - present_names):
        if not any(r.endswith(gk) for _, _, r, *_ in inputs):
            print(f"[ingest] WARNING: gapfill.json lists '{gk}' but no such input file exists")

    if not inputs:
        print("No inputs found. Expected Syllabus/, Notes/, Midsem PYQs/, Endsem PYQs/ ...", file=sys.stderr)
        print("INGEST: 1 errors (no input files)")
        sys.exit(1)

    # ---- slugs: keep the manifest's, give new ones a unique name
    used, slug_of = set(), {}
    for _, f, rel, *_ in inputs:
        s = old_files.get(rel, {}).get("slug")
        if s and s not in used:
            slug_of[rel] = s; used.add(s)
    for cat, f, rel, *_ in inputs:
        if rel in slug_of:
            continue
        base = f"{PREFIX[cat]}_{slugify(f.name, key=rel)}"
        slug, k = base, 2
        while slug in used:
            slug = f"{base}_{k}"; k += 1
        slug_of[rel] = slug; used.add(slug)

    manifest = {"files": {}}
    current = {rel for _, _, rel, *_ in inputs}
    for rel, m in old_files.items():          # inputs that disappeared: drop their outputs
        if rel not in current and m.get("slug") and m["slug"] not in used:
            clean_outputs(work, m["slug"])
            print(f"[ingest] removed stale entry {rel}")

    for cat, f, rel, kind, ext_kind, mismatch, unresolved in inputs:
        slug = slug_of[rel]
        origin = origin_of(f, rel, gap)
        stamp = file_stamp(f, ocr_ok)
        prev = cache.get(rel)
        if (prev and prev.get("stamp") == stamp and "error" not in prev and prev.get("slug") == slug
                and (corpus / f"{slug}.md").exists()):
            prev = dict(prev, origin=origin)
            manifest["files"][rel] = prev
            continue
        base_entry = {"slug": slug, "category": cat, "origin": origin, "kind_detected": kind,
                      "ext_kind": ext_kind, "mismatch": mismatch}
        clean_outputs(work, slug)
        if unresolved:
            manifest["files"][rel] = dict(base_entry, unresolved=True, error=
                f"extension says {f.suffix.lower()} but the bytes are not a recognisable {ext_kind} file")
            print(f"[ingest] {cat:10s} {rel}\n   !! unresolved type mismatch: {manifest['files'][rel]['error']}")
            continue
        if kind not in SUPPORTED:
            manifest["files"][rel] = dict(base_entry, unresolved=True, error=
                f"extension says {f.suffix.lower()} but the bytes are a {kind} file (unsupported)")
            print(f"[ingest] {cat:10s} {rel}\n   !! {manifest['files'][rel]['error']}")
            continue
        print(f"[ingest] {cat:10s} {rel}")
        if mismatch:
            print(f"   .. bytes are {kind}, extension says {f.suffix.lower()}: reading it as {kind}")
        OCR_CONF.clear()
        try:
            pages, nocr, figs, npages = ingest_one(f, kind, slug, cat, work, tmp, not a.no_figures)
        except Exception as e:
            clean_outputs(work, slug)
            manifest["files"][rel] = dict(base_entry, error=repr(e))
            print(f"   !! {e!r}")
            continue

        body = [f"# SOURCE: {rel}\n# CATEGORY: {cat} | PAGES: {npages} | OCR pages: {nocr}\n# ORIGIN: {origin}\n"]
        alltext, lost, blank, text_pages, image_only = [], [], 0, 0, 0
        for p in pages:
            t = re.sub(r"\n{3,}", "\n\n", p["text"].strip())
            tag = " (OCR)" if p["ocr"] else ""
            body.append(f"\n## [{slug} p{p['i']}]{tag}\n")
            has_text = len(t) >= TEXT_PAGE_MIN
            text_pages += has_text
            if p["image"] and not p["image"].startswith("pyq_pages/"):
                body.append(f"[page image: work/{p['image']}]")
            if t:
                body.append(t)
            elif p["image"]:
                body.append("[no extractable text: read the page image]")
            elif p["blank"]:
                body.append("[blank page]")
                blank += 1
            else:
                body.append("[LOST: no text and no image]")
            if not t and not p["image"] and not p["blank"]:
                lost.append(p["i"])
            if p["image"] and not has_text:
                image_only += 1
            alltext.append(p["text"])
        (corpus / f"{slug}.md").write_text("\n".join(body), encoding="utf-8")
        joined = "\n".join(alltext)
        gr = garble_ratio(joined)
        conf = round(sum(OCR_CONF) / len(OCR_CONF), 1) if OCR_CONF else None
        # OCR confidence condemns a file only when OCR carries a real share of it (or it is a paper):
        # a typed deck with a few OCR'd diagram slides is not "poor"
        ocr_matters = cat.startswith("pyq") or cat == "imp" or nocr >= 0.25 * max(1, npages)
        poor = (gr > 0.18 or len(joined) < 200 or (conf is not None and conf < POOR_OCR_CONF and ocr_matters)
                or image_only > 0.25 * max(1, npages) or bool(lost))
        manifest["files"][rel] = dict(base_entry, **{
            "pages": npages, "ocr_pages": nocr, "text_pages": text_pages, "image_only_pages": image_only,
            "blank_pages": blank, "lost_pages": lost,
            "chars": len(joined), "garble": gr, "ocr_conf": conf, "figures": len(figs), "stamp": stamp,
            "ocr_available": ocr_ok,
            "quality": "POOR - read page images (work/note_pages or work/pyq_pages)" if poor else "ok",
        })
        if lost:
            print(f"   !! {len(lost)} page(s) with neither text nor image: {lost[:12]}")
        if figs:
            (work / "figures").mkdir(parents=True, exist_ok=True)
            (work / "figures" / f"{slug}.figs.json").write_text(json.dumps(figs, indent=1), "utf-8")

    # ---- health
    files = manifest["files"]
    errored = sorted(r for r, m in files.items() if "error" in m and not m.get("unresolved"))
    unres = sorted(r for r, m in files.items() if m.get("unresolved"))
    lost = {r: m["lost_pages"] for r, m in files.items() if m.get("lost_pages")}
    n_lost = sum(len(v) for v in lost.values())
    resolved = sorted(r for r, m in files.items() if m.get("mismatch") and "error" not in m)
    n_err = len(errored) + len(unres) + n_lost
    ok_files = [m for m in files.values() if "error" not in m]
    manifest["health"] = {
        "errors": n_err, "files_errored": errored, "unresolved_mismatch": unres, "lost_pages": lost,
        "mismatch_resolved": resolved, "skipped": skipped,
        "files": len(files), "files_ok": len(ok_files),
        "pages": sum(m.get("pages", 0) for m in ok_files),
        "text_pages": sum(m.get("text_pages", 0) for m in ok_files),
        "image_only_pages": sum(m.get("image_only_pages", 0) for m in ok_files),
        "ocr_available": ocr_ok, "ingest_version": INGEST_VERSION,
    }
    manifest["skipped"] = skipped
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)

    # ---- INDEX.md — the first file every agent reads
    h = manifest["health"]
    lines = [f"# Corpus index — {subj.name}\n",
             "Each corpus file is page-tagged `## [<slug> pN]`. Cite sources as `[slug pN]`.",
             "PYQ page images (ground truth for verbatim text): `work/pyq_pages/`. Low-text notes pages and "
             "slides are rendered to `work/note_pages/` (the corpus page says `[page image: ...]`).",
             "Extracted figures: `work/figures/src/` (per-file lists in `work/figures/*.figs.json`).",
             "Origin `instructor` = course material; `gapfill:<source>` = added to fill a syllabus gap "
             "(prefer instructor material when both cover a topic).\n",
             f"Health: {h['files_ok']}/{h['files']} files ok, {h['text_pages']}/{h['pages']} pages with text, "
             f"{h['image_only_pages']} image-only pages, {n_err} errors, OCR {'on' if ocr_ok else 'OFF'}.\n",
             "| category | slug | origin | kind | pages | text pp | img-only | OCR | conf | chars | quality | figs | source |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for rel, m in sorted(files.items(), key=lambda kv: (kv[1].get("category", ""), kv[0])):
        kd = m.get("kind_detected") or "?"
        if m.get("mismatch"):
            kd += f" (ext {m.get('ext_kind')})"
        org = m.get("origin", "instructor")
        if "error" in m:
            lines.append(f"| {m['category']} | {m['slug']} | {org} | {kd} | - | - | - | - | - | - | "
                         f"ERROR: {m['error']} | - | {rel} |")
        else:
            q = m["quality"] + (f"; LOST pages {m['lost_pages']}" if m.get("lost_pages") else "")
            lines.append(f"| {m['category']} | {m['slug']} | {org} | {kd} | {m['pages']} | {m.get('text_pages', '-')} | "
                         f"{m.get('image_only_pages', '-')} | {m['ocr_pages']} | {m.get('ocr_conf') or '-'} | "
                         f"{m['chars']} | {q} | {m['figures']} | {rel} |")
    if skipped:
        lines.append("\nSkipped (not ingested):")
        lines += [f"- {r}: {why}" for r, why in sorted(skipped.items())]
    (corpus / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ingest] done -> {corpus / 'INDEX.md'}")

    for r, why in sorted(skipped.items()):
        print(f"[ingest] skipped {r}: {why}")
    for r in resolved:
        print(f"[ingest] note: {r} is really {files[r]['kind_detected']} (extension {files[r]['ext_kind']})")
    detail = (f"{len(errored)} files errored, {len(unres)} unresolved type mismatches, "
              f"{n_lost} pages with neither text nor image")
    if n_err:
        for r in errored + unres:
            print(f"   ERROR {r}: {files[r]['error']}")
        for r, pp in lost.items():
            print(f"   LOST  {r}: pages {pp}")
        print(f"INGEST: {n_err} errors ({detail})")
        sys.exit(1)
    print(f"INGEST: 0 errors ({h['files_ok']} files ok, {h['text_pages']}/{h['pages']} pages with text, "
          f"{len(resolved)} type mismatches resolved, {len(skipped)} skipped)")


if __name__ == "__main__":
    main()
