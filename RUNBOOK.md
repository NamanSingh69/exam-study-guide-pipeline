# RUNBOOK: generate a subject's guide at the lowest usage cost

This is the only file a fresh session (or another agent) must read to run the pipeline. `prompts/00_orchestrator.md`
is the reference for edge cases (zero-paper subjects, split mode, post-exam scoring, no-subagent runners).

**Trigger:** "generate the <midsem|endsem> notes for <SUBJ>[, <SUBJ>...]". Hints ("teacher stressed X") go word for
word into `<SUBJ>/work/<scope>/class_signal.json`; never ask for them.

## Session rules (they decide the cost)
Measured on the 2026-11 runs (`docs/COST.md`): the usage limit is spent on **context x turns**, and most of it went to
(1) writers reading images of their own pages, (2) writers carrying the whole contract, JSONs and corpus, and
(3) a 1,200-turn main session carrying everything. So:
1. **One batch per session:** 2–3 subjects. Run `/compact` after each subject. The ledger makes a fresh session
   resume exactly (`state.py <S> --scope <sc> next`).
2. **The main session never reads** logs, PDFs, corpus files or agent transcripts. It runs `run_subject.py` (≤ 15 lines
   per phase), `pack.py`, and reads agent reports (≤ 12 lines each).
3. **Agents get a pack, not a reading list.** `pack.py` writes one capped file per writer: the writer card,
   assignment, targets, conventions and the cited corpus pages.
4. **No image reads unless a check flagged the page.** `build.py --render` runs `layout_check.py` and draws contact
   sheets only for flagged pages (about 9% of pages). PYQ page images are read only by the transcriber.
5. **Batched builds:** writers build all their atoms in one call (`--atom a,b,c --render`; print only, no phone edition since 2026-11-10).
6. **Model tiers.** Pass `model:` explicitly on every Agent call, or use the project agents in
   `Study Prep/.claude/agents/` (copies in `_pipeline/agents/`): `pyq-transcriber` (sonnet), `guide-fixer` (sonnet),
   `pipeline-checker` (haiku). Do not set `CLAUDE_CODE_SUBAGENT_MODEL`: it overrides every agent's own model.
   Do not delegate a job of a few tool calls: each agent starts from scratch and costs more than doing it.

| model | agents | why it is safe |
|---|---|---|
| `haiku` | file/log searches, "did X build" checks, smoke tests | a script checks the result |
| `sonnet` | PYQ transcriber (`verify_pyqs` gates it), writers (A/B 2026-11-10: Sonnet won 4-1-1), fixer (`metrics` + `layout_check` gate it), scaffolding | each output has a gate or the review |
| main model | blueprint/merge (clustering is judgment), reviewer | judgment is the product |

7. **Never** publish, upload, post or message anyone; the user does that. Commits to `_pipeline` carry no AI
   attribution trailer. `_publish/` belongs to another session.

## Per subject (lean mode; about 6 agents)
```
py _pipeline/tools/state.py <S> --scope <sc> next                  # resume point; skip every step already ok
py _pipeline/tools/run_subject.py <S> --scope <sc> --phase ingest  # exit 1 = ingest errors: stop and report
```
1. **Transcribe** (Sonnet, one agent, only if the bank lacks papers; at most 5 papers in the window):
   "Read `_pipeline/prompts/01a_transcribe_pyqs.md`. Subject <S>, scope <sc>, papers <slugs>. Report ≤ 8 lines."
2. **Blueprint + merge** (main model, one agent, `prompts/01_blueprint.md` Part 1, then Part 2 via SendMessage).
   An endsem after a midsem reuses the midsem blueprint (`00_orchestrator.md` "Endsem reuse").
3. `py _pipeline/tools/run_subject.py <S> --scope <sc> --phase gate` (receipts → verify_pyqs `RESULT PASS` → score).
   A bank that passed is frozen: new papers are only added.
4. **Assignments:** `py _pipeline/tools/assign.py <S> --scope <sc>` writes `assignments.json` (Phase C: `writers`,
   `atoms`, `chapters`, `solve_owners`, `figures`, `"one_pdf": true`). The lean split: notes-A/notes-B (contiguous
   units, split only above 24 topics), pyq-full (the 3 newest in-window papers of the scope's exam + important
   questions + mock), pyq-older-A/B (≤ 10 older papers each). Add `"updates_url"` if the user shared a folder.
5. **Packs and writers** (Sonnet, all writers in ONE message): `py _pipeline/tools/pack.py <S> --scope <sc> --writer <id>`
   for each writer in `assignments.json`.
   - Notes writer: "Read `<S>/work/<sc>/packs/<id>.md` (its WRITER CARD is binding) and `_pipeline/prompts/02_unit_notes.md`.
     Write every notes atom and unit chapter it lists (the last notes writer also does the Q1 drill and night-before
     sheet, `07_recall.md`, and the cheatsheet, `05_cheatsheet.md`). Report ≤ 12 lines."
   - PYQ writer: "Read `<S>/work/<sc>/packs/<id>.md` (WRITER CARD binding) and `_pipeline/prompts/03_pyq_solutions.md`
     (pyq-full also `04_important_questions.md`). Write every solve atom and chapter it lists. Report ≤ 12 lines."
   - Merge reported conventions into `conventions.json`; one-line fixes via SendMessage (the writer keeps its context).
   - Copy each writer's doubts and assumptions into `work/<sc>/reviews/writer_notes.md`: the reviewer starts there.
6. `py _pipeline/tools/run_subject.py <S> --scope <sc> --phase post` (guide, flashcards, web, metrics, layout; `--phone` only if the user asks for a phone edition
   summary). Every hard gate must be 0 and `pyq_gate` 1.
7. **Review** (main model, one agent, wrote nothing): `prompts/06_review.md` + `08_answerability.md`, planted
   defects as in `00_orchestrator.md` Phase F. It looks at the flagged pages plus a sample of 8 figure pages.
8. **Fix** (Sonnet, one agent, at most 2 rounds): the metrics lines, `LAYOUT` lines and the review's criticals and
   majors. Then `--phase post` again.
9. **Report** (≤ 12 lines per subject): pages, gates, tracked metrics (`answers_vs_checks`, `over_budget_pages`,
   `iq_count_vs_target`), layout flags left, review score, what is unverified. Then
   `py _pipeline/tools/usage_report.py --since <today>` and add a row to `docs/COST.md`.

## Writer A/B (done 2026-11-10, ML endsem U7)
Sonnet and the main model each wrote ML U7 (T33-T38); `pairs.py` made 6 blind pairs; the main-model reviewer judged
them (`ML/work/endsem/reviews/ab/verdict.json`): Sonnet 4, main 1, tie 1; 3 small errors each, no wrong final
answer. Writers run on Sonnet. Re-run the A/B (same recipe) if review scores drop on Sonnet-written subjects.

## Gates (never weakened)
- PYQs are never invented: the bank is transcribed from page images; `verify_pyqs.py` must print `RESULT PASS`.
- `metrics.py` hard gates must all be 0 and `pyq_gate` must be 1: `ingest_errors`, `undefined_refs`, `tex_errors`,
  `float_too_large`, `missing_chapters`, `missing_receipts`, `checks_failed`, `stale_pdf`, `cross_refs_unresolved`,
  `out_of_window_in_chapters`, `internal_leaks`.
- Usage-limit stop: launch nothing new, set unfinished items back to `todo --note "usage limit"`, give the user the
  same trigger sentence to resume.

## Changing the pipeline
AIDE² node per change (`aide2_cycle.py begin|guard|record`), RED test first, `py _pipeline/tests/run_all.py` all PASS
(local CI is the gate). Lessons go to the shared memory vault (project `study-prep`).
