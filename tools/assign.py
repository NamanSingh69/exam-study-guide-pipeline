"""Write work/<scope>/assignments.json from blueprint.json + pyq_bank.json + important_questions.json
(00_orchestrator.md Phase C), with the lean writer split of RUNBOOK.md.

    py _pipeline/tools/assign.py <SUBJ> --scope S [--dry-run]

- full papers: the 3 newest in-window papers of the scope's own exam (endsem/midsem), newest first (in a year the
  autumn sitting is after the spring one); chapters 700_.. ; the other in-window papers are "older" (7NN_, newest
  first). Out-of-window papers get no chapter and own no solve.
- solve owners, first rule that applies: (1) asked in a full paper -> pyq-full, anchor = newest such question,
  chapter = that paper's; (2) asked only in older in-window papers -> the older writer of the anchor's paper,
  chapter 62_older_ideas; (3) in targets.iq_clusters -> pyq-full (the IQ author), chapter 60, anchor null;
  (4) none.
- writers: notes-A / notes-B split the in-scope units into two contiguous halves balanced by topic count (one
  notes writer when there are <= 24 topics); older papers go to pyq-older-A, -B, .. in groups of <= 10.
- keeps keys already in assignments.json that this tool does not own (papers, transcribe, multi_set_papers, ...).
Exit 0 written, 1 inputs missing, 2 usage error.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workdir import resolve, setup_stdout  # noqa: E402

OWNED = ("full_papers", "older_papers", "chapters", "atoms", "solve_owners", "figures", "writers", "one_pdf",
         "lean_note")
SESSION_RANK = {"spring": 1, "summer": 2, "autumn": 3, "fall": 3}


def load(p):
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def paper_key(p):
    s = str(p.get("session", "")).lower()
    rank = SESSION_RANK.get(s, 1 if re.search(r"SP", str(p.get("id", ""))) else 3)
    return (int(p.get("year") or 0), rank, str(p.get("id")))


def qno_key(q):
    return [int(x) if x.isdigit() else x for x in re.findall(r"\d+|[A-Za-z]+", str(q.get("qno", "")))]


def letters(n):
    return [chr(ord("A") + i) for i in range(n)]


def build(bp, bank, iq, scope):
    win = bp.get("pyq_window") or {}
    lo, hi = int(win.get("from", 0)), int(win.get("to", 9999))
    plist = bank["papers"] if isinstance(bank["papers"], list) else list(bank["papers"].values())
    inwin = [p for p in plist if lo <= int(p.get("year") or 0) <= hi and (p.get("weight", 1) or 0) > 0]
    inwin.sort(key=paper_key, reverse=True)
    own_exam = [p for p in inwin if str(p.get("exam", "")).lower() == scope]
    full = [p["id"] for p in own_exam[:3]]
    older = [p["id"] for p in inwin if p["id"] not in full]
    n_old_w = max(1, -(-len(older) // 10)) if older else 0
    old_groups = {}
    if older:
        size = -(-len(older) // n_old_w)
        for i, pid in enumerate(older):
            old_groups[pid] = f"pyq-older-{letters(n_old_w)[i // size]}"

    # notes writers
    units = [u for u in bp.get("units", []) if u.get("in_scope", True)]
    topics_of = {u["id"]: [t["id"] for t in u.get("topics", []) if t.get("in_scope", True)] for u in units}
    total = sum(len(v) for v in topics_of.values())
    unit_writer = {}
    if total <= 24:
        unit_writer = {u["id"]: "notes-A" for u in units}
    else:
        run, best = 0, None
        for i, u in enumerate(units[:-1]):
            run += len(topics_of[u["id"]])
            gap = abs(total - 2 * run)
            if best is None or gap < best[0]:
                best = (gap, i)
        cut = best[1] if best else 0
        for i, u in enumerate(units):
            unit_writer[u["id"]] = "notes-A" if i <= cut else "notes-B"
    writers = {}
    atoms = {}
    for u in units:
        w = unit_writer[u["id"]]
        for t in topics_of[u["id"]]:
            writers.setdefault(w, []).append(t)
            atoms[f"notes/{t}"] = w
    last_notes = "notes-B" if "notes-B" in writers else "notes-A"

    # chapters
    chapters = [{"stem": u["chapter"], "kind": "unit", "unit": u["id"], "owner": unit_writer[u["id"]]}
                for u in units if u.get("chapter")]
    chapters += [{"stem": "60_important_questions", "kind": "iq", "owner": "pyq-full"}]
    stem_of = {}
    for i, pid in enumerate(full + older):
        stem_of[pid] = f"{700 + i}_pyq_{pid.lower()}"
    # solve owners
    order = {pid: i for i, pid in enumerate(full + older)}           # 0 = newest
    qs = [q for q in bank.get("questions", []) if q.get("in_scope", True) and q.get("paper") in order and q.get("cluster")]
    by_cluster = {}
    for q in qs:
        by_cluster.setdefault(q["cluster"], []).append(q)
    iq_list = ((iq or {}).get("targets", {}).get("iq_clusters", {}) or {}).get("clusters", []) or []
    cids = [c["id"] if isinstance(c, dict) else c for c in
            (bank.get("clusters") if isinstance(bank.get("clusters"), list) else list(bank.get("clusters") or {}))]
    for c in iq_list:
        if c not in cids:
            cids.append(c)
    solve = {}
    for cid in cids:
        cq = sorted(by_cluster.get(cid, []), key=lambda q: (order[q["paper"]], qno_key(q)))
        in_full = [q for q in cq if q["paper"] in full]
        if in_full:
            a = in_full[0]
            solve[cid] = {"owner": "pyq-full", "chapter": stem_of[a["paper"]], "anchor": a["id"]}
        elif cq:
            a = cq[0]
            solve[cid] = {"owner": old_groups[a["paper"]], "chapter": "62_older_ideas", "anchor": a["id"]}
        elif cid in iq_list:
            solve[cid] = {"owner": "pyq-full", "chapter": "60_important_questions", "anchor": None}
    if older:
        chapters.append({"stem": "62_older_ideas", "kind": "solved_ideas", "owner": "pyq-older-A"})
    chapters.append({"stem": "65_q1_drill", "kind": "recall", "owner": last_notes})
    for pid in full:
        chapters.append({"stem": stem_of[pid], "kind": "pyq_full", "paper": pid, "owner": "pyq-full"})
    for pid in older:
        chapters.append({"stem": stem_of[pid], "kind": "pyq_older", "paper": pid, "owner": old_groups[pid]})
    chapters += [{"stem": "80_mock_paper", "kind": "mock", "owner": "pyq-full"},
                 {"stem": "cheatsheet", "kind": "cheatsheet", "owner": last_notes}]
    figures = {}
    for f in bp.get("figure_plan", []) or []:
        if f.get("fig") and f.get("owner"):
            figures[f["fig"]] = re.sub(r"^atoms/", "", f["owner"])
    return {"full_papers": full, "older_papers": older, "chapters": chapters, "atoms": atoms, "solve_owners": solve,
            "figures": figures, "writers": writers, "one_pdf": True,
            "lean_note": "assign.py: notes writers " + ", ".join(sorted(writers)) + "; pyq-full; "
                         + ", ".join(sorted(set(old_groups.values())))}


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("subject")
    ap.add_argument("--scope", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    subj_dir, shared, work = resolve(a.subject, a.scope)
    bp, bank = load(work / "blueprint.json"), load(work / "pyq_bank.json")
    iq = load(work / "important_questions.json")
    if not bp or not bank:
        print("blueprint.json and pyq_bank.json are required (run the gate first)", file=sys.stderr)
        sys.exit(1)
    new = build(bp, bank, iq, work.name)
    f = work / "assignments.json"
    old = load(f) or {}
    out = {k: v for k, v in old.items() if k not in OWNED}
    out.update(new)
    if not a.dry_run:
        f.write_text(json.dumps(out, indent=1, ensure_ascii=False), "utf-8")
    owners = {}
    for c in new["chapters"]:
        owners.setdefault(c["owner"], 0)
        owners[c["owner"]] += 1
    print(f"ASSIGN {a.subject} {work.name}: full {new['full_papers']}, older {len(new['older_papers'])}, "
          f"{len(new['atoms'])} atoms, {len(new['solve_owners'])} solves, chapters per owner {owners}"
          + (" (dry run)" if a.dry_run else ""))


if __name__ == "__main__":
    main()
