# Stage 1b: Vision transcription of POOR notes pages (only the pages this scope needs)

Run this only for **notes** files that `work/corpus/INDEX.md` marks `POOR` (low OCR confidence: handwritten
or scanned), and only for the pages the scope needs:
- midsem: the in-scope units' decks
- the pages cited by in-scope PYQs
- never the post-cutoff decks in a midsem run

Each agent takes about 40 pages. These agents run in parallel with the blueprint and the transcribers. The
work is done once; every writer then reads clean text instead of re-reading images.

**Assignment:** subject `<SUBJ>`, corpus slug `<SLUG>`, pages `<FROM>`–`<TO>`.

**Read:** `work/note_pages/<SLUG>_p<N>.png` for each page, with your image reader. The garbled OCR in
`work/corpus/<SLUG>.md` is a hint only.

**Skip:** `work/corpus/<SLUG>__vision_p<FROM>-<TO>.md` already exists and covers these pages (resume).

**Write:** `work/corpus/<SLUG>__vision_p<FROM>-<TO>.md`. Use the corpus page tags, so citations stay valid:
```
## [<SLUG> p<N>] (vision)
<faithful transcription: headings, bullets, formulas in LaTeX ($...$), tables as | rows |>
[FIGURE: one paragraph per diagram: boxes, arrows, labels and what it shows, precise enough to redraw in
 TikZ. Image: work/note_pages/<SLUG>_p<N>.png]
[ILLEGIBLE: <what is unreadable>]
```

**Rules:**
- Transcribe; do not explain or add content.
- Keep the instructor's notation, numbering and the worked examples' numbers exactly. Mark examples
  "Example:" with their given values. Writers use these examples in the notes.
- **POOR flag.** A page that stays mostly unreadable even in the image gets the heading
  `## [<SLUG> p<N>] (vision, POOR)` and an `[ILLEGIBLE: ...]` line. The blueprint lowers that unit's source
  confidence.

**Report** (≤ 6 lines): pages done, figures described, worked examples found, the POOR pages.
