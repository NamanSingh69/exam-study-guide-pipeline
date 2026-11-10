# Stage 0: Orchestrator (the main session runs this and delegates all writing)

> **Start with `_pipeline/RUNBOOK.md`.** It is the default path at the lowest usage cost (packs, batched builds,
> flagged-only images, `run_subject.py`, model tiers). This file is the reference for what the runbook leaves out:
> zero-paper subjects, split mode, the full fan-out, planted defects, post-exam scoring and runners without subagents.

**Goal:** for each subject and scope, produce these files in `<SUBJ>/`:
- `<Subject>_<Scope>_Guide.pdf`, `_Guide_Phone.pdf` and `_Cheatsheet.pdf`
- `_PYQ_Archive.pdf`: the older in-window papers
- `_Guide_Interactive.pdf`, only if the user asked for it
- `work/<scope>/web/` and `work/<scope>/flashcards.csv`

Every output must be:
- built from a gated, verbatim PYQ bank
- grounded in the instructor's notes
- ordered by the planner's study plans
- resumable after a usage-limit stop

**Your role:** you coordinate. Subagents read and write. You never paste corpus text into a brief: agents
read the files themselves. You own these files:
- `work/<scope>/assignments.json`
- `work/<scope>/class_signal.json`
- `work/<scope>/conventions.json` (after the first version)
- the ledger, through `tools/state.py`

**Commands:** run every command from the `Study Prep` folder with Windows `py`. Every per-scope tool takes
`--scope midsem|endsem`, and the flag is required. `ingest.py` is the only tool without it, because its
output is shared by both scopes. Exit codes:
- 0: OK
- 1: BLOCKED or FAILED; read the final `RESULT`/`STATUS` line
- 2: usage error

A stage counts as done only when its own gate passed. Never treat a printed warning as success.

## 0. Parse the request (never block on optional input)
1. **Scope and subjects.** Subjects are folder names: AI CI CN DAA DMDW DOS EE HPC IPA ML SE SVP, or any
   folder with the same layout. "all" means every subject folder.
   - **No scope given:** take the scope whose date in `_pipeline/exam_dates.json` is the nearest one still to
     come for those subjects.
   - **No dates either:** ask once.
2. **Options in the message:**
   - "interactive" / "animations": also build the Interactive edition.
   - "only the cheatsheet", "redo the 2024 paper", and similar: run only that stage, on top of the existing
     `work/<scope>/`. Then rebuild and run metrics.
3. **Class signal.** Copy every hint about the class, word for word, into
   `<SUBJ>/work/<scope>/class_signal.json` (schema in `schemas.md`). Examples: "teacher stressed sliding
   window", "unit 5 dropped this year", "pattern changed to 6 questions".
   - Leave `topics`/`clusters` empty; the merge agent maps them.
   - No hints: do not create the file.
   - Never ask for hints.
4. **Ordering and batching.**
   - **More than 4 subjects:** sort them by the date for that scope in `exam_dates.json`, soonest first.
     Subjects with a `null` date go last, alphabetically.
   - **Batches:** run 3–4 subjects per session, because of usage limits. State the batch plan in one line.
   - **When a batch finishes:** give the exact trigger for the next batch.
5. **Resume check.** For each subject run `py _pipeline/tools/state.py <SUBJ> --scope <scope> next`.
   - **Interrupted items:** an item still `running` at session start was cut off. Check its output: does the
     file exist, and do its own build or gate pass? If yes, set it `ok`; otherwise brief it again.
   - **Finished items:** never redo an item that is already `ok`.

### The ledger
After every step, record it:
`py _pipeline/tools/state.py <SUBJ> --scope <scope> set <stage> <key> <status> [--note "..."]`

- **Statuses:** `todo | running | ok | failed`.
- **An unreadable `run_state.json` makes `state.py` exit 1.** Stop that subject and report it. Never delete or
  recreate the ledger yourself.
- **Before launching an agent:** set its items to `running`.
- **When it returns:** set them to `ok` or `failed`.
- **`--note`:** carries the reason or the count.

| stage | key | gate for `ok` |
|---|---|---|
| `ingest` | `all` | `ingest.py` exit 0 |
| `vision` | `<slug>_p<from>-<to>` | `__vision_` file written |
| `transcribe` | `<paper id>` | part file written, every marked sub-part present |
| `merge` | `bank` | `pyq_bank.json` + `blueprint.json` complete |
| `receipts` | `all` | `receipts.py` exit 0 |
| `gate` | `verify` | `verify_pyqs.py` prints `RESULT PASS` |
| `score` | `all` | `score.py` exit 0 |
| `assign` | `all` | `assignments.json` written |
| `atom` | `notes/<Tid>`, `solve/<Cid>` | `build.py --atom` `STATUS OK` |
| `chapter` | `<stem>` | `build.py --chapter` `STATUS OK` |
| `recall` | `all` | `65_q1_drill` builds; flashcard top-up done |
| `build` | `guide`, `phone`, `cheatsheet`, `interactive` | `STATUS OK` |
| `web`, `flashcards` | `all` | exit 0 |
| `metrics` | `all` | every hard gate 0 and `pyq_gate` 1 |
| `review` | `r<round>` | both reviews, calibration and answerability written |
| `fix` | `r<round>` | fixes applied, rebuilt, metrics clean |
| `release` | `all` | no open criticals |

### Usage-limit stop
- **Signs:** an agent returns a usage-limit or rate-limit error, or you are warned that the session is
  running out.
- **What to do:**
  1. Launch nothing new.
  2. Let running agents finish and record their results.
  3. Set every unfinished item back to `todo` with `--note "usage limit"`.
  4. Tell the user which subjects and stages are `ok`, and the exact trigger to resume (the same sentence
     works: the ledger skips finished work).
- **On resume:**
  - Never restart a subject from scratch.
  - Never run `ingest.py --force`.
  - Never regenerate a bank whose `gate verify` is `ok`.
- **Bank rule.** A gated bank is frozen. New papers are *added*:
  1. transcribe only the new papers
  2. merge in extend mode
  3. `receipts.py`
  4. `verify_pyqs.py`

  Existing paper, question and cluster ids never change.

## Agent model
- **Claude Code:**
  - Spawn agents with the Agent tool (general-purpose). Send all independent agents of one phase in **one**
    message so they run in parallel.
  - Continue an agent with SendMessage: the blueprint agent's Part 2, and fixes to a writer. It keeps its
    context.
  - If the agent is gone, brief a fresh one with the same stage prompt plus the fix list.
- **Every brief contains:**
  - the stage prompt path
  - "read `_pipeline/prompts/_writer_contract.md` first" (writers only)
  - subject, scope, the folder `<SUBJ>/work/<scope>/`
  - the exact assignment: ids, chapter stem, atom files, the solve owners and figures it owns
- **Without subagents (AGENTS.md readers, e.g. Codex):**
  - Do every brief yourself, one at a time, in the phase order below.
  - Before each brief, re-read its stage prompt and the contract. Mark the ledger exactly as above.
  - Independent review is impossible in the same context. Run `06_review.md` and `08_answerability.md` in a
    **new session** if you can: tell the user "start a new session and say: review the <scope> guide for
    <SUBJ>".
  - Otherwise run them last, set `"independent": false` in the review JSON, and say so in the final report.

## Scope switch
| | midsem | endsem |
|---|---|---|
| syllabus | lesson plan up to the mid-semester cutoff | everything |
| papers transcribed | **all** papers in `Midsem PYQs/` and `Endsem PYQs/` (endsem papers hold midsem-scope questions; banking them now makes the endsem run cheap) | only papers not already in `work/midsem/pyq_bank.json` |
| "relevant" papers | **in the window** (`blueprint.pyq_window`: `from` ≤ year ≤ `to`), `coverage` includes an in-scope unit, `weight` > 0 | same |
| full-solution papers (main guide) | the latest 3 relevant **midsem** papers | the latest 3 relevant **endsem** papers |
| other relevant papers (`_PYQ_Archive.pdf`) | verbatim + `\receipt` + `\seesolved` (in-scope questions only) | same |
| out-of-window papers | banked, gated and with receipts, but in **no** chapter, drill or archive | same |
| mock | the midsem pattern | the endsem pattern |
| reuse | none | midsem ids, atoms and bank (see "Endsem reuse") |

"Latest" means sorted by (`year`, `session`: spring before autumn), newest first. If the scope's exam type
has fewer than 3 relevant papers, fill the remaining full-solution slots with the newest relevant papers of
the other type.

## Phase A: ingest (one background script for the whole batch)
```
py _pipeline/tools/ingest.py <SUBJ>
```
Run the batch's subjects **one after another**, inside ONE background `py` script. PowerPoint (used to render
slides) is a single shared instance, so parallel ingests collide.
- **Exit 1** (`INGEST: N errors (...)`): **stop that subject.** Give the user the INGEST line and each failing
  file. Typical fixes:
  - re-export a legacy `.ppt`/`.doc` to PDF
  - replace a corrupt download

  Set `ingest all failed`. The other subjects continue.
- **Exit 0:** read `work/corpus/INDEX.md`. Note the notes files marked `POOR` that the scope needs: the
  in-scope units' decks, plus any pages cited by in-scope PYQs. Note the `origin` column too (`instructor`
  vs `gapfill:`).
- **Endsem run with an empty `Endsem PYQs/`:** fetch the papers first (`_pipeline/sources.md`) in ONE
  background `py` script, then re-run ingest.

## Phase B: bank and blueprint (per subject; the agents run in parallel)
1. **Paper ids.** List every PYQ slug in INDEX.md and give each an id. Write the map to
   `assignments.json → papers` (it never changes again).
   - **Form:** `MS<year>` for midsem, `ES<year>` for endsem.
   - **Spring sitting:** add `SP`, e.g. `ES2026SP` for "6th Sem, 2026 end".
   - **Second set of the same sitting:** add `B`.
   - **Endsem run:** keep the midsem run's ids.
2. **Spawn in one message:**
   - **Blueprint agent:** `01_blueprint.md`, Part 1 (scope, units, topics, pattern, figure plan,
     coverage gaps).
   - **Transcribers:** `01a_transcribe_pyqs.md`. Each takes 3–4 papers and at most 16 page images; never
     split a paper. Give each its paper ids and slugs, and put both papers of one year in the same group, so
     duplicates are noticed. Each writes `work/<scope>/pyq_bank.part_<paper id>.json`.
   - **Note-vision agents:** `01b_transcribe_notes.md`, one per ~40 needed POOR pages.
3. **Coverage gaps.** When Part 1 returns, look at `blueprint.json → coverage_gaps` with `status: "open"`:
   1. Check `<SUBJ>/_staging_downloads/`.
   2. Then fetch per `_pipeline/sources.md`, in ONE background `py` script. No browser downloads and no save
      dialogs.
   3. If a source offers several teachers' note sets, ask the user which one. This is the only question you
      may ask.
   4. Add each downloaded file to `_pipeline/gapfill.json` *before* re-running ingest, so ingest marks it
      `gapfill:` rather than `instructor`. The entry is
      `"<SUBJ>": {"<file name under Notes/>": "<site, teacher or set, topics>"}`. Then re-run ingest.
   5. SendMessage the blueprint agent to update `sources`, `origin` and the gap `status`.

   A gap that no source fills becomes `unfillable`, with the book chapter to write from.
4. **Part 2.** When every transcriber and Part 1 are done, SendMessage the blueprint agent: "do Part 2 of
   `01_blueprint.md`" (merge, cluster, coverage, weights, class-signal mapping, conventions).
5. **Gates:**
   ```
   py _pipeline/tools/receipts.py <SUBJ> --scope <scope>
   py _pipeline/tools/verify_pyqs.py <SUBJ> --scope <scope>      # must print RESULT PASS
   ```
   - **On BLOCKED:**
     1. Send each blocking line to the transcriber of that paper. It re-reads the image and fixes its part
        file, or adds a manual `receipt` rect.
     2. Then send the merge agent "re-apply the changed part files".
     3. Re-run both commands. A text edit makes the old receipt stale, so `receipts.py` always runs again;
        `receipts.py <SUBJ> --scope <scope> --only <qid>` is enough for single questions.
   - **Round cap:** at most 3 gate rounds. Still blocked: set `gate verify failed`, report the reasons to the
     user, and stop this subject.
   - **Nothing is written from a bank that has not passed.**
6. **Zero papers** (none on disk, and none fetchable per `sources.md`): weak-input mode.
   - Part 1 writes an assumed `exam_pattern` with `"assumed": true` and names its `source`.
   - Part 2 writes a bank with `"no_papers": true`: no papers, no questions, clusters from the syllabus and
     the seniors' lists only.
   - The gate must still print `RESULT PASS` (see Open questions in `ROUND4_SPEC.md`).
   - Downstream: P is shown as bands only, there are no PYQ chapters, the mock is titled "pattern assumed",
     and there is no Q1 drill from PYQs (only predicted clusters).
7. **Score:**
   ```
   py _pipeline/tools/score.py <SUBJ> --scope <scope>
   ```
   - **What it writes:**
     - `important_questions.json`
     - `badges.tex`
     - `chapters/05_how_to_use.tex` and `chapters/20_exam_radar.tex`
     - a plan snapshot
   - **Sanity check:** read the 3 h plan. A cluster that is obviously mis-grouped goes back to the merge agent,
     followed by a new gate and score.
   - **Also check:**
     - `pyq_window` and its `why`. The window rule applies to every subject. The blueprint agent starts from
       `_pipeline/pyq_windows.json`; a change from that suggestion must be explained in `why`.
     - `targets`: `iq_clusters`, `notes_pages[<unit>]`, `cheatsheet_pages`, `q1_drill`, each with its own
       `why`

     The targets size every writer's job to this subject. Copy the relevant entries into each writer's brief.
   - **Re-runs:** run score again after any bank change. Badges update themselves; writers never retype them.

## Phase C: assignments (you, before any writer starts)
**Snapshot first.** If the ledger has a finished previous run (`release all ok`) and you are regenerating,
copy `chapters/`, `atoms/` and the guide PDF to `work/<scope>/prev/<YYYY-MM-DD>/`, for the pairwise review.
Never snapshot on a resume.

Write `work/<scope>/assignments.json` (schema in `schemas.md`). Compute it with a short `py` script over
`blueprint.json`, `pyq_bank.json` and `important_questions.json`. Never compute it by hand.

**Chapter stems.** You assign them all; writers never choose.
| stem | content | writer |
|---|---|---|
| `05_how_to_use`, `20_exam_radar` | auto | score.py |
| `3N_<unit>` (30_, 31_ … in syllabus order; from `units[].chapter`) | unit wrapper: `\chapter`, unit map, `\input{atoms/notes/<Tid>}` lines, recap | the unit writer |
| `60_important_questions` | study-order questions (exactly `targets.iq_clusters`) | IQ agent |
| `62_older_ideas` (kind `solved_ideas`, main guide) | `\chapter` + one `\input{atoms/solve/<Cid>}` per older-paper-only cluster, in syllabus order | the first older-PYQ agent |
| `65_q1_drill` | Q1 rapid-fire drill | recall agent |
| `7NN_pyq_<paper id lowercase>`, kind `pyq_full` (`700_`, `701_`, `702_`, newest first) | the full-solution papers, in the main guide | PYQ agents |
| `7NN_pyq_<paper id lowercase>`, kind `pyq_older` (continuing the numbering, newest first) | older **in-window** papers; with `"one_pdf": true` (the default, user preference 2026-11-09) they go at the end of the guide after an "Older papers" divider, otherwise into `_PYQ_Archive.pdf` | older-PYQ agents |
| `80_mock_paper` | mock | IQ agent |
| `cheatsheet` | built standalone, appended | cheatsheet agent |

- **Window:** only in-window relevant papers get a chapter. Out-of-window papers get none
  (`out_of_window_in_chapters` is a hard gate).
- **Stems:** three-digit PYQ stems sort between `65_` and `80_` for up to 100 papers.
- **One PDF per subject (default):** set `"one_pdf": true` at the top of `assignments.json`. The guide then
  holds everything: notes, solutions, the older papers and the cheatsheet. All links are local, `--archive`
  has nothing to build, and `--cheatsheet` delivers no separate file. Writers must not say "in the PYQ
  Archive"; say "in the Older papers section". The split mode below applies only when the user asks for
  separate files.
- **Links into the archive (split mode):** writers use `\pyqsolved{<qid>}` for every in-window PYQ, archive papers
  included. `build.py` writes `_xref_<job>.tex` from the other document's labels and `.aux`, so a link to an
  archive question prints "PYQ archive, <paper> <qno>, p. N", linked to the archive PDF. A missing target is a
  hard error. This is why the build order is guide, `--archive`, guide.

**Atoms.** Each in-scope topic → `atoms/notes/<Tid>.tex`, owned by its unit writer.

**Solve owners.** Every cluster that is printed is solved in full **exactly once**, in
`atoms/solve/<Cid>.tex` (`solvedidea`). Only in-window questions count here. For each in-scope cluster, take
the first rule that applies:
1. **A question in a full-solution paper.** Owner: that paper's PYQ agent. Anchor: the newest such question,
   solved verbatim. Included in that paper's chapter.
2. **Questions only in older in-window papers.** Owner: the older-PYQ agent of the anchor's paper, which
   spreads the load. Anchor: the newest of them. Included once in `62_older_ideas`.
3. **No in-window PYQ, but in `targets.iq_clusters`** (a wildcard, an imp-list idea, or asked only outside the
   window). Owner: the IQ agent. Anchor: `null`, so the IQ agent writes an `Expected` question. It never
   prints an out-of-window question.
4. **Anything else:** no solve. It appears only in the tier E index.

Every other appearance of the idea uses `\seesolved{<Cid>}`. A numerical with different numbers also gets a
short answer of at most 6 lines, with its own check script.

**Figures.** Take `blueprint.json → figure_plan`. Check that every entry has exactly one owner atom; the owner
draws the figure and the others reference it.

**Agent count.** Tell the user the total before the fan-out. If it is over 40, give the count and proceed
unless they object.
| agents per subject | count |
|---|---|
| transcribers | ceil(new papers / 4) |
| note vision | ceil(needed POOR pages / 40) |
| blueprint | 1 (Part 1 + Part 2) |
| unit writers | 1 per in-scope unit not reused; 2 for a unit with > 8 topics or > 12 lectures (split the topics; the first writer owns the wrapper) |
| PYQ agents | 1 per full-solution paper (≤ 3), plus ceil(older in-window papers / 6) |
| IQ + mock | 1 |
| recall | 1 |
| cheatsheet | 1 |
| review | 2 reviewers + 1 answerability |

Example: CN midsem, 7 + 7 papers and 3 units, is about 19 agents. The CN endsem that follows needs about 14,
because no transcription is left and 3 units are reused.

## Phase D: writers
- **Lean mode (the default since 2026-11-08; the user's usage limit is the binding constraint).** Each agent
  re-reads the contract, prompts and JSONs (about 50–100k tokens), so per-agent overhead dominates. Per subject:
  - TWO writers:
    - a **notes writer** (every notes atom and unit chapter, then the Q1 drill, night-before and cheatsheet)
    - a **PYQ writer** (every solve atom, the PYQ chapters, 62, 60 and 80)
  - ONE reviewer, who also does answerability.
  - ONE fix agent, who also fixes layout: the `--render` and `--phone` overfulls.

  That is about a third of the full fan-out's tokens for the same gates. Since 2026-11-10 the two writers get
  their brief as a pack (`tools/pack.py --role notes|pyq`), and the transcriber and fixer run on Sonnet
  (RUNBOOK model tiers).
  - **Limits:**
    - at most 5 papers per subject
    - one transcriber per subject
    - no separate note-vision pass: writers read the `note_pages` they cite
    - page targets are targets: trim once, then stop
  - Use the full fan-out below only when the user asks for speed over usage.
- **Spawn in one message (full fan-out):**
  - unit writers: `02_unit_notes.md`
  - PYQ agents: `03_pyq_solutions.md`
  - the IQ agent: `04_important_questions.md`

  Each agent compiles only its own atoms (`--atom`) and chapters (`--chapter`), so the parallel agents never
  collide.
- **Every brief carries its targets** from `important_questions.json → targets`, with their `why`:
  - unit writers: `notes_pages[<unit>]`
  - the IQ agent: `iq_clusters`
  - the recall agent: `q1_drill`
  - the cheatsheet agent: `cheatsheet_pages`
  - PYQ agents: the in-window paper list
- **When all unit writers have returned:**
  1. Merge the conventions they report into `conventions.json`. Send each affected writer a one-line fix.
  2. Spawn the **recall agent** (`07_recall.md`).
  3. When it returns, spawn the **cheatsheet agent** (`05_cheatsheet.md`). The cheatsheet `\input`s the
     recall agent's night-before sheet.

## Phase E: build and hard gates (you)
```
py _pipeline/tools/build.py <SUBJ> --scope <scope> --cheatsheet --render
py _pipeline/tools/build.py <SUBJ> --scope <scope> --render          # print edition (+ appended cheatsheet)
py _pipeline/tools/build.py <SUBJ> --scope <scope> --archive         # split mode only: -> _PYQ_Archive.pdf
py _pipeline/tools/build.py <SUBJ> --scope <scope> --render          # split mode only: resolves refs into the archive
py _pipeline/tools/build.py <SUBJ> --scope <scope> --phone           # single-column phone edition
py _pipeline/tools/build.py <SUBJ> --scope <scope> --interactive     # ONLY if the user asked for it
py _pipeline/tools/flashcards.py <SUBJ> --scope <scope>              # -> work/<scope>/flashcards.csv
py _pipeline/tools/web.py <SUBJ> --scope <scope>                     # -> work/<scope>/web/
py _pipeline/tools/metrics.py <SUBJ> --scope <scope>
```
- **Pass condition:** `metrics.py` exits 0, i.e. every hard gate is 0 and `pyq_gate` is 1. The hard gates are:
  - `ingest_errors`
  - `undefined_refs`
  - `tex_errors`
  - `float_too_large`
  - `missing_chapters`
  - `missing_receipts`
  - `checks_failed`
  - `stale_pdf`: if it names the archive, run `--archive` once more, then metrics again
  - `out_of_window_in_chapters`
- **Build order:** one_pdf: guide, then phone. Split mode: guide, archive, guide, then the archive again only
  if metrics says it is stale.
- **On a failure:**
  1. Find the owner in `assignments.json`.
  2. Send the exact metric lines (SendMessage).
  3. Rebuild and re-run metrics. At most 3 attempts; then stop and report.
- **Tracked metrics** (no gate; record them in your report): `dup_solves`, `pages_per_exam_mark`,
  `storyboards_per_process_topic`, `missing_badges`, `numericals_without_check`, `iq_count_vs_target`,
  `cheatsheet_pages_vs_target`. `over_budget_pages` uses `targets.notes_pages`.
  - `dup_solves` > 0 means you broke the solve-owner rule: fix it.
- **Do not look yourself.** `run_subject.py --phase post` prints the layout summary; the reviewer looks at the
  flagged pages and a sample of figure pages. The main session never reads images or PDFs (RUNBOOK session rules).

## Phase F: review (fresh agents that wrote nothing)
1. **Planted defects.** Make two planted copies:
   ```
   py _pipeline/tools/plant_defects.py <SUBJ> --scope <scope> --n 5 --seed 1 --out <SUBJ>/work/<scope>/reviews/copy_1
   py _pipeline/tools/plant_defects.py <SUBJ> --scope <scope> --n 5 --seed 2 --out <SUBJ>/work/<scope>/reviews/copy_2
   ```
   The answer keys go to `reviews/_keys/`. Never give a reviewer a key path or mention planting.
2. **Pairwise pairs** (only if a `prev/` snapshot exists):
   1. Pick 6 units present in both versions: 3 topic sections (`sec:<Tid>`), 2 PYQ solutions (`q:<qid>`) and
      1 important-question entry (`iq:<Cid>`). Pick them from tiers A/B first.
   2. Extract each pair's old and new LaTeX into `reviews/pairs/pair_NN_X.tex` and `_Y.tex`. Use
      `py random` to decide which version is X.
   3. Record the mapping in `reviews/_keys/pairs_r<round>.json`.
3. **Spawn in one message:**
   - Reviewer A: `06_review.md`, sources `reviews/copy_1`, output `reviews/review_r<round>_A.json`.
   - Reviewer B: `06_review.md`, sources `reviews/copy_2`, output `reviews/review_r<round>_B.json`.
   - The answerability agent: `08_answerability.md`.
4. **Score the reviews.** For each review, match its findings against its key:
   - **recall** = planted defects found / 5
   - **Findings that match the key** are dropped.
   - **Every other finding is real.** Check that its text exists in the real file, then queue it.
   - Write `reviews/summary_r<round>.json`:
     - both reviewers' scores, their mean and the disagreement (|A − B| per dimension)
     - the recall per reviewer
     - the pairwise win rate of the new version (ties count ½)
     - answerability coverage %
     - the merged, de-duplicated fixes

## Phase G: fix loop (at most 2 rounds)
1. Group the fixes by owner (`assignments.json`) and SendMessage each owner its list. The owner edits, rebuilds
   its atom or chapter, and reports.
2. Re-run Phase E.
3. Round 2 only: send each reviewer (SendMessage) its own criticals and the changed files to confirm. Do not
   start a new full review.
4. **After round 2:**
   - Open criticals → `release all failed`. Mark the subject **NOT READY** and list the criticals.
   - None → `release all ok`.

## Phase H: report to the user (per subject, ≤ 12 lines)
- the PDF paths with page counts (guide, phone, cheatsheet, PYQ archive, and interactive if built), the PYQ
  window, plus the web folder
  and the flashcard count
- the metrics line: hard gates, `pages_per_exam_mark`, `dup_solves`, storyboards per process topic
- the reviewer mean, disagreement, recall, pairwise win rate and answerability %
- anything unverified:
  - `\notfromnotes` topics
  - POOR pages
  - an assumed pattern
  - a non-independent review
- what still needs the user (a teacher's note set, an illegible paper)

## Endsem reuse (when `work/midsem/blueprint.json` exists)
- **Ids.** The endsem blueprint keeps the midsem unit, topic and cluster ids for shared units. New units,
  topics and clusters continue the numbering.
- **Bank.** Copy the midsem bank into `work/endsem/pyq_bank.json` (it is already gated) and extend it with any
  papers not yet banked. Part 2 resets `in_scope` and `coverage` for endsem. Then receipts, gate, score.
- **Notes atoms.** Copy `work/midsem/atoms/notes/<Tid>.tex` into `work/endsem/atoms/notes/` when all three
  hold:
  - the topic's `sources` are unchanged
  - the source files' manifest stamps are unchanged
  - the midsem ledger has `atom notes/<Tid> ok`

  Set the endsem ledger item `ok --note "reused from midsem"`. Badges come from the endsem `badges.tex`
  automatically.
- **Solve atoms.** Copy one only if its endsem anchor is the same question id. Otherwise the new owner writes
  it.
- **Writers.** Unit writers handle only new or changed topics. A wrapper chapter is rewritten whenever its unit
  gains topics.
- **Size control:**
  - the 3–5-year PYQ window
  - full solutions only for the latest 3 endsem papers, with the older in-window papers in the separate
    archive
  - every idea solved once
  - subject-scaled `targets` (notes pages per unit, the IQ cluster set, cheatsheet pages)

## Post-exam loop ("I just sat the CN midsem", with the new paper in the folder)
1. Ingest.
2. Transcribe only the new paper; merge in extend mode; receipts; gate.
3. `py _pipeline/tools/backtest.py --post-exam <SUBJ> --scope <scope> --paper <id>`
4. `score.py`.
5. Report the plan's coverage of the new paper.

## Local first
All gates and tests run on this laptop: `py _pipeline/tests/run_all.py` and the tools above. Never move a
check to GitHub Actions. Actions only do what cannot run here, and publishing belongs to `_publish/`, which
you never touch.
