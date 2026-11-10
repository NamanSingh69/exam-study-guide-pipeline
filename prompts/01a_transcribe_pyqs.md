# Stage 1a: Transcribe past papers verbatim (one agent per 3–4 papers, run in parallel)

**Assignment:** subject `<SUBJ>`, scope `<scope>`, papers `[<paper id> = <slug>, ...]`. The orchestrator fixed
the ids; never rename them.

**Output:** one file per paper, `<SUBJ>/work/<scope>/pyq_bank.part_<paper id>.json`, in the part-file shape
from `_pipeline/schemas.md`. You write no LaTeX, and you do not assign topics, clusters or `in_scope`: the
merge agent does that.

**Read, for each paper:**
- its page images `work/pyq_pages/<slug>_p<N>.png`, with your image reader. These are the ground truth.
- its OCR/text layer `work/corpus/<slug>.md`, as a hint and for spotting OCR errors

## Rules
1. **Paper header.** `paper` holds:
   - `id`, `year`, and `session` (`spring` or `autumn`: a "6th Sem" paper is spring)
   - `exam` (`midsem`/`endsem`), `source_slug`, `course_code`
   - `full_marks`, `duration`
   - `instructions`: verbatim from the paper
   - `pattern`: a short machine-readable line such as `Q1 compulsory 5x1; any 3 of Q2-Q5`
   - `pages`: `[first, last]`, the page range of this paper's question set inside the PDF. Set it when one
     PDF holds several question sets.
   - `reading_order` (optional): for 2-up booklet scans, the order of the half-pages, e.g.
     `["1R","2L","2R","1L"]` (page number + Left/Right half)

   `verify_pyqs.py` checks that the banked marks add up to `full_marks` under this pattern, so write
   `pattern` in that form: `Q<n> compulsory <k>x<m>`, then `any <k> of Q<a>-Q<b>` (or `any 3 of the
   remaining four`).
   - The optional questions must carry equal marks, as printed. A mismatch means a sub-part is missing or
     extra: re-read the page.
   - A sub-part banked twice blocks the gate.
2. **One entry per sub-part that carries its own marks:** 1(a), 1(b), 2(a)… If one sub-part has two asks
   ("Define X. Calculate Y"), keep it as one entry.
   - Fields: `id` = `<paper id>-<qno compact>` (e.g. `MS2024-1c`, `ES2023-4b`), `paper`, `qno` as printed,
     `marks` (a JSON number, never `"2.5 M"`), `compulsory`, `text`, `type`, `verified`, `ocr_fixes`.
   - **Every sub-part on the page is banked.** The gate blocks a paper whose marks don't add up.
   - **"OR" alternatives** are both banked, with qno such as `4(a) OR`.
   - **"Answer any two of the following"** inside one question: keep that sentence in the first sub-part's
     text, so the gate can read the internal choice.
   - **A printed question number used twice** (the 2022 CN paper prints "3" twice): add a tag such as
     `3(a) [2nd Q3]` and add a warning.
3. **Text is verbatim from the image.**
   - Fix OCR errors only. Keep the examiner's grammar, spelling, numbers, units and symbols exactly.
   - Name **every** token you wrote differently from the paper's text layer in `ocr_fixes`, e.g.
     "‘4th’ was ‘Ath’ in OCR; ‘UDP’ was ‘UOP’".
     - The gate allows only max(1, 4 % of tokens) unexplained edits.
     - A number or ALL-CAPS token is excused only when it is named there *and* the question is
       `verified: "vision"`.
   - **Tables:** put exactly one `[table]` placeholder in `text`, plus
     `"table": {"header": [...], "rows": [[...], ...]}`.
     - No empty cells; write `-` where the paper prints a dash.
     - Requires `verified: "vision"` and a receipt.
   - **Formulas OCR can't read:** write them as `$...$` maths spans.
     - These spans are checked by vision + receipt only, so they need `verified: "vision"`.
     - They are capped at 60% of a question's tokens.
     - Currency such as `$17,000` stays plain text; write a literal `$` as `\$`.
   - A figure in the question: describe it in `figure` (one line). The receipt crop shows the real one.
   - Unreadable text: write what you can, put `[illegible]` in the gap, and add a warning.
   - **Never add, merge, reorder or "improve" a question.**
4. **`verified: "vision"`** only for sub-parts you actually compared with the image. Otherwise use `"ocr"`.
   Questions shorter than 4 tokens must be vision-verified.
5. **Receipts.** `receipts.py` crops each question from its page automatically, matching the text layer or
   OCR.
   - **When to add a manual `receipt` up front:** the paper's INDEX quality is `POOR`, or its text layer is
     garbage. Use `"receipt": {"page": <N>, "rect": [x0, y0, x1, y1]}` in PDF points.
     - **Convert from the image:** ingest renders `pyq_pages` at 170 dpi (`PYQ_RENDER_DPI` in `ingest.py`),
       so points = pixels × 72 / 170.
     - **The band:** use the full text width (x0 ≈ 30, x1 ≈ page width − 30). Run y0 from just above the
       sub-part's label to just below its last line.
   - **Later:** the orchestrator forwards `low-match receipt` lines. Add rects for those questions and set
     them `verified: "vision"`; a low match passes only with both.
   - **The image is still required.** The pair waives only the match threshold. `receipts.py` crops your rect
     into `receipts/<qid>.png`, and a missing PNG still blocks.
6. **Duplicates and strays.** Note each in `warnings`; the merge agent decides:
   - two of your papers are the same sitting
   - a paper is from another course
   - a paper has a different course code that looks like an alias
7. **Report** (≤ 8 lines per paper): sub-parts banked and the marks total vs `full_marks`, vision-verified
   count, manual receipts, illegible spots, warnings.

**On a gate fix from the orchestrator:** re-read the image for exactly the listed questions and fix only those
fields in your part file. Report what changed.
