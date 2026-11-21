# Roadmap

Ordered by how much each item would improve what a student gets, then by cost. Each item names its evidence
of success, so it can be closed by a test or a number instead of an opinion.

## Next

1. **Score the planner after each real exam.**
   Bank the new paper, run `backtest.py --post-exam`, and record predicted against actual coverage per course.
   *Done when:* every course has a post-exam row, and the table is published with the misses.
2. **Convention-consistency checker.**
   Most real review findings were one fact stated two ways (a formula, a rounding rule, a sequence-number
   convention). The blueprint stage should propose a convention for every recurring numeric idea, and a script
   should check every boxed answer against it.
   *Done when:* the five historical inconsistencies in `AUTORESEARCH_LOG.md` are caught by a test.
3. **A fully public sample guide.**
   Run the pipeline on openly licensed course material and publish the complete guide with its web edition.
   *Done when:* a stranger can read a whole guide without any university's exam papers being redistributed.
4. **Important-question chapter from the planner.**
   `score.py` should emit the tier skeleton and writers should own one file per idea, so a re-plan never needs
   a manual regroup.
   *Done when:* moving an idea between tiers changes no hand-written file.
5a. **One likelihood wording everywhere.** The guides print a band only for courses with fewer than four
   papers and a percentage otherwise; the planner does not beat the base rate (see the case study), so print a
   band for every course. *Done when:* a lint rule finds no printed per-idea percentage in any guide.

## Later

5. **A planner that beats the base rate.** Pool evidence across courses with a hierarchical model; report
   calibration (Brier, reliability) and not only coverage. *Done when:* held-out Brier beats the flat base rate
   on at least three courses.
6. **Cheaper orchestration.** The orchestrating session is now the largest cost line (about 340 M input-side
   tokens over three sessions). Batch its turns and move whole phases into single commands.
   *Done when:* a course costs under 100 M tokens in total, not only for the writers.
7. **Second agent runner.** The pipeline is plain files. Run one course end to end under a different coding
   agent and record what breaks. *Done when:* the same gates pass with no pipeline change.
8. **Other universities.** Package the subject template, the PYQ-window config and the exam-pattern config so a
   new syllabus needs configuration only.
9. **Reader feedback loop.** An error-report form whose confirmed reports become regression tests or check
   scripts, and spaced repetition in the web edition's self-test mode.
10. **Linux-native toolchain.** TeX Live and a container image, so the whole gate (not only the TeX-free
    subset) runs outside Windows.

## Not planned

- A hosted service that accepts uploads of course material: it would mean storing other people's copyrighted
  notes and papers, and an open endpoint in front of a paid model.
- Predicting exact questions. The planner ranks topics by expected marks and says how uncertain it is.
