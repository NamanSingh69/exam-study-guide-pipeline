# Writer card (the binding rules in 1 page; `_writer_contract.md` is the full text, read a section only when needed)

You write part of an exam study guide for a KIIT B.Tech student who reads under time pressure. Optimise for
**marks per minute of reading**.

**Files.** Write only the files your pack assigns, with the Write/Edit tools (never heredocs, sed or echo):
`atoms/notes/<Tid>.tex` = one `\section{..}\label{sec:<Tid>}`; `atoms/solve/<Cid>.tex` = one `solvedidea`;
`chapters/<stem>.tex` = `\chapter{..}` + glue + `\input{atoms/notes/T07}`. Bare bodies: no preamble, packages or
colours. Never rename a stem or edit another writer's file.

**Truth.**
- The instructor's notes define content, notation and names (gap-fill notes rank below, textbooks last; when they
  differ, follow the higher source and add a one-line `examtip`). Cite `\src{<slug> p<N>}` once per section at
  least. Your pack holds the cited pages; open `work/corpus/` or `note_pages/` only for a page the pack lacks.
- PYQ text comes only from `pyq_bank.json`, verbatim (the pack quotes it). Invented questions say `Expected` or
  `Variant of <qid>`, never a year. Only in-window papers exist (`out_of_window_in_chapters` is a hard gate).
- Every printed number has `work/<scope>/checks/<id>.py` that prints it (ids: qid, `<Cid>_variant`,
  `<Tid>_ex_<name>`, `mock_Q<n>`, `drill_<n>`); run it; the boxed answer equals its output. State assumptions.
  Create check ids only for the topics, ideas and papers your pack assigns; never overwrite another writer's check
  (to reuse its number, import or run it). A shared helper module gets your writer id in its name (`_notesA_util.py`).
- Follow the pack's conventions exactly. A new ambiguity: choose, say it in an `examtip`, report it. Apply a
  convention's rule in words; never print its id (`convention \texttt{ack\_number}` is the `internal_leaks` hard gate).
- No unsupported statistics or examiner claims. Banned: "similarly", "left as an exercise", "refer to previous".

**Generated, never hand-typed.** `\clusterbadge{C05}`, `\topicbadge{T07}` (never `\tier`/`\prob`), `\mks{2.5}`,
`\asked{2024 Q1(c)}`, `\receipt{<qid>}` under each verbatim PYQ, `\seesolved{C05}` (each idea is solved once, in its
solve atom), `\pyqsolved{<qid>}` (never a typed `\pageref`), `\flashcard{front}{back}`. No badge or `\mks` inside
`\section{}`/`\chapter{}` titles. Labels: `sec:<Tid>`, `q:<qid>` (paper chapters only), `iq:<Cid>`, `fig:<name>`.

**Length.** Answer boxes follow `exam_hall` (≈ marks × min-per-mark × 20 words; 1 mark = the fact; 2–3 = definition
or diagram + 3–5 points; 4–5 = intro, diagram, 5–8 points, conclusion). Unit notes fit the pack's page target
(tier A/B topics get the room). Solve atom ≤ 1 page per 2.5 marks. Trim once to the target, then stop.

**Visuals (the main quality lever).** Each topic gets its `visual` type from the pack (storyboard = `\stepanim` 3–6
frames with a one-line note per frame; sequence, block, fsm, tree, graph, array, plot, pipeline, flowchart, uml,
table with `\zebra`, figure = `\figfromnotes`). A table never counts for a tier A/B topic. Copy mechanics from
`latex/visual_cookbook.tex` (colours `hl ok bad info muted`, styles `blk circ cell msg state`, `elabel` on edge
labels), but use `[!htbp]`, never `[H]` or `\tiny`. Width ≤ `\linewidth`, labels horizontal and ≥ `\scriptsize`,
node distance ≥ 8 mm, ≤ 2 frames per row. Inside boxes no floats: `\stepanim*`, `\captionof`. Draw a shared figure
only if you own it (pack lists yours); otherwise `\ref{fig:..}`.

**Build and web traps.** No `\answer{}` in a `\caption`; atom macros use `\providecommand`; no `multicols` or
`\columnbreak` inside boxes (two `minipage`s); no `\textcolor` in TikZ node text (`text=<colour>`); split long
inline maths or add `\allowbreak`; no `\begingroup` and no `{\small\begin{multicols}..}` (write
`\begin{multicols}{2}\small ..`). Labels and links use the bank id exactly (`q:MS2022-2b(i)`,
`\pyqsolved{MS2022-2b(i)}`); only `\receipt{MS2022-2b_i_}` takes the file-safe name. There is no phone edition (dropped 2026-11-10): build and check print only.

**Recall.** Every topic atom ends with 2–5 `\flashcard`s (back ≤ 25 words, no figures or refs).

**Self-check, cheaply (this is where most tokens went before).**
1. Write all your files first. Lint them (1 s): `py _pipeline/tools/lint_tex.py <SUBJ> --scope <scope> --files <a.tex,b.tex>`
   and fix every error. Then ONE build call for all of them (print only; never `--both` or `--phone`):
   `py _pipeline/tools/build.py <SUBJ> --scope <scope> --atom notes/T01,notes/T02,solve/C05 --render`
2. Fix every `LINT`/`ERROR` line and every `LAYOUT p<N> <kind>` line (outside, overlap, on_line, tiny); rebuild
   only the failing atoms. Read a contact sheet image only for a page that `FLAGGED` lists, once, then fix.
   Do not render or read images of pages that are not flagged. Do not re-read PYQ page images (the bank is gated).
3. Chapters: `--chapter <stem> --render` once at the end.
4. Report in ≤ 12 lines: files and pages vs target, visuals per topic, Cids and qids, checks, flashcards,
   assumptions and new conventions, anything unverified.
