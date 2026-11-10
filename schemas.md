# Data contracts (pipeline v2, Round 4)

Every per-scope file lives in `<SUBJ>/work/<scope>/` (`scope` = `midsem` | `endsem`, the folder name). The
shared ingest output lives in `<SUBJ>/work/`. Keep the keys exactly as below. `ROUND4_SPEC.md` is binding
where the two disagree; report any disagreement there under "Open questions".

| file | written by | read by |
|---|---|---|
| `work/manifest.json`, `corpus/INDEX.md` | ingest.py | everyone |
| `blueprint.json` | blueprint agent (`01_blueprint.md`) | all tools and writers |
| `pyq_bank.part_<paper>.json` | transcribers (`01a`) | blueprint agent, Part 2 |
| `pyq_bank.json` | blueprint agent, Part 2 | verify_pyqs, receipts, score, writers |
| `conventions.json` | blueprint agent; the orchestrator merges later additions | writers, reviewers |
| `class_signal.json` | orchestrator (text); blueprint agent (ids) | score.py |
| `receipts/receipts.json`, `receipts/<qid>.png` | receipts.py | verify_pyqs, `\receipt`, metrics |
| `important_questions.json`, `badges.tex`, `plan_snapshots/<date>.json` | score.py | writers, metrics, web |
| `assignments.json` | orchestrator | writers, fixers, reviewers |
| `run_state.json` | state.py | orchestrator |
| `flashcards.csv` | flashcards.py | the student (Anki) |
| `reviews/*.json` | reviewers, answerability agent, orchestrator | orchestrator, autoresearch |
| `_pipeline/exam_dates.json` | the user | orchestrator |
| `_pipeline/pyq_windows.json` | the lead (suggested windows: `{"<SUBJ>": {"from", "to", "why"}}`) | blueprint agent, which confirms or changes them into `blueprint.pyq_window` |

## `blueprint.json`
```jsonc
{
  "subject": "Computer Networks",            // cover, headers, PDF names and metadata
  "code": "CS 30003",
  "code_aliases": ["IT-3005", "CS30003"],    // other codes of the SAME course seen on papers/plans
  "scope": "Midsem",                         // display only; tools take the scope from the folder name
  "cutoff": "Lesson plan L1-23: Data Comm, Application, Transport [SYL_... p2-3]",
  "pyq_window": {"from": 2022, "to": 2026, "years": 5,   // starts from _pipeline/pyq_windows.json; default:
                 // the latest 5 calendar years with papers;
                 "why": "syllabus revised 2022; 2022-2026 gives 5 midsem papers"},  // later start on a syllabus/
                 // code change (>= 3 years kept); back to 5 years only if < 3 relevant papers. Papers outside
                 // stay banked and gated; score.py weights them 0; no chapter, drill or archive prints them.
  "exam_pattern": {
    "full_marks": 20, "duration": "1.5 h",
    "structure": "Q1 compulsory (5 x 1 mark); answer any 3 of Q2-Q5 (each 2.5 + 2.5)",
    "compulsory": ["1"],
    "choose": {"from": ["2","3","4","5"], "answer": 3},
    "source": "PYQM_2025_Midsem_1_Computer_Networks_1 p1",   // where it was read, or what it was assumed from
    "assumed": false                         // true only on the zero-papers path; then "source" names the basis
  },
  "units": [
    {"id": "U3", "title": "Transport Layer", "in_scope": true, "lectures": 12,
     "chapter": "32_transport_layer",        // "3N_<name>" for in-scope units, "" otherwise
     "source_confidence": {"level": "high", "why": "instructor notes for every topic"},  // high|medium|low
     "topics": [
       {"id": "T15", "title": "Go-Back-N protocol",
        "lectures": 1.5,                     // from the plan, or estimated (say so in notes)
        "senior_imp": true,
        "sources": ["N_Computer_Networks_compressed p66-68"],
        "origin": "instructor",              // best source: instructor | gapfill | none
        "visual": "storyboard",              // see "Visual types" below
        "notes": ""}
     ]}
  ],
  "figure_plan": [                           // only figures that more than one topic needs
    {"fig": "fig:T15-window", "owner": "atoms/notes/T15",
     "desc": "GBN sender window: Sf, Sn, Ssize over a sequence-number strip",
     "used_by": ["T16", "C09"]}
  ],
  "coverage_gaps": [
    {"topic": "T24", "title": "Quality of Service", "why": "no notes pages",
     "status": "open",                       // open | filled | unfillable
     "filled_by": [],                        // corpus slugs once filled
     "book": "Forouzan, Data Communications and Networking 5e, ch. 30"}   // required when unfillable
  ],
  "imp_docs": ["N_cn_imp_topics_and_pyqs"],  // seniors' important-question lists
  "warnings": ["..."]
}
```

**Visual types (`topic.visual`)**
| type | when to use it |
|---|---|
| `storyboard` | every **process** topic: ≥ 3 steps over time (protocols, algorithms, mechanisms) |
| `sequence` | a message exchange over time, when the steps are not the point |
| `block` | structure, architecture, layers |
| `fsm` | a state machine |
| `tree` | recursion trees, BSTs, heaps, decision trees |
| `graph` | graphs with weights or paths |
| `array` | data-structure state traces (sorting, DP, hashing) |
| `plot` | a quantity vs a parameter |
| `pipeline` | pipelines, Gantt and schedule charts |
| `flowchart` | decisions |
| `uml` | UML, DFD and ER diagrams |
| `table` | comparison topics only; never for a topic with tier A/B clusters |
| `figure` | `\figfromnotes`, only when redrawing would lose information |

`metrics.py`'s `storyboards_per_process_topic` treats `visual: storyboard` topics as the process topics.

## `pyq_bank.part_<paper>.json` (one per paper, written by a transcriber)
```jsonc
{
  "paper": {"id": "MS2024", "year": 2024, "session": "autumn",   // spring | autumn ("6th Sem" = spring)
            "exam": "midsem", "source_slug": "PYQM_2024_Midsem_1_Computer_Networks_1",
            "course_code": "CS 30003", "full_marks": 20, "duration": "1.5 h",
            "pattern": "Q1 compulsory 5x1; any 3 of Q2-Q5",       // machine-readable; verify_pyqs parses it
            "instructions": "Answer any four questions including question No.1 ...",   // verbatim
            "pages": [1, 2],                        // [first, last] page of this set in the PDF
            "reading_order": ["1R", "2L", "2R", "1L"]},   // OPTIONAL: 2-up booklet spreads
  "questions": [ /* question objects as below, WITHOUT topic, cluster and in_scope */ ],
  "warnings": []
}
```

## `pyq_bank.json`
```jsonc
{
  "no_papers": false,                        // true only on the zero-papers path (papers and questions empty)
  "papers": [
    {"id": "MS2024", "year": 2024, "session": "autumn", "exam": "midsem",
     "source_slug": "PYQM_2024_Midsem_1_Computer_Networks_1", "course_code": "CS 30003",
     "full_marks": 20, "duration": "1.5 h", "pattern": "Q1 compulsory 5x1; any 3 of Q2-Q5",
     "instructions": "...", "pages": [1, 2],    // + optional "reading_order", as in the part file
     "coverage": ["U1", "U2", "U3"],         // units this paper examines (score.py's per-cluster denominator)
     "weight": 1}                            // 1 same course | 0.5 similar course | 0 record only
  ],
  "questions": [
    {"id": "MS2024-1c", "paper": "MS2024", "qno": "1(c)", "marks": 1,   // marks: a JSON number
     "compulsory": true,
     "text": "In Stop and wait protocol every 4th packet is lost ...",  // VERBATIM (OCR typos fixed only)
     "topic": "T14", "cluster": "C05",
     "type": "numerical",        // numerical | theory | derivation | diagram | compare | code | trace
     "in_scope": true,
     "verified": "vision",       // "vision" = checked against the page image; "ocr" = text only
     "ocr_fixes": "'4th' was 'Ath' in OCR",   // name every corrected number/acronym
     "figure": "",               // one-line description if the question contains a figure or table image
     "table": {"header": ["Process", "Arrival", "Burst"], "rows": [["P1", "0", "5"], ["P2", "-", "3"]]},
                                 // OPTIONAL: text holds exactly one "[table]"; no empty cells ("-" = printed
                                 // dash); needs verified "vision" + a receipt
                                 // $...$ maths spans in text: vision + receipt only, <= 60% of tokens;
                                 // currency ($17,000) stays plain; a literal $ is written \$
     "receipt": {"page": 1, "rect": [30, 412, 565, 470]},   // OPTIONAL manual crop, PDF points (px x 72/170)
     "table": {"header": ["X", "Y", "Label"],                // OPTIONAL: a data table, verbatim from the image;
               "rows": [["7", "7", "1"], ["7", "4", "1"]]}}  // `text` then holds the prose with "[table]" where
  ],                                                         // the table sits (see Rules)
  "clusters": [
    {"id": "C05", "topic": "T14", "label": "Stop-and-wait: count transmissions with periodic loss",
     "type": "numerical", "effort_min": 20}
  ],
  "imp_list": [
    {"text": "Explain why the GBN sender window must be less than 2^m",
     "source": "N_cn_imp_topics_and_pyqs p1", "cluster": "C09"}
  ]
}
```

**Rules**
- **Entries:** one `questions[]` entry per sub-part that carries its own marks. Every sub-part on the page is
  banked; the gate checks that the marks add up to `full_marks` under `pattern`.
- **Clusters:** every question has a cluster. Clusters may hold one question, or none (wildcards).
- **Out of scope:** `in_scope: false` questions stay banked; they are not solved.
- **Ids:** they never change once the bank has passed the gate. New papers are appended.
- **The gate:** `verify_pyqs.py --scope <scope>` must print `RESULT PASS` before anything is written from the
  bank. Re-run `receipts.py` after any text change; a stale receipt blocks.
- **Data tables** (`table`): the OCR of a table is garbage, so its cells are never matched as text.
  - Copy the table cell by cell from the page image into `header` and `rows`. Every row must be as long as the
    header. Never leave a cell empty; write `"-"` for a printed dash.
  - In `text`, keep only the prose and put `[table]` exactly once where the table sits. The prose is matched
    against the paper with all the usual rules.
  - The gate accepts a table only with `verified: "vision"` and a good receipt (an automatic one with match
    >= 0.6, or a manual rect). Editing the table makes the receipt stale, the same as editing the text.

## `receipts/receipts.json` (receipts.py)
```jsonc
{"MS2024-1c": {"paper": "MS2024", "page": 1, "rect": [30, 412, 565, 470],
               "parts": [{"page": 1, "rect": [30, 412, 565, 470]}],  // several when a question spans pages
               "match": 0.93, "tri": 0.9,                            // gate threshold: match >= 0.6
               "method": "pdf-words|tesseract|png-tesseract|manual",
               "file": "receipts/MS2024-1c.png",                     // null when nothing was found
               "text_sha": "<hash of the normalised question text>"}}  // a mismatch = stale receipt: re-run
```
Re-crop single questions with `receipts.py <S> --scope <sc> --only <qid>`. A manual rect plus
`verified: "vision"` waives only the match threshold: the PNG must still exist.

## `conventions.json`
```json
[{"id": "reno_fast_recovery", "decision": "...", "source": "N_slug p91 | textbook (name)", "alternative": "..."}]
```

## `class_signal.json` (optional)
```jsonc
{"source": "user trigger message, 2026-11-05",
 "signals": [{"text": "teacher stressed sliding window",   // verbatim from the user
              "kind": "stress",                            // stress | drop | pattern
              "topics": ["T15", "T16"], "clusters": []}]}  // filled by the blueprint agent, Part 2
```

## `important_questions.json` (score.py; read-only for agents)
These keys are guaranteed (exact sub-shapes: see score.py's output):
- `model`: parameters, papers used, the backtest source
- `clusters[]`:
  - `cluster`, `label`, `topic`, `unit`, `type`
  - `P` (or a band), `prior`, `typical_marks`, `EV`, `effort_min`
  - `tier`: A = 3 h plan, B = added by 6 h, C = added by 12 h, D = wildcard, E = rest
  - `asked`, `question_ids`, `in_imp_list`
- `topics[]`: `topic`, `title`, `unit`, `P`, `papers`, `marks_by_paper`
- `plans`: `3h`, `6h`, `12h` (nested), each with its topics/clusters, `expected_marks` and `p_safe`
- `q1_drill`: the one-mark PYQ ids and the predicted cluster ids
- `must_draw`: question ids and clusters whose questions ask for a diagram
- `skip_safety`: per unit and per past paper, "you could still answer k of the n optional questions"
- `exam_hall`: minutes per mark, plus a word budget per marks value (≈ marks × min-per-mark × 20)
- `backtest`: the latest leave-one-out numbers for this subject, or null
- `targets`: subject-scaled sizes, data-driven; each carries a `why` and is printed in "How to use":
  ```jsonc
  "targets": {
    "iq_clusters": {"ids": ["C05", "C09"], "why": "12 h plan (22) + 3 wildcards"},
        // the 12 h plan's clusters + at most 5 tier-D wildcards; 60_important_questions covers exactly these
    "notes_pages": {"U3": {"pages": 25, "why": "12 lectures x 1.9 (61% of window marks) + 1"}},
        // lectures_u * clamp(1 + share_u / mean_share, 1, 2) + 1
    "cheatsheet_pages": {"pages": 3, "why": "2 + numerical share 46% > 40%"},
        // 2 + (in-scope topics > 20) + (numerical share of window marks > 40%); night-before sheet extra
    "q1_drill": {"pyq_ids": ["MS2025-1a"], "predicted": 12, "why": "6 one-mark clusters x 2"}
        // newest in-window 1-mark PYQ per one-mark idea + min(30, 2 x one-mark clusters) predicted items
  }
  ```
  The exact sub-shapes are owned by score.py; the key names above are binding.

## `badges.tex` (score.py; regenerated on every run)
`\sgdefbadge{C05}{A}{79}{high}{1.58}` per cluster (the P argument is `-` when shown as a band only), and
`\sgdeftopic{T07}{84}{high}` per topic. Writers use `\clusterbadge{C05}` / `\topicbadge{T07}`.

## `assignments.json` (orchestrator)
```jsonc
{
  "papers": {"PYQM_2024_Midsem_1_Computer_Networks_1": "MS2024"},          // slug -> paper id, fixed
  "transcribe": [{"agent": "tx1", "papers": ["MS2019", "MS2020", "MS2022"]}],
  "full_papers": ["MS2026SP", "MS2025", "MS2024"],                          // latest 3 relevant, newest first
  "chapters": [
    {"stem": "32_transport_layer", "kind": "unit", "unit": "U3", "owner": "unit-U3"},
    {"stem": "60_important_questions", "kind": "iq", "owner": "iq"},
    {"stem": "62_older_ideas", "kind": "solved_ideas", "owner": "pyq-older-1"},  // main guide: older-only solves
    {"stem": "65_q1_drill", "kind": "recall", "owner": "recall"},
    {"stem": "700_pyq_ms2026sp", "kind": "pyq_full", "paper": "MS2026SP", "owner": "pyq-1"},   // main guide
    {"stem": "703_pyq_ms2023", "kind": "pyq_older", "paper": "MS2023", "owner": "pyq-older-1"}, // archive only
    {"stem": "80_mock_paper", "kind": "mock", "owner": "iq"},
    {"stem": "cheatsheet", "kind": "cheatsheet", "owner": "cheatsheet"}
  ],
  "atoms": {"notes/T15": "unit-U3"},
  "solve_owners": {"C05": {"owner": "pyq-1", "chapter": "700_pyq_ms2026sp", "anchor": "MS2026SP-1c"},
                   "C21": {"owner": "pyq-older-1", "chapter": "62_older_ideas", "anchor": "MS2023-4a"},
                   "C40": {"owner": "iq", "chapter": "60_important_questions", "anchor": null}},
      // "chapter" = where the atom is \input (once). Only in-window papers appear in chapters.
  "figures": {"fig:T15-window": "notes/T15"}
}
```
Stems:
- `05_`, `20_`: auto (score.py)
- `3N_`: units
- `60_important_questions`
- `62_older_ideas`
- `65_q1_drill`
- `7NN_pyq_<paperid>`: `700_` = the newest paper. `pyq_full` chapters go in the guide; `pyq_older` chapters go
  only in `<Subject>_<Scope>_PYQ_Archive.pdf` (`build.py --archive`).
- `80_mock_paper`
- `cheatsheet`

## `run_state.json` (state.py; never edit by hand)
```jsonc
{"subject": "CN", "scope": "midsem", "updated": "2026-11-05T14:02:11",
 "items": {"gate/verify": {"status": "ok", "note": "RESULT PASS", "updated": "..."},
           "atom/notes/T15": {"status": "running", "note": "", "updated": "..."}}}
```
- CLI: `state.py <S> --scope <sc> set <stage> <key> <todo|running|ok|failed> [--note ..]`, plus `show` and
  `next`.
- The stage names are listed in `prompts/00_orchestrator.md`.

## Atom store (LaTeX, per scope)
- `atoms/notes/<Tid>.tex`: exactly one `\section{..}\label{sec:<Tid>}` with 2–5 `\flashcard`s
- `atoms/solve/<Cid>.tex`: exactly one `solvedidea{<Cid>}{<title>}`, so `solve:<Cid>` exists once
- `atoms/recall/night_before.tex`: the night-before sheet (`\input` by the cheatsheet)

## `flashcards.csv` (flashcards.py)
Anki-importable, `;`-separated: `front;back;tags`. Tags include the subject, scope, unit and topic id.

## Reviews (`reviews/`)
- `review_r<r>_<A|B>.json`: the schema in `prompts/06_review.md`
- `answerability_r<r>.json`: the schema in `prompts/08_answerability.md`
- `summary_r<r>.json` (orchestrator):
  ```jsonc
  {"scores": {"A": {}, "B": {}, "mean": {}, "disagreement": {}},
   "recall": {"A": 0.8, "B": 0.6},
   "pairwise_win_rate": 0.67,
   "answerability_pct": 82.5,
   "fixes": []}
  ```
- `copy_<k>/`: the planted copies; `_keys/`: the answer keys and the pair mapping. Reviewers never read
  `_keys/`.

## `_pipeline/exam_dates.json` (the user)
`{"_note": "...", "CN": {"midsem": "2026-09-22", "endsem": null}, ...}`. Dates are ISO `YYYY-MM-DD` or
`null`. The orchestrator orders batches by them.
