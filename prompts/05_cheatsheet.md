# Stage 3a: Cheatsheet (one agent per subject, after the unit notes and the recall agent)

Read `_pipeline/prompts/_writer_contract.md` first. It is binding, except that §3 (length) and §4 (visuals)
are replaced by the density rules below.

**Assignment:** subject `<SUBJ>`, scope `<scope>`. Write `chapters/cheatsheet.tex`. It is built standalone as
a landscape PDF and appended to the guide:
`py _pipeline/tools/build.py <SUBJ> --scope <scope> --cheatsheet --render`.

**Read:**
- `conventions.json`: state every convention exactly as decided there
- every topic atom `atoms/notes/*.tex` of the in-scope units: the cheatsheet must agree with them
- `important_questions.json`: tiers, `exam_hall`, `must_draw`
- `atoms/recall/night_before.tex`, written by the recall agent; do not edit it

**Size:** `important_questions.json → targets.cheatsheet_pages` landscape pages (2–4), quoted in your brief with
its `why`. score.py gives one extra page for more than 20 in-scope topics, and one for a numerical share of the
window's marks above 40%. The night-before sheet comes on top of that. `metrics.py` reports
`cheatsheet_pages_vs_target`.

## Layout: `targets.cheatsheet_pages` landscape pages in 3 columns, then the night-before sheet
```
\chapter*{Cheatsheet}
\begin{multicols*}{3}\footnotesize
  \section*{<Unit>}  one block per unit, units in syllabus order
    formulas: one line each, "name: formula (symbols; units; when to use)"
    definitions: one line each, in the instructor's wording, only for terms examiners ask to define
    tiny comparison tables (X vs Y), ≤ 4 rows of the differences that score
    algorithm/protocol skeletons: 3–6 numbered steps + complexity or key numbers
    standard values: ports, constants, header sizes, defaults
  \section*{Exam hall}   minutes per mark and the word budget per marks value (from exam_hall)
  \section*{Traps}       the 8–12 commonest mistakes across the subject
  \section*{Tier A ideas} each cluster label with its answer in ≤ 1 line
  \section*{Mnemonics}   only genuinely useful ones
\end{multicols*}
\clearpage
\input{atoms/recall/night_before}
```

## Density rules
- **No prose:** no intuition paragraphs and no worked examples. One fact per line.
- **Emphasis:** `\keyword{}` for terms; `\answer{}` only for the 5–10 most important results.
- **Formatting:** plain `\section*` headings, `formulabox` only for true must-know formulas, small
  `tabular`s, and no floats.
- **Badges:** none. Tiers live in the guide.
- **Sketches:** only where one replaces many words: a TikZ of at most 3 cm, at most one per unit.
- **Page cap:** over `targets.cheatsheet_pages` before the night-before sheet? Cut tier D/E material first.
  Well under it? Add the tier A/B formulas and skeletons you left out; never pad.

The guide inserts the standalone PDF's pages, so **the standalone build is the one that counts**. Look at its
contact sheets (`qa/cheatsheet/`):
- readable at print size
- nothing clipped
- columns balanced
- the night-before answers start on a new page

Report the page count.
