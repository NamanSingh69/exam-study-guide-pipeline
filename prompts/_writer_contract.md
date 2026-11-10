# Writer contract: binding for every agent that writes LaTeX

> Writers normally read the 1-page `_writer_card.md` (embedded in their pack by `tools/pack.py`); this file is the
> full text behind it. Read a section here only when the card or your stage prompt sends you to it.

You write part of an exam study guide for a B.Tech student (KIIT, School of Computer Engineering). The student
reads under time pressure and reproduces your answers by hand in the exam. Optimise for **marks per minute of
reading**.

## 0. What you write and where
- **Write only the files your brief assigns you** (`work/<scope>/assignments.json` is the source):
  - topic atoms `atoms/notes/<Tid>.tex`: exactly one `\section{...}\label{sec:<Tid>}` each
  - solve atoms `atoms/solve/<Cid>.tex`: exactly one `solvedidea` environment each
  - chapters `chapters/<stem>.tex`

  Never rename a stem, never create another chapter, never edit another agent's file.
- **A chapter that holds atoms** is `\chapter{...}` plus your own glue and `\input{atoms/notes/T07}` lines. The
  build resolves `atoms/`, `badges.tex` and `receipts/` itself.
- **Bare bodies only:** no `\documentclass`, `\usepackage`, `\begin{document}` and no colour definitions. They
  live in `_pipeline/latex/studyguide.sty`.
- **Write `.tex` with the Write/Edit tools only:** never heredocs, `sed` or `echo`, which mangle backslashes.

## 1. Ground truth and honesty
- **Notation.** The **instructor's notes** (`origin: instructor` in `work/corpus/INDEX.md`) define the content,
  notation and names; examiners mark against them. Use their definitions and symbols. For example, if the
  slides say "Go-Back-N ARQ" with window `2^m − 1`, so do you.
  - **Gap-fill notes** (`origin: gapfill:<desc>`: downloaded slides, Han, R. Mall, Anna Univ. DIP) rank
    *below* the instructor's notes. Use them for content the instructor's notes lack, but never let their
    notation override the instructor's.
  - **A textbook** ranks last.
  - **When two sources differ,** follow the higher one and add a one-line `examtip` naming the difference.
- **Citations.** Cite with `\src{<slug> p<N>}` at least once per section: a definition, formula or figure.
  - **Scanned or handwritten notes:** read `work/corpus/<slug>__vision_*.md` if it exists, otherwise the images
    in `work/note_pages/`. Raw OCR of POOR files is unreliable.
  - **A topic listed in `blueprint.json → coverage_gaps` with `status: "unfillable"`:** start its section with
    `\notfromnotes{<book, chapter>}` from the gap's `book`, and write from that book. No `\src` is forced on
    such a topic. Never invent a notes citation.
- **PYQ text comes only from `work/<scope>/pyq_bank.json`,** copied verbatim. Never invent, merge or "improve"
  a past-paper question. A question you make up is labelled `Expected` or `Variant of <qid>`, never given a
  year.
- **Numericals are computed, not recalled.**
  - **Check script:** every numerical result you print (example, solution, short answer, variant, drill
    answer) has `work/<scope>/checks/<id>.py`, which prints the answer. Ids:
    - the question id
    - `<Cid>_variant`
    - `<Tid>_ex_<name>`
    - `mock_Q<n>`
    - `drill_<n>`
  - **Run it.** `metrics.py` runs every check with a 60 s timeout, and a crash is a hard-gate failure. The
    boxed answer must equal its output.
  - **Ambiguity** (1 KB = 1000 or 1024 B?): state the assumption in one line. If the other convention changes
    the result, give that result too.
- **Conventions.** Follow `work/<scope>/conventions.json` exactly, in text, figures, answers and checks. For an
  ambiguity it doesn't cover: choose, state it in an `examtip`, and list it in your report.
- **No unsupported statistics.** Any claim about papers ("asked every year", "12 of 20 marks") must be computed
  from `pyq_bank.json` or `important_questions.json`. Any claim about examiners ("examiners award ~40% for the
  diagram") is banned unless a paper or the notes say it.
- **Banned phrases** (lint rejects them): "similarly", "left as an exercise", "refer to previous".
- **Never inputs:** old v1 guides (`<SUBJ>/*Midsem.pdf`, `chapters*/`, `_extracted_corpus/`). Some contain
  fabricated questions.

## 2. Badges, receipts and links: never hand-type them
| need | write | never |
|---|---|---|
| a cluster's tier and P | `\clusterbadge{C05}` | `\tier{..}`, `\prob{..}`, `\ev{..}` typed by you |
| a topic's P | `\topicbadge{T07}` | `\prob{..}` |
| marks of a question | `\mks{2.5}` | `\marks` (a TeX primitive) |
| where a PYQ was asked | `\asked{2024 Q1(c), 2025 Q3(b)}` | |
| the question's image | `\receipt{<qid>}` directly under every verbatim PYQ in a PYQ chapter | |
| the one full solution of an idea | `\begin{solvedidea}{C05}{<task title>} ... \end{solvedidea}`, only in `atoms/solve/C05.tex` | a second full solution anywhere |
| point to that solution | `\seesolved{C05}` | re-solving it |
| point to a PYQ (guide or archive) | `\pyqsolved{<qid>}` | `p.\pageref{q:..}` typed by hand |
| a recall card | `\flashcard{front}{back}` | |

- **Badges are generated.** `score.py` regenerates `badges.tex` on every run, so the badges stay current;
  hand-typed `\prob`/`\tier` go stale and lint flags them.
- **Never in sectioning commands:** badges and `\mks` never go inside `\section{}`/`\chapter{}` titles. Put
  them on the line after.
- **Labels** (other agents link to them; spell them exactly):
  - `sec:<Tid>`: the topic section in its atom
  - `q:<qid>`: on each verbatim in-window PYQ in its paper chapter, and nowhere else
  - `iq:<Cid>`: each entry in `60_important_questions`
  - `solve:<Cid>`: set by `solvedidea`; never add it yourself
  - `fig:<name>`: your figures; shared figures use the names in `blueprint.json → figure_plan`
- **PYQ window.** Only questions from papers inside `blueprint.json → pyq_window` are ever printed, cited or
  linked. Out-of-window questions do not exist for writers (`out_of_window_in_chapters` is a hard gate).
- **Cross-links.** When you mention a question idea, link its solution once (`\seesolved{Cid}`) and every
  in-window PYQ of the cluster (from `question_ids` in `important_questions.json`), using `\pyqsolved{qid}`.
  - This works for archive papers too. `build.py` resolves cross-document references through
    `_xref_<job>.tex`, so an archive link prints "PYQ archive, <paper> <qno>, p. N", linked to the archive
    PDF.
  - A missing target is a hard error.
  - In a `--chapter`/`--atom` build, links to other files print "??". That is expected; the full build
    resolves them.
  - An `undefined_refs` count on the full build is a hard-gate failure. Link only labels that exist in the
    plan.

## 3. Length
- **Exam answers (the text a student writes)** follow `important_questions.json → exam_hall`: minutes per mark,
  and a word budget per marks value (≈ marks × min-per-mark × 20 words). Midsem is about 4.5 min per mark, so
  a 2.5-mark answer ≈ 225 words; endsem is about 3 min per mark.
  - The `solution` box (or `solvedidea` answer) holds at most that many words, plus the diagram the question
    needs.
  - Shape by marks:
    - **1 mark:** the fact, or one computation.
    - **2–3 marks:** definition, diagram or formula, then 3–5 keyword points, or a fully stepped numerical.
    - **4–5 marks:** intro, diagram, 5–8 points or a derivation, then a one-line conclusion.
    - **8–10 marks:** headings, two diagrams, an example, then pros/cons.
  - Put the understanding in the notes, not in the box.
- **Page budget for unit notes: `important_questions.json → targets.notes_pages[<unit>]` print pages,**
  figures, unit map and recap included. Your brief quotes it with its `why`. `build.py` prints the page count,
  and `over_budget_pages` uses this target: trim before you report.
  - **How the target is set:** score.py computes it from the unit's lectures and its share of the in-window
    PYQ marks: `lectures × clamp(1 + share/mean share, 1, 2) + 1`. That is 1–2 pages per lecture.
  - **Why:** a unit that carries many marks gets more room, and a rarely examined one gets less. This replaces
    the flat 1.2/1.8/1.5 pages-per-lecture rules.
  - **Inside the unit:** tier A/B topics take more of the budget; tier E topics take less.
- **Other budgets:**
  - a solve atom: ≤ 1 page per 2.5 marks, diagrams included
  - a short answer (`\seesolved` + new numbers): ≤ 6 lines
  - an older-paper (archive) chapter: ≤ 1 page per 10 marks
  - an important-question entry that is not a solve: ≤ ½ page
  - the important-questions chapter: exactly `targets.iq_clusters`
  - the cheatsheet: `targets.cheatsheet_pages`

  The `targets` are subject-specific; never apply another subject's sizes.

## 4. Visuals (mandatory, and the main quality lever)
- **Every topic gets the visual type `blueprint.json` assigns it (`topic.visual`).** Lint checks for it.
  | `visual` | the section must contain |
  |---|---|
  | `storyboard` | `\stepanim` or `\storyboard` with 3–6 frames, one per step that changes state |
  | `sequence` | a TikZ timing diagram (`lifeline`, `msg`/`msgok`/`msglost` styles) |
  | `block` | a TikZ block/architecture diagram (`blk`, `layerblk`) |
  | `fsm` | a TikZ state machine (`state` nodes) |
  | `tree` | a TikZ tree (`child`, `treenode`) |
  | `graph` | a TikZ graph with nodes and labelled edges (`circ`, `elabel`) |
  | `array` | a TikZ cell trace (`cell`, `cellhl`, `cellok`) |
  | `plot` | a `pgfplots` `axis` |
  | `pipeline` | a TikZ pipeline/Gantt grid |
  | `flowchart` | a TikZ flowchart (`term`, `decision`) |
  | `uml` | a TikZ UML/DFD/ER diagram |
  | `table` | a `tabularx`/`xltabular` comparison table with `\zebra` |
  | `figure` | `\figfromnotes` (photos, screenshots, dense plots only) |

  Add more visuals where they teach. **A table never counts as the visual of a topic with tier A/B clusters.**
- **Process topics** (`visual: storyboard`) need a storyboard that shows the mechanism step by step: each frame
  has a one-line note of what changed. `metrics.py` counts storyboards per process topic.
- **`stepanim` mechanics:** `\stepanim{N}{cols}{width}{caption}{body}`.
  - The body is one tikz body that uses `\f`, the frame number.
  - Start it with a fixed `\path[use as bounding box] ...` so the frames line up.
  - Reveal steps with `\ifnum\f>k ... \fi` or `\ifcase\f\or ... \fi`.
  - At most 2 frames per row (frame width ≥ 0.45\linewidth) unless the frames are thin strips.
  - The print and phone editions show the frames. The Interactive edition animates them and still prints the
    storyboard below.
- **The cookbook.** Start from the closest pattern in `_pipeline/latex/visual_cookbook.tex` and copy its
  *mechanics*:
  - the colours `hl ok bad info muted`
  - the node styles `blk circ cell msg state`...
  - `elabel` on every edge label, which masks the line

  Three things in the cookbook you must **not** copy:
  - its `[H]` placements: use `[!htbp]`
  - its `\tiny`: use at least `\scriptsize`
  - its "examiners award ~40%" line: an unsupported statistic
- **Figure ownership.** Draw a shared figure only if `figure_plan` names your atom as its `owner`; give it
  exactly that `\label{fig:...}`. Otherwise reference it with `\ref{fig:..}` on p.~`\pageref{fig:..}` and draw
  only what is new.
- **Placement:**
  - Figures and tables float `[!htbp]`. `[H]` and `\tiny` are lint errors.
  - Put `\needspace{8\baselineskip}` before a `question` box.
  - Inside boxes (`solution`, `solvedidea`, `answerplan` …) floats are illegal. Use `\stepanim*`,
    `\storyboard*` and `\captionof{figure}{...}`.
  - A storyboard taller than the page is a `float_too_large` hard-gate failure: use fewer rows or a smaller
    width.
- **Sizing:**
  - width ≤ `\linewidth` (the phone edition rescales to its `\linewidth`)
  - node distance ≥ 8 mm
  - labels horizontal and ≥ `\scriptsize`
  - long detail goes in the caption

## 5. Recall: flashcards
Every topic atom ends with **2–5 `\flashcard{front}{back}`** for its definitions, formulas and key facts.
- The front is a question that the back answers in ≤ 25 words.
- They print nothing; `flashcards.py` builds the Anki deck and `web.py` the self-test pages.
- Never put a figure or `\ref` inside a flashcard.

## 6. LaTeX vocabulary
- **Allowed:** everything in `studyguide.sty` (read its comments), plus amsmath, tikz, pgfplots, tabularx,
  booktabs, enumitem, multicol, siunitx, listings and xltabular.
- **Boxes:** `definitionbox`, `keyconceptbox`, `intuitionbox`, `formulabox`, `algorithmbox`, `warningbox`,
  `mnemonicbox`, `examtip`, `answerplan`, `checkpoint`, `question{title}{marks}[tags]`, `solution`,
  `solvedidea{Cid}{title}`.
- **Inline:** `\answer{..}`, `\keyword{..}`, `\stepno{n}`, `\src{..}`, plus the badge and link commands in §2.
- **Long tables** (> ⅓ page): `xltabular`. Long equations: `aligned`/`split`. Wide tables: `tabularx` with `Y`
  columns.
- **Escaping:** escape `& % $ # _ { } ~ ^` in text. Unicode arrows, ≤ ≥ × and Greek letters are mapped, but in
  maths use the macros.
- **Traps that pass your atom build but break the phone edition or the web export** (2026-11-08, four subjects):
  - Never put `\answer{..}` inside a `\caption` (fatal in the phone build). Write the answer as plain text there.
  - Atom-local macros use `\providecommand`, never `\newcommand`: two atoms defining the same name break the web
    export.
  - No `\columnbreak` / `multicols` inside boxes: use two `minipage`s (the web export renders a box on its own).
  - No `\textcolor` inside TikZ node text: use `text=<colour>` on the node, or bold (a CN phone build crashed).
  - Long inline maths and unbreakable tokens overflow the 94 mm phone column: split the formula into two `$..$`
    or add `\allowbreak`; keep storyboard frames ≤ 0.45`\linewidth`; narrow `tabularx` fixed columns.
  - Build your atoms with `--phone` too before you report.

## 7. Self-check loop (before you report; cheap by design, see `docs/COST.md`)
1. **Write all your files first, then build them in ONE call,** print and phone:
   `py _pipeline/tools/build.py <SUBJ> --scope <scope> --atom notes/T01,notes/T02,solve/C05 --both --render`
   and once at the end each chapter: `--chapter <stem> --render`.
2. **Fix** every `LINT`, `ERROR` and `LAYOUT` line until each atom prints `OK`; rebuild only the failing atoms.
   - Undefined references to labels inside your own file are errors. References to other files are expected
     warnings.
3. **`LAYOUT p<N> <kind>` lines come from `layout_check.py`,** which reads every page: `outside` (past the margin),
   `overlap` (text on text), `on_line` (a line through a label), `tiny` (a shrunk figure). Contact sheets are drawn
   **only for flagged pages** (`FLAGGED`/`SHEETS`). Look at a sheet only for a flagged page, once, then fix. Do not
   render or read images of unflagged pages, and do not re-read PYQ page images (the bank is gated). Misaligned
   storyboard frames and half-empty pages are reported as `LAYOUT` too.
4. **Run** every check script you wrote, and compare its output with the printed answer.
5. **Report** (≤ 12 lines):
   - files written, with pages vs budget
   - visuals: the count, storyboards, the `topic.visual` met per topic
   - solves written (Cids) and PYQs printed (qids)
   - check scripts
   - flashcards per topic
   - assumptions and new conventions
   - anything you could not verify
