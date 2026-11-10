"""Run every regression test:  py _pipeline/tests/run_all.py   (exit 0 only if all pass)

Each tests/test_*.py is a standalone script: it prints 'OK <name>' lines and exits 0, or prints
'FAIL ...' and exits non-zero. Tests must never write inside a subject folder: they copy what they
need into tests/_tmp/<test name>/ (gitignored) and run the tools against that copy via
ROOT-independent arguments or the STUDYPREP_ROOT environment variable.
"""
import subprocess, sys, time
from pathlib import Path

here = Path(__file__).parent
for _s in (sys.stdout, sys.stderr):   # cp1252 consoles/pipes: a failing test's Unicode output crashed the runner
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
bad = 0
skipped = 0
for t in sorted(here.glob("test_*.py")):
    # The public copy (_publish/pipeline) ships without tests/fixtures (real course content). Tests that need them
    # are reported as SKIP with the reason, never silently passed. Locally the fixtures exist and nothing is skipped.
    if "fixtures" in t.read_text("utf-8", errors="replace") and not (here / "fixtures").is_dir():
        skipped += 1
        print(f"SKIP  {t.name}  (needs tests/fixtures/, which holds course content and is not published)")
        continue
    t0 = time.time()
    r = subprocess.run([sys.executable, str(t)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    bad += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {t.name}  ({time.time() - t0:.0f}s)")
    if not ok:
        print((r.stdout + r.stderr)[-3000:])
print(("ALL PASS" if not bad else f"{bad} test file(s) failed") + (f" ({skipped} skipped)" if skipped else ""))
sys.exit(1 if bad else 0)
