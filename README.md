# Exam study-guide pipeline

An agent pipeline (Claude Code + Python + LaTeX) that turns a university course's instructor notes and past exam
papers (PYQs) into an exam-ready study guide. It never invents a past-paper question: every PYQ is transcribed
from the page image, verified by a gate against its own paper, and printed with a cropped image of the original
("receipt").

**Results so far (one semester, 7 courses, end-semester scope):**

| course | print guide | phone edition |
|---|---|---|
| Computer Networks | 282 pp | 519 pp |
| Design & Analysis of Algorithms | 285 pp | 526 pp |
| Computational Intelligence | 322 pp | 582 pp |
| Engineering Economics | 199 pp | 358 pp |
| High Performance Computing | 202 pp | 371 pp |
| Software Engineering | 218 pp | 407 pp |
| Speech & Video Processing | 171 pp | 324 pp |

Each guide holds: unit notes with step-by-step storyboard figures, every in-window past paper solved (each
question idea solved once, then cross-linked), important questions ranked by a backtested coverage planner
(3/6/12-hour study plans), a Q1 drill, a mock paper, a cheatsheet and a night-before sheet. There are also Anki
flashcards and a static web edition with a self-test mode.

> Unofficial student project; not affiliated with or endorsed by any university. The course material and the
> generated guides are not in this repository: it holds only the tools, prompts, LaTeX style and tests.
> The test fixtures are synthetic.

**Start here:** [`RUNBOOK.md`](RUNBOOK.md) (how to run a subject at the lowest usage cost) · [`docs/COST.md`](docs/COST.md)
(measured token cost) · `py tests/run_all.py` (local CI: every regression test).

**Engineering notes:**
- **Hard gates:** a stage counts as done only when its gate passes; `metrics.py` blocks a release on any of
  11 defects.
- **AIDE² change journal** (`docs/aide2_tree.jsonl`): every change starts with a failing test; reverts are
  recorded too.
- **Cost:** measured from transcripts. An automatic layout check (`layout_check.py`) replaced reading page
  images, and each writer gets one context pack.

## Outputs

The pipeline turns a subject folder (`Syllabus/`, `Notes/`, `Midsem PYQs/`, `Endsem PYQs/`) into these
outputs, per scope (`midsem` | `endsem`):

| output | where | what |
|---|---|---|
| Guide (print) | `<SUBJ>/<Subject>_<Scope>_Guide.pdf` | how to use, exam radar, unit notes, important questions in study order, Q1 drill, PYQ chapters with receipts, mock paper, the "Older papers" section (one_pdf, the default) and the appended cheatsheet. One PDF per subject. Storyboards work in every viewer. |
| Guide (phone) | `<SUBJ>/<Subject>_<Scope>_Guide_Phone.pdf` | the same chapters on a single-column small page |
| Guide (interactive, opt-in) | `<SUBJ>/<Subject>_<Scope>_Guide_Interactive.pdf` | animations (Acrobat, Okular, Foxit), with each storyboard still printed under its animation |
| Cheatsheet (split mode only) | `<SUBJ>/<Subject>_<Scope>_Cheatsheet.pdf` | 2–4 landscape pages (`targets.cheatsheet_pages`), then the night-before Q&A sheet; with one_pdf it is only inside the guide |
| PYQ Archive (split mode only) | `<SUBJ>/<Subject>_<Scope>_PYQ_Archive.pdf` | the older in-window papers: verbatim, receipt, "same idea as…" (`build.py --archive`); with one_pdf they are inside the guide |
| Web | `<SUBJ>/work/<scope>/web/` | static pages per topic and per solved PYQ; web animations; self-test mode |
| Flashcards | `<SUBJ>/work/<scope>/flashcards.csv` | Anki-importable `front;back;tags` |

Deliverable PDFs are copied into `<SUBJ>/` **only when their build succeeded**.

Optional `assignments.json` key `"updates_url"`: the shared folder that holds the latest version. It is printed and
linked on the guide's title page ("Latest version and corrections"). Plain https URLs only; anything else blocks
the build.

It replaces an earlier single-prompt version, which fabricated past papers. That failure is why the gates exist.

## How it works
1. **Ingest:** `ingest.py`, plus a health gate.
2. **PYQ transcription,** fanned out: one agent per 3–4 papers.
3. **Merge and cluster:** one blueprint agent.
4. **Receipts and the verbatim gate:** `receipts.py`, then `verify_pyqs.py`.
5. **The planner:** `score.py`. Its 3/6/12-hour study plans set the tiers (A/B/C = the 3 h/6 h/12 h plan, D =
   wildcard, E = the rest). P is shown as a band when there are fewer than 4 papers.
6. **Writers,** in parallel:
   - topic atoms per unit
   - one full solve per question idea (`atoms/solve/`)
   - the PYQ chapters: the latest 3 papers in full; older papers verbatim + receipt + "same idea as…"
   - important questions and the mock
7. **Recall:** the Q1 drill, the flashcard top-up and the night-before sheet. Then the cheatsheet.
8. **Builds,** `web.py`, `flashcards.py`, and `metrics.py` (hard gates).
9. **Review:**
   - 2 fresh reviewers judging correctness and pedagogy, calibrated with planted defects
   - a blind pairwise comparison against the previous version
   - an answerability check
   - a fix loop of at most 2 rounds

`run_state.json` (`tools/state.py`) makes every step resumable after a usage-limit stop.

| v1 problem | Round 4 fix |
|---|---|
| invented PYQs; a gate that passed an empty bank | the bank is transcribed from page images; `verify_pyqs` aligns every question with its own paper (numbers and acronyms exact); a cropped **receipt** of the real question is printed under it |
| "ranked by chance" without evidence | a coverage planner with nested plans, backtested (`backtest.py`); P shown as a band below 4 papers |
| the same idea solved 4 times | one `solvedidea` per cluster; everything else uses `\seesolved` |
| stale hand-typed badges | `score.py` writes `badges.tex`; writers use `\clusterbadge`/`\topicbadge` |
| silent partial success ("?? " refs, lost notes) | every stage exits 1 on partial failure; metrics hard gates |
| reading-only guides | Q1 drill, flashcards, night-before sheet, web self-test |

## Files
```
_pipeline/
  RUNBOOK.md                       START HERE: the low-usage default path per subject, session rules, model tiers
  docs/COST.md                     measured token cost per run (baseline + every run since)
  prompts/_writer_card.md          the 1-page writer rules that every pack embeds
  prompts/00_orchestrator.md       reference playbook: phases, ledger, fan-out, batching, resume, edge cases
  prompts/_writer_contract.md      binding rules for every writer agent
  prompts/01_blueprint.md          Part 1 scope/topics/visuals/figure plan; Part 2 merge, cluster, coverage
  prompts/01a_transcribe_pyqs.md   verbatim PYQ transcription, 3–4 papers per agent
  prompts/01b_transcribe_notes.md  vision transcription of the POOR notes pages a scope needs
  prompts/02_unit_notes.md         topic atoms + unit wrapper
  prompts/03_pyq_solutions.md      PYQ chapters + solve atoms
  prompts/04_important_questions.md  study-order questions + mock paper
  prompts/05_cheatsheet.md
  prompts/06_review.md             independent reviewer (rubric, pairwise, JSON)
  prompts/07_recall.md             Q1 drill, flashcard top-up, night-before sheet
  prompts/08_answerability.md      can the guide answer held-out questions?
  schemas.md                       every JSON contract
  exam_dates.json                  exam dates per subject and scope (for ordering batches)
  ROUND4_SPEC.md                   binding tool interfaces
  tools/ingest.py      PDF/PPTX/DOCX -> page-tagged corpus, OCR, page images, figures; health gate
  tools/receipts.py    crop each banked question from its page
  tools/verify_pyqs.py the verbatim gate
  tools/score.py       planner -> important_questions.json, badges.tex, radar + how-to-use chapters
  tools/backtest.py    leave-one-year-out backtest; pooled parameters; --post-exam scoring
  tools/state.py       the resume ledger
  tools/build.py       lint, compile (full / --phone / --interactive / --cheatsheet / --chapter / --atom), contact sheets
  tools/metrics.py     objective numbers and hard gates
  tools/layout_check.py  page-by-page layout defects (outside, overlap, on_line, tiny); --render sheets only for flagged pages
  tools/pack.py        one capped context file per writer (card, assignment, targets, conventions, cited pages)
  tools/run_subject.py one command per deterministic phase (ingest | gate | post), ledger + <= 15 lines
  tools/usage_report.py  tokens per agent from Claude Code transcripts (docs/COST.md)
  tools/plant_defects.py  planted-defect copies for reviewer calibration
  tools/web.py, tools/flashcards.py
  latex/studyguide.sty, latex/visual_cookbook.tex
  tests/run_all.py     every regression test
```

## Commands (from the `Study Prep` folder, Windows `py`)
`--scope midsem|endsem` is **required** by every per-scope tool. Only `ingest.py` has no scope, because its
output is shared.
```
py _pipeline/tools/ingest.py CN                                   # exit 1 = INGEST errors: stop
py _pipeline/tools/receipts.py CN --scope midsem
py _pipeline/tools/verify_pyqs.py CN --scope midsem               # must print RESULT PASS
py _pipeline/tools/score.py CN --scope midsem
py _pipeline/tools/state.py CN --scope midsem next
py _pipeline/tools/build.py CN --scope midsem --atom notes/T15 --render
py _pipeline/tools/build.py CN --scope midsem --chapter 32_transport_layer --render
py _pipeline/tools/build.py CN --scope midsem --cheatsheet --render
py _pipeline/tools/build.py CN --scope midsem --render            # print guide
py _pipeline/tools/build.py CN --scope midsem --archive           # PYQ archive (then rebuild the guide once)
py _pipeline/tools/build.py CN --scope midsem --phone             # phone guide
py _pipeline/tools/build.py CN --scope midsem --interactive       # opt-in
py _pipeline/tools/flashcards.py CN --scope midsem
py _pipeline/tools/web.py CN --scope midsem
py _pipeline/tools/metrics.py CN --scope midsem                   # exit 1 if any hard gate is non-zero
py _pipeline/tools/build.py --cookbook
py _pipeline/tests/run_all.py
```

**Gates:**
- A gate's PASS is required before the next stage: ingest exit 0, then `RESULT PASS`, then `STATUS OK`.
- `metrics.py`'s hard gates must all be 0, and `pyq_gate` must be 1:
  - `ingest_errors`
  - `undefined_refs`
  - `tex_errors`
  - `float_too_large`
  - `missing_chapters`
  - `missing_receipts`
  - `checks_failed`
  - `stale_pdf`
  - `out_of_window_in_chapters`
  - `internal_leaks` (a convention id such as `ack_number` printed in the guide)

**Sizes and the PYQ window are per subject.** Only PYQs inside `blueprint.pyq_window` (3–5 years) are printed.
Notes pages per unit, the important-question set, the cheatsheet pages and the Q1 drill come from
`important_questions.json → targets`.

**CI is local.** `py _pipeline/tests/run_all.py` and the gates above run on this laptop and are the gate. GitHub
Actions are used only for what cannot run here; publishing lives in `../_publish/`.

**Other files:**
- `AUTORESEARCH_LOG.md`: rounds and scores
- `sources.md`: where to fetch missing notes and PYQs (kept local, not published)
- `gapfill.json`: which notes are gap-fill, not instructor material

**Requirements:**
- Windows Python 3.12 via `py`, with pymupdf, python-pptx, python-docx, pypdf and pillow
- MiKTeX pdflatex, with `animate`, `ocgx2`, `zref`, `newunicodechar`, `xltabular` and `adjustbox`
- poppler (`pdftoppm`) and Tesseract
