# Case study: a study-guide pipeline that is not allowed to make things up

**One line:** a multi-agent pipeline (Claude Code agents, Python tools, one LaTeX style) that turns a course's
lecture notes and past exam papers into a print-ready study guide, where every stage must pass a check that the
writing agent cannot influence.

**Scale reached (one semester, end-semester scope, November 2026):** 12 courses, 3,045 guide pages, 132 past
papers transcribed, 2,310 past-paper questions matched against their own paper, about 2,000 executable answer
checks per full build, 34 journaled changes, each started from a failing test.

Interactive version of this page: [`site/`](../site/index.html).

## 1. The problem

Version 1 was a single long prompt. Its guides looked finished. An audit against the scanned papers found
that its "2024 past paper" chapter was invented: 0 of its 13 questions were in the real paper, and the paper's
metadata was wrong too. A reviewer agent scored it 16/35 on a seven-part rubric, with 0/5 for fidelity.

The lesson was not "write a better prompt". A language model that is asked to produce a past paper will produce
one whether or not it has seen it. The fix had to be structural: the model may transcribe and explain, but a
separate program decides whether what it wrote is admissible.

## 2. Design

Nine stages. A stage counts as done only when its gate passes.

| # | stage | what runs | gate |
|---|---|---|---|
| 1 | Ingest | `tools/ingest.py`: PDF, PPTX, DOCX to a page-tagged corpus, OCR, page images | exits 1 if any file is dropped or unreadable |
| 2 | Transcribe | one agent per course reads the paper page images, word for word | none: its output is untrusted until stage 3 |
| 3 | Receipts and verbatim gate | `tools/receipts.py`, `tools/verify_pyqs.py` | numbers and acronyms exact, marks add up, `RESULT PASS` or stop |
| 4 | Plan | `tools/score.py`: marks model per topic, Monte-Carlo coverage planner under the exam's choice rules | backtest on held-out papers (`tools/backtest.py`) |
| 5 | Write | parallel writer agents, small LaTeX pieces against `latex/studyguide.sty` | each writer compiles only its own files; every numerical gets a check script |
| 6 | Recall | short-answer drill, flashcards, cheatsheet, night-before sheet | sizes come from per-course targets |
| 7 | Build | `tools/lint_tex.py`, `tools/build.py`, `tools/layout_check.py` | overfull boxes are errors; layout defects are listed page by page |
| 8 | Metrics | `tools/metrics.py` | ten hard gates must be 0 and the PYQ gate must be 1 |
| 9 | Review | two fresh reviewer agents, an answerability agent, a fix loop of at most two rounds | reviewers are calibrated with planted defects |

Design decisions that mattered:

- **Receipts.** Every printed past-paper question carries a cropped image of the original. A reader can check
  the transcription by eye, and a missing receipt blocks the build.
- **One solution per idea.** Questions are clustered into ideas. Each idea is solved once and every repeat
  links to it, which removed the largest source of contradictions and cut length.
- **Generated badges.** "Asked in 2023, 2025" badges come from the bank through `score.py`. Writers cannot
  type them, so they cannot be stale or wrong.
- **One figure source, two outputs.** A step-by-step figure is one TikZ source: a storyboard of frames in the
  print edition, an animation in the interactive and web editions.
- **Files, not conversation.** All state is JSON and LaTeX on disk, with a ledger (`tools/state.py`), so a run
  that stops at a usage limit resumes where it stopped and any coding agent can run the pipeline.

## 3. Results

| measure | result | source |
|---|---|---|
| Reviewer rubric, same test bed | 16/35 (single prompt) to 30/35 (pipeline, round 1) | `AUTORESEARCH_LOG.md` |
| Verbatim gate against tampered banks | 77 of 77 blocked; the gate it replaced failed 39 of the first 43 attack tests | `tests/test_verify.py` |
| Answerability on a held-out paper | 94.5%: 13 of 14 parts in full | `prompts/08_answerability.md` |
| Reviewer recall on planted defects | 3 to 5 of 5 | `tools/plant_defects.py` |
| Hard-gate defects in the 12 released guides | 0 | `tools/metrics.py` |
| Ingest health gate | one course had silently lost 8 of 16 slide decks; now 16 of 16 | `tests/test_ingest.py` |
| Token cost per course | about 250–350 M input-side tokens before, 91–221 M after | `docs/COST.md` |
| Writer model tier | a blind A/B preferred the cheaper model 4–1 with 1 tie, so writers moved down a tier | `docs/COST.md` |

Per course (end-semester guides):

| course | pages | papers in bank | questions gated | answer checks |
|---|---|---|---|---|
| Machine Learning | 358 | 24 | 380 | 270 |
| Artificial Intelligence | 323 | 17 | 284 | 207 |
| Computational Intelligence | 323 | 19 | 346 | 228 |
| Data Mining and Data Warehousing | 287 | 16 | 263 | 239 |
| Design and Analysis of Algorithms | 286 | 18 | 305 | 232 |
| Computer Networks | 281 | 14 | 251 | 197 |
| Software Engineering | 218 | 4 | 89 | 48 |
| Distributed Operating Systems | 210 | 6 | 98 | 77 |
| High Performance Computing | 202 | 5 | 103 | 147 |
| Engineering Economics | 199 | 5 | 106 | 160 |
| Image Processing and Applications | 187 | 4 | 85 | 132 |
| Speech and Video Processing | 171 | 0 (weak-input mode) | 0 | 125 |

## 4. What did not work

- **The probability model.** The planner's 6-hour plan covered 0.41 of the marks on held-out papers, against
  0.36 for random ideas and 0.36 for lecture time alone. With four folds this is not conclusive, and per-idea
  Brier scores are no better than a flat base rate. The guides therefore print likelihood as a band or a "rough
  estimate", and that wording is enforced by tests.
- **Unit tests on fixtures.** Every first run on real material found bugs the fixtures had missed: OCR'd
  superscripts, sub-part letters past (h), either-or pairs, two-page booklet spreads. Each became a regression
  test.
- **Fan-out.** About 20 agents per course hit the usage limit three times. Each agent re-read the same
  contract and JSON files, so per-agent overhead dominated. Lean mode (about six agents and one context pack
  each) gives the same gates for roughly a third of the tokens.
- **Reading page images to check layout.** Writers looked at about 2,000 renders of their own pages. A layout
  checker that reads the PDF geometry now flags about 9% of pages, and only those are looked at.

## 5. How it was built

- **Test first, journaled.** Each change is a node in `docs/aide2_tree.jsonl`: hypothesis, failing test,
  minimal change, own-test and full-suite scores, kept or reverted.
- **Regression suite.** 28 test files, about 5,700 lines, on synthetic fixtures, run locally with one command
  (`py tests/run_all.py`). Hosted CI is manual and only smoke-tests a fresh clone.
- **Measured cost.** `tools/usage_report.py` reads agent transcripts and reports tokens per agent. Every run
  since the baseline has a row in `docs/COST.md`.
- **Independent review.** Reviewers never see the writer's reasoning, and their recall is measured with planted
  defects before their verdict is trusted.

## 6. Limits

- Unofficial student project. The guides are generated with AI assistance and can contain mistakes.
- The course material and the generated guides are not in this repository. Only tools, prompts, the LaTeX
  style, tests on synthetic fixtures and a few sample pages on the showcase site are public.
- One university, one semester, one author. Usage by other students has not been measured yet.
- The toolchain is Windows-first (MiKTeX, `py`), with a TeX-free subset that runs on Linux.

Future work: [`ROADMAP.md`](ROADMAP.md).
