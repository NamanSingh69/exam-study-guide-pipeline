"""Tokens per agent from Claude Code transcripts: the cost measurement for a pipeline run.

    py _pipeline/tools/usage_report.py [--dir <~/.claude/projects/<project>>] [--session <id> | --since 2026-11-10]
                                       [--top 10] [--json]

Default --dir: the Claude Code project folder of the `Study Prep` folder. Counts, per session: main-session
turns and input-side tokens (input + cache read + cache creation; a repeated message id counts once) and
output tokens; per subagent (<session>/subagents/*.jsonl) the same, plus image reads (Read of .png/.jpg) and
build calls. Input-side tokens are what the usage limit mostly spends: every turn re-reads the whole context.
Compare a run against the baseline in _pipeline/docs/COST.md.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def default_dir():
    root = Path(__file__).resolve().parents[2]
    mangled = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    return Path.home() / ".claude" / "projects" / mangled


def scan(path: Path):
    tot = {"turns": 0, "in": 0, "out": 0, "images": 0, "builds": 0, "prompt": ""}
    seen = set()
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") or {}
        if not isinstance(m, dict):
            continue
        if not tot["prompt"] and d.get("type") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
            tot["prompt"] = re.sub(r"\s+", " ", str(c or ""))[:100]
        us = m.get("usage")
        if us and m.get("id") not in seen:
            seen.add(m.get("id"))
            tot["turns"] += 1
            tot["in"] += sum(us.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            tot["out"] += us.get("output_tokens") or 0
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                inp = b.get("input") or {}
                if b.get("name") == "Read" and re.search(r"\.(png|jpe?g)$", str(inp.get("file_path", "")), re.I):
                    tot["images"] += 1
                if b.get("name") in ("Bash", "PowerShell") and "build.py" in str(inp.get("command", "")):
                    tot["builds"] += 1
    return tot


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", type=Path, default=None)
    ap.add_argument("--session")
    ap.add_argument("--since", help="YYYY-MM-DD: sessions whose transcript changed on or after this date")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = a.dir or default_dir()
    sessions = sorted(d.glob("*.jsonl"))
    if a.session:
        sessions = [p for p in sessions if p.stem == a.session]
    if a.since:
        t0 = datetime.strptime(a.since, "%Y-%m-%d").timestamp()
        sessions = [p for p in sessions if p.stat().st_mtime >= t0]
    if not sessions:
        print(f"no transcripts in {d}", file=sys.stderr)
        sys.exit(2)
    main_t = {"turns": 0, "in": 0, "out": 0}
    agents = []
    for s in sessions:
        t = scan(s)
        for k in main_t:
            main_t[k] += t[k]
        for p in sorted((d / s.stem).rglob("*.jsonl")) if (d / s.stem).is_dir() else []:
            agents.append(scan(p))
    at = {k: sum(x[k] for x in agents) for k in ("turns", "in", "out", "images", "builds")}
    if a.json:
        print(json.dumps({"sessions": [s.stem for s in sessions], "main": main_t, "agents_total": at,
                          "agents": sorted(agents, key=lambda x: -x["in"])[:a.top]}, indent=1))
        return
    print(f"SESSIONS {len(sessions)}  ({d})")
    print(f"MAIN turns={main_t['turns']} in={main_t['in']} out={main_t['out']}"
          f"  (mean context {main_t['in'] / max(main_t['turns'], 1) / 1000:.0f}k)")
    print(f"AGENTS n={len(agents)} turns={at['turns']} in={at['in']} out={at['out']} images={at['images']} builds={at['builds']}")
    for x in sorted(agents, key=lambda x: -x["in"])[:a.top]:
        print(f"  in={x['in'] / 1e6:6.1f}M out={x['out'] / 1e3:5.0f}k turns={x['turns']:4} ctx={x['in'] / max(x['turns'], 1) / 1000:4.0f}k "
              f"images={x['images']:3} builds={x['builds']:3}  {x['prompt']}")


if __name__ == "__main__":
    main()
