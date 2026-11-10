# Stage 2a: Unit notes as topic atoms (one agent per unit, run in parallel)

Read `_pipeline/prompts/_writer_contract.md` first. It is binding.

**Assignment** (from `assignments.json`): subject `<SUBJ>`, scope `<scope>`, unit `<UNIT_ID>`, your topic ids,
and whether you own the unit wrapper `chapters/<stem>.tex`. A large unit is split over two writers; only one
owns the wrapper. Write:
- `atoms/notes/<Tid>.tex` for each of your topics
- the wrapper, if you own it

**Skip:** topics whose ledger item `atom notes/<Tid>` is already `ok`, for example those reused from midsem.
Do not rewrite them.

**Read:**
- `work/<scope>/blueprint.json`: your topics, their `sources`, `origin`, `visual`, `coverage_gaps`, and the
  `figure_plan` entries you own or use
- the source pages of each topic in `work/corpus/` (the `__vision_` files for POOR scans), and
  `work/figures/src/` where a diagram matters
- `work/<scope>/important_questions.json`: `clusters` (tier, `question_ids`) and `exam_hall`
- the in-window `pyq_bank.json` questions of your topics (`blueprint.json → pyq_window`), to know the
  question *forms*; you do not solve them
- `work/<scope>/assignments.json → solve_owners` (the `\seesolved` targets) and `conventions.json`
- `_pipeline/latex/visual_cookbook.tex`, with the contract's three exceptions

## The topic atom `atoms/notes/<Tid>.tex`
```
\section{<Topic title>}\label{sec:<Tid>}
\topicbadge{<Tid>} \asked{<every year+qno of this topic's IN-WINDOW PYQs, or "not asked in <from>-<to>">}
[\notfromnotes{<book, chapter>}   only for an unfillable coverage gap]
intuitionbox: what problem it solves, an analogy, 2–4 sentences
definitionbox / formal content in the instructor's notation, with \src{...}
how it works: numbered steps + the blueprint's VISUAL (a storyboard for every process topic)
formulabox: each formula, every symbol's meaning and units, when to use it
worked example: the instructor's OWN example from the notes (its numbers), fully stepped, \answer{},
  with checks/<Tid>_ex_<name>.py. With no example in the notes, write one in the style of the PYQs
  (never a PYQ itself)
warningbox: the 1–3 mistakes students actually make here
answerplan: how to write this topic's typical question for full marks: structure, the diagram to draw,
  the keywords examiners look for
question forms: one line per cluster of this topic: \clusterbadge{<Cid>} <cluster label>:
  \seesolved{<Cid>} if it has a solve; \pyqsolved{<qid>} for each of its in-window PYQs (guide or
  archive)
checkpoint: 2–3 quick self-test questions (answers in the unit recap)
2–5 \flashcard{..}{..}
```

## The unit wrapper `chapters/<stem>.tex` (if you own it)
```
\chapter{<Unit title>}
Unit map (≤ 1 page): a TikZ concept map of the topics, or a table of topic | \topicbadge | asked in |
  must-know items, in syllabus order, with \S\ref{sec:<Tid>}
\input{atoms/notes/<Tid>}   one line per topic of the unit, in blueprint order (the other writer's too)
\section*{Unit recap}  ≤ 12 bullets: the exam-critical facts and formulas
\section*{Self-check answers}  the answers to every checkpoint of the unit
```
If another writer owns some of this unit's topics, still `\input` them. Your `--chapter` build passes once
their atoms exist; until then it fails on the missing files.

## Depth rules
- **Depth follows the planner's tiers** (`important_questions.json → clusters[].tier`: A = 3 h plan,
  B = 6 h, C = 12 h, D = wildcard, E = the rest).
  - **A topic with A/B clusters** gets the full treatment, and every *form* its PYQs take is taught (worked
    once in the notes' own example, or pointed to with `\seesolved`).
  - **Topics with only D/E clusters** get definition, visual, key points and flashcards.
- **Coverage:** cover every topic in your assignment, plus anything the notes teach that a question could
  reasonably target. If the notes include a derivation, include every step.
- **No PYQ solving here.** The PYQ chapters and solve atoms do it once. Link them with `\seesolved` and
  `\pyqsolved`.
- **Budget:** `targets.notes_pages[<UNIT_ID>]` print pages for the whole unit, quoted in your brief (the
  contract, §3).
  - It scales with the unit's lectures and its share of the in-window PYQ marks, so a heavily examined unit
    gets up to 2 pages per lecture and a rarely examined one about 1.
  - Split the budget across your topics by tier.
  - Stop when the content is covered; never pad up to the target.

Then run the self-check loop from the contract: `--atom notes/<Tid>` for each atom, and `--chapter <stem>` if
you own the wrapper. Report.
