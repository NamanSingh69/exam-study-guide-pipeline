# Stage 4b: Answerability check (a fresh agent that wrote nothing)

**The question you answer:** if one of these questions appears in the exam, does the guide contain what a
student needs to answer it for full marks? You measure the guide's *teaching*, not its copy of the answer.

**Assignment:** subject `<SUBJ>`, scope `<scope>`, round `<r>`, and the question set. Take the first that
exists:
1. the question ids or a text file the brief gives (held-out or newly sat papers)
2. otherwise, every in-scope question of the **newest relevant paper** in `pyq_bank.json`

**Read:**
- the guide: `<SUBJ>/work/<scope>/chapters/`, `atoms/` and the built `build/guide/guide.pdf` (for page
  numbers)
- the question text: `pyq_bank.json`, or the given file

**Excluded from the search:** you may not use these, because they hold the question's own answer:
- the PYQ chapter of the held-out paper
- the solve atoms whose anchor is a held-out question (`assignments.json → solve_owners`)

Everything else counts: notes atoms, other solve atoms, important questions, the drill and the cheatsheet.

## For each question
1. **Write down the pieces a full-marks answer needs:** facts, definitions, formula, method, diagram,
   standard values.
2. **Find where each piece lives:** a label (`sec:T15`, `solve:C09`, `iq:C09`) and the PDF page. Search the
   `.tex` with Grep and the PDF text with `py` + pymupdf.
3. **Judge:**
   - **`full`:** every piece is present, and a student could assemble the answer from it in the exam.
   - **`partial`:** some pieces are missing, or present only as a one-line mention. Name what's missing.
   - **`none`:** the guide doesn't teach it.
4. **Numericals:** solve the question from the guide's material only, in `py`. If the guide's formula or
   method gives the wrong answer, the verdict is `none`, with the reason.

## Output: `<SUBJ>/work/<scope>/reviews/answerability_r<r>.json`
```json
{"round": 1, "question_set": "newest relevant paper ES2025",
 "excluded": ["chapters/700_pyq_es2025.tex", "atoms/solve/C12.tex"],
 "items": [{"qid": "ES2025-3a", "marks": 5, "verdict": "full|partial|none",
            "found_in": [{"label": "sec:T15", "page": 41}], "missing": "", "why": "one line"}],
 "coverage_pct": 0.0,
 "by_unit": {"U3": {"marks": 20, "covered": 17.5}}}
```
- **`coverage_pct`** = 100 × Σ marks × (1 for full, 0.5 for partial, 0 for none) / Σ marks.
- **`missing`:** for every `partial`/`none`, state what to add and to which atom. The orchestrator turns these
  into fixes.

**Report** (≤ 6 lines): the coverage %, the weakest unit, and the 3 most valuable additions.
