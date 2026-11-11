# Cost of a run (usage-limit tokens), measured

Measure every run: `py _pipeline/tools/usage_report.py --since <YYYY-MM-DD>` (or `--session <id>`), then add a row
below. "Input-side" = input + cache-read + cache-creation tokens: every turn re-reads its whole context, so
**context size x turns** is what the usage limit spends. Output tokens are small next to it.

## Baseline: Round 4 runs, 2026-11-06 .. 2026-11-09 (before the cost refactor)
Sessions `4e0dc151` (CN, DAA, CI, EE, HPC, SE endsem, plus the Round 4 tool workstreams) and `7f0daca1` (SVP).

| part | agents | turns | input-side | output | mean context per turn |
|---|---|---|---|---|---|
| main session | 1 | 1,196 | 498 M | 0.9 M | 417 k |
| all subagents | 164 | ~10,300 | 2,330 M | 12.7 M | ~225 k |
| of which unit/PYQ writers | 52 | 10,045 | ~1,350 M (est.) | | 243 k (max 685 k) |
| of which Round 4 tool workstreams (one-off) | 5 | ~1,040 | 377 M | 1.4 M | 330–390 k |

Where the writers' context came from (tool calls in 52 writer transcripts):
- **3,500 image reads**: ~2,000 renders of their own pages (`qa/` contact sheets, scratch renders), ~850 PYQ page
  images and receipts of an already-gated bank, ~400 note pages. An image stays in context for every later turn.
- **~1,100 single-atom builds** and ~740 log greps (one turn each).
- Reading the 15 KB contract, 6 JSONs and whole corpus files at the start.

Per subject (rough, excluding tool development): **~250–350 M input-side tokens**.

## Changes made 2026-11-10 (AIDE² nodes C16–C19)
| change | what it removes | expected effect (estimate, to be measured) |
|---|---|---|
| `layout_check.py` + flagged-only contact sheets | ~2,000 self-render image reads | writers look at ~9% of pages (430 of 4,766 flagged across the 14 shipped PDFs) |
| writer card + `pack.py` | contract + JSON + whole-corpus reads | start context ~10–30 k (CN unit pack 29 KB, CN notes 84 KB, SE notes 113 KB, PYQ packs ~24 KB) |
| `--atom a,b,c --both` | ~1,100 build turns | one build call per writer pass, print and phone |
| `run_subject.py` | ~40 main-session turns per subject, log reading | 3 commands per subject, ≤ 15 lines each |
| model tiers | main-model transcriber, fixer and writers | Sonnet for gated mechanical work; writers on Sonnet since the 2026-11-10 blind A/B (Sonnet 4, main 1, tie 1; `ML/work/endsem/reviews/ab/verdict.json`) |
| lean mode (2026-11-08) | ~20 agents per subject | ~6 agents per subject |

**Target:** ≤ 100 M input-side tokens per subject at the same gates and review scores.

## Runs after the refactor
| date | subject/scope | agents | main turns | input-side total | writers' mean context | images | notes |
|---|---|---|---|---|---|---|---|
| 2026-11-10/11 | IPA endsem | 7 (4 writers, 1 review, 1 fix, 1 other) | shared | 91 M | ~13 M per writer | 70 | first subject under the 100 M target; Sonnet writers, packs, print only |
| 2026-11-10/11 | DOS endsem | 7 (4 writers, 1 review, 1 fix, 1 other) | shared | 171 M | ~32 M per writer | 106 | fix round added 36 checks |
| 2026-11-10/11 | AI endsem | 11 (5 writers, 1 review, 1 fix, 4 other) | shared | 178 M | ~25 M per writer | 263 | biggest bank (284 question blocks) |
| 2026-11-10/11 | DMDW endsem | 9 (5 writers, 1 review, 1 fix, 2 other) | shared | 221 M | ~33 M per writer | 189 | one writer re-reported repeatedly (stopped) |
| 2026-11-10/11 | ML endsem (review + fix only) | 2 | shared | 49 M | | 81 | writers ran before the window |
| 2026-11-10/11 | whole window (3 sessions) | 66 subagents | 1,167 | 340 M main + 1,149 M agents | | 1,482 | includes A/B test, 3 Sonnet tool builders, rebuild of all 12 guides |

Measured with `usage_report.py --since 2026-11-10 --top 400` (input-side = input + cache read + cache creation).
Per subject the refactor cut ~250–350 M to ~90–220 M; the main session is now the largest single line (340 M over
1,167 turns): orchestration turns re-read a long context, so fewer, batched main turns are the next lever.
