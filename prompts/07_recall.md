# Stage 2d: Recall outputs (one agent per subject, after every unit writer has finished)

Read `_pipeline/prompts/_writer_contract.md` first. It is binding.

Rereading is the weakest way to study; retrieval practice is among the strongest. You turn material that
already exists into self-tests. You write no new teaching content.

**Assignment:** subject `<SUBJ>`, scope `<scope>`. Write:
- `chapters/65_q1_drill.tex`
- `atoms/recall/night_before.tex` (the cheatsheet `\input`s it)
- extra `\flashcard` lines appended to the topic atoms (only the top-up pass below)

**Read:**
- `important_questions.json`:
  - `targets.q1_drill` (the newest in-window one-mark PYQ of each idea and the predicted item count, quoted in your brief)
  - `q1_drill` (the predicted cluster ids)
  - `clusters`, `exam_hall`
- `pyq_bank.json`: the verbatim text of every drill question
- every `atoms/notes/*.tex`
- `assignments.json` and `conventions.json`

## 1. `65_q1_drill.tex`: Q1 rapid-fire drill
Q1 is compulsory: about 25% of midsem marks and 20% of endsem marks.
```
\chapter{Q1 rapid-fire drill}\label{ch:q1drill}
  2-line intro: cover the answers, answer each in under exam_hall minutes per mark, then check at the end
  \section*{Past Q1 questions}   every IN-WINDOW one-mark PYQ in targets.q1_drill, newest paper first:
     \textbf{D<n>.} <verbatim bank text>  \asked{<year Q1(x)>}  \clusterbadge{<Cid>}
  \section*{Predicted}   exactly the predicted count in targets.q1_drill (= min(30, 2 x one-mark clusters)):
     new one-mark questions in the forms of the predicted clusters, marked "Expected", \clusterbadge{<Cid>}
  \clearpage
  \section*{Answers}   D<n>: the answer in 1–3 lines (the fact, or the computation and \answer{}), then
     \pyqsolved{<qid>} for every past question (guide or archive), \seesolved{<Cid>} where a full
     solution exists
```
- **Window:** never include a one-mark PYQ from a paper outside `blueprint.json → pyq_window`, even if an old
  `q1_drill` list contains it. `out_of_window_in_chapters` is a hard gate.
- **Labels:** none on the drill items. `q:<qid>` belongs to the paper chapters.
- **Checks:** every numerical answer gets `checks/drill_<n>.py`, and agrees with the paper chapter's answer
  for the same qid.
- **Zero papers:** "Predicted" only, with a note "no past papers available".

## 2. Flashcard top-up pass
- **Counting:**
  1. Run `py _pipeline/tools/flashcards.py <SUBJ> --scope <scope>`.
  2. Read the cards it collected per topic.
- **Topics with fewer than 2 cards,** or missing a card for a formula in their `formulabox`: append
  `\flashcard{front}{back}` lines at the end of that topic's atom with the Edit tool. Change nothing else in
  the atom.
- **Cap:** 5 per topic.
- **Card rules:** fronts are questions, backs ≤ 25 words, in the atom's notation, no `\ref`.
- **Afterwards:** rebuild each edited atom (`--atom notes/<Tid>`) and re-run `flashcards.py`.

## 3. `atoms/recall/night_before.tex`: the night-before sheet
It is printed at the end of the cheatsheet, in portrait or landscape as it falls. Write it as a body fragment:
no `\chapter`; it starts with `\section*`.
```
\section*{Night before: questions}   one numbered line per tier A and B cluster (from the plans): a
   question in the cluster's form, answerable in ≤ 3 lines; then the 10 most-tested definitions and
   formulas as questions. 25–40 questions in total, grouped by unit
\clearpage
\section*{Night before: answers}   the same numbers, each answer ≤ 2 lines
```
- **Format:** two-column `multicols` is fine. No floats, no badges.
- **Page order:** questions on one side, answers on the next page.

## Self-check
- `py _pipeline/tools/build.py <SUBJ> --scope <scope> --chapter 65_q1_drill --render`
- `--atom notes/<Tid>` for each atom you edited
- the night-before sheet is checked by the cheatsheet build, which runs after you: make sure it compiles on
  its own inside a `\begin{document}` body (no undefined macros)

**Report:** drill items (past / predicted), cards added per topic, the total card count, the night-before
question count.
