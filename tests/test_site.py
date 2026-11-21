"""Pre-deploy gate for the static showcase in site/:  py tests/test_site.py   (exit 0 = safe to deploy)

Checks the files as they would be served: every local reference resolves, nothing is loaded from another
origin, no inline script/style (the CSP in vercel.json forbids them), security and cache headers are set,
size budgets hold, and no private string (local path, e-mail, Drive link, key pattern, redaction term) is
in any served file. Prints the request count and bytes of one page view and projects monthly edge requests.
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "site"
bad = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


need = ["index.html", "404.html", "vercel.json", "robots.txt", "favicon.svg", "styles.css", "app.js"]
missing = [n for n in need if not (SITE / n).is_file()]
check("required files exist", not missing, str(missing))
if missing:
    print("RESULT FAIL")
    sys.exit(1)

pages = sorted(SITE.glob("*.html"))
ref_re = re.compile(r'(?:href|src|poster)\s*=\s*"([^"]+)"|srcset\s*=\s*"([^"]+)"', re.I)
first_view = set()
for page in pages:
    html = page.read_text("utf-8")
    refs = []
    for a, b in ref_re.findall(html):
        refs += [a] if a else [p.strip().split(" ")[0] for p in b.split(",")]
    dangling, external_loads = [], []
    for r in refs:
        if r.startswith(("#", "mailto:", "data:")):
            continue
        if re.match(r"https?://", r):
            continue                     # outbound links are checked below: only <a> may point off-site
        target = (SITE / (r.split("#")[0].split("?")[0].lstrip("/") or "index.html"))
        if not target.is_file():
            dangling.append(r)
        elif page.name == "index.html" and not r.endswith(".html"):
            first_view.add(target)
    for tag, attr in re.findall(r"<(script|link|img|source|iframe|video|audio)\b([^>]*)>", html, re.I):
        m = re.search(r'(?:src|href|srcset)\s*=\s*"(https?:)?//', attr, re.I)
        if m and not (tag.lower() == "link" and re.search(r'rel\s*=\s*"canonical"', attr, re.I)):
            external_loads.append(f"<{tag}{attr[:60]}>")
    check(f"{page.name}: local references resolve", not dangling, str(dangling[:5]))
    check(f"{page.name}: nothing loaded from another origin", not external_loads, str(external_loads[:3]))
    check(f"{page.name}: no inline <script>", not re.search(r"<script(?![^>]*\bsrc=)(?![^>]*application/ld\+json)", html, re.I))
    check(f"{page.name}: no inline <style> or style attribute",
          not re.search(r"<style\b|\sstyle\s*=\s*\"", html, re.I))
    check(f"{page.name}: has title, description and viewport",
          all(re.search(p, html, re.I) for p in (r"<title>[^<]{10,}", r'name="description"', r'name="viewport"')))
    check(f"{page.name}: every <img> has alt, width and height",
          all(re.search(r"\balt=", t) and re.search(r"\bwidth=", t) and re.search(r"\bheight=", t)
              for t in re.findall(r"<img\b[^>]*>", html, re.I)))
    check(f"{page.name}: outbound links open safely",
          all('rel="noopener' in t for t in re.findall(r'<a\b[^>]*target="_blank"[^>]*>', html, re.I)))

# CSS url() references
css = (SITE / "styles.css").read_text("utf-8")
css_bad = [u for u in re.findall(r"url\(([^)]+)\)", css)
           if not u.strip("'\"").startswith("data:") and not (SITE / u.strip("'\"").lstrip("/")).is_file()]
check("styles.css: url() targets exist and are local", not css_bad, str(css_bad))

# vercel.json: headers
vj = json.loads((SITE / "vercel.json").read_text("utf-8"))
hdrs = {}
for block in vj.get("headers", []):
    for h in block.get("headers", []):
        hdrs.setdefault(h["key"].lower(), []).append((block.get("source"), h["value"]))
csp = " ".join(v for _, v in hdrs.get("content-security-policy", []))
check("vercel.json: CSP is self-only with no unsafe-inline/eval",
      "default-src 'none'" in csp and "script-src 'self'" in csp and "unsafe" not in csp and "frame-ancestors 'none'" in csp)
for key in ("x-content-type-options", "referrer-policy", "permissions-policy", "strict-transport-security"):
    check(f"vercel.json: {key} set", key in hdrs)
check("vercel.json: immutable cache for /img",
      any(src and "img" in src and "immutable" in v for src, v in hdrs.get("cache-control", [])))
check("vercel.json: no functions, rewrites to other hosts or builds",
      not any(k in vj for k in ("functions", "builds", "routes")) and
      not any(re.match(r"https?://", r.get("destination", "")) for r in vj.get("rewrites", [])))

# size budgets
files = [f for f in SITE.rglob("*") if f.is_file()]
total = sum(f.stat().st_size for f in files)
big = [(f.name, f.stat().st_size) for f in files if f.stat().st_size > 400_000]
check("no served file above 400 kB", not big, str(big))
check("whole site under 3 MB", total < 3_000_000, f"{total} bytes")
check("no sourcemaps or stray files", not [f.name for f in files if f.suffix in (".map", ".bak", ".py", ".tex", ".json")
                                             and f.name not in ("vercel.json", "site.webmanifest")])

# leak scan over every text file that is served
terms = []
priv = HERE.parent.parent / "_publish" / "_private" / "redact.json"      # local only; absent in a fresh clone
if priv.is_file():
    r = json.loads(priv.read_text("utf-8"))
    def flat(v):                       # "redact" is {guide code: [text | [text, replacement], ...]}; only the text is a term
        if isinstance(v, dict):
            return [t for x in v.values() for t in flat(x)]
        if isinstance(v, list):
            return [str(x[0]) if isinstance(x, list) and x else str(x) for x in v if x]
        return [str(v)] if v else []
    terms = [t for k in ("redact", "scan_terms") for t in flat(r.get(k, [])) if len(t) > 3]
patterns = {
    "local path": r"[A-Za-z]:\\\\?Users|/c/Users|/home/[a-z]",
    "e-mail": r"[\w.+-]+@(?!users\.noreply)[\w-]+\.(?:com|in|org|ac\.in)\b",
    "drive link": r"drive\.google|docs\.google",
    "private ip": r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+",
    "key pattern": r"sk-[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_-]{20,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN",
}
leaks = []
for f in files:
    if f.suffix.lower() in (".html", ".css", ".js", ".json", ".txt", ".xml", ".svg", ".webmanifest"):
        t = f.read_text("utf-8", errors="replace")
        leaks += [f"{f.name}: {n}" for n, p in patterns.items() if re.search(p, t)]
        leaks += [f"{f.name}: redaction term" for x in terms if x and x.lower() in t.lower()]
check("leak scan: no private strings in served files" + ("" if terms else " (redaction list not present: patterns only)"),
      not leaks, str(leaks[:5]))

# request projection for one first page view (index + its static references)
req = 1 + len(first_view)
kb = ((SITE / "index.html").stat().st_size + sum(f.stat().st_size for f in first_view)) / 1000
cap = 1_000_000
print(f"INFO one page view: {req} requests, {kb:.0f} kB uncompressed (repeat views hit the immutable cache)")
print(f"INFO Hobby cap {cap:,} edge requests/month = {cap // req:,} cold page views/month before the cap")
check("a cold page view stays under 30 requests and 1.5 MB", req <= 30 and kb <= 1500, f"{req} req, {kb:.0f} kB")

print("RESULT " + ("FAIL" if bad else "PASS"))
sys.exit(1 if bad else 0)
