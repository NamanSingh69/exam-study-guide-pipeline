# Round 4 spec: shared interfaces (read this before touching any file)

Background: `../REVIEW_2026-11-05.md` (the findings, §2, and the first-principles rethink, §6). Round 4
turns every finding into a gate that fails loudly, adds the new features, then regenerates the test
bed from scratch. Several agents work **in parallel**: each owns only the files listed for it in
**Ownership**. Anything another workstream needs from you is specified here. If you need to change an
interface, write the proposal under "Open questions" at the bottom of this file. Never silently
diverge from it.

## Ground rules (all workstreams)
- **Python:** Windows `py` (3.12). Never use msys `python`. No shebang lines. Write `.tex` files and
  LaTeX-heavy Python strings with the Write/Edit tools, never with heredocs or `sed`, which mangle
  backslashes.
- **Shared helpers:** every tool calls `workdir.setup_stdout()` first. Per-scope tools take a
  **required** `--scope midsem|endsem` (`workdir.resolve` enforces it). Paths come from
  `workdir.ROOT`, which honours the `STUDYPREP_ROOT` env var so tests can run against a temp copy.
- **Exit codes:**
  - 0: OK
  - 1: BLOCKED/FAILED (a gate failed, or an input errored)
  - 2: usage error

  Gates print a final line `RESULT PASS` or `RESULT BLOCKED: <reasons>`. Silent partial success is
  forbidden.
- **Tests:** add `tests/test_<area>.py` (standalone; prints `OK ...`; exits 0). They run under
  `py _pipeline/tests/run_all.py`.
  - Never write into a real subject folder. Copy fixtures into `tests/_tmp/<name>/` and set
    `STUDYPREP_ROOT`.
  - The CN midsem data (`CN/work/`) is the realistic fixture; copy only what you need.
- **Real data is read-only for you**, except where your ownership says otherwise. Re-ingesting,
  regenerating and re-scoring real subjects happens later, in the integration step.
- **Compatibility:**
  - Keep the existing macros (`\mks \asked \prob \tier \src \ev \stepanim \storyboard \figfromnotes`,
    the boxes) and labels.
  - The trial chapters in `CN/work/midsem/chapters/` must still compile, or fail only on the new
    hard gates (undefined refs and the like), which is expected.

## Paths (per subject `<S>`, scope `<sc>`)
| path | writer | contents |
|---|---|---|
| `<S>/work/manifest.json`, `corpus/`, `pyq_pages/`, `note_pages/`, `figures/` | ingest.py | as today, plus `origin` and `kind_detected` per file (see Ingest) |
| `<S>/work/<sc>/pyq_bank.json` | blueprint agent(s) | schema in `schemas.md`, plus the new optional per-question `receipt` |
| `<S>/work/<sc>/receipts/<qid>.png`, `receipts.json` | receipts.py | cropped image of each question from its paper page |
| `<S>/work/<sc>/important_questions.json`, `badges.tex`, `chapters/05_how_to_use.tex`, `chapters/20_exam_radar.tex` | score.py | see Score |
| `<S>/work/<sc>/atoms/notes/<Tid>.tex` | unit-notes writers | one topic's notes (one `\section`) |
| `<S>/work/<sc>/atoms/solve/<Cid>.tex` | whoever the orchestrator assigns | the one full model solution of a question idea |
| `<S>/work/<sc>/chapters/<stem>.tex` | writers / orchestrator | chapters; unit chapters may be `\chapter{..}` + `\input{atoms/notes/T07}` lines |
| `<S>/work/<sc>/run_state.json` | `tools/state.py` (called by the orchestrator) | resume ledger |
| `<S>/work/<sc>/flashcards.csv` | flashcards.py | Anki-importable `front;back;tags` |
| `<S>/work/<sc>/web/` | web.py | static site for this subject and scope |
| `<S>/<Subject>_<Scope>_Guide.pdf`, `_Guide_Interactive.pdf`, `_Guide_Phone.pdf`, `_Cheatsheet.pdf` | build.py | deliverables, copied **only when the build succeeded** |
| `_pipeline/model_params.json` | backtest.py | pooled, tuned model parameters (score.py uses defaults if absent) |
| `_pipeline/gapfill.json` | ingest workstream (initial content from `GATHERING_LOG.md`) | `{ "<SUBJ>": {"<file name under Notes/>": "<origin description>"} }` |

`build.py` compiles with `TEXINPUTS=<_pipeline/latex>;<S>/work/<sc>;` (so `\input{atoms/...}`,
`badges.tex` and `receipts/` resolve). It no longer copies the `.sty` into work folders.

## LaTeX macros (defined in `studyguide.sty` by the build workstream; used by score.py output and writers)
- **`\sgdefbadge{C05}{A}{79}{high}{1.58}`:** one line per cluster in `badges.tex`. Arguments: tier
  letter A–E; P as an integer percent, or `-` when it is shown as a band only; band
  `low|med|high`; EV.
- **`\sgdeftopic{T07}{84}{high}`:** one line per topic.
- **`\clusterbadge{C05}`:** the tier pill plus a P pill (or band pill), read from the definitions
  above. If undefined, prints a red `?C05` and `\typeout{SG-BADGE-MISSING:C05}`.
- **`\topicbadge{T07}`:** the topic's P pill (or band).
- Writers **must** use these two instead of hand-typed `\prob`/`\tier`. Lint flags `\prob{` /
  `\tier{` outside `20_exam_radar.tex`.
- **`\receipt{<qid>}`:** the question's crop from `receipts/<qid>.png`, at most 0.9\linewidth, in a
  thin grey frame captioned "From the paper". If the file is missing: a red box "receipt missing"
  plus `\typeout{SG-RECEIPT-MISSING:<qid>}`.
- **`\notfromnotes{<book, chapter>}`:** a red banner at the top of a section: "Not in your
  instructor's notes — written from <book, chapter>; check it against class material". Use it for
  unfillable `coverage_gaps` topics instead of `\src`.
- **`\begin{solvedidea}{C05}{<title>} ... \end{solvedidea}`:** the full model solution of an idea.
  Sets `\label{solve:C05}`.
- **`\seesolved{C05}`:** "Same idea as <title>: full solution on p. N" (hyperlinked to `solve:C05`).
- **`\flashcard{front}{back}`:** prints nothing in the print edition. flashcards.py collects them.
  Writers put 2–5 per topic, for definitions, formulas and key facts.
- **`\pyqsolved{<qid>}`:** link text "solved on p. N" to `q:<qid>`. It writes `\typeout{SG-REF:q:<qid>}`
  so the build can tell a dangling link from a chapter that is missing.
- **Labels:**
  - `q:<qid>`: PYQ solutions
  - `sec:<Tid>`: topic sections
  - `iq:<Cid>`: important-question entries
  - `solve:<Cid>`: solved ideas
  - `fig:<name>`: figures
- **Package options:**
  - `[interactive]`: animations, **with the storyboard still printed under each animation**, so
    viewers that can't play `animate` lose nothing.
  - `[phone]`: a single-column small page (about 105 × 187 mm, 10.5 pt, small margins, tables and
    TikZ scaled to `\linewidth`) for reading on phones.
  - `[cheatsheet]`: as today.
- **`\mks`, `\clusterbadge` and the other pills are robust in moving arguments** (`\section` titles,
  bookmarks): `\pdfstringdefDisableCommands` gives them a text form.

## Score (score.py + backtest.py)
- **Scope** comes from the work folder name (`work.name`), never from `blueprint.json`.
- **Weights:**
  - A paper counts for a cluster only if the paper's coverage includes that cluster's unit. A
    midsem paper never counts for post-midsem units.
  - Typical marks `m` come only from papers with weight > 0.
  - With 0 relevant papers: P = prior, the output says so, and nothing crashes.
- **Planner** (replaces ranking by P):
  - Choose topic and idea sets for 3, 6 and 12 hours of study that maximise the expected
    *attainable* marks under the paper's choice rules.
  - Estimate it with Monte-Carlo papers drawn from the topic-level marks model and the real
    per-unit structure.
  - Plans are **nested** (12 h ⊇ 6 h ⊇ 3 h).
  - Report the expected marks and `p_safe`: the probability that you can still answer the required
    number of optional questions.
- **Tiers mean study order:**
  - A = in the 3 h plan
  - B = added by the 6 h plan
  - C = added by the 12 h plan
  - D = wildcard (never asked, strong prior)
  - E = the rest
- **P display:** an integer percent when the subject has ≥ 4 relevant papers, otherwise a band
  (low < 25 % ≤ med < 50 % ≤ high).
- **`important_questions.json` keeps `model`, `clusters`, `topics` and `plans`**, and adds:
  - `q1_drill`: one-mark PYQ ids plus predicted cluster ids
  - `must_draw`: question ids and clusters whose questions ask to draw a diagram
  - `skip_safety`: per unit, "if you skip this unit, in each past paper you could still answer k of
    the n optional questions"
  - `exam_hall`: minutes per mark, plus a word budget per marks value (≈ marks × min-per-mark × 20
    words)
  - `backtest`: the latest leave-one-out numbers for this subject, if any
- **`05_how_to_use.tex` and `20_exam_radar.tex`** print:
  - the plans, with `\pageref`s to `iq:`/`sec:`, in **syllabus order** within each plan
  - the exam-hall time plan, word budgets and answer templates for each marks value
  - the must-draw list, skip-safety, and the Q1 drill pointer
  - the backtest line ("tested on held-out papers: the 6 h plan covered X% of the marks"), or "not
    yet backtested"
- **badges.tex** is regenerated on every run.
- **`backtest.py`:**
  - Leave-one-year-out over every subject and scope with a bank of ≥ 3 relevant papers.
  - Metrics: log-loss and Brier for P, "marks covered by the 3/6/12 h plans", and the same for
    baselines (uniform; lecture-time only).
  - Tunes DECAY, ALPHA and the prior weights *pooled across subjects* (hierarchical shrinkage toward
    a shared mean) and writes `_pipeline/model_params.json`.
  - `--post-exam <SUBJ> --scope <sc> --paper <id>` scores a saved plan snapshot
    (`work/<sc>/plan_snapshots/<date>.json`, which score.py writes each run) against a newly banked
    paper.

## Receipts and the gate (receipts.py + verify_pyqs.py)
- **`receipts.py <S> --scope <sc>`:** for each banked question, locate its text on the paper's page
  and crop a full-width band.
  - Page words come from pymupdf words, or from Tesseract TSV for scanned pages.
  - Paper PDF → page via `manifest.json` and `pyq_pages/`.
  - A manual override `"receipt": {"page": 2, "rect": [x0, y0, x1, y1]}` (PDF points) in the bank
    wins.
  - Writes `receipts.json`: `{qid: {page, rect, match, method}}`.
- **`verify_pyqs.py` blocks on:**
  - an empty bank, or a paper with 0 questions
  - a paper whose banked marks don't add up to its pattern (allowing for choice)
  - an unknown topic or cluster
  - a missing corpus file
  - non-numeric marks
  - any number or ALL-CAPS acronym in the question that isn't present *in the matched window*
  - a word-trigram containment below the threshold
  - a question of fewer than 4 tokens without vision verification
  - a missing or low-match receipt, unless the question has `verified: "vision"` **and** a manual
    receipt rect
- **The attack suite** (`tests/test_verify.py`) must BLOCK every case in `REVIEW_2026-11-05.md`
  §2.1. The real CN bank must still PASS, or the failures must be real and listed.

## Build and metrics
- **`build.py`:**
  - Parses the pdflatex return code.
  - Error regex `^(.+?\.\w+):(\d+): `.
  - `Float too large` is a LAYOUT error.
  - Undefined references are **errors on full builds**; on `--chapter` builds they are warnings,
    except `SG-REF` targets inside the same chapter.
  - Timeout of 180 s per pass for `--chapter` builds and 600 s otherwise.
  - Takes chapter starts from the TOC for the page-fill check.
  - Copies deliverables only on success.
  - Sets PDF metadata from the blueprint: title "<Subject> <Scope> Study Guide (unofficial)",
    author "Unofficial student study guide", subject, keywords.
  - New `--phone` edition and a `--atom notes/T07` standalone build.
  - Lint checks:
    - badge/`\mks` usage inside sectioning
    - hand-typed `\prob`/`\tier`
    - `[H]`
    - `\tiny`
    - a topic without its blueprint-assigned visual type (`topic.visual`)
    - tables don't count as visuals for tier A/B topics
- **`metrics.py` adds:**
  - `undefined_refs`, `float_too_large`
  - `missing_chapters`: expected from the blueprint units plus papers, vs files
  - `missing_receipts`, `missing_badges`
  - `stale_pdf`: newest chapter or atom newer than the guide PDF
  - `checks_failed`: runs every `checks/*.py` with a 60 s timeout
  - `numericals_without_check`: from the bank, not from labels
  - `dup_solves`: a cluster with a full solution in more than one place
  - `pages_per_exam_mark`, `storyboards_per_process_topic`
  - `ingest_errors`: from the manifest
  - `backtest_6h_cover`

  Each metric is printed, and the run exits 1 if any **hard gate** is non-zero: `ingest_errors`,
  `undefined_refs`, `tex_errors`, `float_too_large`, `missing_chapters`, `missing_receipts`,
  `checks_failed`, `stale_pdf`, `pyq_gate` ≠ 1.

## Ingest
- **Type detection:** sniff the magic bytes first (`%PDF`, PK zip → docx or pptx by content, OLE →
  legacy, images), and use the extension only as a fallback. Record `kind_detected` and a
  `mismatch` flag.
- **PPTX:**
  - a notes slide without a text frame is skipped, not fatal
  - recurse into group shapes
  - render slides that have little text (via the PDF route when one is available)
- **Low-text pages:** always render them to `note_pages/` or `pyq_pages/`, even when OCR is
  missing. The cache stamp includes OCR availability.
- **Slugs:** keep the existing slug from the manifest; new slugs get a short hash suffix when
  truncated.
- **Origin:** `origin`: `instructor` or `gapfill:<desc>` (from `_pipeline/gapfill.json`), shown in
  the manifest and the INDEX.
- **Health summary:** on any errored file, type mismatch or page with neither text nor image, end
  with `INGEST: N errors (...)` and exit 1.

## Orchestration (prompts)
- **`tools/state.py`:**
  - `state.py <S> --scope <sc> set <stage> <key> <status> [--note ..]`
  - `state.py <S> --scope <sc> show`
  - `state.py <S> --scope <sc> next`: prints what to resume

  Statuses: `todo | running | ok | failed`. The file is `run_state.json`, written atomically.
- **The orchestrator assigns every chapter stem and every `solve:` owner** in the briefs. Writers
  never choose them.
- **Endsem reuses midsem:** the endsem blueprint reuses the midsem unit, topic and cluster ids for
  shared units when `work/midsem/blueprint.json` exists. Those atoms are copied rather than
  rewritten when their sources are unchanged.
- **PYQ chapters:**
  - the latest 3 relevant papers are solved in full, each question solved once via
    `atoms/solve/<Cid>` + `\seesolved`
  - older papers: the verbatim question, its `\receipt`, and `\seesolved`
- **Recall outputs:**
  - a Q1 rapid-fire drill chapter (`65_q1_drill.tex`, answers folded to the end of the chapter)
  - `\flashcard`s in the atoms
  - a "night before" sheet section in the cheatsheet: questions on one side, answers on the next
    page
- **Weak-input mode:**
  - 0 papers: an assumed pattern with its source named; bands only; the mock labelled "pattern
    assumed"
  - `\notfromnotes` for unfillable gaps
  - a per-unit source-confidence table in "How to use"
- **Optional class signal:** hints in the user's trigger message (e.g. "teacher stressed X") go to
  `work/<sc>/class_signal.json`, which score.py reads as a prior boost. Never block to ask.
- **Review:**
  - planted-defect calibration (`tools/plant_defects.py` makes a scratch copy with N planted
    defects and an answer key; reviewer recall is reported)
  - blind pairwise comparison against the previous round
  - an answerability check: for each held-out question, does the guide contain what's needed?

## Ownership
| workstream | owns (may create/edit) |
|---|---|
| **T1 gate** | `tools/verify_pyqs.py`, `tools/receipts.py`, `tools/state.py`, `tests/test_verify.py`, `tests/test_receipts.py`, `tests/test_state.py` |
| **T2 ingest** | `tools/ingest.py`, `gapfill.json`, `tests/test_ingest.py` |
| **T3 score** | `tools/score.py`, `tools/backtest.py`, `model_params.json`, `tests/test_score.py`, `tests/test_backtest.py` |
| **T4 build** | `tools/build.py`, `tools/metrics.py`, `tools/plant_defects.py`, `latex/studyguide.sty`, `latex/visual_cookbook.tex`, `tests/test_build.py`, `tests/test_metrics.py` |
| **T5 web** | `tools/web.py`, `tools/flashcards.py`, `latex/web/` (templates, JS, CSS), `tests/test_web.py`, `tests/test_flashcards.py` |
| **P prompts** | `prompts/*.md` (incl. new `07_recall.md`, `08_answerability.md`), `schemas.md`, `README.md`, `../CLAUDE.md`, `../AGENTS.md`, `../.claude/skills/generate-notes/SKILL.md`, `exam_dates.json` |
| **U publish** | `../_publish/**` only |
| **lead (main session)** | `tools/workdir.py`, `tests/run_all.py`, this file, `AUTORESEARCH_LOG.md`, integration, regeneration |

## Open questions (append below; the lead resolves them)

- **T2 ingest: `ingest_errors` source for metrics.py (T4).** `manifest.json` now has a top-level
  `health` block: `{errors, files_errored[], unresolved_mismatch[], lost_pages{rel: [pages]},
  mismatch_resolved[], skipped{rel: reason}, files, files_ok, pages, text_pages, image_only_pages,
  ocr_available, ingest_version}`. Proposal: `ingest_errors = health.errors` (fallback for old
  manifests: count entries with an `error` key). Per-file entries add `origin`, `kind_detected`,
  `ext_kind`, `mismatch`, `text_pages`, `image_only_pages`, `blank_pages`, `lost_pages`, `ocr_available`.
- **T2 ingest: how slides are rendered.** Low-text PPTX slides are rendered with PowerPoint COM
  `Slide.Export` (PNG), not by exporting a PDF: PDF export drops hidden slides and shifts the page
  numbers. Without PowerPoint, the slide's largest picture is used. If neither works and the slide has
  content, the page counts as lost (exit 1). PowerPoint is a single shared instance, so run the
  re-ingests **one subject at a time** (one background script), not in parallel.
- **T2 ingest: files ingest skips.** Files whose type ingest doesn't recognise (no known extension and
  no known magic bytes, or xlsx/zip) go in `manifest.skipped` and the INDEX and are printed. They
  are not errors. A file whose extension names a type its bytes don't match (e.g. an HTML page saved
  as `.pdf`) is an error.
- **T1 gate: where `receipts.json` lives.** It is `<S>/work/<sc>/receipts/receipts.json`, next to the
  PNGs (`verify_pyqs.receipts_path(work)`). metrics.py (T4) should read `missing_receipts` from there or
  just count missing `receipts/<qid>.png`. Entries add `parts` ([{page, rect}], several when a question
  runs over a page break: the PNG is stacked), `tri`, `file` (`receipts/<qid>.png`, or null when nothing
  was found), `paper` and `text_sha` (a short hash of the normalised question text). The gate treats a
  receipt whose `text_sha` doesn't match the current text as stale, so editing a question means
  rerunning `receipts.py` (`--only <qid>` is enough). `match` = fraction of the question's tokens found
  in the cropped words; the threshold is 0.6. `method`: `pdf-words | tesseract | png-tesseract | manual`.
- **T1 gate: order and the vision-plus-manual exemption.** Orchestrator order: bank, then
  `receipts.py`, then `verify_pyqs.py`. The gate blocks while receipts haven't been made, so the real
  CN bank blocks until the integration step runs receipts.py. `verified: "vision"` plus a manual
  `receipt` rect waives the **match** threshold only. The PNG must still exist (receipts.py always
  crops a manual rect), because `\receipt` needs it.
- **T1 gate: new rule that prompts (P) should mention.** "Verbatim" is now enforced. Each question
  token that the paper doesn't have at that spot (that is, one not aligned, and not a near-miss OCR
  typo within edit distance ~len/5) must be named in the question's `ocr_fixes`. The limit is
  max(1, 4 % of tokens) unexplained edits. An ALL-CAPS token or number that is in the window but out
  of place is excused only with `verified: "vision"` plus the token named in `ocr_fixes`. The marks
  check reads the `pattern` string when it has the forms `Q1 compulsory 5x1` and
  `any 3 of Q2-Q5` / `any 3 of the remaining four`. Optional questions must carry equal marks. A
  question group whose text says "any two" must bank more than two parts.
- **P prompts: the zero-papers gate (T1).** `verify_pyqs` blocks an empty bank, but weak-input mode
  (SVP) has no papers at all.
  - Proposal: accept `{"no_papers": true, "papers": [], "questions": []}` when the manifest holds no
    `pyq_midsem`/`pyq_endsem` files. Print `RESULT PASS (no papers: weak-input mode)`, still checking
    the clusters' topics against the blueprint.
  - The prompts (00, 01) already describe this behaviour.
  - score.py (T3) then needs to handle the empty bank with bands only (the spec already says "0
    relevant papers: P = prior").
- **P prompts: `plant_defects.py` CLI (T4).** The prompts assume:

  `py _pipeline/tools/plant_defects.py <S> --scope <sc> --n 5 --seed <k> --out <S>/work/<sc>/reviews/copy_<k>`
  - `--out` receives a copy of `chapters/`, `atoms/` and the JSON files, with paths relative to it.
  - The answer key goes to `<S>/work/<sc>/reviews/_keys/copy_<k>.json`, never inside `--out`. Shape:
    `[{file, where, kind, original, planted}]`.
  - Two seeds, one per reviewer.
  - Please match this, or tell the lead so the prompts can be changed.
- **P prompts: `web.py` / `flashcards.py` CLIs (T5).** Assumed `py _pipeline/tools/<tool>.py <S> --scope <sc>`,
  exit 0/1.
  - flashcards.py scans `\flashcard{..}{..}` in `atoms/**/*.tex` and `chapters/*.tex`, tagging each card with
    the enclosing atom's topic id.
  - The recall agent re-runs it to count cards per topic: please print a per-topic count.
- **P prompts: `--atom` scope (T4).** The prompts build `--atom notes/<Tid>` and `--atom solve/<Cid>`.
  `atoms/recall/night_before.tex` is only compiled through the cheatsheet build.
- **P prompts: `assignments.json` (orchestrator-owned; schema in `schemas.md`).** It records:
  - the paper id map
  - every chapter stem with its kind and paper
  - the atom owners
  - the solve owners (Cid → chapter + anchor qid)
  - the figure owners

  Proposal for metrics.py (T4):
  - `missing_chapters`: expected = `assignments.json → chapters[].stem` when the file exists; otherwise
    blueprint units + papers.
  - `dup_solves`: count `\begin{solvedidea}{Cid}` per Cid across `atoms/` and `chapters/`, plus any
    `\input{atoms/solve/Cid}` that appears more than once.
- **P prompts: PYQ chapter stems.** To survive more than 10 papers (ML endsem has 12 plus the midsem papers)
  without spilling into `80_`, PYQ chapters are `7NN_pyq_<paperid lowercase>`. `700_` is the newest paper:
  the 3 full-solution papers first, then the older ones. They sort between `65_q1_drill` and
  `80_mock_paper`. Every relevant paper gets its own chapter; the old combined `79_pyq_endsem_inscope` is
  retired. metrics/web should not assume one-digit `7N_`.
- **P prompts: visual-type detection for lint (T4).** The prompts define the vocabulary of `topic.visual` and
  what each must contain (`_writer_contract.md` §4, `schemas.md`):
  - `storyboard` → `\stepanim`/`\storyboard`
  - `plot` → `axis`
  - `table` → `tabularx`/`xltabular`
  - `figure` → `\figfromnotes`
  - the TikZ types → a `tikzpicture`, plus the named node styles where practical (`state` for `fsm`,
    `child` for `tree`, `lifeline` for `sequence`)

  `storyboards_per_process_topic` treats `visual: storyboard` topics as process topics.
- **P prompts: source-confidence table (T3).** The spec puts "a per-unit source-confidence table in How to
  use". `05_how_to_use.tex` is regenerated by score.py, so score.py must print it.
  - The blueprint now has `units[].source_confidence = {level: high|medium|low, why}`.
  - Proposal: also print the count of `\notfromnotes` topics, taken from `coverage_gaps[status=unfillable]`.
- **P prompts: `class_signal.json` shape (T3).**
  `{"source", "signals": [{"text", "kind": "stress|drop|pattern", "topics": [], "clusters": []}]}`
  - The orchestrator writes `text`/`kind`; the blueprint agent maps the ids.
  - Proposal: `stress` boosts the prior of the listed topics or clusters; `drop` sets the topic's prior to ~0
    and excludes it from the plans; `pattern` is informational (printed in the radar).
- **P prompts: paper weight vs exam type (T3).** `papers[].weight` now means source relevance only: 1 same
  course, 0.5 similar course, 0 record only. The old "midsem papers at half weight in an endsem run" rule is
  not encoded by the prompts. score.py should decide how midsem papers count for endsem clusters, via
  `exam` and `coverage`.
  - Each paper now also has `session: spring|autumn`, for recency ("6th Sem 2026" sits before autumn 2026).
    Use (`year`, `session`) as the recency key.
- **P prompts: pairwise extraction helper (lead).** The orchestrator extracts the X/Y pairs by label with an
  ad-hoc `py` snippet. A small `tools/pairs.py <S> --scope <sc> --prev <dir> --n 6` would make the step
  deterministic.

- **T3 score: what other workstreams must match (proposals).**
  - **`iq:` labels.** The radar and how-to chapters `pageref` `iq:<Cid>` for every tier A-D cluster and `sec:<Tid>` for
    every topic in a plan. The important-questions chapter (prompt 04) must label every A-D cluster, not only A/B.
    Topics with no recorded question form get a synthetic idea `<Tid>-any` in the JSON (`synthetic: true`); it has no
    badge and no `iq:` ref.
  - **Tiers changed meaning** (A = 3 h plan, B = added by 6 h, C = added by 12 h, D = wildcard, E = rest). Prompt 04's
    "grouped by P >= 60%" text and the old CN chapter 60 intro are stale; ordering inside a tier should follow
    `plans.<h>.clusters` (study order) or `plan_gain`.
  - **Q1 drill chapter label.** 05_how_to_use points to `ch:q1drill` only if that label exists (guarded with
    `ifcsname r@ch:q1drill`). Proposal: `65_q1_drill.tex` sets `label{ch:q1drill}`.
  - **metrics.py `backtest_6h_cover`** = `model_params.json -> backtest["<S>/<sc>"].summary.new.cover_6h.mean`
    (also copied into `important_questions.json -> backtest`). Null when the bank has < 3 relevant papers.
  - **Midsem papers in an endsem scope** count only for the units they examine (`coverage`, else the sibling midsem
    blueprint's units), at `cross_weight` 0.5 times their source `weight`; they never enter the unit-share
    denominator, which uses endsem papers only. Endsem papers never count in a midsem scope.
  - **`p_safe`** = share of simulated papers on which the plan lets you earn at least half the marks of k optional
    questions. `expected_marks` in the plans is the model's own estimate (in-sample, optimistic); the held-out
    backtest number is the honest one and is the one printed as the "track record".
  - score.py now imports **numpy** (already installed with the Windows py 3.12).
- **T4 build: interpretations and interface notes (please confirm or overrule).**
  - **Lint `\prob`/`\tier`:** allowed in *both* score.py chapters (`05_how_to_use`, `20_exam_radar`), not only 20.
  - **Chapter-build refs:** an undefined `\pyqsolved`/`\seesolved` target is an *error* only when the chapter owns
    it: `q:<qid>` in a chapter whose stem ends `_pyq_<paper of qid>`, or `solve:<Cid>` in `--atom solve/<Cid>`.
    Everything else undefined is a warning. Full builds (print/interactive/phone): every undefined ref is an error,
    and each one is classified ("paper chapter missing", "no `\label` anywhere", "atom missing").
  - **Full builds also FAIL** when `chapters/cheatsheet.tex` is missing or doesn't compile. The cheatsheet is
    included with pdfpages (real TOC page and bookmark) in **all three** editions, phone included (A4 landscape pages).
  - **`missing_chapters` fallback** (no `assignments.json`): the auto/IQ/mock/cheatsheet chapters (`05_`, `20_`,
    `60_`, `80_`, `cheatsheet`) + in-scope unit stems + one `7NN_pyq_<id>` per paper (midsem scope: midsem papers and
    endsem papers with in-scope questions; endsem scope: endsem papers + the 3 latest midsem by (year, session)).
  - **`numericals_without_check`** accepts `checks/<qid>.py` *or* `checks/<Cid>.py` (the solved idea's check).
  - **`missing_receipts`** = R7's count plus any `SG-RECEIPT-MISSING` in the guide log.
  - **`pages_per_exam_mark`** = pages of the `7NN_pyq_*` chapters / full marks of those papers (contract ≈ 0.4).
    Chapter page spans come from `\sgchapterend` markers the wrapper writes into the `.aux`.
  - **`stale_pdf`** compares against the *delivered* `<S>/<Subject>_<Scope>_Guide.pdf` (none = stale), so a failed
    build (not copied) keeps the gate red. `over_budget_pages` uses the contract's 1.5 pp/lecture + 1.
  - **Phone edition limits:** `xltabular` can't be boxed, so fixed-width xltabular columns overflow. On the CN copy
    that's the radar table (+28 pt, its header cell is clipped). **score.py (T3)** should give that table `Y`
    columns. `tabularx` with fixed `p/L{}` columns is typeset 1.4x wide then shrunk; wide TikZ, `tabular`,
    `\[..\]`, `equation*` and `align*` are shrunk to `\linewidth`; storyboards become 1 frame per row and inline.
  - **Pill labels:** `\tier` prints `A · 3 h`, `B · 6 h`, `C · 12 h`, `D · wildcard`, `E · later`. `\prob` colours
    follow the bands (≥ 50 red, ≥ 25 amber).
  - **Interactive:** the storyboard under each animation drops `\label`s inside the caption (it would define them
    twice); a label after `\stepanim` points at the storyboard figure.
- **T4 build: PYQ archive (second document), as built.**
  - `assignments.json` kind `pyq_older` chapters leave the main editions and are built by
    `build.py <S> --scope <sc> --archive [--phone]` into `<Subject>_<Scope>_PYQ_Archive[_Phone].pdf`. No
    assignments.json means everything stays in the guide, as before.
  - **Cross refs: no xr-hyper.** build.py writes `work/<sc>/_xref_<job>.tex`: the other document's labels, taken
    from its *sources*, with page numbers from its `.aux` when it has been built. A stale `.aux` can't
    resurrect a deleted label. The table defines them the way xr does (`\r@…`), so plain
    `\ref`/`\pageref`/`\nameref` print "3.2", "12 (Guide)" and the title. `\seesolved` prints "… full solution in
    the Guide, p. N" and `\pyqsolved` prints "PYQ archive, <paper> <qno>, p. N"; both are linked to the other PDF
    (`\href[page=N]`, so keep both PDFs in one folder).
  - Before the other PDF exists, the pointer prints without a page and counts as `cross_refs_pending`.
  - A target in neither document stays an undefined ref (hard error); build.py labels it "CROSS-DOC target missing".
  - **Build order:** guide, `--archive`, guide. The phone pair is built the same way and uses the other phone
    `.aux`. Each build records a fingerprint of the cited pages of the other document (`result.json → xref_sig`).
    `stale_pdf` fires when they have changed since, so metrics says which one to rebuild.
  - The archive's `tex_errors`/`undefined_refs`/`float_too_large` count in the same hard gates.
    `cross_refs_unresolved` is a new hard gate. `archive_pages` is reported separately, and
    `pages_per_exam_mark` covers the main guide only.
  - **web.py:** no change needed. It renders every chapter into one site, so archived papers already get their
    per-PYQ pages with links to the solve and topic pages. Optional: list `kind: pyq_older` papers under an
    "Older papers" heading.
- **T1 gate: forms for transcribers, from the real CN papers.**
  - **Either-or questions:** use qno `"1(a) OR"`; `1(a)OR` and `1 OR (a)` are also accepted. `Qn` plus
    `Qn OR` make one choice slot, so the marks count one alternative. The two alternatives must carry
    equal marks, and they are never treated as duplicates of each other.
  - **2-up booklet spreads:** add `"reading_order": ["1R", "2L", "2R", "1L"]` to the paper entry
    (page plus L/R half). receipts.py splits a landscape OCR'd page in half only when the OCR shows a
    gutter, then reads the halves in this order, so a question that continues backwards in the booklet
    (ES2026SP 4b) is cropped whole.
  - **OCR damage:** a number or ALL-CAPS token missing from an OCR window is excused only when the
    question is `verified: "vision"`, the token is named in its `ocr_fixes`, and its receipt is fresh
    with match ≥ 0.6 (or is a vision-checked manual rect). A text-layer window gets no excuse. A
    *different* legible number or acronym at that spot is a swap and always blocks. An OCR near-miss
    is not a swap: lost digits (`$00,000`), or an acronym within edit distance 1, or 2 from five
    letters (`EPRAME`). The OCR fold now includes `|`→1 and 0↔O.
- **T1 gate: `receipts.json` gains `ocr_text`, `ocr_method`, `ocr_is_ocr`.** This is the fresh text of
  the crop region: the page words, or a region-only re-OCR at 300 dpi (psm 6 and 4) when that reads
  better. When the corpus text fails a question, the gate reruns the same checks on `ocr_text`, and
  `ocr_text` decides only if every check passes. Receipts made before this change have no `ocr_text`,
  so rerun receipts.py.

## Lead resolutions (binding)
- **R1. T2's health-block proposals are accepted.** `ingest_errors = manifest.health.errors`, with the stated fallback. Re-ingests run one subject at a time.
- **R2. T1's receipts location and the vision exemption rules are accepted as written.**
- **R3. All P proposals are accepted:**
  - the zero-papers PASS (`no_papers: true`; T1 implements it)
  - the `plant_defects.py` CLI and key location (T4)
  - the web.py and flashcards.py CLIs, with the per-topic card counts (T5)
  - `--atom notes/<Tid>` and `--atom solve/<Cid>` (T4)
  - `assignments.json` drives `missing_chapters` and `dup_solves` (T4)
  - the `7NN_pyq_<id>` stems (T4 and T5 must not assume one-digit stems)
  - the visual-type vocabulary for lint (T4)
  - the source-confidence table, the `class_signal.json` semantics, paper `weight` as source relevance only, and `(year, session)` as the recency key (T3)
  - `tools/pairs.py` (T1)

## R4 (user instruction, 2026-11-05): PYQ window and subject-scaled sizes (binding)
The user asked for:
- **A PYQ window:** only the previous 3-5 years of PYQs, as suits the subject.
- **Sizes by subject:** the number of important questions and the length of the notes and the cheatsheet depend on each subject's content.

**1. `blueprint.pyq_window`**
- **Shape:** `{"from": 2022, "to": 2026, "years": 5, "why": "..."}`, chosen by the blueprint agent.
- **Default:** the latest 5 calendar years that have papers.
- **Start later** (keeping at least 3 years) when the syllabus or course code changed inside the window. The window starts at the change.
- **Extend back** (up to 5 years) only if the scope type would otherwise have fewer than 3 relevant papers.

Papers outside the window stay in the bank for the record: gated, with receipts. They are excluded from:
- the scoring and backtests (`score.py` treats them as weight 0, reason "outside window")
- every chapter
- the Q1 drill and the PYQ archive

**2. `score.py` → `important_questions.json.targets`**
These are data-driven, printed in "How to use", and each carries a `why` string.
- **`iq_clusters`:** the 12 h plan's clusters plus at most 5 tier-D wildcards. The important-questions chapter covers exactly these; tier E becomes a one-line index only.
- **`notes_pages[<unit>]`:** `lectures_u * clamp(1.0 + share_u / mean_share, 1.0, 2.0) + 1`, where `share_u` is the unit's share of the window's in-scope PYQ marks. High-weight units get more room and low-weight units get less.
- **`cheatsheet_pages`:** `2 + (in-scope topics > 20) + (numerical share of window marks > 40%)`, so 2-4 landscape pages, excluding the night-before sheet.
- **`q1_drill`:**
  - the newest in-window 1-mark PYQ of each one-mark idea (amended 2026-11-06: ML's 24 papers gave 177 items)
  - `min(30, 2 * one-mark clusters)` predicted items

**3. `metrics.py`**
- `over_budget_pages` uses `targets.notes_pages`.
- New tracked metrics, not gates:
  - `iq_count_vs_target`
  - `cheatsheet_pages_vs_target`
  - `out_of_window_in_chapters` (count of `\label{q:<qid>}` of papers outside the window). This one is a hard gate.
