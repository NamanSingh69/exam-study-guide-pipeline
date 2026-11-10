"""Resolve a subject's working folders (shared by every tool).

  <SUBJ>/work/                  shared, scope-independent ingest output: corpus/, pyq_pages/, note_pages/,
                                figures/, manifest.json   (written by ingest.py)
  <SUBJ>/work/<scope>/          per exam scope (midsem | endsem): blueprint.json, pyq_bank.json,
                                important_questions.json, badges.tex, receipts/, atoms/, chapters/,
                                checks/, build/, qa/, review*.json, run_state.json

--scope is REQUIRED for every per-scope tool (Round 4): guessing it once let an endsem run be gated
against the midsem bank.
"""
import os, sys
from pathlib import Path

# STUDYPREP_ROOT lets tests (and the public portable copy) point the tools at another folder of subjects.
ROOT = Path(os.environ.get("STUDYPREP_ROOT") or Path(__file__).resolve().parents[2]).resolve()
PIPE = Path(__file__).resolve().parents[1]
SCOPES = ("midsem", "endsem")


def setup_stdout():
    """Windows consoles/pipes default to cp1252; labels contain arrows and Greek letters."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def resolve(subject: str, scope: str | None, create: bool = False):
    """Return (subject_dir, shared_work_dir, scoped_work_dir). Exits with code 2 on bad input."""
    if not subject:
        raise SystemExit(2)
    subj = (ROOT / subject).resolve()
    if not subj.is_dir():
        print(f"no subject folder {subj}", file=sys.stderr)
        raise SystemExit(2)
    if not scope:
        print("--scope midsem|endsem is required", file=sys.stderr)
        raise SystemExit(2)
    s = scope.lower()
    if s not in SCOPES:
        print(f"--scope must be one of {SCOPES}", file=sys.stderr)
        raise SystemExit(2)
    shared = subj / "work"
    scoped = shared / s
    if create:
        scoped.mkdir(parents=True, exist_ok=True)
    return subj, shared, scoped
