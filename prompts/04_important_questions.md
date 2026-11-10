# Stage 2c: Important questions in study order, and the mock paper (one agent per subject)

Read `_pipeline/prompts/_writer_contract.md` first. It is binding.

**Assignment:** subject `<SUBJ>`, scope `<scope>`. Write:
- `chapters/60_important_questions.tex`
- `chapters/80_mock_paper.tex`
- the solve atoms `atoms/solve/<Cid>.tex` that `assignments.json → solve_owners` gives to
  `60_important_questions`: clusters in `targets.iq_clusters` with no in-window PYQ. Older-paper-only clusters
  belong to the older-PYQ agents and are printed in `62_older_ideas`.

**Size:** the chapter covers **exactly** `important_questions.json → targets.iq_clusters`: the 12 h plan's
clusters plus at most 5 tier-D wildcards, quoted in your brief with its `why`. Never add or drop one. Every
other cluster appears only in the one-line tier E index.

**Window:** only in-window PYQs (`blueprint.json → pyq_window`) are ever cited.

**Read:**
- `work/<scope>/important_questions.json`:
  - `clusters`: tier, `question_ids`, P or band, EV, `effort_min`
  - `plans`
  - `exam_hall`
  - `must_draw`
  - `skip_safety`
- `pyq_bank.json`, `blueprint.json` (pattern, `exam_pattern.assumed`), `assignments.json`, `conventions.json`
- the corpus pages of each cluster's topic

## Tiers are study order, not probability
score.py's planner chooses the clusters that maximise the expected *attainable* marks for 3, 6 and 12 hours
of study. The plans are nested.

| tier | meaning |
|---|---|
| A | in the 3-hour plan |
| B | added by the 6-hour plan |
| C | added by the 12-hour plan |
| D | wildcard: never asked, strongly taught |
| E | the rest |

Never call a tier "must"/"likely", and never quote P as a calibrated chance. The badge shows P as a percent
only when there are ≥ 4 relevant papers, otherwise as a band.

## 60_important_questions.tex
```
\chapter{Important questions in study order}
  3-line intro: tiers = the planner's 3 h / 6 h / 12 h plans (point to the Exam Radar, \ref{ch:radar});
    work top-down and stop where your time ends
  \section{Tier A: the 3-hour plan}   \section{Tier B: add these for 6 hours}
     per cluster, in syllabus order (unit, then topic order) within the tier:
       \subsection*{<cluster label>}\label{iq:<Cid>}   then on the next line \clusterbadge{<Cid>}
       one "why" line, computed from the bank only: asked k of n relevant papers, latest year, marks
         typical, in the seniors' list, class signal
       forms to practise: \pyqsolved{<qid>} for every in-window question_id of the cluster (guide or
         archive)
       the solution: \input{atoms/solve/<Cid>} if you own it, otherwise \seesolved{<Cid>}
       answerplan (≤ 3 lines): the marks-earning skeleton for this idea
       one practice variant (new numbers or a twist): question only; its answer goes to the
         "Variant answers" section at the end, checked by checks/<Cid>_variant.py
  \section{Tier C: add these for 12 hours}   per cluster: label + \label{iq:<Cid>}, badge, \seesolved or
     your own solve, a 3–5 line answer outline, the practice links as above
  \section{Tier D: wildcards}   only the wildcards in targets.iq_clusters (≤ 5); per cluster: label +
     \label{iq:<Cid>}, why it is a risk (lecture time, seniors' list), your solve atom, the answerplan
  \section*{Index of the rest}   a one-line index only: one line per remaining cluster (tier E and any
     wildcard beyond the 5): label, \clusterbadge, \S\ref{sec:<Tid>}. No solutions, no iq: labels
  \section{Must-draw diagrams}   from must_draw (in-window only): each diagram with \seesolved / \pyqsolved
     page links
  \section*{Variant answers}   compact answers for every variant above (final values + 2–4 key points)
```
- **Solve atoms you own** (anchor `null`): write an `Expected` question first, from the seniors' list or the
  lesson-plan wording, then solve it. Use the same rules as `03_pyq_solutions.md`, within the `exam_hall` word
  budget. Never print an out-of-window question, even when the cluster was asked before the window.
- **Completeness:** every cluster in `targets.iq_clusters` appears with `\label{iq:<Cid>}`, because the radar
  and "How to use" link to these labels. No other cluster gets one. `metrics.py` reports
  `iq_count_vs_target`.

## 80_mock_paper.tex: a predicted paper in the exact pattern
- **Header:** copy the real format, sub-part marks exactly as in `exam_pattern`:
  - full marks, duration
  - instructions
  - the compulsory and choice structure

  If `exam_pattern.assumed` is true, title it "Mock paper (pattern assumed: <source>)".
- **Choose the questions** to maximise the coverage of tier A/B clusters:
  - Q1-type compulsory parts come from short clusters.
  - Each optional question pairs ideas from different units.
  - Include at least one wildcard (tier D).
  - Use fresh numbers; never copy a PYQ verbatim.
- **`\section*{Answer key}`:** per question, compact answers (final values + 2–4 key points) and a marking
  scheme labelled **"suggested split"** (e.g. "suggested split: diagram 1, explanation 1.5"). It is never
  presented as the examiner's scheme. Numericals get `checks/mock_Q<n>.py`.
- **Mapping table:** mock Q → cluster → `\clusterbadge`, so the student sees why each question is there.

Build each solve atom you own (`--atom solve/<Cid>`), then both chapters (`--chapter`). Run the contract's
self-check loop and report.
