# Stage 2b: PYQ chapters and their solve atoms (one agent per full-solution paper, or per ≤ 6 older papers)

Read `_pipeline/prompts/_writer_contract.md` first. It is binding.

**In-window papers only.** You are only ever assigned papers inside `blueprint.json → pyq_window`. Never print,
cite or link a question from a paper outside it (`out_of_window_in_chapters` is a hard gate).

**Assignment** (from `assignments.json`): subject `<SUBJ>`, scope `<scope>`, and:
- **your papers**, each with its stem `7NN_pyq_<paper id lowercase>` and its kind:
  - `pyq_full`: one of the latest 3 relevant papers; built into the main guide
  - `pyq_older`: an older in-window paper; built into the separate `_PYQ_Archive.pdf` by
    `build.py --archive`
- **the solve atoms `atoms/solve/<Cid>.tex` you own,** with their anchor question ids:
  - a `pyq_full` agent owns the clusters anchored in its paper
  - an older-PYQ agent owns the older-paper-only clusters anchored in *its* papers
- **the first older-PYQ agent only:** the wrapper `chapters/62_older_ideas.tex`

Write exactly those files.

**Read:**
- `work/<scope>/pyq_bank.json`: your papers' questions. It is the only source of question text.
- `work/pyq_pages/<slug>_p*.png`: ONLY for a question whose text says it has a figure or table (the bank text is
  gated and verbatim; do not re-read page images to check it)
- `work/<scope>/receipts/receipts.json`: every question has a crop
- `work/<scope>/blueprint.json` (pattern, topics, `pyq_window`)
- `important_questions.json` (`clusters`, `exam_hall`)
- `work/<scope>/assignments.json` (`solve_owners`, `full_papers`)
- `conventions.json`, and the corpus pages of each question's topic, so you answer in the instructor's terms

## Chapter skeleton (both kinds)
```
\chapter{<Year> <Midsem|Endsem> paper<, spring> — <solutions | questions>}
metadata line: full marks, duration, instructions (verbatim from the paper), \src{<slug> p1}
one short table: Q | topic | marks | \clusterbadge{<Cid>}   (the paper's shape)
for each in-scope sub-part, in paper order:
  \needspace{8\baselineskip}
  \begin{question}{<Year> <Exam> Q<qno>}{<marks>}[\clusterbadge{<Cid>}]  <verbatim text>  \end{question}
  \label{q:<qid>}
  \receipt{<qid>}
  <answer part: see below>
```
- **`in_scope: false` questions:**
  - in a paper of the scope's own exam type: verbatim text, `\receipt` and one line, "Out of <scope> scope
    (Unit X)"; not solved
  - in an endsem paper inside a midsem run: left out, with one count line under the table
- **"OR" alternatives:** both get the treatment their cluster's owner rule gives.
- **Illegible or ambiguous bank text:** answer under a clearly stated interpretation. Never quietly change the
  question.

## The answer part
1. **A `pyq_full` paper, where you own this cluster's solve atom and this question is its anchor:** write
   `atoms/solve/<Cid>.tex` and put `\input{atoms/solve/<Cid>}` right after the receipt. The atom:
   ```
   \begin{solvedidea}{<Cid>}{<cluster label, as a task>}
     the exam-ready answer for THIS question's text, within the exam_hall word budget for its marks:
     numericals: Given -> Find -> Formula (\src) -> substituted steps (align*) -> \answer{} with units
     theory: definition -> diagram -> keyword points -> one-line conclusion
     "draw" / "with a neat diagram": the diagram comes first and is mandatory
     ≤ 4 lines after it: "why / common mistake" (examtip), and \S\ref{sec:<Tid>} for the notes
   \end{solvedidea}
   ```
2. **Any other question,** in either kind of chapter:
   - `\seesolved{<Cid>}`
   - for a numerical: a short answer of ≤ 6 lines, with the substituted computation for *these* numbers and
     `\answer{}`
   - for theory: 1–3 lines on what this wording asks beyond the solved idea, if anything

   Never write a second full solution: `dup_solves` counts them.
3. **Older-paper-only solve atoms you own** (anchored in one of your `pyq_older` papers):
   - Write them exactly as in rule 1, solving the anchor's verbatim text.
   - Do **not** `\input` them in the archive chapter: they are `\input` once in `62_older_ideas`, in the main
     guide. The archive question uses rule 2.
4. **`62_older_ideas.tex`** (first older-PYQ agent only):
   - `\chapter{Solved ideas from older papers}`, a 2-line intro ("each idea solved once; the original papers
     are in the PYQ Archive"), then one `\input{atoms/solve/<Cid>}` per cluster that
     `assignments.json → solve_owners` places in `62_older_ideas`, in syllabus order.
   - The other older-PYQ agents' atoms are included too.
   - The chapter's `--chapter` build passes only once all those atoms exist.

**Checks.** Every numerical question gets `work/<scope>/checks/<qid>.py`, which prints the final answer. This
includes archive questions and short answers: `numericals_without_check` is counted from the bank. The printed
answer must match the check.

**Self-check:**
- all your solve atoms in ONE call: `--atom solve/C01,solve/C05,... --both --render`
- each `pyq_full` chapter, and `62_older_ideas`: `--chapter <stem> --render`
- the printed `\answer{}` under each `\label{q:<qid>}` must contain the number its check prints
  (`answers_vs_checks` in metrics)
- `pyq_older` chapters: check them with `--chapter <stem> --render` too (the orchestrator builds the archive
  with `--archive`)

Then run the contract's loop. A missing receipt prints a red box and fails `missing_receipts`: report it, don't
hide it. Report per chapter: questions printed, solves written, short answers, checks, pages vs budget.
