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
| model tiers | main-model transcriber and fixer | Sonnet for gated mechanical work; writers pending the A/B |
| lean mode (2026-11-08) | ~20 agents per subject | ~6 agents per subject |

**Target:** ≤ 100 M input-side tokens per subject at the same gates and review scores.

## Runs after the refactor
| date | subject/scope | agents | main turns | input-side total | writers' mean context | images | notes |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
