"""web.py collect_defs: a chapter-level \\newenvironment reaches the standalone figure renders (DMDW endsem 2026-11-10).

Three DMDW chapters define `olbox` (a box-plot environment) at top level, wrapped in \\ifcsundef{olbox}{..}{}; the
web edition compiles each figure standalone with the collected definitions, did not collect \\newenvironment, and
failed 3 renders with "Environment olbox undefined". The same definition in several chapters must not redefine it.
No TeX: checks the collected definition text.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")
import web  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    fails += not ok


CH = ("\\chapter{Older papers}\n\\ifcsundef{olbox}{%\n"
      "\\newenvironment{olbox}[9]{\\par\\noindent\\begin{minipage}{\\linewidth}#1}{\\end{minipage}\\par}%\n}{}\n"
      "\\begin{olbox}{4mm}{0}{30}{5}{2}{5}{12}{19}{29}\\end{olbox}\n")
defs = web.collect_defs(CH)
text = "\n".join(defs)
check("newenvironment is collected", "\\newenvironment{olbox}" in text, defs)
check("collected definition is guarded (safe when several chapters define it)",
      all(("\\ifcsundef{olbox}" in d) for d in defs if "olbox" in d), defs)
both = web.collect_defs(CH) + web.collect_defs(CH)
pre = web.dedupe_defs(both) if hasattr(web, "dedupe_defs") else both
check("the same definition from two chapters appears once", sum("newenvironment{olbox}" in d for d in pre) == 1, pre)

# a cached render failure is retried once the collected definitions change (the first fix left the 3 cached
# "olbox undefined" failures in place: the cache key covered the snippet and the style, not the definitions)
import tempfile  # noqa: E402
cache = Path(tempfile.mkdtemp(prefix="webcache_"))
(cache / "k1.fail").write_text("! LaTeX Error: Environment olbox undefined.", "utf-8")
fic = getattr(web, "fail_is_current", None)
check("fail_is_current exists", fic is not None)
if fic:
    check("an unstamped old failure is retried", fic(cache, "k1", "aaaa") is False and not (cache / "k1.fail").exists())
    (cache / "k2.fail").write_text("err", "utf-8")
    (cache / "k2.faildefs").write_text("bbbb", "utf-8")
    check("a failure under the same definitions is kept", fic(cache, "k2", "bbbb") is True)
    check("a failure under other definitions is retried", fic(cache, "k2", "cccc") is False)

print("ALL OK" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
