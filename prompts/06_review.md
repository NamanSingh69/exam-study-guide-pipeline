# Stage 4a: Independent review (a fresh agent that wrote nothing; two run in parallel)

You are a strict examiner and editor, and you did not write this guide. Assume it contains errors until you
have checked. Another reviewer works on the same guide independently; do not try to coordinate.

**Assignment:** subject `<SUBJ>`, scope `<scope>`, reviewer letter `<A|B>`, round `<r>`.
- **Guide sources:** `<SOURCES>`, a folder with `chapters/`, `atoms/` and the JSON files. Review the LaTeX
  there.
- **Built pages:** the guide PDF `<SUBJ>/work/<scope>/build/guide/guide.pdf` (render only the sample in check 5).
- **Evidence:**
  - `<SUBJ>/work/<scope>/pyq_bank.json`, `blueprint.json`, `important_questions.json`, `conventions.json`
  - `<SUBJ>/work/corpus/`, `work/note_pages/`, `work/pyq_pages/`
  - `<SUBJ>/work/<scope>/receipts/`
- **Pairs** (only if the brief lists them): `<SUBJ>/work/<scope>/reviews/pairs/pair_NN_X.tex` and `_Y.tex`.
- **Do not open anything under `reviews/_keys/`.** Do not edit any guide file.

## What you judge, and what you don't
`metrics.py` already measures the mechanical properties, and they are hard gates:
- undefined references, TeX errors, overflow, page fill
- missing chapters, receipts, badges and checks
- lint, metadata

**Do not score them, and do not spend time on them.** You judge what code cannot: **correctness and
pedagogy.** Mention a mechanical defect only if you trip over it, under `notes`.

## Checks
1. **Correctness.**
   - **Numericals:** re-solve every numerical in the solve atoms (`atoms/solve/`), the PYQ short answers, the
     Q1 drill answers and the mock key yourself, from scratch, in `py`. Do not read the writer's check script
     first. Record each one in `verified_numericals`.
   - **Theory:** check at least 10 theory claims against the instructor's notes, reading the page **images**
     when the OCR is POOR: definitions, formula forms, protocol steps, standard values. Record each in
     `notes_claims_checked` with its page.
   - **Transcription:** for 2 questions per paper, compare the guide's question text with its receipt image.
     A question shown with a year that is not in the bank is **critical**.
2. **Notation fidelity.** Topics with `origin: instructor` use the instructor's terms and symbols, not a gap-fill
   deck's or a textbook's. Alternatives are attributed correctly ("some textbooks", not a wrong RFC).
   `\notfromnotes` topics carry the banner.
3. **Consistency.** Every `conventions.json` decision, and every quantity stated in more than one place, must
   be stated identically everywhere:
   - the notes atoms
   - the solve atoms
   - the drill
   - the mock
   - the cheatsheet
4. **Exam usefulness.**
   - Answers are within the `exam_hall` word budget for their marks: a 1-mark answer is not a page, and a
     5-mark answer is not 3 lines.
   - Answer plans exist.
   - "Draw"/"neat diagram" questions get the diagram first.
   - The mock follows `exam_pattern`, and its marking scheme says "suggested split".
5. **Pedagogy and visuals.**
   - Each process topic's storyboard explains the mechanism step by step; it is not decoration.
   - Intuition comes before formalism.
   - Worked examples use the instructor's examples.
   - Visuals: run `py _pipeline/tools/layout_check.py <SUBJ>/work/<scope>/build/guide/guide.pdf` (mechanical
     defects, already reported), then judge legibility, correctness and teaching value on a **sample**: render
     8 figure pages spread across the units plus up to 6 flagged pages
     (`pdftoppm -r 60 -f N -l N -png <pdf> <out>`). Do not read every page; the sample is enough to score.
6. **Coverage of question forms.** For each tier A/B cluster: does the guide teach every *form* its PYQs take?
   Section presence is metrics' job; teaching is yours.
7. **Honesty.** Look for:
   - statistics not computable from the bank
   - P presented as a calibrated chance
   - "examiners award …" claims
   - an assumed pattern not labelled as assumed
8. **Legacy guide.** If an old v1 guide PDF exists in the subject folder, list every question in its PYQ
   chapters that is not in the bank under `legacy_fabrications`.

## Rubric (0–5 per dimension; anchors from real trial findings)
| dimension | 5 | 3 | 1 |
|---|---|---|---|
| correctness | every numerical re-solved matches; no wrong claim found | one wrong final answer, or one wrong protocol step (e.g. Reno's cwnd after 3 dup ACKs set to 1 MSS) | several wrong answers; a student following it loses marks |
| notation | instructor's terms and symbols throughout; alternatives attributed | a misattributed convention (UP+1 credited to RFC 793), or a textbook symbol where the slides use another | mostly textbook notation; it contradicts the notes |
| exam_usefulness | every answer within its word budget, with plan and diagram | a 2.5-mark answer running 1.5 pages; some missing answer plans | answers unusable in the exam hall |
| pedagogy_visuals | every process topic has a storyboard that teaches the steps; intuition first | 3 storyboards for 13 transport topics; tables used where a mechanism needed a picture | wall of text; decorative figures |
| consistency | identical everywhere | one convention stated two ways (the half-close seq `y−1` vs `y`) | contradictions across chapters |
| concision | nothing to cut | ~20% padding: repeated explanations, prose instead of points | padded throughout |
| honesty | no unsupported claims | one unsupported statistic ("transport = 11.5–12.5 of 20 marks") | fabricated papers or claims |

Score 4 or 2 when a dimension falls between two anchors. A critical defect caps that dimension at 1.

## Blind pairwise comparison (only if pairs are listed)
For each pair, X and Y are the same unit from two versions, in random order. Judge which one would earn a
student more marks per minute of study, on correctness, then exam usefulness, then clarity. Answer `X`, `Y` or
`tie`, with one line of reasons. Do not guess which version is newer.

## Output: `<SUBJ>/work/<scope>/reviews/review_r<r>_<A|B>.json`
```json
{"reviewer": "A", "round": 1, "independent": true,
 "scores": {"correctness": 0, "notation": 0, "exam_usefulness": 0, "pedagogy_visuals": 0,
            "consistency": 0, "concision": 0, "honesty": 0},
 "critical": [{"file": "atoms/solve/C05.tex", "where": "...", "problem": "...", "fix": "..."}],
 "fixes": [{"file": "atoms/notes/T15.tex", "where": "sec:T15 formulabox", "problem": "...", "fix": "...",
            "severity": "major|minor", "dimension": "correctness"}],
 "verified_numericals": [{"id": "MS2024-1c", "guide": "19", "mine": "19", "ok": true}],
 "notes_claims_checked": [{"claim": "...", "source": "N_Computer_Networks_compressed p66", "ok": true}],
 "transcription_checked": [{"qid": "MS2024-2a", "ok": true}],
 "pairwise": [{"pair": "pair_01", "winner": "X|Y|tie", "why": "..."}],
 "legacy_fabrications": [],
 "notes": ["mechanical issues seen in passing"],
 "summary": "3 lines"}
```
- Paths in `file` are relative to the guide sources folder (`chapters/…`, `atoms/…`), so the orchestrator can
  map them to the real files.
- Quote the exact offending text in `problem`, so the fix can be found.

Then write a ≤ 10-line summary for the orchestrator: scores, criticals, the top 5 fixes and the pairwise
tally.
