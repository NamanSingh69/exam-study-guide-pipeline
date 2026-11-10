# Autoresearch log: pipeline v2

**Method:** change one batch of prompts or tools → regenerate on a fixed test bed → grade with a
**fresh** reviewer agent (`06_review.md` rubric, 7 dimensions, each 0–5) → keep only changes that
don't lower any score.

**Test bed:** CN Midsem. Chapters 05, 20, 32 (U3 Transport), 60, 71 (paper MS2024), 80 and the
cheatsheet.

## Round 0: v1 baseline vs v2 first pass (2026-11-04)

| | fidelity | correctness | coverage | usefulness | visuals | layout | concision | total |
|---|---|---|---|---|---|---|---|---|
| v1 (old prompt.txt) | 0 | 3 | 1 | 1 | 3 | 4 | 4 | 16/35 |
| v2 first pass | 5 | 4 | 5 | 4 | 4 | 3 | 3 | 28/35 |

**Findings**
- v1's "2024 paper" is fabricated: 0 of its 13 questions are in the real paper, and its metadata
  is wrong.
- v2: the reviewer re-solved all 51 numericals independently, and every one matched.
- Weak spots were layout and concision:
  - the radar table was clipped
  - the cheatsheet broke when embedded in the portrait guide
  - [H] floats left pages a third blank
  - unit notes ran 29 pages for 12 lectures
  - Reno fast recovery was stated differently in different chapters
  - the "Asked" badges dropped questions

## Round 1 changes
- **`score.py`:**
  - page-breaking `xltabular` tables
  - every question listed per cluster
  - one ranking rule: rank by EV; the time plans pick by yield
  - the three overlapping plans merged into one list with cut-off lines
  - exponents rendered properly
- **`build.py`:**
  - overfull \vbox, and \hbox above 4 pt, are now ERRORs
  - half-empty-page detector (LAYOUT warnings)
  - the cheatsheet is built standalone and appended as landscape pages, never `\input`
  - chapter builds run 2 passes
  - `--interactive` edition
  - `--scope` and per-scope work folders (`work/midsem`, `work/endsem`)
- **`studyguide.sty`:**
  - print edition = storyboards only; `[interactive]` = animations only
  - storyboards float `[!htbp]`
  - `\stepanim*` / `\storyboard*` for use inside boxes
  - `xltabular` for long tables
- **Prompts:**
  - `conventions.json` written by the blueprint stage and binding on all writers
  - page budgets (1.8 pages per lecture; a 2.5-mark answer ≤ 1 page)
  - float and `\needspace` rules
  - storyboard legibility (≤ 2 frames per row, labels ≥ `\scriptsize`)
  - review now checks cross-chapter consistency and diffs legacy guides
  - the cheatsheet's standalone build is the one that counts
- **Ingest:**
  - Tesseract-confidence quality flag (handwritten notes now marked POOR)
  - `work/note_pages/` renders of scanned pages
  - optional `01b_transcribe_notes` stage
- **Effects measured by the build:**

  | chapter | before | after |
  |---|---|---|
  | 32 (Transport) | 29 pp | 22 pp |
  | 60 (Important questions) | 28 pp | 24 pp |
  | 71 (PYQ 2024) | 11 pp | 10 pp |
  | full guide | 84 pp | 71 pp (68 portrait + 3 landscape cheatsheet) |

  - No LAYOUT errors in any chapter.

## Round 1 score: kept (fresh reviewer, independent of round 0)

| | fidelity | correctness | coverage | usefulness | visuals | layout | concision | total |
|---|---|---|---|---|---|---|---|---|
| v2 round 1 | 5 | 4 | 5 | 4 | 4 | 4 | 4 | **30/35** (+2) |

- Criticals went from 1 to 0.
- All 52 numerical groups re-solved and agreed.
- All 10 theory claims matched the notes page images.
- All round-0 layout and consistency issues are fixed, except the tier-vs-EV wording and a few
  stranded headings.
- New issues found:
  - an unsupported statistic ("transport = 11.5–12.5 of 20 marks")
  - a misattributed convention (UP+1 credited to RFC 793)
  - missing links to every PYQ of a cluster
  - `\tiny` labels in strips
  - one topic with no figure
  - the cheatsheet missing from the table of contents

## Round 2 changes
- `score.py`: the tier comes from the rounded percentage shown to the reader (no 35% in two
  tiers); the radar states "tier by P, EV within tier".
- `build.py` lint:
  - `\tiny` is rejected
  - every `sec:T..` topic must contain a visual
  - the TOC line for the appended cheatsheet is written on the last real page
- `studyguide.sty`: auto `\needspace` before `\section` / `\subsection` (no stranded headings).
- Contract:
  - no unsupported statistics (compute from the bank or omit)
  - attribute alternative conventions correctly
  - link every `question_id` of a cluster
- `04_important_questions`: "ordered by EV within the tier".

## Round 2 score: noise-limited, changes kept

| | fidelity | correctness | coverage | usefulness | visuals | layout | concision | total |
|---|---|---|---|---|---|---|---|---|
| v2 round 2 | 5 | 4 | 5 | 4 | 4 | 3 | 3 | 28/35 (−2 vs r1) |

Every round-1 and round-2 target issue was verified fixed: tiny labels, TOC entry, statistics,
cross-links, tier boundary, Reno, urgent pointer. The drop comes from **new** findings that the
round-1 reviewer never examined:
- half-close `y−1` reasoning
- mock tier-B count
- topic badges pairing topic P with a cluster tier
- the 6-hour cut line
- duplicated figures
- a 2.5-mark answer of 1.5 pages
- one real tool bug: the NBSP map in `studyguide.sty` was corrupted to an ASCII space, giving 2
  recovered TeX errors in every build, which `build.py` did not parse

**Lesson:** one reviewer's 7×0–5 score varies by about ±2 between independent reviewers, which is
as big as the effects being measured. Changes are therefore judged by:
1. objective metrics (`tools/metrics.py`)
2. whether the specific defects targeted are fixed
3. the reviewer score as a coarse guard (no dimension may drop by 2 or more)

## Round 3 changes (tool and prompt level)
- `studyguide.sty`: NBSP mapping repaired. Full-build TeX errors went from 2 to 0.
- `build.py`:
  - errors raised inside `.sty`/`.cls` files are now parsed
  - contact sheets shrink landscape pages instead of cropping them
- `score.py`:
  - the 3h/6h/12h list puts the 3h and 6h plans first, so the cut lines land exactly at 180 and
    360 minutes
  - tier legend unified (B 35–59%, C 15–34%); long shots defined
- Prompts:
  - topic headers carry the topic's P only (tiers belong to question ideas)
  - don't redraw a figure that exists in another chapter: reference it
- New `tools/metrics.py`: objective signal per round.

## Objective metrics after round 3 (CN trial build)
```
lint_issues 0 | layout_warnings 0 | tex_errors 0 | overfull_boxes 0 | over_budget_pages 0
numericals_without_check 0 | pyq_gate 1 | visuals_per_topic 1.85
```

## One-line trigger tests (fresh agents, dry run)
- **Test 1, "generate the endsem notes for DOS":** found the entry via CLAUDE.md, the skill and the
  README. It also surfaced several issues, all now fixed:
  - extensionless notes were never ingested; ingest now sniffs file content
  - a garbage PYQ text layer went unnoticed; PYQs now always get an OCR cross-check
  - duplicate papers; `verify_pyqs` now blocks them
  - no syllabus fallback; added to the blueprint prompt
  - endsem PYQ chapter rules unclear; clarified in the orchestrator
- **Test 2, "generate the midsem notes for SE":** found the entry, planned about 13 agents with
  correct commands, and raised 3 small ambiguities, all now fixed:
  - one combined in-scope-endsem PYQ chapter per midsem run
  - transcribe only the notes the scope needs
  - course-code aliases are banked; similar other courses get paper weight 0.5
  - the INDEX header now has 9 columns

## Status and next steps
- The pipeline is ready for batch runs. Remaining content-level items in the CN trial chapters
  (half-close wording, mock count, Q2(b) length) are left as they are; they only affect the trial.
- Future protocol per round:
  - run `metrics.py`
  - use 2 fresh reviewers and average them
  - keep a change if the metrics don't regress and the averaged score doesn't drop

## Round 4 (2026-11-05/06): gates that fail loudly, regenerated from scratch

**Why:** the final review (`../REVIEW_2026-11-05.md`) found that the safety and measurement layer gave false "all
clean" results:
- the PYQ gate passed an empty bank, changed numbers and invented questions
- metrics missed 50 "p. ??"
- ingest silently dropped 8 of ML's 16 decks
- the probability model did no better than a flat guess

**How:**
- **Workstreams:** seven parallel workstreams against one interface spec (`ROUND4_SPEC.md`).
- **Journal:** every change is a journaled AIDE² node (`docs/aide2_tree.jsonl`, C1–C7), with RED tests first
  (`tests/`, 11 files, `py _pipeline/tests/run_all.py`).
- **Test bed:** CN midsem was then **regenerated from scratch**, not patched.

### Tool changes (every one has a regression test that failed before it)
| area | change | evidence |
|---|---|---|
| PYQ gate | aligned-window matching; exact numbers and acronyms; marks add up; OR pairs; internal choice; OCR folds; vision + `ocr_fixes` + receipt excuses only on OCR'd pages | attack suite 77/77 BLOCK; RED on the old gate: 39 of 43 failed |
| receipts | crop each question from its page; stop at the next sub-part; 2-up booklet spreads; 16-level greyscale | 251/251 CN receipts; archive PDF 13.7 MB → 3.9 MB |
| ingest | magic-byte sniffing, notes-less slides, group shapes, health gate (exit 1) | ML decks 8/16 → 16/16, DMDW 22/24 → 24/24; 12 subjects re-ingested with 0 errors |
| planner | topic-level marks model, Monte-Carlo coverage planner under choice rules, nested plans, tiers = study order, P as bands below 4 papers | see the backtest below |
| build/metrics | undefined refs, float-too-large, missing chapters/receipts, stale PDF, checks run, out-of-window labels and cross-doc refs are hard gates; TOC-based page fill; PDF metadata | the old trial guide is now **blocked** (32 dangling labels) |
| editions | `[phone]` (scaled `L{}` columns with a floor, wrapping badges); PYQ archive with cross-document references; web export (SVG frame animations, per-PYQ pages); Anki flashcards | CN: guide 156 pp, archive 40 pp, phone editions, 225 web pages, 111 cards |
| R4 (user instruction) | PYQ window of 3–5 years per subject (`pyq_windows.json`, `blueprint.pyq_window`) and subject-scaled targets for important questions, notes pages, cheatsheet and drill | CN window 2022–2026 (course code IT-3001 before); notes targets 9.1 / 10.2 / 25.0 pp by marks share |

### CN midsem backtest (held-out papers, 2022–2026 window, 4 folds; mean [range])
| method | 6 h plan cover | 3 h |
|---|---|---|
| new planner | 0.41 [0.15..0.62] | 0.36 |
| old P-ranking | 0.375 | 0.13 |
| lecture time only | 0.36 | 0.29 |
| random ideas | 0.36 | 0.18 |

- The planner never loses to lecture-time-only on any fold.
- With 4 folds, no difference is conclusive.
- With 14 papers and no window (6 folds), new 0.50, old 0.475, lecture 0.46, uniform 0.35.
- Per-idea Brier is still no better than a flat base rate, so P stays a band or a "rough estimate" in the guide.

### Review round 1 (2 fresh reviewers, each reviewing a copy with 5 planted defects, plus answerability)
| | correctness | notation | exam use | pedagogy/visuals | consistency | concision | honesty | total |
|---|---|---|---|---|---|---|---|---|
| A | 3 | 4 | 4 | 4 | 2 | 4 | 3 | 24 |
| B | 4 | 4 | 3 | 4 | 2 | 3 | 1 | 21 |

- **Planted-defect recall:**
  - A: 3/5. The scorer said 2/5 because it could not match the short planted number "11"; adjudicated by hand.
  - B: 4/5 after fixing the scorer to read `critical[]`.
  - Planted criticals capped B's honesty and A's correctness, so real-guide scores are higher on those two.
- **Answerability on the held-out MS2025 paper:** 94.5%. 13 of 14 parts full; MS2025-4a was partial, and fixed.
- **Blind pairwise vs the round-3 trial:** the new version wins 50%. It wins the 3 notes topics and loses the 2 PYQ
  solutions and 1 IQ entry. Those new units point to a solve atom outside the extracted text, a measurement artefact
  that `pairs.py` should fix by inlining `\seesolved` targets.
- **Real findings, all fixed in fix round 1:**
  - **Pure-ACK sequence numbers:** the convention was broken in 5 places.
  - **Utilisation:** two boxed answers for one numerical; now 1/(1+2a) boxed and L/BDP "also accepted".
  - **Bandwidth-delay product:** defined two ways.
  - **Exam-hall figures:** stated differently in 3 places.
  - **Segments per window:** floor vs ceiling.
  - **MS2026SP coverage:** wrong in the bank, so the radar dropped 3 topics.
  - **Honesty wording in `score.py`:** P called a "chance"; wildcards called "never asked".
  - **Thin answers:** C14 had no conditional-GET answer; MS2023-3a had no diagram.

### Lessons
1. **Real data finds what fixtures don't.** Every real-run stage found bugs that the unit tests missed:
   - OCR'd superscripts
   - sub-part letters past (h)
   - either-or pairs
   - booklet spreads
   - the flashcards/web folder marker
   - phone table widths
   - the target JSON shapes
   - the scorer ignoring `critical[]`

   Each became a regression test.
2. **Hand-grouped chapters go stale when the model re-runs.** A coverage fix moved 14 ideas between tiers and
   chapter 60 had to be regrouped by hand. **Next:** `score.py` should emit the tier skeleton of chapter 60 and
   writers should own `atoms/iq/<Cid>.tex`.
3. **Conventions must be decided before the writers start.** Five of the real findings were the same fact stated two
   ways: the pure-ACK sequence number, the utilisation formula, BDP, the exam-hall budget and floor vs ceiling.
   **Next:** the blueprint stage proposes conventions for every recurring numeric idea, and a consistency script greps
   the boxed answers per convention.
4. **Concision is the weakest dimension.** Units ran 20–60% over their targets until the data-driven targets were
   enforced.

### Next round (Round 5) backlog
- Chapter-60 skeleton from `score.py`.
- A convention-consistency checker.
- `pairs.py` inlines `\seesolved` targets.
- Regenerate SVP endsem (zero-paper mode) and ML endsem (12+ papers) as the other test-bed subjects.
- A post-exam scoring run after the next real paper.

### Test bed 2: SVP endsem, weak-input mode (0 papers, video modules without notes), 2026-11-06
- Pipeline in zero-paper mode:
  - blueprint: assumed pattern from the IPA endsem header, 40 topics, 122 clusters, 19 video topics `unfillable`
  - gate `RESULT PASS (no papers)`
  - 52 important ideas, 6 unit writers, 7 agents in the fix round
- Outputs: guide 171 pp, phone edition, 3-page cheatsheet + night-before sheet, 30-item predicted Q1 drill, 177
  flashcards, web 0 fallbacks.
- Review r1 (2 reviewers, planted defects):
  - mean 22/35; honesty capped at 1 by the planted criticals
  - recall: A 5/5, B 3/5
  - no real critical
- **Real findings, all fixed with tests:**
  - **`score.py` zero-paper wording:** paper-mode text ("past papers in the window", "seniors' lists",
    "recency-weighted") leaked into a subject that has no papers.
  - **Radar wildcards:** it listed 48 wildcards where the guide covers 5.
  - **Predicted Q1 drill:** 28 of 30 items were video; it is now spread by unit share.
  - **Conventions:** four decided only after writers diverged.
  - **Banners:** 41 video solve atoms had none.
- **Tool bugs found only on real data:**
  - `\fbox` box and `\ifcsname` handling in web
  - `gather*` and long `\src` slugs on phone
  - underscore slugs in generated text
  - stale phone PDF not caught by metrics
  - scorer missing quoted short formulas
  - metrics ignoring dict `notes_pages` (an earlier test passed by coincidence)
- **Lesson:** a regression test only counts if it fails against the old code. Two of this round's first-draft tests
  passed both before and after the change; each was rewritten to discriminate.
