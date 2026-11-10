# Stage 1: Blueprint, merge and clustering (one agent per subject, in two parts)

You write JSON only, no LaTeX, in exactly the shapes given in `_pipeline/schemas.md`. You run in two parts:
- **Part 1:** starts in parallel with the PYQ transcribers (`01a_transcribe_pyqs.md`).
- **Part 2:** begins when the orchestrator messages you. By then every `pyq_bank.part_<paper>.json` exists.

**Folder:** `<SUBJ>/work/<scope>/` (create it). Read `<SUBJ>/work/corpus/INDEX.md` first.

**Trust order of sources:**
1. instructor notes (`origin: instructor` in INDEX/manifest)
2. gap-fill notes (`origin: gapfill:<desc>`)
3. a textbook

Old v1 guides (`<SUBJ>/*Midsem.pdf`, `chapters*/`, `_extracted_corpus/`) are never inputs.

**Endsem with `work/midsem/blueprint.json` present:** start from a copy of it. Keep every unit, topic and
cluster id for shared units. Continue the numbering for new ones. Re-decide only `in_scope`, `chapter`,
`visual` (for new topics) and `exam_pattern`.

## Part 1: scope (write `blueprint.json` without bank-dependent fields)
1. **Units and topics.** Read every syllabus/lesson-plan file.
   - **If `Syllabus/` is empty,** build the unit list from these, in order of trust, then set `cutoff` and add
     a warning saying which you used:
     1. a handout or course plan in `Notes/`
     2. the endsem papers (they span the syllabus)
     3. the structure of the notes
   - **Order:** units and topics in lesson-plan order.
   - **All units, including out-of-scope ones,** get topics: the gate checks every banked question's topic,
     and endsem papers hold out-of-scope questions.
   - **Lectures** come from the plan. Spread a unit's total over its topics when only totals are given, and
     say so in `notes`. Without a plan, estimate from the notes' page share and say so.
   - **Midsem cutoff:** the lesson plan's mid-semester boundary. With none stated, use the topics the midsem
     papers test plus the lectures before them. Write the rule into `cutoff`. Endsem: everything is in scope.
   - **Granularity:** one topic ≈ one examinable sub-area of 0.5–2 lectures; usually 3–8 per unit.
   - **`sources`:** corpus slug + page ranges, for every topic. Grep the corpus.
   - **`origin`:** the best source's origin: `instructor`, `gapfill` or `none`.
   - **`senior_imp: true`** when a seniors' "imp topics/questions" document lists the topic. Recognise those
     documents by content; list them in `imp_docs`.
   - **`chapter`:** in-scope units get `3N_<short_name>` (30_, 31_ … in syllabus order); out-of-scope units
     get `""`.
   - **`code_aliases`:** every other code of this course seen on papers or plans (e.g. IT-3005 = CS30003).
2. **Visual type per topic.** Set `topic.visual` to the visual that teaches this topic best. Vocabulary
   (also in `schemas.md`):
   `storyboard | sequence | block | fsm | tree | graph | array | plot | pipeline | flowchart | uml | table | figure`.
   - **Use `storyboard`** for every process topic: a protocol, algorithm or mechanism with ≥ 3 steps over
     time (e.g. stop-and-wait, GBN, SR, the handshake, teardown, slow start, Dijkstra, Tomasulo, Lamport
     clocks, backprop).
   - **`table` is never the visual of a topic with tier A/B clusters.** Tiers aren't known yet, so use `table`
     only for pure comparison topics with little lecture time.
   - **`figure`** (copying a figure from the notes) is only for photos, screenshots and dense plots.
3. **`figure_plan`.** List the figures more than one topic will need: windows, header layouts, the stack, a
   reference architecture. Give each one owner topic. Format: `fig:<Tid>-<short>`, an owner, a one-line
   `desc` and `used_by`.
   - The owner draws the figure; every other writer references it. Writers run in parallel and cannot see
     each other's figures, so anything shared must be listed here.
   - Figures used by one topic only are not listed.
4. **Source confidence per in-scope unit:** `units[].source_confidence = {"level": "high|medium|low", "why": "..."}`.
   - **high:** instructor notes cover every topic, with legible text.
   - **medium:** some topics come only from gap-fill notes, or from POOR scans transcribed by vision.
   - **low:** at least one `unfillable` gap, or most pages are illegible.
5. **Exam pattern.** Read the header of the newest paper image. Fill `exam_pattern`:
   - full marks, duration, structure, the compulsory questions, `choose`
   - `source` = `<slug> p1`

   If the years differ, use the newest and add a warning. **Zero papers on disk:** see "Weak inputs" below.

   **PYQ window.** Start from your subject's entry in `_pipeline/pyq_windows.json`, the lead's suggestion
   computed from the INDEX paper years. Treat it as a draft:
   - **Part 1:** check it against the INDEX years and the syllabus.
   - **Part 2:** confirm or change it once the transcribed headers show the course codes.

   Record the final `pyq_window = {"from", "to", "years", "why"}` in `blueprint.json`, and say in `why` whether
   you kept or changed the suggestion. The rules:
   - **Default:** the latest 5 calendar years that have papers.
   - **Start later** (keeping at least 3 years) when the syllabus or course code changed inside the window:
     a new lesson plan with different units, or a code change such as IT-3005 → CS30003 that came with new
     content. The window starts at the change.
   - **Extend back** (up to 5 years) only if the scope's exam type would otherwise have fewer than 3 relevant
     papers.
   - **`why`:** one sentence naming the evidence, e.g. "syllabus revised 2022 (new lesson plan drops Unit 5);
     2022-2026 gives 4 midsem papers".

   Papers outside the window are still transcribed, banked, gated and given receipts, so a later endsem run
   or a post-exam backtest can use them. score.py gives them weight 0 ("outside window"), and no chapter, drill
   or archive prints them.
6. **Coverage gaps.** Add an entry to `coverage_gaps` for every in-scope topic whose `sources` is empty, or
   whose notes give only a one-line mention. Use `status: "open"`.
   - The orchestrator tries to fetch notes and messages you to update `sources`, `origin` and `status`
     (`filled` + `filled_by`).
   - If nothing can be fetched: `status: "unfillable"` and `book`, the textbook and chapter to write from
     (e.g. "Hennessy & Patterson 6e, ch. 3.4"). Writers put a `\notfromnotes{<book>}` banner on such topics.
   - Never invent notes.
7. **Report to the orchestrator** (≤ 10 lines): units/topics in scope with the cutoff rule, the pattern, the `pyq_window` and its `why`,
   `figure_plan` size, coverage gaps, warnings. Then wait for Part 2.

## Part 2: merge and cluster (write `pyq_bank.json`, finish `blueprint.json`)
1. **Merge.** Read every `pyq_bank.part_<paper>.json`.
   - **New bank:** copy each part's `paper` and `questions` into `pyq_bank.json`.
   - **A bank that already passed the gate:** extend it only. Append the new papers and their questions. Never
     change an existing paper, question or cluster id. Never edit an existing question's text unless the
     orchestrator forwards a gate fix.
   - **On "re-apply the changed part files":** copy only `text`, `marks`, `ocr_fixes`, `verified` and
     `receipt` from the changed parts. Keep `topic`/`cluster`.
   - **Duplicates:** the same paper scanned twice, or a set file with the same set code. Bank it once and list
     the extra file in `warnings`.
   - **A paper from another course** filed here is not banked; list it in `warnings`.
2. **Per paper:**
   - **`coverage`:** the unit ids the paper examines. A midsem paper covers the midsem units of its year's
     plan; an endsem paper covers the whole syllabus as mapped. score.py counts a paper for a cluster only if
     `coverage` holds that cluster's unit, so this is the per-cluster denominator. Get it right.
   - **`weight`:**
     - 1 for this course, including alias codes
     - 0.5 for a similar course (an open elective "Introduction to SE", a 7th-sem variant), banking only its
       questions on our topics
     - 0 for a paper kept for the record only

     Exam type (midsem vs endsem) is not a weight: score.py handles it. Neither is the window: never set an
     out-of-window paper's weight to 0 yourself, because score.py applies `pyq_window`.
   - **Revisit `pyq_window`** now that the papers are read. A header showing a changed code or pattern can move
     `from`; keep `why` current.
3. **Per question:** set `topic`, `cluster` and `in_scope` (against the cutoff). Endsem papers in a midsem run:
   their midsem-unit questions are `in_scope: true`.
4. **Clusters.** A cluster is one examinable idea: the same skill with different numbers or wording, across
   years.
   - **Label:** name it as a task ("Count GBN transmissions with every k-th frame lost"), not a chapter
     title.
   - **Unasked clusters:** add them for topics with heavy lecture time or a seniors' listing that were never
     asked (the wildcards).
   - **`effort_min`** for an average student starting from the notes:
     - 10–20 for a definition or difference
     - 20–40 for a numerical type
     - 40–90 for a long derivation or algorithm
   - **`imp_list`:** the seniors' expected questions (not past papers), each linked to a cluster.
5. **Class signal.** If `class_signal.json` exists, fill each signal's `topics`/`clusters` with the ids it
   refers to. Never change its `text`.
6. **Conventions.** Write `conventions.json`: one decision for every ambiguity the papers or notes expose, so
   parallel writers agree. Examples:
   - Reno cwnd after 3 duplicate ACKs
   - 1 KB = 1000 or 1024 B
   - whether "every k-th packet lost" counts retransmissions
   - the log base in complexity
   - the sign convention for demand elasticity

   Shape: `[{"id","decision","source","alternative"}]`. Take the decision from the instructor's notes when
   they state one. Otherwise take it from a named textbook, and say which.
7. **Endsem conventions:** start from a copy of `work/midsem/conventions.json`. Add new entries; never change
   an existing decision silently. A change needs a warning, because reused atoms follow the old one.
8. **Gate.** The orchestrator runs `receipts.py` and `verify_pyqs.py`. When it forwards blocking lines that are
   about clustering (unknown topic or cluster), fix them. Text and receipt problems go back to the
   transcribers.
9. **Report** (≤ 12 lines):
   - papers banked, with question counts and `coverage`
   - clusters: total, unasked
   - warnings
   - conventions written
   - class-signal mapping

## Weak inputs
- **Zero papers.**
  - **Pattern:** `exam_pattern.assumed: true`, with `source` naming where the pattern comes from. In order of
    preference:
    1. the pattern printed in the lesson plan or handout
    2. the pattern of the same school's papers for another subject of the same semester and exam (name the
       subject and paper id, e.g. "CN ES2025, same school and semester")
  - **Bank:** `{"no_papers": true, "papers": [], "questions": [], "clusters": [...], "imp_list": [...]}`.
    The clusters come from the syllabus wording and the seniors' lists.
  - **Warnings** must say this.
- **POOR scans that 01b agents marked illegible:** keep the pages in `sources`, set the unit's
  `source_confidence` to at most `medium`, and add a warning.
- **Gap-fill notes** (`origin: gapfill`) are allowed as `sources`. They rank below instructor notes for
  notation.
