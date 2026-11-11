"""metrics.py missing_receipts: a receipt saved under a file-safe name counts as present (AI endsem, 2026-11-11).

receipts.py writes the crop of a sub-part id with brackets, such as MS2022-2b(i), as receipts/MS2022-2b_i_.png and
records that name in receipts.json ("file": "receipts/MS2022-2b_i_.png"). metrics.py looked only for
receipts/<qid>.png, so 8 AI questions whose receipts exist were listed as missing (a hard gate).
No TeX: a synthetic receipts folder.
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
TMP = HERE / "_tmp" / "metrics_receipts"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import metrics  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
rdir = TMP / "receipts"
rdir.mkdir(parents=True)
for f in ("MS2022-1a.png", "MS2022-2b_i_.png"):
    (rdir / f).write_bytes(b"png")
rjson = {"MS2022-1a": {"file": "receipts/MS2022-1a.png"},
         "MS2022-2b(i)": {"file": "receipts/MS2022-2b_i_.png"},
         "MS2022-2b(ii)": {"file": "receipts/MS2022-2b_ii_.png"},       # recorded but the file is absent
         "MS2022-3a": {"file": None}}                                   # receipts.py found no crop
(rdir / "receipts.json").write_text(json.dumps(rjson), "utf-8")
qs = [{"id": q} for q in ("MS2022-1a", "MS2022-2b(i)", "MS2022-2b(ii)", "MS2022-3a", "MS2022-4a")]

fn = getattr(metrics, "receipts_missing", None)
check("metrics.receipts_missing exists", fn is not None)
if fn:
    miss = set(fn(rdir, qs, rjson))
    check("a plain <qid>.png receipt is present", "MS2022-1a" not in miss, miss)
    check("a file-safe receipt named in receipts.json is present", "MS2022-2b(i)" not in miss, miss)
    check("a receipt named in receipts.json but absent on disk is missing", "MS2022-2b(ii)" in miss, miss)
    check("file: null is missing", "MS2022-3a" in miss, miss)
    check("a question with no receipt at all is missing", "MS2022-4a" in miss, miss)

shutil.rmtree(TMP, ignore_errors=True)
print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
