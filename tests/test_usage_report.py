"""usage_report.py: tokens per agent from Claude Code transcripts (the cost baseline for every run).

A synthetic project folder: one main session jsonl with 2 assistant turns (one repeated message id, counted
once) and a subagent jsonl with an image Read and a build call. Checks the totals, the per-agent row (first
prompt line), the image-read count, and --json output.
"""
import json, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
TMP = HERE / "_tmp" / "usage"
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({str(detail)[:500]})" if detail else ""))
    fails += not ok


if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)
sid = "11111111-2222-3333-4444-555555555555"


def turn(mid, cr, cc, out, content=None):
    return {"type": "assistant", "message": {"id": mid, "usage": {"input_tokens": 1, "cache_read_input_tokens": cr,
                                                                  "cache_creation_input_tokens": cc, "output_tokens": out},
                                             "content": content or []}}


main = [{"type": "user", "message": {"content": "generate the endsem notes for CN"}},
        turn("m1", 1000, 100, 50), turn("m1", 1000, 100, 50), turn("m2", 2000, 0, 70)]
(TMP / f"{sid}.jsonl").write_text("\n".join(json.dumps(x) for x in main), "utf-8")
sub = TMP / sid / "subagents"
sub.mkdir(parents=True)
agent = [{"type": "user", "message": {"content": "Read pack CN/work/endsem/packs/notes.md and write the notes"}},
         turn("a1", 5000, 500, 300, [{"type": "tool_use", "id": "t1", "name": "Read",
                                      "input": {"file_path": "C:/x/qa/atom_notes_T01/sheet-01.png"}}]),
         turn("a2", 9000, 0, 200, [{"type": "tool_use", "id": "t2", "name": "Bash",
                                    "input": {"command": "py _pipeline/tools/build.py CN --scope endsem --atom notes/T01"}}])]
(sub / "agent-abc.jsonl").write_text("\n".join(json.dumps(x) for x in agent), "utf-8")

r = subprocess.run([sys.executable, str(PIPE / "tools" / "usage_report.py"), "--dir", str(TMP), "--session", sid],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
out = r.stdout + r.stderr
check("exit 0", r.returncode == 0, out)
check("main: 2 turns (repeated message id once), 3102 input-side", "MAIN turns=2" in out and "in=3102" in out, out)
check("agents: 1 agent, 14502 input-side, 500 output", "AGENTS n=1" in out and "in=14502" in out and "out=500" in out, out)
check("agent row names its first prompt", "Read pack CN/work/endsem/packs/notes.md" in out, out)
check("image reads and build calls counted", "images=1" in out and "builds=1" in out, out)
r = subprocess.run([sys.executable, str(PIPE / "tools" / "usage_report.py"), "--dir", str(TMP), "--session", sid, "--json"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
try:
    j = json.loads(r.stdout)
    check("--json: totals", j["main"]["turns"] == 2 and j["agents_total"]["in"] == 14502, j)
except ValueError:
    check("--json parses", False, r.stdout[-300:])

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
