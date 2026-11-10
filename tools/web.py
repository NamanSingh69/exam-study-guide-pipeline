"""web.py - static, phone-first web export of one subject and scope.

  py _pipeline/tools/web.py CN --scope midsem [--out DIR] [--base-url URL] [--pdf-base PREFIX]
                                              [--no-render] [--jobs N]

Reads <S>/work/<sc>/ (blueprint.json, pyq_bank.json, important_questions.json, badges.tex,
chapters/*.tex with their \\input{atoms/...}, receipts/) and writes <S>/work/<sc>/web/ (or --out):

  index.html               subject, scope, study plans, topics with P bands, papers, downloads
  t-<Tid>-<slug>.html      one page per topic section (\\section{..}\\label{sec:<Tid>})
  q-<qid>-<slug>.html      one page per solved PYQ (\\label{q:<qid>}): verbatim question from the bank,
                           receipt image, the solution, links to the topic
  paper-<pid>.html, u-<Uid>-*.html, ch-<stem>.html   paper / unit / other chapter pages
  drill.html               Q1 rapid-fire (important_questions.json q1_drill, else the bank's 1-mark PYQs)
  flashcards.html          \\flashcard self-test (tools/flashcards.py also writes the Anki CSV)
  search.json, sitemap-fragment.xml, site.json, og.png, assets/, fig/*.svg, img/, receipts/
  CONVERSION_REPORT.md     every block that fell back to a rendered image, every failed figure,
                           every dangling reference

LaTeX -> HTML is a pragmatic converter for the writer-contract macro subset. TikZ pictures and every
\\stepanim/\\storyboard frame are compiled standalone with the real studyguide.sty (pdflatex + preview,
then pymupdf page.get_svg_image) and cached in <S>/work/<sc>/build/web_cache/. Anything the converter
does not recognise is rendered the same way as an image of that block, and logged.

Exit 0 = site written (fallbacks are fine and listed); 1 = a figure could not be rendered at all, or an
input is missing; 2 = usage.  Last line: RESULT PASS ... | RESULT BLOCKED: <reasons>.
"""
import argparse, hashlib, html, json, os, re, shutil, subprocess, sys, tempfile, time, unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import workdir

KATEX_VER = "0.16.21"
CDN = f"https://cdnjs.cloudflare.com/ajax/libs/KaTeX/{KATEX_VER}"
WEBSRC = workdir.PIPE / "latex" / "web"
STY = workdir.PIPE / "latex" / "studyguide.sty"
SITE_TAG = "Unofficial KIIT guide"
MARKER = ".sgweb"            # an --out folder is wiped only if it carries this marker
BATCH = 30                   # render jobs per pdflatex run
esc = html.escape


class Unsupported(Exception):
    """Raised by the converter for anything it cannot translate faithfully: the enclosing block
    is then rendered as an image instead."""


# ============================================================================ LaTeX scanning helpers
CMD_RE = re.compile(r"\\([A-Za-z@]+\*?|.)", re.S)


def strip_comments(s: str) -> str:
    """Remove % comments (not \\%). Like TeX, a comment also eats the newline and the next line's
    leading spaces, so a commented-out line never creates a paragraph break. Verbatim-like
    environments are left untouched."""
    keep = {}

    def protect(m):
        k = f"\x00V{len(keep)}\x00"
        keep[k] = m.group(0)
        return k
    s = re.sub(r"\\begin\{(lstlisting|verbatim)\}.*?\\end\{\1\}", protect, s, flags=re.S)
    out, join = [], False
    for line in s.split("\n"):
        if join:
            line = line.lstrip()
        j = 0
        cut = None
        while True:
            j = line.find("%", j)
            if j < 0:
                break
            n, k = 0, j
            while k > 0 and line[k - 1] == "\\":
                n += 1
                k -= 1
            if n % 2 == 0:
                cut = j
                break
            j += 1
        if cut is not None:
            seg = line[:cut]
            if join and out:
                out[-1] += seg
            else:
                out.append(seg)
            join = True
        else:
            if join and out:
                out[-1] += line
            else:
                out.append(line)
            join = False
    s = "\n".join(out)
    for k, v in keep.items():
        s = s.replace(k, v)
    return s


def skip_ws(s, i):
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def read_group(s, i):
    """s[i] == '{': return (inner text, index after the closing brace)."""
    if i >= len(s) or s[i] != "{":
        raise Unsupported("expected {")
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise Unsupported("unbalanced {")


def read_opt(s, i):
    """Optional [..] argument after optional whitespace: (text|None, index)."""
    j = skip_ws(s, i)
    if j < len(s) and s[j] == "[":
        depth, k = 0, j + 1
        while k < len(s):
            c = s[k]
            if c == "\\":
                k += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            elif c == "]" and depth == 0:
                return s[j + 1:k], k + 1
            k += 1
        raise Unsupported("unbalanced [")
    return None, i


def read_arg(s, i):
    j = skip_ws(s, i)
    if j >= len(s):
        raise Unsupported("missing argument")
    if s[j] == "{":
        return read_group(s, j)
    if s[j] == "\\":
        m = CMD_RE.match(s, j)
        return m.group(0), m.end()
    return s[j], j + 1


def find_end(s, name, i):
    """Index range of the \\end{name} matching a \\begin{name} whose body starts at i."""
    pat = re.compile(r"\\(begin|end)\{" + re.escape(name) + r"\}")
    depth = 1
    for m in pat.finditer(s, i):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.start(), m.end()
    raise Unsupported(f"unclosed environment {name}")


def find_math_end(s, i, closer):
    """Index of the closing delimiter of inline/display math opened before i."""
    j, depth = i, 0
    while j < len(s):
        if s[j] == "\\":
            if s.startswith(closer, j) and closer.startswith("\\") and depth == 0:
                return j
            j += 2
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
        elif closer in ("$", "$$") and depth <= 0 and s.startswith(closer, j):
            return j
        j += 1
    raise Unsupported("unclosed math")


def split_top(s, seps):
    """Split s on top-level occurrences of the given separators ('\\\\', '&', '\\item', ...),
    ignoring anything inside braces, math and nested environments. Returns [(sep_before, part)]."""
    parts, buf_start, i, depth, env = [], 0, 0, 0, 0
    last_sep = None
    while i < len(s):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "$":
            closer = "$$" if s.startswith("$$", i) else "$"
            j = find_math_end(s, i + len(closer), closer)
            i = j + len(closer)
            continue
        elif c == "\\":
            m = CMD_RE.match(s, i)
            name = m.group(1)
            if name == "begin":
                env += 1
            elif name == "end":
                env -= 1
            if depth == 0 and env == 0:
                tok = m.group(0)
                for sp in seps:
                    if tok == sp or (sp == "\\item" and name == "item"):
                        parts.append((last_sep, s[buf_start:i]))
                        last_sep = tok
                        buf_start = m.end()
                        break
            i = m.end()
            continue
        elif c == "&" and depth == 0 and env == 0 and "&" in seps:
            parts.append((last_sep, s[buf_start:i]))
            last_sep = "&"
            buf_start = i + 1
        i += 1
    parts.append((last_sep, s[buf_start:]))
    return parts


def html_id(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-")


def slugify(t: str, n=60) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    if len(t) > n:
        t = t[:n].rsplit("-", 1)[0]
    return t or "page"


def strip_tags(h: str) -> str:
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S)
    h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(h)).strip()


def shorten(t: str, n: int) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= n:
        return t
    return t[:n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


# ============================================================================ vocabulary
PALETTE = {"sgnavy": (27, 54, 93), "sgteal": (0, 128, 128), "sgamber": (217, 119, 6), "sgred": (185, 28, 28),
           "sggreen": (21, 128, 61), "sgpurple": (109, 40, 217), "sgslate": (45, 55, 72),
           "sgtint": (244, 247, 251), "sggrid": (203, 213, 225), "hl": (217, 119, 6), "ok": (21, 128, 61),
           "bad": (185, 28, 28), "info": (0, 128, 128), "muted": (45, 55, 72), "primaryblue": (27, 54, 93),
           "accentteal": (0, 128, 128), "accentorange": (217, 119, 6), "red": (200, 0, 0),
           "blue": (0, 0, 200), "green": (0, 140, 0), "orange": (230, 120, 0), "gray": (128, 128, 128),
           "black": (0, 0, 0), "white": (255, 255, 255), "darkgray": (45, 55, 72), "softblue": (244, 247, 251)}
COLOR_CLASS = {"hl": "c-hl", "sgamber": "c-hl", "accentorange": "c-hl", "orange": "c-hl", "ok": "c-ok",
               "sggreen": "c-ok", "green": "c-ok", "bad": "c-bad", "sgred": "c-bad", "red": "c-bad",
               "info": "c-info", "sgteal": "c-info", "accentteal": "c-info", "muted": "c-muted",
               "gray": "c-muted", "sgslate": "c-muted", "darkgray": "c-muted", "sgnavy": "c-navy",
               "primaryblue": "c-navy", "blue": "c-navy", "sgpurple": "c-purple"}

TEXT_SYMBOLS = {"S": "§", "P": "¶", "textonehalf": "½", "ldots": "…", "dots": "…", "textellipsis": "…",
                "textbullet": "•", "textdegree": "°", "checkmark": "✓", "LaTeX": "LaTeX", "TeX": "TeX",
                "textbackslash": "\\", "%": "%", "&": "&amp;", "$": "$", "#": "#", "_": "_", "{": "{",
                "}": "}", ",": "\u2009", ";": " ", ":": " ", "!": "", " ": " ", "quad": "\u2003",
                "qquad": "\u2003\u2003", "hfill": " ", "@": "", "/": "", "-": "", "textendash": "–",
                "textemdash": "—", "textless": "&lt;", "textgreater": "&gt;", "textbar": "|",
                "textasciitilde": "~", "textasciicircum": "^", "copyright": "©", "euro": "€",
                "vs": "<i>vs.</i> ", "newline": "<br>", "linebreak": "<br>", "tabularnewline": "<br>",
                "dag": "†", "ddag": "‡", "textregistered": "®", "texttrademark": "™", "pounds": "£",
                "slash": "/", "enspace": " ", "thinspace": "\u2009", "nobreakspace": "\u00a0",
                "textquotedbl": '"', "textquoteright": "’", "textquoteleft": "‘", "ss": "ß",
                "times": "×", "textperiodcentered": "·", "dotfill": '<span class="dotfill"></span>',
                "hrulefill": '<span class="dotfill"></span>', "break": "", "allowbreak": "",
                "textsection": "§", "textmu": "µ", "\n": " ", "\t": " ", "\r": " ", "o": "ø", "O": "Ø", "ae": "æ", "AE": "Æ"}
SWITCHES = {"bfseries": "b", "itshape": "i", "em": "i", "slshape": "i", "ttfamily": "tt", "sffamily": "",
            "rmfamily": "", "upshape": "", "mdseries": "", "normalfont": "", "small": "sm",
            "footnotesize": "sm", "scriptsize": "xs", "tiny": "xs", "normalsize": "", "large": "lg",
            "Large": "lg", "LARGE": "lg", "huge": "lg", "Huge": "lg", "centering": "", "raggedright": "",
            "raggedleft": "", "noindent": "", "relax": "", "protect": "", "zebra": "", "phantomsection": "",
            "FloatBarrier": "", "makeatletter": "", "makeatother": "", "null": "", "strut": "",
            "hline": "", "toprule": "", "midrule": "", "bottomrule": "", "endhead": "", "endfoot": "",
            "endfirsthead": "", "endlastfoot": "", "sloppy": "", "selectfont": "", "arraybackslash": "",
            "leavevmode": "", "indent": "", "unskip": "", "ignorespaces": "", "smallskip": "",
            "medskip": "", "bigskip": "", "clearpage": "", "newpage": "", "pagebreak": "",
            "nopagebreak": "", "maketitle": "", "tableofcontents": "", "listoffigures": "",
            "raggedcolumns": "", "displaystyle": "", "boldmath": "", "unboldmath": "", "hss": "",
            "vfill": "", "vss": "", "nointerlineskip": "", "frenchspacing": "", "par": "", "nobreak": "",
            "goodbreak": "", "filbreak": "", "smallbreak": "", "medbreak": "", "bigbreak": ""}
SWITCH_CLASS = {"b": "b", "i": "i", "tt": "tt", "sm": "sm", "xs": "sm", "lg": "lg"}
# commands whose arguments are dropped: name -> number of mandatory args (optional args skipped too)
IGNORE_ARGS = {"needspace": 1, "vspace": 1, "vspace*": 1, "addvspace": 1, "setcounter": 2,
               "addtocounter": 2, "stepcounter": 1, "refstepcounter": 1, "pagestyle": 1,
               "thispagestyle": 1, "enlargethispage": 1, "captionsetup": 1, "rowcolors": 3,
               "arrayrulecolor": 1, "sisetup": 1, "pgfplotsset": 1, "tikzset": 1, "setlist": 1,
               "linespread": 1, "typeout": 1, "cline": 1, "rowcolor": 1, "columncolor": 1,
               "graphicspath": 1, "hypersetup": 1, "setsubject": 3, "sgmarkchapterend": 1,
               "setlength": 2, "addtolength": 2, "addcontentsline": 3, "usetikzlibrary": 1,
               "definecolor": 3, "colorlet": 2, "newcolumntype": 2, "cellcolor": 1,
               "pdfbookmark": 2, "markboth": 2, "markright": 1, "hyphenation": 1, "newcounter": 1,
               "cmidrule": 1, "renewcommand*": 2, "nopagebreakhere": 0, "sgdefbadge": 5,
               "sgdeftopic": 3, "noalign": 1, "hhline": 1, "addlinespace": 0, "titleformat": 0,
               "pgfmathsetmacro": 2, "pgfmathtruncatemacro": 2}
TEXT_WRAP = {"textbf": ("<strong>", "</strong>"), "bf": ("<strong>", "</strong>"),
             "emph": ("<em>", "</em>"), "textit": ("<em>", "</em>"), "textsl": ("<em>", "</em>"),
             "texttt": ("<code>", "</code>"), "textsf": ("", ""), "textrm": ("", ""),
             "textmd": ("", ""), "textup": ("", ""), "textnormal": ("", ""), "mbox": ("", ""),
             "text": ("", ""), "hbox": ("", ""), "fbox": ('<span class="fbox">', "</span>"),
             "textsuperscript": ("<sup>", "</sup>"), "textsubscript": ("<sub>", "</sub>"),
             "underline": ("<u>", "</u>"), "uline": ("<u>", "</u>"), "sout": ("<s>", "</s>"),
             "textsc": ('<span class="sc">', "</span>"), "keyword": ('<strong class="kw">', "</strong>"),
             "answer": ('<span class="answer">', "</span>"), "thead": ("<b>", "</b>"),
             "enquote": ("“", "”"), "footnote": ('<span class="fn">(', ")</span>"),
             "nolinkurl": ("<code>", "</code>"), "textcircled": ("(", ")"), "cshead": ("<b>", "</b>")}
ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", "c": "\u0327",
           "=": "\u0304", "u": "\u0306", "v": "\u030c", ".": "\u0307", "H": "\u030b"}

BOXES = {"definitionbox": ("def", "Definition"), "keyconceptbox": ("key", "Key idea"),
         "formulabox": ("formula", "Formula"), "algorithmbox": ("algo", "Algorithm"),
         "warningbox": ("warn", "Exam pitfall"), "intuitionbox": ("intuition", "Intuition"),
         "mnemonicbox": ("mnemonic", "Remember it"), "answerplan": ("plan", "Answer plan for full marks"),
         "examtip": ("tip", "Exam tip"), "checkpoint": ("check", "Self-check")}
BOX_SEP = {"answerplan": " — "}
MATH_ENVS = {"align": "aligned", "align*": "aligned", "equation": None, "equation*": None,
             "gather": "gathered", "gather*": "gathered", "multline": None, "multline*": None,
             "eqnarray": "aligned", "eqnarray*": "aligned", "displaymath": None, "flalign": "aligned",
             "flalign*": "aligned", "alignat": "aligned", "alignat*": "aligned"}
TABLE_ENVS = {"tabular", "tabular*", "tabularx", "xltabular", "longtable", "tabulary", "array"}
FIG_ENVS = {"figure", "figure*", "table", "table*", "wrapfigure", "SCfigure"}

KATEX_OK = set("""
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho
varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi
Psi Omega digamma varkappa times div cdot cdots ldots dots ddots vdots pm mp ast star circ bullet oplus
ominus otimes oslash odot cap cup vee wedge setminus wr diamond bigcirc triangle triangleleft triangleright
neg lnot land lor le leq ge geq ne neq equiv approx sim simeq cong propto ll gg lll ggg subset subseteq supset
supseteq in notin ni mid parallel perp prec succ preceq succeq doteq models vdash dashv asymp bowtie
leqslant geqslant lesssim gtrsim coloneqq triangleq to gets leftarrow rightarrow Leftarrow Rightarrow
leftrightarrow Leftrightarrow longleftarrow longrightarrow Longleftarrow Longrightarrow longleftrightarrow
Longleftrightarrow uparrow downarrow Uparrow Downarrow updownarrow mapsto longmapsto hookleftarrow
hookrightarrow nearrow searrow swarrow nwarrow leftharpoonup rightharpoonup rightleftharpoons iff implies
impliedby xrightarrow xleftarrow xleftrightarrow xRightarrow xLeftarrow xmapsto sum prod coprod int iint
iiint oint bigcup bigcap bigvee bigwedge bigoplus bigotimes bigodot biguplus bigsqcup lim limsup liminf max
min sup inf arg det exp gcd hom ker Pr deg dim log ln lg sin cos tan cot sec csc arcsin arccos arctan sinh
cosh tanh coth bmod pmod pod mod left right big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr
middle langle rangle lfloor rfloor lceil rceil lvert rvert lVert rVert vert Vert backslash lbrace rbrace
lbrack rbrack hat widehat tilde widetilde bar overline underline vec dot ddot acute grave breve check
mathring overrightarrow overleftarrow overbrace underbrace overset underset stackrel mathbf mathrm mathit
mathsf mathtt mathcal mathbb mathfrak mathscr boldsymbol text textbf textit textrm textsf texttt textnormal
textup textmd emph operatorname mbox hbox boxed fbox colorbox color textcolor frac dfrac tfrac cfrac binom
dbinom tbinom choose over sqrt quad qquad space enspace hspace phantom hphantom vphantom kern mkern mskip
negthinspace thinspace infty partial nabla forall exists nexists emptyset varnothing ell hbar Re Im aleph
angle prime surd top bot flat sharp natural clubsuit diamondsuit heartsuit spadesuit dagger ddagger S P
checkmark degree circledR copyright pounds dollar displaystyle textstyle scriptstyle scriptscriptstyle
limits nolimits substack begin end hline cline hdashline not cancel bcancel xcancel sout underbar tag
notag nonumber char mathrel mathbin mathop mathord mathpunct mathopen mathclose mathinner smash rule
raisebox llap rlap clap mathllap mathrlap mathclap colon vcentcolon dotsb dotsc dotsi dotsm dotso cdotp
ldotp complement subsetneq supsetneq nsubseteq nsupseteq uplus sqcup sqcap sqsubseteq sqsupseteq because
therefore square blacksquare Box lozenge blacklozenge triangledown vartriangle bigtriangleup
bigtriangledown ltimes rtimes intercal dotplus boxplus boxminus boxtimes boxdot centerdot barwedge veebar
curlywedge curlyvee leqq geqq ngtr nless nleq ngeq lneq gneq lneqq gneqq lnsim gnsim nprec nsucc ncong
nsim nmid nparallel nvdash approxeq thicksim thickapprox backsim eqsim lt gt textendash textemdash
mathstrut operatorname* argmax argmin ast lceil rceil uparrow downarrow textsuperscript textsubscript
underline overleftrightarrow underrightarrow underleftarrow widecheck utilde iddots cdotp lhd rhd unlhd
unrhd leftrightarrows rightleftarrows twoheadrightarrow twoheadleftarrow rightsquigarrow leadsto
looparrowright circlearrowright curvearrowright Rrightarrow Lleftarrow nleftarrow nrightarrow
nLeftarrow nRightarrow nleftrightarrow nLeftrightarrow shortmid shortparallel varpropto blacktriangle
blacktriangleleft blacktriangleright bigstar maltese yen circledS diagup diagdown Finv Game eth mho
backprime varkappa beth gimel daleth hslash imath jmath Bbbk minuscolon textasciitilde textbackslash
mathellipsis mathsterling textdollar textunderscore textbraceleft textbraceright KaTeX TeX LaTeX
ce pu units vline atop brace brack genfrac above abovewithdelims overwithdelims
""".split())
KATEX_ENVS = {"matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "array",
              "darray", "cases", "dcases", "rcases", "drcases", "aligned", "alignedat", "gathered",
              "split", "subarray", "CD", "equation", "equation*", "align", "align*", "gather",
              "gather*", "alignat", "alignat*", "matrix*", "pmatrix*", "bmatrix*"}
# writer macros that may appear inside math: rewritten to KaTeX equivalents before rendering
MATH_REWRITE = [(r"\\answer\b", r"\\boxed"), (r"\\keyword\b", r"\\textbf"), (r"\\ensuremath\b", ""),
                (r"\\bm\b", r"\\boldsymbol"), (r"\\textonehalf\b", r"\\tfrac12"),
                (r"\\mks\{([^{}]*)\}", r"\\text{[\1 M]}"), (r"\\SI\{([^{}]*)\}\{([^{}]*)\}", r"\1\\,\\text{\2}"),
                (r"\\num\{([^{}]*)\}", r"\1"), (r"\\si\{([^{}]*)\}", r"\\text{\1}"),
                (r"\\vs\b", r"\\textit{vs.}"), (r"\\textsc\b", r"\\text"), (r"\\label\{[^{}]*\}", ""),
                (r"\\nonumber\b|\\notag\b", ""),
                # mathtools' small delimited matrices -> KaTeX smallmatrix inside delimiters
                (r"\\begin\{psmallmatrix\}", r"\\left(\\begin{smallmatrix}"), (r"\\end\{psmallmatrix\}", r"\\end{smallmatrix}\\right)"),
                (r"\\begin\{bsmallmatrix\}", r"\\left[\\begin{smallmatrix}"), (r"\\end\{bsmallmatrix\}", r"\\end{smallmatrix}\\right]"),
                (r"\\begin\{vsmallmatrix\}", r"\\left|\\begin{smallmatrix}"), (r"\\end\{vsmallmatrix\}", r"\\end{smallmatrix}\\right|"),
                (r"\\begin\{Bsmallmatrix\}", r"\\left\\{\\begin{smallmatrix}"), (r"\\end\{Bsmallmatrix\}", r"\\end{smallmatrix}\\right\\}"),
(r"\\intertext\{([^{}]*)\}", r"\\text{\1}\\\\")]
SIUNIT = {"milli": "m", "micro": "µ", "nano": "n", "kilo": "k", "mega": "M", "giga": "G", "tera": "T",
          "second": "s", "metre": "m", "meter": "m", "bit": "bit", "byte": "B", "hertz": "Hz",
          "per": "/", "watt": "W", "volt": "V", "ampere": "A", "ohm": "Ω", "decibel": "dB", "percent": "%"}


# ============================================================================ the converter
class Conv:
    """Converts one page's LaTeX to HTML. Block-level failures fall back to rendered images."""

    def __init__(self, site, page, head_base=2, open_solutions=False, math="katex", allow_fallback=True):
        self.site, self.page = site, page
        self.head_base = head_base
        self.open_solutions = open_solutions
        self.math_mode = math
        self.allow_fallback = allow_fallback
        self.alt = ""

    # ------------------------------------------------------------------ blocks
    BLOCK_CMDS = {"section", "section*", "subsection", "subsection*", "subsubsection", "subsubsection*",
                  "paragraph", "paragraph*", "chapter", "chapter*", "stepanim", "stepanim*", "storyboard",
                  "storyboard*", "figfromnotes", "receipt", "notfromnotes", "par", "caption", "captionof",
                  "[", "sgwebpyqlink", "item", "rule", "includegraphics", "noindent", "centering"}

    def blocks(self, s: str) -> str:
        out, para, i = [], [], 0
        n = len(s)

        def flush():
            src = "".join(para).strip()
            para.clear()
            if not src or not src.strip():
                return
            out.append(self._guard("paragraph", src, lambda: self._para(src)))

        while i < n:
            c = s[i]
            if c == "\n":
                j = i + 1
                while j < n and s[j] in " \t\r":
                    j += 1
                if j < n and s[j] == "\n":
                    flush()
                    i = skip_ws(s, j)
                    continue
                para.append(" ")
                i += 1
                continue
            if c == "{":
                try:
                    inner, j = read_group(s, i)
                except Unsupported:
                    para.append(s[i:])
                    break
                if re.search(r"\\begin\{|\\\[|\n\s*\n|\\par\b|\\(sub)*section|\\stepanim|\\storyboard", inner):
                    flush()
                    out.append(self._group_block(inner))
                else:
                    para.append(s[i:j])
                i = j
                continue
            if c == "$":
                closer = "$$" if s.startswith("$$", i) else "$"
                try:
                    j = find_math_end(s, i + len(closer), closer)
                except Unsupported:
                    para.append(s[i:])
                    break
                if closer == "$$":
                    flush()
                    tex = s[i + 2:j]
                    out.append(self._guard("display math", s[i:j + 2], lambda t=tex: self.math(t, True)))
                else:
                    para.append(s[i:j + 1])
                i = j + len(closer)
                continue
            if c == "\\":
                m = CMD_RE.match(s, i)
                name = m.group(1)
                if name == "begin":
                    try:
                        env, j = read_group(s, m.end())
                        a, b = find_end(s, env, j)
                    except Unsupported:
                        para.append(s[i:])
                        break
                    if env in ("math",):
                        para.append(s[i:b])
                        i = b
                        continue
                    flush()
                    src = s[i:b]
                    out.append(self._guard(f"environment {env}", src,
                                           lambda e=env, body=s[j:a]: self.env(e, body, src)))
                    i = b
                    continue
                if name in self.BLOCK_CMDS:
                    flush()
                    try:
                        h, j = self.block_cmd(name, s, m.end())
                    except Unsupported as e:
                        # the command itself cannot be converted: render exactly its extent as an image
                        k = cmd_extent(name, s, m.end())
                        h, j = self.fallback(s[i:k], str(e)), k
                    out.append(h)
                    i = j
                    continue
                # an inline command keeps its whole argument chain in the paragraph, even when an
                # argument holds maths environments or display maths (\flashcard{..}{$\begin{bmatrix}..$},
                # \providecommand{\x}[6]{..\begin{scope}..}): splitting it off cut the command in half
                j = m.end()
                if name not in SWITCHES and name not in TEXT_SYMBOLS and name.isalpha() or name.endswith("*"):
                    j = arg_chain_end(s, j)
                para.append(s[i:j])
                i = j
                continue
            para.append(c)
            i += 1
        flush()
        return "\n".join(x for x in out if x)

    def _guard(self, kind, src, fn):
        try:
            return fn()
        except Unsupported as e:
            return self.fallback(src, f"{kind}: {e}")

    def _group_block(self, inner):
        cls = []
        while True:
            m = re.match(r"\s*\\([A-Za-z]+)\b\s*", inner)
            if m and m.group(1) in SWITCHES:
                c = SWITCH_CLASS.get(SWITCHES[m.group(1)])
                if m.group(1) == "centering":
                    c = "center"
                if c:
                    cls.append(c)
                inner = inner[m.end():]
                continue
            m = re.match(r"\s*\\color\{([^}]*)\}\s*", inner)
            if m:
                c = COLOR_CLASS.get(m.group(1).split("!")[0])
                if c:
                    cls.append(c)
                inner = inner[m.end():]
                continue
            break
        body = self.blocks(inner)
        return f'<div class="{" ".join(cls)}">{body}</div>' if cls else body

    def _para(self, src):
        h = self.inline(src).strip()
        if not strip_tags(h) and "<img" not in h and "<span id=" not in h and "class=\"pill" not in h:
            return h  # only anchors / nothing visible
        if re.fullmatch(r"(<span id=\"[^\"]*\" class=\"anchor\"></span>\s*)+", h):
            return h
        return f"<p>{h}</p>"

    def heading(self, level, title_src, s, j):
        lab, j2 = self._peek_label(s, j)
        title = self.inline(title_src)
        lvl = min(6, max(2, self.head_base + level))
        hid = f' id="{html_id(lab)}"' if lab else ""
        if lab:
            self.site.register_label(lab, self.page, html_id(lab), title=strip_tags(title), title_html=title)
        return f"<h{lvl}{hid}>{title}</h{lvl}>", j2

    def _peek_label(self, s, j):
        k = skip_ws(s, j)
        if s.startswith("\\label{", k):
            lab, k2 = read_group(s, k + 6)
            return lab.strip(), k2
        return None, j

    def block_cmd(self, name, s, j):
        star = name.endswith("*")
        base = name.rstrip("*")
        if base in ("section", "subsection", "subsubsection", "chapter", "paragraph"):
            _, j = read_opt(s, j)
            title, j = read_arg(s, j)
            level = {"chapter": -1, "section": 0, "subsection": 1, "subsubsection": 2, "paragraph": 3}[base]
            if base == "paragraph":
                lab, j = self._peek_label(s, j)
                return f'<h6 class="para">{self.inline(title)}</h6>', j
            return self.heading(level, title, s, j)
        if base in ("stepanim", "storyboard"):
            nf, j = read_arg(s, j)
            _cols, j = read_arg(s, j)
            _w, j = read_arg(s, j)
            cap, j = read_arg(s, j)
            body, j = read_arg(s, j)
            return self.stepanim(nf, cap, body), j
        if name == "figfromnotes":
            _, j = read_opt(s, j)
            path, j = read_arg(s, j)
            cap, j = read_arg(s, j)
            return self.figure_wrap(self.image(path.strip()), cap, None), j
        if name == "includegraphics":
            _, j = read_opt(s, j)
            path, j = read_arg(s, j)
            return f'<p class="center">{self.image(path.strip())}</p>', j
        if name == "receipt":
            qid, j = read_arg(s, j)
            return self.site.receipt_html(qid.strip()), j
        if name == "notfromnotes":
            src, j = read_arg(s, j)
            return (f'<div class="notfromnotes"><b>Not in your instructor\'s notes</b> — written from '
                    f'{self.inline(src)}; check it against class material.</div>'), j
        if name in ("par", "noindent", "centering"):
            return "", j
        if name in ("caption", "captionof"):
            if name == "captionof":
                _, j = read_arg(s, j)
            _, j = read_opt(s, j)
            cap, j = read_arg(s, j)
            return self.caption_html(cap, "figure"), j
        if name == "[":
            k = find_math_end(s, j, "\\]")
            return self.math(s[j:k], True), k + 2
        if name == "sgwebpyqlink":
            qid, j = read_arg(s, j)
            return self.site.pyq_card(qid.strip()), j
        if name == "rule":
            _, j = read_opt(s, j)
            w, j = read_arg(s, j)
            _h, j = read_arg(s, j)
            return ("<hr>" if "linewidth" in w or "textwidth" in w else ""), j
        if name == "item":
            raise Unsupported("\\item outside a list")
        raise Unsupported(f"block \\{name}")

    # ------------------------------------------------------------------ environments
    def env(self, name, body, src):
        opt = None
        if name in BOXES:
            opt, k = read_opt(body, 0)
            body = body[k:]
            cls, title = BOXES[name]
            sep = BOX_SEP.get(name, ": ")
            t = esc(title) + (sep + self.inline(opt) if opt and opt.strip() else "")
            return (f'<div class="box box-{cls}"><div class="box-t">{t}</div>'
                    f'<div class="box-b">{self.blocks(body)}</div></div>')
        if name == "question":
            title, k = read_arg(body, 0)
            mk, k = read_arg(body, k)
            tags, k = read_opt(body, k)
            t = self.inline(title)
            tg = self.inline(tags) if tags else ""
            return (f'<div class="box box-q"><div class="box-t"><span>{t}</span> <span class="tags">{tg}'
                    f' {pill("mks", esc(mk.strip()) + " M")}</span></div>'
                    f'<div class="box-b qtext">{self.blocks(body[k:])}</div></div>')
        if name == "solution":
            opt, k = read_opt(body, 0)
            t = "Solution" + (" — " + self.inline(opt) if opt and opt.strip() else "")
            op = " open" if self.open_solutions else ""
            return f'<details class="box box-sol ans"{op}><summary>{t}</summary><div class="box-b">{self.blocks(body[k:])}</div></details>'
        if name == "solvedidea":
            cid, k = read_arg(body, 0)
            title, k = read_arg(body, k)
            cid = cid.strip()
            self.site.register_label(f"solve:{cid}", self.page, html_id(f"solve:{cid}"),
                                     title=strip_tags(self.inline(title)))
            return (f'<div class="box box-solved" id="{html_id("solve:" + cid)}"><div class="box-t">Solved idea: '
                    f'{self.inline(title)} {self.site.cluster_badge(cid)}</div><div class="box-b">'
                    f'{self.blocks(body[k:])}</div></div>')
        if name in ("itemize", "enumerate", "description", "compactitem", "compactenum"):
            return self.listing(name, body)
        if name in FIG_ENVS:
            _, k = read_opt(body, 0)
            if name == "wrapfigure":
                _, k = read_arg(body, k)
                _, k = read_arg(body, k)
            return self.float_env(body[k:], "table" if name.startswith("table") else "figure")
        if name in ("center", "flushleft", "flushright", "minipage", "multicols", "multicols*", "quote",
                    "quotation", "adjustbox", "small", "footnotesize", "samepage", "raggedright"):
            k = 0
            if name == "minipage":
                _, k = read_opt(body, 0)
                _, k = read_opt(body, k)
                _, k = read_opt(body, k)
                _, k = read_arg(body, k)
            elif name.startswith("multicols"):
                _, k = read_arg(body, 0)
                _, k = read_opt(body, k)
            elif name == "adjustbox":
                _, k = read_arg(body, 0)
            cls = {"center": "center", "flushright": "right", "minipage": "minipage", "quote": "quote",
                   "quotation": "quote"}.get(name, "cols" if name.startswith("multicols") else "")
            inner = self.blocks(body[k:])
            return f'<div class="{cls}">{inner}</div>' if cls else inner
        if name in TABLE_ENVS:
            return self.table(name, body)
        if name == "tikzpicture":
            return self.site.job_img(src, self, kind="tikz", alt=self.alt)
        if name in ("lstlisting", "verbatim", "Verbatim", "minted"):
            k = 0
            if name == "lstlisting":
                _, k = read_opt(body, 0)
            elif name == "minted":
                _, k = read_opt(body, 0)
                _, k = read_arg(body, k)
            code = body[k:].strip("\n")
            return f"<pre><code>{esc(code)}</code></pre>"
        if name in MATH_ENVS:
            inner = MATH_ENVS[name]
            if name.startswith("alignat"):
                _, k = read_arg(body, 0)
                body = body[k:]
            tex = f"\\begin{{{inner}}}{body}\\end{{{inner}}}" if inner else body
            return self.math(tex, True)
        raise Unsupported(f"unknown environment {name}")

    def listing(self, name, body):
        opt, k = read_opt(body, 0)
        body = body[k:]
        items = split_top(body, ["\\item"])
        tmpl = None
        if opt:
            m = re.search(r"label\s*=\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|[^,\]]+)", opt)
            if m:
                tmpl = m.group(1).strip()
                if tmpl.startswith("{") and tmpl.endswith("}"):
                    tmpl = tmpl[1:-1]
        lis, n = [], 0
        for sep, part in items:
            if sep is None:
                if part.strip():
                    if strip_tags(self.inline(part)).strip():
                        raise Unsupported("text before the first \\item")
                continue
            lab, k = read_opt(part, 0)
            content = self.flow(part[k:])
            n += 1
            if name == "description" or lab is not None:
                lbl = self.inline(lab or "")
                if name == "description":
                    lis.append(f"<dt>{lbl}</dt><dd>{content}</dd>")
                else:
                    lis.append(f'<li class="lbl"><span class="li-l">{lbl}</span> {content}</li>')
            elif tmpl and name in ("enumerate", "compactenum"):
                lis.append(f'<li class="lbl"><span class="li-l">{self.enum_label(tmpl, n)}</span> {content}</li>')
            elif tmpl and name == "itemize":
                lis.append(f'<li class="lbl"><span class="li-l">{self.inline(tmpl)}</span> {content}</li>')
            else:
                lis.append(f"<li>{content}</li>")
        if name == "description":
            return "<dl>" + "".join(lis) + "</dl>"
        tag = "ol" if name in ("enumerate", "compactenum") else "ul"
        cls = ' class="custom"' if tmpl or any('class="lbl"' in x for x in lis) else ""
        return f"<{tag}{cls}>" + "".join(lis) + f"</{tag}>"

    def enum_label(self, tmpl, n):
        def roman(k):
            vals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
            r = ""
            for v, sym in vals:
                while k >= v:
                    r += sym
                    k -= v
            return r
        reps = {"\\arabic*": str(n), "\\alph*": chr(96 + n) if n <= 26 else str(n),
                "\\Alph*": chr(64 + n) if n <= 26 else str(n), "\\roman*": roman(n),
                "\\Roman*": roman(n).upper()}
        t = tmpl
        for a, b in reps.items():
            t = t.replace(a, b)
        return self.inline(t)

    def flow(self, src):
        """Content that may hold blocks (list items, table cells): a single paragraph is unwrapped."""
        h = self.blocks(src).strip()
        if h.startswith("<p>") and h.endswith("</p>") and h.count("<p>") == 1:
            return h[3:-4]
        return h

    def caption_html(self, cap, kind):
        labs = re.findall(r"\\label\{([^}]*)\}", cap)
        cap = re.sub(r"\\label\{[^}]*\}", "", cap)
        num = self.page.next_num(kind)
        word = "Table" if kind == "table" else "Figure"
        for lab in labs:
            self.site.register_label(lab, self.page, html_id(lab), num=num, title=f"{word} {num}")
        anchor = "".join(f'<span id="{html_id(x)}" class="anchor"></span>' for x in labs)
        return f'<figcaption>{anchor}<b>{word} {num}.</b> {self.inline(cap)}</figcaption>'

    def float_env(self, body, kind):
        caps, rest, i = [], [], 0
        for m in re.finditer(r"\\caption(of)?\b", body):
            if m.start() < i:
                continue
            rest.append(body[i:m.start()])
            j = m.end()
            if m.group(1):
                _, j = read_arg(body, j)
            _, j = read_opt(body, j)
            cap, j = read_arg(body, j)
            caps.append(cap)
            i = j
        rest.append(body[i:])
        body = "".join(rest)
        labs = re.findall(r"\\label\{([^}]*)\}", body)
        body = re.sub(r"\\label\{[^}]*\}", "", body)
        if caps:
            cap = caps[0] + "".join(f"\\label{{{x}}}" for x in labs)
            self.alt = shorten(strip_tags(self.inline(re.sub(r"\\label\{[^}]*\}", "", cap))), 160)
        else:
            cap = None
            for lab in labs:
                self.site.register_label(lab, self.page, html_id(lab), title=kind)
        inner = self.blocks(body)
        self.alt = ""
        return self.figure_wrap(inner, cap, kind)

    def figure_wrap(self, inner, cap, kind):
        kind = kind or "figure"
        capt = self.caption_html(cap, kind) if cap is not None else ""
        return f'<figure class="{kind}">{inner}{capt}</figure>'

    def image(self, path):
        url = self.site.copy_image(path)
        if not url:
            self.site.log("missing image", self.page, path)
            return f'<span class="missing">image missing: {esc(path)}</span>'
        return f'<a href="{url}"><img src="{url}" alt="{esc(self.alt or "figure from the notes")}" loading="lazy"></a>'

    def stepanim(self, nf, cap, body):
        try:
            n = int(nf.strip())
        except ValueError:
            raise Unsupported("non-numeric frame count")
        labs = re.findall(r"\\label\{([^}]*)\}", cap)
        alt = shorten(strip_tags(self.inline(re.sub(r"\\label\{[^}]*\}", "", cap))), 160)
        frames = []
        gid = hashlib.sha1(body.encode("utf-8")).hexdigest()[:12]
        for k in range(1, n + 1):
            src = (f"\\begin{{tikzpicture}}\\edef\\f{{{k}}}{body}\\sg@frametitle{{{k}}}\\end{{tikzpicture}}")
            frames.append(self.site.job_img(src, self, kind="frame", alt=f"Step {k} of {n}: {alt}",
                                            lazy=k > 1, cls="frame", group=gid))
        capt = self.caption_html(cap, "figure")
        dots = "".join(f'<button class="dot" aria-label="Step {k}" data-k="{k - 1}"></button>' for k in range(1, n + 1))
        return (f'<figure class="anim" data-n="{n}"><div class="anim-stage" tabindex="0" '
                f'aria-roledescription="animation" aria-label="{esc(alt)}">{"".join(frames)}</div>'
                f'<div class="anim-ctl" hidden><button class="prev" aria-label="Previous step">&#9664;</button>'
                f'<button class="play" aria-label="Play">&#9654; Play</button>'
                f'<button class="next" aria-label="Next step">&#9654;&#124;</button>'
                f'<span class="dots">{dots}</span><span class="cnt">1 / {n}</span></div>{capt}</figure>')

    # ------------------------------------------------------------------ tables
    def table(self, name, body):
        k = 0
        if name in ("tabularx", "xltabular", "tabular*", "tabulary"):
            _, k = read_arg(body, 0)
        _, k = read_opt(body, k)
        spec, k = read_arg(body, k)
        aligns = col_aligns(spec)
        rows_raw = split_top(body[k:], ["\\\\", "\\tabularnewline"])
        groups, cur = [], []
        marker_re = re.compile(r"\\(endfirsthead|endhead|endfoot|endlastfoot)\b")
        rows = []          # (is_header, cells_src)
        seen_mid = False
        head_rows = []
        for idx, (_sep, row) in enumerate(rows_raw):
            row = re.sub(r"^\s*\[[^\]]*\]", "", row)           # \\[2pt]
            mk = marker_re.findall(row)
            pre_mid = bool(re.match(r"\s*(\\(hline|toprule|addlinespace|cline\{[^}]*\}|cmidrule(\([^)]*\))?\{[^}]*\}|rowcolor(\[[^\]]*\])?\{[^}]*\})\s*)*\\midrule", row)) or \
                bool(re.match(r"\s*\\endhead", row))
            row = marker_re.sub("", row)
            row = re.sub(r"\\(hline|toprule|midrule|bottomrule|addlinespace(\[[^\]]*\])?|hdashline)\b", "", row)
            row = re.sub(r"\\(cline|cmidrule)(\([^)]*\))?\{[^}]*\}", "", row)
            row = re.sub(r"\\noalign\{[^{}]*\}", "", row)
            row = re.sub(r"\\rowcolor(\[[^\]]*\])?\{[^}]*\}", "", row)
            if pre_mid and not seen_mid and rows:
                seen_mid = True
                head_rows = list(range(len(rows)))
            for m_ in mk:
                if m_ in ("endfoot", "endlastfoot"):
                    # rows since the last group boundary are a repeated footer: drop them
                    while rows and rows[-1][2] >= len(groups):
                        rows.pop()
                    head_rows = [h for h in head_rows if h < len(rows)]
                if m_ == "endfirsthead":
                    pass
                groups.append(idx)
            if not row.strip():
                continue
            rows.append((None, row, len(groups)))
        if not rows:
            return ""
        out = ['<div class="tbl"><table>']
        pending = {}     # col -> rows still covered by a multirow
        hdr_done = False
        for ri, (_, row, _g) in enumerate(rows):
            is_head = ri in head_rows
            if not is_head and head_rows and not hdr_done:
                out.append("</thead><tbody>")
                hdr_done = True
            elif ri == 0:
                out.append("<thead>" if is_head else "<tbody>")
                hdr_done = not is_head
            cells = [p for _s, p in split_top(row, ["&"])]
            tds, col = [], 0
            for cell in cells:
                while pending.get(col, 0) > 0:
                    pending[col] -= 1
                    col += 1
                    if cell.strip() == "":
                        break
                else:
                    pass
                attrs, cs, rs = [], 1, 1
                c = cell.strip()
                bg = None
                m = re.search(r"\\cellcolor(\[[^\]]*\])?\{([^}]*)\}", c)
                if m:
                    bg = css_color(m.group(2))
                    c = c[:m.start()] + c[m.end():]
                m = re.match(r"\\multicolumn\s*\{(\d+)\}", c)
                if m:
                    cs = int(m.group(1))
                    j = m.end()
                    spec2, j = read_arg(c, j)
                    c, _ = read_arg(c, j)
                    a2 = col_aligns(spec2)
                    al = a2[0] if a2 else "l"
                else:
                    al = aligns[col] if col < len(aligns) else "l"
                m = re.match(r"\s*\\multirow\s*(\[[^\]]*\])?\s*\{(\d+)\}", c)
                if m:
                    rs = int(m.group(2))
                    j = m.end()
                    _, j = read_opt(c, j)
                    _, j = read_arg(c, j)
                    _, j = read_opt(c, j)
                    c, _ = read_arg(c, j)
                    if rs > 1:
                        for cc in range(col, col + cs):
                            pending[cc] = rs - 1
                tag = "th" if is_head or c.startswith("\\thead") else "td"
                if cs > 1:
                    attrs.append(f'colspan="{cs}"')
                if rs > 1:
                    attrs.append(f'rowspan="{rs}"')
                if al in ("c", "r"):
                    attrs.append(f'class="{al}"')
                if bg:
                    attrs.append(f'style="background:{bg}"')
                a = (" " + " ".join(attrs)) if attrs else ""
                tds.append(f"<{tag}{a}>{self.flow(c)}</{tag}>")
                col += cs
            out.append("<tr>" + "".join(tds) + "</tr>")
            for cc in list(pending):
                if pending[cc] and cc >= col:
                    pending[cc] -= 1
        out.append("</thead></table></div>" if not hdr_done else "</tbody></table></div>")
        return "".join(out)

    # ------------------------------------------------------------------ inline
    def inline(self, s: str) -> str:
        out, i, n = [], 0, len(s)
        while i < n:
            c = s[i]
            if c == "\\":
                m = CMD_RE.match(s, i)
                name = m.group(1)
                j = m.end()
                if name in SWITCHES:
                    cls = SWITCH_CLASS.get(SWITCHES[name])
                    rest = self.inline(s[j:])
                    out.append(f'<span class="{cls}">{rest}</span>' if cls and rest.strip() else rest)
                    return "".join(out)
                if name == "color":
                    col, j = read_arg(s, j)
                    rest = self.inline(s[j:])
                    cls = COLOR_CLASS.get(col.split("!")[0].strip())
                    out.append(f'<span class="{cls}">{rest}</span>' if cls else rest)
                    return "".join(out)
                h, i = self.command(name, s, j)
                out.append(h)
                continue
            if c == "{":
                inner, i = read_group(s, i)
                out.append(self.inline(inner))
                continue
            if c == "}":
                raise Unsupported("unbalanced }")
            if c == "$":
                closer = "$$" if s.startswith("$$", i) else "$"
                j = find_math_end(s, i + len(closer), closer)
                out.append(self.math(s[i + len(closer):j], closer == "$$"))
                i = j + len(closer)
                continue
            if c == "~":
                out.append("\u00a0")
            elif s.startswith("---", i):
                out.append("—")
                i += 3
                continue
            elif s.startswith("--", i):
                out.append("–")
                i += 2
                continue
            elif s.startswith("``", i):
                out.append("“")
                i += 2
                continue
            elif s.startswith("''", i):
                out.append("”")
                i += 2
                continue
            elif c == "`":
                out.append("‘")
            elif c == "'":
                out.append("’")
            elif c == "&":
                out.append("&amp;")
            elif c == "<":
                out.append("&lt;")
            elif c == ">":
                out.append("&gt;")
            elif c == '"':
                out.append("&quot;")
            elif c in "\n\t\r":
                out.append(" ")
            elif c == "#":
                raise Unsupported("macro parameter #")
            else:
                out.append(c)
            i += 1
        return "".join(out)

    def command(self, name, s, j):
        """One inline command starting after its name at s[j]; returns (html, new index)."""
        site = self.site
        if name in site.user_macros:
            nargs, default, body = site.user_macros[name]
            args = []
            if default is not None:
                o, j = read_opt(s, j)
                args.append(default if o is None else o)
            while len(args) < nargs:
                a, j = read_arg(s, j)
                args.append(a)
            for k, a in enumerate(args, 1):
                body = body.replace(f"#{k}", a)
            return self.inline(body), j
        if name == "\\":
            if j < len(s) and s[j] == "*":
                j += 1
            _, j = read_opt(s, j)
            return "<br>", j
        if name in TEXT_SYMBOLS:
            if name.isalpha() and j < len(s) and s[j] == " ":
                j += 1   # a control word eats the following space; keep one for readability
                return TEXT_SYMBOLS[name] + (" " if name not in ("dotfill", "newline", "hfill") else ""), j
            if j + 1 < len(s) and s[j:j + 2] == "{}":
                j += 2
            return TEXT_SYMBOLS[name], j
        if name in ACCENTS and len(name) == 1 and j < len(s):
            a, j = read_arg(s, j)
            base = self.inline(a)
            return unicodedata.normalize("NFC", base + ACCENTS[name]) if len(base) == 1 else base, j
        if name in ("i", "j") and j < len(s) and s[j] in " {":
            return ("ı" if name == "i" else "ȷ"), j
        if name in IGNORE_ARGS:
            n_args = IGNORE_ARGS[name]
            _, j = read_opt(s, j)
            if name == "cmidrule":
                k = skip_ws(s, j)
                if k < len(s) and s[k] == "(":
                    j = s.index(")", k) + 1
            for _ in range(n_args):
                _, j = read_arg(s, j)
            return "", j
        if name in ("hspace", "hspace*", "hskip", "kern"):
            if name in ("hskip", "kern"):
                m = re.match(r"\s*-?[\d.]+\s*[a-z]{2}", s[j:])
                return " ", j + (m.end() if m else 0)
            _, j = read_arg(s, j)
            return " ", j
        if name in ("newcommand", "renewcommand", "providecommand", "newcommand*", "renewcommand*",
                    "DeclareRobustCommand", "def"):
            return self.define(name, s, j)
        if name in TEXT_WRAP:
            a, j = read_arg(s, j)
            o, c = TEXT_WRAP[name]
            return o + self.inline(a) + c, j
        if name in ("makebox", "framebox", "parbox", "raisebox", "scalebox", "resizebox", "adjustbox"):
            _, j = read_opt(s, j)
            if name in ("parbox", "raisebox", "scalebox"):
                _, j = read_arg(s, j)
            if name == "resizebox":
                _, j = read_arg(s, j)
                _, j = read_arg(s, j)
            if name == "adjustbox":
                _, j = read_arg(s, j)
            _, j = read_opt(s, j)
            a, j = read_arg(s, j)
            return self.inline(a), j
        if name == "makecell":
            _, j = read_opt(s, j)
            a, j = read_arg(s, j)
            return self.inline(a), j
        if name in ("textcolor", "colorbox"):
            col, j = read_arg(s, j)
            a, j = read_arg(s, j)
            cls = COLOR_CLASS.get(col.split("!")[0].strip(), "")
            if name == "colorbox":
                return f'<span class="cbox" style="background:{css_color(col)}">{self.inline(a)}</span>', j
            return f'<span class="{cls}">{self.inline(a)}</span>', j
        if name == "mks":
            a, j = read_arg(s, j)
            return pill("mks", self.inline(a) + " M"), j
        if name == "tier":
            a, j = read_arg(s, j)
            return tier_pill(a.strip()), j
        if name == "prob":
            a, j = read_arg(s, j)
            return prob_pill(a.strip()), j
        if name == "ev":
            a, j = read_arg(s, j)
            return pill("ev", "EV " + self.inline(a)), j
        if name == "asked":
            a, j = read_arg(s, j)
            return f'<span class="asked"><b>Asked:</b> {self.inline(a)}</span>', j
        if name == "src":
            a, j = read_arg(s, j)
            t = a.replace("\\_", "_").replace("\\&", "&").replace("\\%", "%")
            return f'<span class="src">[{esc(t)}]</span>', j
        if name == "stepno":
            a, j = read_arg(s, j)
            return f'<span class="stepno">{self.inline(a)}</span>', j
        if name == "clusterbadge":
            a, j = read_arg(s, j)
            return site.cluster_badge(a.strip()), j
        if name == "topicbadge":
            a, j = read_arg(s, j)
            return site.topic_badge(a.strip()), j
        if name == "pyqsolved":
            a, j = read_arg(s, j)
            return f'solved: {site.ref_link("q:" + a.strip(), self.page)}', j
        if name == "seesolved":
            a, j = read_arg(s, j)
            lab = "solve:" + a.strip()
            return (f'<span class="seesolved">Same idea as {site.ref_link(lab, self.page)}: full solution '
                    f'there</span>'), j
        if name == "flashcard":
            f, j = read_arg(s, j)
            b, j = read_arg(s, j)
            self.page.flashcards.append((f, b))
            return "", j
        if name == "label":
            a, j = read_arg(s, j)
            lab = a.strip()
            site.register_label(lab, self.page, html_id(lab))
            return f'<span id="{html_id(lab)}" class="anchor"></span>', j
        if name in ("ref", "pageref", "autoref", "nameref", "cref", "Cref", "eqref", "sgwebpref",
                    "ref*", "pageref*", "nameref*"):
            a, j = read_arg(s, j)
            return site.ref_link(a.strip(), self.page, page_style=name.startswith(("pageref", "sgwebpref"))), j
        if name == "hyperref":
            lab, j = read_opt(s, j)
            a, j = read_arg(s, j)
            if lab:
                return site.ref_link(lab.strip(), self.page, text=self.inline(a)), j
            return self.inline(a), j
        if name == "href":
            u, j = read_arg(s, j)
            a, j = read_arg(s, j)
            u = u.replace("\\#", "#").replace("\\%", "%").replace("\\_", "_")
            return f'<a href="{esc(u)}" rel="noopener">{self.inline(a)}</a>', j
        if name == "url":
            u, j = read_arg(s, j)
            return f'<a href="{esc(u)}" rel="noopener">{esc(u)}</a>', j
        if name in ("verb", "lstinline"):
            if j < len(s) and s[j] == "[":
                _, j = read_opt(s, j)
            d = s[j]
            if d == "{":
                a, j = read_group(s, j)
                return f"<code>{esc(a)}</code>", j
            k = s.index(d, j + 1)
            return f"<code>{esc(s[j + 1:k])}</code>", k + 1
        if name == "(":
            k = find_math_end(s, j, "\\)")
            return self.math(s[j:k], False), k + 2
        if name == "[":
            k = find_math_end(s, j, "\\]")
            return self.math(s[j:k], True), k + 2
        if name == "ensuremath":
            a, j = read_arg(s, j)
            return self.math(a, False), j
        if name == "texorpdfstring":   # {TeX}{PDF-bookmark text}: the page shows the TeX form
            a, j = read_arg(s, j)
            _, j = read_arg(s, j)
            return self.inline(a), j
        if name in ("SI", "qty"):
            _, j = read_opt(s, j)
            v, j = read_arg(s, j)
            u, j = read_arg(s, j)
            return esc(v) + "\u00a0" + si_units(u), j
        if name in ("si", "unit"):
            _, j = read_opt(s, j)
            u, j = read_arg(s, j)
            return si_units(u), j
        if name == "num":
            _, j = read_opt(s, j)
            v, j = read_arg(s, j)
            return esc(v), j
        if name in ("multicolumn",):
            _, j = read_arg(s, j)
            _, j = read_arg(s, j)
            a, j = read_arg(s, j)
            return self.inline(a), j
        if name == "multirow":
            _, j = read_opt(s, j)
            _, j = read_arg(s, j)
            _, j = read_opt(s, j)
            _, j = read_arg(s, j)
            _, j = read_opt(s, j)
            a, j = read_arg(s, j)
            return self.inline(a), j
        if name in ("caption", "captionof"):
            if name == "captionof":
                _, j = read_arg(s, j)
            _, j = read_opt(s, j)
            a, j = read_arg(s, j)
            return f'<span class="caption">{self.inline(a)}</span>', j
        if name == "includegraphics":
            _, j = read_opt(s, j)
            p, j = read_arg(s, j)
            return self.image(p.strip()), j
        if name == "receipt":
            a, j = read_arg(s, j)
            return site.receipt_html(a.strip()), j
        if name == "begin":
            env, j = read_group(s, j)
            a, b = find_end(s, env, j)
            src = s[j - len(env) - 8:b]
            return self.env(env, s[j:a], src), b
        if name in ("item",):
            raise Unsupported("\\item outside a list")
        if name in ("paragraph", "paragraph*"):
            a, j = read_arg(s, j)
            return f"<strong>{self.inline(a)}</strong> ", j
        if name in ("rule",):
            _, j = read_opt(s, j)
            _, j = read_arg(s, j)
            _, j = read_arg(s, j)
            return "", j
        if name == "today":
            return time.strftime("%d %b %Y"), j
        raise Unsupported(f"unknown command \\{name}")

    def define(self, name, s, j):
        if name == "def":
            m = re.match(r"\s*\\([A-Za-z@]+)", s[j:])
            if not m:
                raise Unsupported("\\def")
            j += m.end()
            k = skip_ws(s, j)
            if k < len(s) and s[k] == "{":
                body, j = read_group(s, k)
                self.site.user_macros[m.group(1)] = (0, None, body)
                return "", j
            raise Unsupported("\\def with parameters")
        k = skip_ws(s, j)
        if s[k] == "{":
            nm, j = read_group(s, k)
        else:
            m = CMD_RE.match(s, k)
            nm, j = m.group(0), m.end()
        nm = nm.strip().lstrip("\\")
        na, j = read_opt(s, j)
        de, j = read_opt(s, j)
        body, j = read_arg(s, j)
        if nm in ("arraystretch", "theadfont", "tabcolsep"):
            return "", j
        self.site.user_macros[nm] = (int(na or 0), de, body)
        return "", j

    # ------------------------------------------------------------------ math
    def math(self, tex, display):
        t = tex.strip()
        # \answer{$20\,000$ bits} inside maths: text with nested maths -> \boxed{\text{..}}
        t = rewrite_cmd(t, "answer", lambda a: "\\boxed{\\text{" + a + "}}" if "$" in a else "\\boxed{" + a + "}")
        t = rewrite_cmd(t, "keyword", lambda a: "\\textbf{" + a + "}")
        for pat, rep in MATH_REWRITE:
            t = re.sub(pat, rep, t)
        t = self.expand_math_macros(t)
        for m in re.finditer(r"\\([A-Za-z]+|.)", t, re.S):     # '\\v' is a row break + v, not \v
            nm = m.group(1)
            if nm.isalpha() and nm not in KATEX_OK:
                raise Unsupported(f"math \\{nm}")
        for m in re.finditer(r"\\(?:begin|end)\{([^}]*)\}", t):
            if m.group(1) not in KATEX_ENVS:
                raise Unsupported(f"math environment {m.group(1)}")
        if self.math_mode == "anki":
            return (r"\[" if display else r"\(") + esc(t, quote=False) + (r"\]" if display else r"\)")
        self.page.has_math = True
        if display:
            return f'<div class="md">{esc(t, quote=False)}</div>'
        parts = split_tuple_list(t) if len(t) > 40 else [t]
        # a list of tuples "(1,0,-2),(0,1,-1),..." has no operator KaTeX may break at: one span per tuple
        return ", ".join(f'<span class="m">{esc(p, quote=False)}</span>' for p in parts)

    def expand_math_macros(self, t):
        um = self.site.user_macros
        if not um:
            return t
        for _ in range(5):
            changed = False

            def rep(m):
                nonlocal changed
                nm = m.group(1)
                if nm in um and um[nm][0] == 0:
                    changed = True
                    return um[nm][2]
                return m.group(0)
            t = re.sub(r"\\([A-Za-z]+|.)", rep, t, flags=re.S)
            if not changed:
                break
        return t

    # ------------------------------------------------------------------ fallback
    def fallback(self, src, reason):
        if not self.allow_fallback:
            raise Unsupported(reason)
        if not latex_balanced(src) or re.search(r"(?<!\\)#\d", src):
            # a fragment (unbalanced, or a macro body with #1 parameters) cannot compile on its own:
            # show it as text rather than send LaTeX a document that fails
            self.site.issues.append(("unrenderable fragment shown as text", self.page.url,
                                     f"{reason}: {shorten(re.sub(r'\s+', ' ', src), 120)}"))
            return f'<p class="fallback-text">{esc(latex_to_text(src))}</p>'
        self.site.fallbacks.append({"page": self.page.url, "reason": reason, "src": src})
        # cross-references cannot resolve in a standalone image: mark them, and list them as real links
        refre = re.compile(r"\\(?:ref|pageref|sgwebpref|nameref|autoref|eqref)\*?\{([^}]*)\}")
        labs = refre.findall(src)
        body = refre.sub(lambda m: "\\textsuperscript{[link]}", src)
        wrapped = f"\\begin{{minipage}}{{95mm}}\\raggedright\n{body}\n\\end{{minipage}}"
        img = self.site.job_img(wrapped, self, kind="fallback", alt=shorten(re.sub(r"\s+", " ", src), 120))
        links = ""
        if labs:
            links = '<p class="fb-links">Links: ' + ", ".join(self.site.ref_link(x.strip(), self.page, page_style=True) for x in labs) + "</p>"
        return f'<div class="fallback" title="rendered from LaTeX: {esc(reason)}">{img}{links}</div>'


def arg_chain_end(s, j):
    """Index after the [..]/{..} groups that directly follow a command (spaces and single newlines
    allowed between them, a blank line ends the chain)."""
    while True:
        k = j
        while k < len(s) and s[k] in " \t\r\n":
            if s[k] == "\n" and "\n" in s[j:k]:
                return j          # blank line
            k += 1
        if k < len(s) and s[k] == "{":
            try:
                _, j = read_group(s, k)
            except Unsupported:
                return j
        elif k < len(s) and s[k] == "[":
            try:
                o, k2 = read_opt(s, k)
            except Unsupported:
                return j
            if o is None:
                return j
            j = k2
        else:
            return j


def cmd_extent(name, s, j):
    """End of a block command's source (for the fallback image): its own arguments, never past the
    end of the enclosing environment."""
    try:
        if name == "[":
            return find_math_end(s, j, "\\]") + 2
        return arg_chain_end(s, j + (1 if s[j:j + 1] == "*" else 0))
    except Unsupported:
        k = s.find("\n\n", j)
        return len(s) if k < 0 else k


def split_tuple_list(t):
    """Split inline maths at top-level '),(' (brace depth 0, outside \\left..\\right and environments)."""
    if "\\begin" in t or "\\left" in t:
        return [t]
    parts, depth, start, i = [], 0, 0, 0
    while i < len(t):
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "," and depth == 0 and t[:i].rstrip().endswith(")") and t[i + 1:].lstrip().startswith("("):
            parts.append(t[start:i].strip())
            start = i + 1
        i += 1
    parts.append(t[start:].strip())
    parts = [p for p in parts if p]
    # only a plain list of tuples: every piece must balance on its own ('\{(1,2),(3,4)\}' must not split)
    if len(parts) < 2 or re.search(r"\\\{|\\\}|\\lbrace|\\rbrace|\\langle|\\rangle|\[|\]", t) or \
            any(p.count("(") != p.count(")") or p.count("{") != p.count("}") for p in parts):
        return [t]
    return parts


def latex_balanced(src):
    """True when braces and \\begin/\\end pairs balance (a fragment that does not balance would make the
    standalone render swallow the wrapper's own \\end{minipage})."""
    depth, i = 0, 0
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    if depth:
        return False
    stack = []
    for m in re.finditer(r"\\(begin|end)\s*\{([^}]*)\}", src):
        if m.group(1) == "begin":
            stack.append(m.group(2))
        elif not stack or stack.pop() != m.group(2):
            return False
    return not stack


def rewrite_cmd(t, name, fn):
    """Replace every \\name{arg} (balanced braces) in t by fn(arg)."""
    out, i = [], 0
    pat = re.compile(r"\\" + name + r"(?![A-Za-z])\s*\{")
    while True:
        m = pat.search(t, i)
        if not m:
            out.append(t[i:])
            return "".join(out)
        arg, j = read_group(t, m.end() - 1)
        out.append(t[i:m.start()])
        out.append(fn(arg))
        i = j


def shrink_receipt(src, dst, max_w=1100):
    """Receipts are crops of scanned/printed paper: 16-level greyscale PNG, at most max_w px wide
    (about 10x smaller than the RGB crop, still sharp on a phone)."""
    try:
        from PIL import Image
        im = Image.open(src)
        im = im.convert("L")
        if im.width > max_w:
            im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
        im = im.quantize(colors=16, dither=Image.Dither.NONE)
        im.save(dst, optimize=True)
        if dst.stat().st_size >= src.stat().st_size:
            shutil.copyfile(src, dst)
    except Exception:          # noqa: BLE001 - an unreadable image is still copied as-is
        shutil.copyfile(src, dst)


def col_aligns(spec):
    spec = re.sub(r"[<>@!]\{(?:[^{}]|\{[^{}]*\})*\}", "", spec)

    def expand(m):
        return m.group(2) * int(m.group(1))
    for _ in range(3):
        spec = re.sub(r"\*\{(\d+)\}\{([^{}]*)\}", expand, spec)
    spec = re.sub(r"[pmbLRCw]\{[^{}]*\}", "p", spec)
    spec = re.sub(r"[PM]\{[^{}]*\}", "p", spec)
    out = []
    for ch in spec:
        if ch in "lcr":
            out.append(ch)
        elif ch in "pXYSm":
            out.append("l")
    return out


def css_color(c):
    c = c.strip()
    m = re.match(r"([A-Za-z]+)(?:!(\d+)(?:!([A-Za-z]+))?)?", c)
    if not m:
        return "transparent"
    rgb = PALETTE.get(m.group(1), (128, 128, 128))
    pct = int(m.group(2)) if m.group(2) else 100
    if m.group(3) and m.group(3) != "white":
        other = PALETTE.get(m.group(3), (0, 0, 0))
        rgb = tuple(int(a * pct / 100 + b * (100 - pct) / 100) for a, b in zip(rgb, other))
        return f"rgb{rgb}"
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{pct / 100:.2f})"


def si_units(u):
    parts = re.findall(r"\\([A-Za-z]+)|([^\\\s]+)", u)
    out = ""
    for a, b in parts:
        out += SIUNIT.get(a, a) if a else b
    return esc(out)


def pill(kind, text):
    return f'<span class="pill p-{kind}">{text}</span>'


def tier_pill(t):
    lab = {"A": "A · 3 h", "B": "B · 6 h", "C": "C · 12 h", "D": "D · wildcard"}.get(t, f"{esc(t)} · later")
    return pill(f"t{t if t in 'ABCD' else 'E'}", lab)


def prob_pill(p):
    try:
        v = int(float(p))
    except ValueError:
        return pill("plow", "P " + esc(p))
    band = "high" if v > 49 else "med" if v > 24 else "low"
    return pill("p" + band, f"P {v}%")


def band_pill(band):
    return pill("p" + ({"high": "high", "med": "med"}.get(band, "low")), f"P {esc(band)}")


# ============================================================================ pages and the site
class Page:
    def __init__(self, url, kind, title):
        self.url, self.kind, self.title = url, kind, title
        self.counters = {}
        self.flashcards = []
        self.has_math = False
        self.body = ""
        self.desc = ""
        self.extra_head = ""
        self.search_text = ""

    def next_num(self, kind):
        self.counters[kind] = self.counters.get(kind, 0) + 1
        return self.counters[kind]


class Site:
    def __init__(self, subj_name, subj, shared, scoped, out, args):
        self.S, self.subj, self.shared, self.scoped, self.out = subj_name, subj, shared, scoped, out
        self.args = args
        self.labels = {}
        self.user_macros = {}
        self.jobs = {}            # hash -> {"src", "kind", "pages": set}
        self.fallbacks = []
        self.issues = []          # (kind, page, detail)
        self.copied = {}
        self.pages = []
        self.pyq_pages = {}       # qid -> Page
        self.topic_pages = {}     # Tid -> Page
        self.load_data()
        self.cache = scoped / "build" / "web_cache"
        self.groups = {}          # animation id -> [job hashes] (its frames share one crop box)
        self.render_failed = set()
        self.svg_size = {}

    # ------------------------------------------------------------------ data
    def load_data(self):
        def j(name):
            p = self.scoped / name
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
            return {}
        self.bp = j("blueprint.json")
        self.bank = j("pyq_bank.json")
        self.iq = j("important_questions.json")
        self.subject = self.bp.get("subject") or self.S
        self.code = self.bp.get("code", "")
        self.scope = self.scoped.name.capitalize()
        self.questions = {q["id"]: q for q in self.bank.get("questions", [])}
        self.papers = {p["id"]: p for p in self.bank.get("papers", [])}
        keys = {(p.get("exam"), p.get("year")) for p in self.papers.values()}
        years = [p.get("year") for p in self.papers.values()]
        # "2024 Q1(b)" is ambiguous once a midsem and an endsem (or a spring paper) share a year
        self.mixed_papers = len(set(years)) < len(years) or len({p.get("exam") for p in self.papers.values()}) > 1
        self.mixed_papers = self.mixed_papers and len(keys) > 0
        asg = j("assignments.json")
        self.ch_kind = {c.get("stem"): c.get("kind") for c in asg.get("chapters", []) if isinstance(c, dict)}
        self.clusters = {c["id"]: dict(c) for c in self.bank.get("clusters", [])}
        for c in self.iq.get("clusters", []) or []:
            cid = c.get("cluster") or c.get("id")
            if cid:
                self.clusters.setdefault(cid, {}).update(c)
        self.topics = {}
        self.units = []
        for u in self.bp.get("units", []):
            self.units.append(u)
            for t in u.get("topics", []):
                self.topics[t["id"]] = dict(t, unit=u["id"], unit_title=u.get("title", ""))
        for t in self.iq.get("topics", []) or []:
            tid = t.get("topic") or t.get("id")
            if tid in self.topics:
                self.topics[tid]["P"] = t.get("P")
        # badges.tex (score.py) is authoritative for the displayed P / band / tier
        self.badges, self.tbadges = {}, {}
        bt = self.scoped / "badges.tex"
        if bt.exists():
            txt = bt.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"\\sgdefbadge\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", txt):
                self.badges[m.group(1)] = {"tier": m.group(2), "P": m.group(3), "band": m.group(4), "EV": m.group(5)}
            for m in re.finditer(r"\\sgdeftopic\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}", txt):
                self.tbadges[m.group(1)] = {"P": m.group(2), "band": m.group(3)}
        used = self.iq.get("model", {}).get("papers_used", {}) or {}
        self.n_relevant = sum(1 for v in used.values() if (v or 0) > 0) if used else len(self.papers)

    def band(self, p):
        if p is None:
            return None
        return "high" if p >= 0.5 else "med" if p >= 0.25 else "low"

    def topic_badge(self, tid):
        b = self.tbadges.get(tid)
        if b:
            return band_pill(b["band"]) if b["P"] == "-" else prob_pill(b["P"])
        p = self.topics.get(tid, {}).get("P")
        if p is None:
            return ""
        return prob_pill(round(p * 100)) if self.n_relevant >= 4 else band_pill(self.band(p))

    def cluster_badge(self, cid):
        b = self.badges.get(cid)
        if b:
            pp = band_pill(b["band"]) if b["P"] == "-" else prob_pill(b["P"])
            return tier_pill(b["tier"]) + " " + pp
        c = self.clusters.get(cid, {})
        if not c or c.get("P") is None:
            return ""
        p = c["P"]
        pp = prob_pill(round(p * 100)) if self.n_relevant >= 4 else band_pill(self.band(p))
        return (tier_pill(c["tier"]) + " " if c.get("tier") else "") + pp

    def paper_label(self, pid):
        """'Midsem 2024', 'Endsem 2026 spring' (the paper's own exam, not the guide's scope)."""
        p = self.papers.get(pid, {})
        exam = (p.get("exam") or self.scope).capitalize()
        sess = " spring" if str(p.get("session", "")).lower() == "spring" else ""
        return f"{exam} {p.get('year', '')}{sess}".strip()

    def qlabel(self, qid):
        q = self.questions.get(qid)
        if not q:
            return qid
        p = self.papers.get(q.get("paper"), {})
        if self.mixed_papers:
            return f"{self.paper_label(q.get('paper'))} Q{q.get('qno', '')}"
        return f"{p.get('year', '')} Q{q.get('qno', '')}".strip()

    def log(self, kind, page, detail):
        self.issues.append((kind, page.url if page else "", detail))

    # ------------------------------------------------------------------ labels and links
    def register_label(self, lab, page, anchor, num=None, title=None, title_html=None):
        cur = self.labels.get(lab)
        if cur and cur["page"] is not page and cur["page"].kind != "chapter":
            return    # first definition on a dedicated page wins (topic / PYQ pages beat chapter pages)
        if cur and cur["page"] is page:
            if title and not cur.get("title"):
                cur["title"] = title
            if num and not cur.get("num"):
                cur["num"] = num
            return
        self.labels[lab] = {"page": page, "anchor": anchor, "num": num, "title": title, "title_html": title_html}

    def ref_link(self, lab, page, page_style=False, text=None):
        key = f"\x01REF{len(self._refs) if hasattr(self, '_refs') else 0}\x01"
        if not hasattr(self, "_refs"):
            self._refs = []
        key = f"\x01REF{len(self._refs)}\x01"
        self._refs.append((lab, page, page_style, text))
        return key

    def resolve_refs(self, h, page):
        def rep(m):
            lab, pg, page_style, text = self._refs[int(m.group(1))]
            return self._link(lab, pg, page_style, text)
        return re.sub("\x01REF(\\d+)\x01", rep, h)

    def _link(self, lab, page, page_style, text):
        info = self.labels.get(lab)
        if lab.startswith("q:") and (not info or info["page"].kind != "pyq"):
            qid = lab[2:]
            if qid in self.pyq_pages:
                info = {"page": self.pyq_pages[qid], "anchor": ""}
            elif qid in self.questions:
                tp = self.topic_pages.get(self.questions[qid].get("topic"))
                t = text or esc(self.qlabel(qid))
                if tp:
                    return f'<a class="xref" href="{tp.url}#pyq-{html_id(qid)}">{t}</a>'
                self.log("dangling ref", page, lab)
                return f'<span class="xref dead">{t}</span>'
        if not info:
            self.log("dangling ref", page, lab)
            return f'<span class="xref dead">{esc(text or lab)}</span>' if text else '<span class="xref dead">(see the PDF)</span>'
        tgt = info["page"]
        href = ("" if tgt is page else tgt.url) + (f"#{info['anchor']}" if info.get("anchor") else "")
        if not href:
            href = "#"
        if text:
            t = text
        elif info.get("num") and not page_style:
            t = str(info["num"])
        elif info.get("num"):
            t = esc(info.get("title") or "figure")
        elif lab.startswith("q:"):
            t = esc(self.qlabel(lab[2:]))
        elif lab.startswith(("iq:", "solve:")):
            cid = lab.split(":", 1)[1]
            t = esc(info.get("title") or self.clusters.get(cid, {}).get("label") or cid)
        else:
            t = info.get("title_html") or esc(info.get("title") or tgt.title)
        arrow = "→ " if page_style else ""
        return f'<a class="xref" href="{href}">{arrow}{t}</a>'

    # ------------------------------------------------------------------ assets
    def copy_image(self, path):
        cands = [self.scoped / path, self.shared / path, self.subj / path, workdir.PIPE / "latex" / path]
        for c in list(cands):
            if not c.suffix:
                cands += [c.with_suffix(e) for e in (".png", ".jpg", ".jpeg", ".pdf")]
        for c in cands:
            if c.is_file():
                if c.suffix.lower() == ".pdf":
                    return None
                key = str(c)
                if key not in self.copied:
                    name = f"img/{hashlib.sha1(key.encode()).hexdigest()[:10]}{c.suffix.lower()}"
                    self.copied[key] = name
                    dst = self.out / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(c, dst)
                return self.copied[key]
        return None

    def receipt_html(self, qid):
        src = self.scoped / "receipts" / f"{qid}.png"
        if not src.is_file():
            return f'<p class="missing">receipt missing: {esc(qid)}</p>'
        dst = self.out / "receipts" / f"{qid}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shrink_receipt(src, dst)
        return (f'<figure class="receipt"><a href="receipts/{esc(qid)}.png"><img src="receipts/{esc(qid)}.png" '
                f'alt="{esc(qid)} as printed on the question paper" loading="lazy"></a>'
                f'<figcaption>From the paper ({esc(qid)})</figcaption></figure>')

    def pyq_card(self, qid):
        q = self.questions.get(qid, {})
        pg = self.pyq_pages.get(qid)
        t = esc(shorten(q.get("text", ""), 150))
        head = f"Q{esc(q.get('qno', qid))}"
        mk = pill("mks", f"{q.get('marks', '?')} M") if q else ""
        link = f'<a href="{pg.url}">{head}</a>' if pg else head
        return f'<div class="qcard"><div class="qcard-h">{link} {mk}</div><div class="qcard-t">{t}</div></div>'

    # ------------------------------------------------------------------ render jobs
    def job_img(self, src, conv, kind, alt="", lazy=True, cls=None, group=None):
        h = hashlib.sha1(("v1\n" + src).encode("utf-8")).hexdigest()[:16]
        job = self.jobs.setdefault(h, {"src": src, "kind": kind, "pages": set()})
        job["pages"].add(conv.page.url)
        if group and h not in self.groups.setdefault(group, []):
            self.groups[group].append(h)
        lz = ' loading="lazy"' if lazy else ""
        c = cls or kind
        return f'<img class="{c}" src="fig/{h}.svg" data-job="{h}" alt="{esc(alt)}"{lz}>'


# ============================================================================ rendering (pdflatex -> svg)
PREAMBLE_FILE = WEBSRC / "render_preamble.tex"


def fail_is_current(cache, key, dh):
    """A cached render failure is reused only while the chapters' collected definitions are unchanged (a failure
    such as 'Environment olbox undefined' must be retried once collect_defs supplies the definition). A stale
    failure is deleted; the definitions hash is written next to every failure after a render pass."""
    f, fd = cache / f"{key}.fail", cache / f"{key}.faildefs"
    if not f.exists():
        return False
    if fd.exists() and fd.read_text(encoding="utf-8").strip() == dh:
        return True
    f.unlink()
    fd.unlink(missing_ok=True)
    return False


def render_jobs(site, jobs_n=3):
    """Compile every queued job (cached by content hash) and write fig/<hash>.svg."""
    figdir = site.out / "fig"
    figdir.mkdir(parents=True, exist_ok=True)
    cache = site.cache
    cache.mkdir(parents=True, exist_ok=True)
    pre = PREAMBLE_FILE.read_text(encoding="utf-8")
    ver = hashlib.sha1((pre + STY.read_text(encoding="utf-8", errors="replace") +
                        ((site.scoped / "badges.tex").read_text(encoding="utf-8", errors="replace")
                         if (site.scoped / "badges.tex").exists() else "")).encode()).hexdigest()[:10]
    defs = "\n".join(site.preamble_defs)
    dh = hashlib.sha1(defs.encode()).hexdigest()[:10]
    todo = []
    for h, job in site.jobs.items():
        key = f"{h}-{ver}"
        job["key"] = key
        if (cache / f"{key}.svg").exists() or fail_is_current(cache, key, dh):
            continue
        todo.append(h)
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    t0 = time.time()
    if batches:
        print(f"render: {len(todo)} of {len(site.jobs)} jobs to compile in {len(batches)} batch(es)")
        with ThreadPoolExecutor(max_workers=max(1, jobs_n)) as ex:
            list(ex.map(lambda b: compile_batch(site, b, pre, defs, cache), batches))
        print(f"render: done in {time.time() - t0:.0f}s")
        for h in todo:   # stamp new failures with the definitions they were compiled against
            if (cache / f"{site.jobs[h]['key']}.fail").exists():
                (cache / f"{site.jobs[h]['key']}.faildefs").write_text(dh, encoding="utf-8")
    # crop each SVG to what is actually drawn (TikZ may draw outside a 'use as bounding box' rectangle);
    # every frame of one animation gets the union box, so the frames stay aligned
    boxes = {}
    for h, job in site.jobs.items():
        bj = cache / f"{job['key']}.json"
        if bj.exists():
            boxes[h] = json.loads(bj.read_text(encoding="utf-8"))
    for g, hs in site.groups.items():
        bs = [boxes[x] for x in hs if x in boxes]
        if bs:
            u = [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]
            for x in hs:
                if x in boxes:
                    boxes[x] = u
    for h, job in site.jobs.items():
        key = job["key"]
        f = cache / f"{key}.svg"
        if f.exists():
            svg = f.read_text(encoding="utf-8")
            if h in boxes:
                x0, y0, x1, y1 = boxes[h]
                w, ht = round(x1 - x0, 2), round(y1 - y0, 2)
                svg = re.sub(r'width="[\d.]+" height="[\d.]+" viewBox="[^"]*"',
                             f'width="{w}" height="{ht}" viewBox="{round(x0, 2)} {round(y0, 2)} {w} {ht}"', svg, count=1)
            (figdir / f"{h}.svg").write_text(svg, encoding="utf-8")
            m = re.search(r'width="([\d.]+)" height="([\d.]+)"', svg[:600])
            if m:
                site.svg_size[h] = (float(m.group(1)), float(m.group(2)))
        else:
            reason = ((cache / f"{key}.fail").read_text(encoding="utf-8") if (cache / f"{key}.fail").exists()
                      else "render preamble failed: " + getattr(site, "preamble_error", "not rendered"))
            site.render_failed.add(h)
            site.issues.append(("render failed", ", ".join(sorted(job["pages"])), f"{job['kind']} {h}: {reason}"))


def compile_batch(site, hashes, pre, defs, cache, single=False):
    doc = [pre.replace("%%DEFS%%", defs)]
    for k, h in enumerate(hashes):
        doc.append(f"\\typeout{{SGWEBJOB:{k}}}\n\\begin{{preview}}{site.jobs[h]['src']}\\end{{preview}}\n")
    doc.append("\\typeout{SGWEBJOB:END}\n\\end{document}\n")
    tmp = Path(tempfile.mkdtemp(prefix="sgweb_"))
    try:
        (tmp / "r.tex").write_text("".join(doc), encoding="utf-8")
        env = dict(os.environ)
        sep = ";" if os.name == "nt" else ":"
        env["TEXINPUTS"] = sep.join([str(workdir.PIPE / "latex"), str(site.scoped), str(site.shared), ""])
        try:
            subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error" if single else "-interaction=nonstopmode",
                            "r.tex"], cwd=tmp, env=env, capture_output=True, timeout=600 if not single else 180)
        except subprocess.TimeoutExpired:
            pass
        log = (tmp / "r.log").read_text(encoding="utf-8", errors="replace") if (tmp / "r.log").exists() else ""
        errs = {}
        cur = None
        for line in log.splitlines():
            m = re.match(r"SGWEBJOB:(\d+|END)", line)
            if m:
                cur = None if m.group(1) == "END" else int(m.group(1))
                continue
            if line.startswith("!") and cur is not None:
                errs.setdefault(cur, line[:200])
        pdf = tmp / "r.pdf"
        npages = 0
        doc_pdf = None
        if pdf.exists():
            import pymupdf
            doc_pdf = pymupdf.open(str(pdf))
            npages = len(doc_pdf)
        if doc_pdf is None or npages != len(hashes):
            if doc_pdf is not None:
                doc_pdf.close()
            if single:
                if errs:     # the job's own error: cache it (re-tried only when the job or the sty changes)
                    (cache / f"{site.jobs[hashes[0]]['key']}.fail").write_text(next(iter(errs.values())), encoding="utf-8")
                else:        # the preamble itself failed (sty mid-edit, missing package): never cache that
                    pre_err = re.search(r"^!.*$", log, re.M)
                    site.preamble_error = pre_err.group(0) if pre_err else "pdflatex produced no output"
                return
            head = log.split("SGWEBJOB:0", 1)[0] if "SGWEBJOB:0" in log else log
            if re.search(r"^!", head, re.M) or "SGWEBJOB:0" not in log:
                site.preamble_error = (re.search(r"^!.*$", head, re.M) or re.search(r".*", "pdflatex produced no output")).group(0)
                return              # the preamble is broken: per-job retries cannot help
            for h in hashes:        # isolate the bad job(s)
                compile_batch(site, [h], pre, defs, cache, single=True)
            return
        retry = []
        for k, h in enumerate(hashes):
            if k in errs:
                if single:
                    (cache / f"{site.jobs[h]['key']}.fail").write_text(errs[k], encoding="utf-8")
                else:
                    retry.append(h)
                continue
            pg = doc_pdf[k]
            svg = optimise_svg(pg.get_svg_image(text_as_path=True))
            (cache / f"{site.jobs[h]['key']}.svg").write_text(svg, encoding="utf-8")
            (cache / f"{site.jobs[h]['key']}.json").write_text(json.dumps(content_bbox(pg)), encoding="utf-8")
        doc_pdf.close()
        for h in retry:            # errors can cascade from a neighbour: try each failure alone
            compile_batch(site, [h], pre, defs, cache, single=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def content_bbox(page, pad=2.0):
    """Union of everything drawn on the page (paths, text, images), padded, within the page."""
    r = None
    for kind, rect in page.get_bboxlog():
        if "clip" in kind or kind.startswith("ignore"):
            continue
        x0, y0, x1, y1 = tuple(rect)
        if x1 <= x0 and y1 <= y0:
            continue
        r = [x0, y0, x1, y1] if r is None else [min(r[0], x0), min(r[1], y0), max(r[2], x1), max(r[3], y1)]
    pr = page.rect
    if r is None:
        return [pr.x0, pr.y0, pr.x1, pr.y1]
    return [max(pr.x0, r[0] - pad), max(pr.y0, r[1] - pad), min(pr.x1, r[2] + pad), min(pr.y1, r[3] + pad)]


_NUM = re.compile(r"-?\d*\.\d{3,}")


def optimise_svg(svg: str) -> str:
    """Shrink pymupdf SVG output: 3-decimal numbers, no inkscape namespace, no whitespace."""
    def rnd(m):
        o = m.group(0)
        v = round(float(o), 3)
        if v == 0:
            t = "0"
        else:
            t = f"{v:.3f}".rstrip("0").rstrip(".")
            t = t.replace("0.", ".", 1) if t.startswith("0.") else t.replace("-0.", "-.", 1)
        # path data packs numbers without separators ("1.5.25", ".096-.0001"): a leading '-' or '.'
        # may be the only separator, so when it disappears put a space in its place
        if o[0] in "-." and t[0] != o[0]:
            t = " " + t
        if "." not in t and m.string[m.end():m.end() + 1] == ".":
            t += " "       # "1" + ".5" would read as 1.5
        return t
    svg = _NUM.sub(rnd, svg)
    svg = svg.replace(' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"', "")
    svg = re.sub(r' inkscape:[a-z]+="[^"]*"', "", svg)
    svg = re.sub(r">\s+<", "><", svg)
    return svg.strip()


# ============================================================================ source assembly
def expand_inputs(txt, site, depth=0):
    """Inline \\input{atoms/notes/T07} etc. (searched like build.py's TEXINPUTS: work/<sc>, work/, latex/)."""
    if not hasattr(site, "included"):
        site.included = set()

    def rep(m):
        name = m.group(1).strip()
        if name in ("badges", "badges.tex"):
            return ""
        for base in (site.scoped, site.shared, workdir.PIPE / "latex"):
            for cand in (base / name, base / (name + ".tex")):
                if cand.is_file() and depth < 6:
                    site.included.add(cand.resolve())
                    return "\n" + expand_inputs(strip_comments(cand.read_text(encoding="utf-8", errors="replace")),
                                                site, depth + 1) + "\n"
        site.issues.append(("missing input", "", name))
        return ""
    return re.sub(r"\\(?:input|include)\{([^}]*)\}", rep, txt)


# "solved on p.\,\pageref{q:..}" -> "solved \sgwebpref{q:..}" (pages do not exist on the web)
PAGEREF_RE = re.compile(r"(?:\bon\s+)?\b(?:pp?\.|pages?)\s*(?:~|\\,|\\ |\s)*\\pageref\*?(?=\{)")


IFCS_RE = re.compile(r"\\ifcsname\s+r@([^\\]*?)\\endcsname(.*?)(?:\\else(.*?))?\\fi", re.S)


def resolve_ifcsname(txt):
    """score.py guards page references with \\ifcsname r@<label>\\endcsname .. \\else .. \\fi (does the label
    exist?). On the web every label that exists becomes a link, so keep the 'exists' branch; a missing label
    is reported by the link resolver as a dangling ref."""
    return IFCS_RE.sub(lambda m: m.group(2), txt)


def chapter_sources(site):
    """[(stem, expanded text)] in guide order. Atoms that no chapter \\inputs still get pages:
    notes atoms as an extra unit chapter, solve atoms as a 'Solved ideas' chapter."""
    chs = []
    cdir = site.scoped / "chapters"
    for p in sorted(cdir.glob("*.tex")):
        if p.stem.startswith("cheatsheet") or p.stem.startswith("_"):
            continue
        txt = strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        txt = expand_inputs(txt, site)
        chs.append((p.stem, PAGEREF_RE.sub(lambda m: "\\sgwebpref", resolve_ifcsname(txt))))
    inc = getattr(site, "included", set())
    for sub, title, stem in (("notes", "More topic notes", "zz_atoms_notes"), ("solve", "Solved ideas", "zz_atoms_solve")):
        d = site.scoped / "atoms" / sub
        if not d.is_dir():
            continue
        orphans = [p for p in sorted(d.glob("*.tex")) if p.resolve() not in inc]
        if orphans:
            body = f"\\chapter{{{title}}}\n" + "\n\n".join(
                expand_inputs(strip_comments(p.read_text(encoding="utf-8", errors="replace")), site) for p in orphans)
            chs.append((stem, body))
            site.issues.append((f"atoms/{sub} not \\input by any chapter", "", ", ".join(p.stem for p in orphans)))
    return chs


def collect_defs(txt):
    """Top-level definitions a chapter makes (\\newcommand, \\tikzset, \\definecolor ...) that its
    figures need when compiled standalone."""
    out = []
    for m in re.finditer(r"\\(newcommand|renewcommand|providecommand|tikzset|pgfplotsset|definecolor|colorlet|"
                         r"usetikzlibrary|newcolumntype|DeclareMathOperator|newenvironment)\b", txt):
        # skip definitions that live inside a tikzpicture or a \stepanim body (they are local there)
        before = txt[:m.start()]
        if before.count("\\begin{tikzpicture}") > before.count("\\end{tikzpicture}"):
            continue
        if re.search(r"\\(stepanim|storyboard)\*?\s*\{", before[-4000:]):
            # cheap check: inside the last stepanim body?
            k = before.rfind("\\stepanim")
            k2 = before.rfind("\\storyboard")
            k = max(k, k2)
            if k >= 0:
                try:
                    j = k + (len("\\stepanim") if before.startswith("\\stepanim", k) else len("\\storyboard"))
                    if txt[j] == "*":
                        j += 1
                    for _ in range(5):
                        _, j = read_arg(txt, j)
                    if j > m.start():
                        continue
                except Unsupported:
                    pass
        j = m.end()
        try:
            if m.group(1) in ("newcommand", "renewcommand", "providecommand"):
                k = skip_ws(txt, j)
                if txt[k] == "{":
                    _, j = read_group(txt, k)
                else:
                    j = CMD_RE.match(txt, k).end()
                _, j = read_opt(txt, j)
                _, j = read_opt(txt, j)
                _, j = read_arg(txt, j)
            elif m.group(1) == "newenvironment":
                # \newenvironment{name}[n][default]{begin}{end}; guarded, since several chapters may define it
                env, j = read_arg(txt, j)
                _, j = read_opt(txt, j)
                _, j = read_opt(txt, j)
                for _ in range(2):
                    _, j = read_arg(txt, j)
                out.append("\\ifcsundef{%s}{%s}{}" % (env.strip(), txt[m.start():j]))
                continue
            elif m.group(1) in ("definecolor",):
                _, j = read_opt(txt, j)
                for _ in range(3):
                    _, j = read_arg(txt, j)
            elif m.group(1) in ("colorlet", "newcolumntype", "DeclareMathOperator"):
                _, j = read_opt(txt, j)
                for _ in range(2):
                    _, j = read_arg(txt, j)
            else:
                _, j = read_arg(txt, j)
        except (Unsupported, IndexError):
            continue
        out.append(txt[m.start():j])
    return out


def dedupe_defs(defs):
    """Identical definitions collected from several chapters, once each (first occurrence kept)."""
    seen, out = set(), []
    for d in defs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def split_sections(txt):
    """[(kind, heading-title, label, start, end)] for \\section / \\section* in a chapter body."""
    res = []
    for m in re.finditer(r"\\section(\*?)\s*(\[[^\]]*\])?\s*\{", txt):
        try:
            title, j = read_group(txt, m.end() - 1)
        except Unsupported:
            continue
        k = skip_ws(txt, j)
        lab = None
        if txt.startswith("\\label{", k):
            lab, j2 = read_group(txt, k + 6)
            lab = lab.strip()
            j = j2
        res.append({"start": m.start(), "body": j, "title": title, "label": lab})
    for a, b in zip(res, res[1:] + [None]):
        a["end"] = b["start"] if b else len(txt)
    return res


def chapter_title(txt):
    m = re.search(r"\\chapter\*?\s*(\[[^\]]*\])?\s*\{", txt)
    if not m:
        return None, 0
    t, j = read_group(txt, m.end() - 1)
    k = skip_ws(txt, j)
    if txt.startswith("\\label{", k):
        _, j = read_group(txt, k + 6)
    return t, j


def pyq_segments(txt):
    """For each \\label{q:<qid>}: (qid, start, end, question-env-src) of the solved question's block."""
    segs = []
    stops = [m.start() for m in re.finditer(r"\\begin\{question\}|\\needspace|\\section|\\subsection|\\chapter",
                                            txt)]
    for m in re.finditer(r"\\label\{q:([^}]*)\}", txt):
        qid = m.group(1).strip()
        qb = txt.rfind("\\begin{question}", 0, m.start())
        if qb < 0:
            continue
        try:
            a, b = find_end(txt, "question", qb + len("\\begin{question}"))
        except Unsupported:
            continue
        # the label sits inside the question box or right after it
        if not (m.start() < b or txt[b:m.start()].strip() == ""):
            continue
        nd = txt.rfind("\\needspace", 0, qb)
        start = nd if nd >= 0 and txt[nd:qb].count("\n") <= 2 and "\\begin" not in txt[nd + 10:qb] else qb
        after = max(b, m.end())
        end = next((x for x in stops if x > after), len(txt))
        segs.append({"qid": qid, "start": start, "qstart": qb, "qend": b, "end": end, "label_at": (m.start(), m.end())})
    return segs


# ============================================================================ html shell
def load_asset(name):
    return (WEBSRC / name).read_text(encoding="utf-8")


def shell(site, page, body, crumbs=None):
    base = site.args.base_url.rstrip("/") + "/" if site.args.base_url else ""
    title = page.title
    desc = page.desc or f"{site.subject} {site.scope}: notes, solved past papers and self-tests."
    canon = f'<link rel="canonical" href="{esc(base + page.url)}">\n' if base else ""
    og_img = (base + "og.png") if base else "og.png"
    ogurl = f'<meta property="og:url" content="{esc(base + page.url)}">\n' if base else ""
    katex = ""
    if page.has_math:
        katex = (f'<link rel="stylesheet" href="{CDN}/katex.min.css" crossorigin="anonymous" referrerpolicy="no-referrer">\n'
                 f'<script defer src="{CDN}/katex.min.js" crossorigin="anonymous" referrerpolicy="no-referrer"></script>\n')
    cr = ""
    if crumbs:
        cr = '<nav class="crumbs" aria-label="Breadcrumb">' + " › ".join(
            f'<a href="{u}">{esc(t)}</a>' if u else esc(t) for t, u in crumbs) + "</nav>"
    home = f"{site.S} {site.scope}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(shorten(desc, 158))}">
<meta name="color-scheme" content="light dark">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(shorten(desc, 200))}">
<meta property="og:image" content="{esc(og_img)}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:site_name" content="{esc(SITE_TAG)}">
{ogurl}<meta name="twitter:card" content="summary_large_image">
{canon}<link rel="stylesheet" href="assets/site.css">
{katex}<script defer src="assets/site.js"></script>
{page.extra_head}</head>
<body class="k-{page.kind}">
<header class="top"><a class="brand" href="index.html">{esc(home)}</a>
<div class="search"><input type="search" id="q" placeholder="Search {esc(site.S)}: topic, 2024 Q3…" aria-label="Search" autocomplete="off"><ul id="qres" hidden></ul></div>
</header>
<main id="main">
{cr}
{body}
</main>
<footer class="foot"><p><b>Unofficial</b> student study guide for {esc(site.subject)} {esc(site.code)} ({esc(site.scope)}). Not issued by or affiliated with KIIT; check everything against your instructor's notes. Past-paper questions are reproduced verbatim from the papers.</p>
<p><a href="index.html">All topics</a> · <a href="drill.html">Q1 drill</a> · <a href="flashcards.html">Flashcards</a></p></footer>
</body>
</html>
"""


def write_page(site, page, crumbs=None):
    body = site.resolve_refs(page.body, page)
    body = finalize_imgs(site, body)
    if 'class="m"' in body or 'class="md"' in body:
        page.has_math = True
    h = shell(site, page, body, crumbs)
    (site.out / page.url).write_text(h, encoding="utf-8")
    return h


def finalize_imgs(site, body):
    """Give every rendered SVG its intrinsic size (no layout shift); replace failed renders by a note."""
    def rep(m):
        tag, h = m.group(0), m.group(1)
        if h in site.render_failed:
            return '<span class="missing">This figure could not be converted for the web; see the PDF guide.</span>'
        if h in site.svg_size:
            w, ht = site.svg_size[h]
            return tag.replace(f'data-job="{h}"', f'width="{round(w * 4 / 3)}" height="{round(ht * 4 / 3)}"')
        return tag.replace(f' data-job="{h}"', "")
    return re.sub(r'<img [^>]*data-job="([0-9a-f]+)"[^>]*>', rep, body)


# ============================================================================ building pages
def build(site):
    chs = chapter_sources(site)
    site.solve_ids = {m.group(1).strip() for _s, t in chs for m in re.finditer(r"\\begin\{solvedidea\}\s*\{([^}]*)\}", t)}
    site.preamble_defs = []
    for _stem, txt in chs:
        site.preamble_defs += collect_defs(txt)
    site.preamble_defs = dedupe_defs(site.preamble_defs)
    S, sc = site.S, site.scope
    unit_by_stem = {u.get("chapter"): u for u in site.units if u.get("chapter")}
    index_extra = []          # (kind, title, url)
    topic_order = []
    papers_pages = []

    # pass A: create Page objects (so links can resolve in any order)
    plan = []
    for stem, txt in chs:
        ctitle, cbody_start = chapter_title(txt)
        ctitle = ctitle or stem
        secs = split_sections(txt)
        tsecs = [x for x in secs if x["label"] and x["label"].startswith("sec:")]
        segs = pyq_segments(txt)
        if tsecs:
            plan.append(("unit", stem, txt, ctitle, cbody_start, secs, tsecs))
        elif segs:
            plan.append(("paper", stem, txt, ctitle, cbody_start, secs, segs))
        else:
            plan.append(("chapter", stem, txt, ctitle, cbody_start, secs, None))

    conv_tmp = None
    for kind, stem, txt, ctitle, cstart, secs, items in plan:
        if kind == "unit":
            for x in items:
                tid = x["label"][4:]
                tinfo = site.topics.get(tid, {})
                plain = strip_tags(Conv(site, Page("", "x", "")).inline(x["title"])) if True else ""
                url = f"t-{tid}-{slugify(tinfo.get('title') or plain, 50)}.html"
                pg = Page(url, "topic", f"{plain} — {S} {sc} notes | {SITE_TAG}")
                pg.tid, pg.plain, pg.sec = tid, plain, x
                site.topic_pages[tid] = pg
                topic_order.append(pg)
                site.register_label(x["label"], pg, "", title=plain)
        elif kind == "paper":
            for sg in items:
                qid = sg["qid"]
                q = site.questions.get(qid, {})
                if not q:
                    site.issues.append(("pyq not in bank", stem, qid))
                pp = site.papers.get(q.get("paper"), {})
                cl = site.clusters.get(q.get("cluster"), {})
                what = cl.get("label") or site.topics.get(q.get("topic"), {}).get("title") or ""
                what = shorten(re.sub(r"\s*\(.*?\)", "", what), 64)
                qno = q.get("qno", qid)
                archive = site.ch_kind.get(stem) == "pyq_older"
                url = f"q-{qid.lower()}-{slugify(what or 'solution', 50)}.html"
                pg = Page(url, "pyq", f"{S} {site.paper_label(q.get('paper'))} Q{qno} — {what} "
                                      f"({'answer' if archive else 'solved'}) | {SITE_TAG}")
                pg.qid, pg.seg, pg.archive = qid, sg, archive
                site.pyq_pages[qid] = pg
                site.register_label(f"q:{qid}", pg, "", title=site.qlabel(qid))

    # pass B: convert
    for kind, stem, txt, ctitle, cstart, secs, items in plan:
        ct_plain = strip_tags(Conv(site, Page("", "x", "")).inline(ctitle))
        if kind == "unit":
            u = unit_by_stem.get(stem) or {"id": stem, "title": ct_plain}
            uurl = f"u-{slugify(u['id'], 10)}-{slugify(ct_plain, 40)}.html"
            upage = Page(uurl, "unit", f"{ct_plain} — {S} {sc} notes | {SITE_TAG}")
            upage.unit = u
            site.register_label_chapter = None
            m = re.search(r"\\label\{(ch:[^}]*)\}", txt[:cstart + 5])
            if m:
                site.register_label(m.group(1), upage, "", title=ct_plain)
            # unit page = chapter text outside the topic sections
            parts, last = [], cstart
            for x in items:
                parts.append(txt[last:x["start"]])
                last = x["end"]
            parts.append(txt[last:])
            cv = Conv(site, upage)
            ubody = cv.blocks("".join(parts))
            links = "".join(f'<li><a href="{tp.url}">{esc(tp.plain)}</a> {site.topic_badge(tp.tid)}</li>'
                            for tp in topic_order if getattr(tp, "sec", None) in items)
            upage.body = (f'<h1>{esc(ct_plain)}</h1><h2>Topics</h2><ul class="tlist">{links}</ul>{ubody}')
            upage.desc = f"{S} {sc}: {ct_plain}. Topic notes, diagrams, animations and solved past questions."
            upage.search_text = strip_tags(ubody)
            site.pages.append((upage, [("Home", "index.html"), (ct_plain, None)]))
            index_extra.append(("unit", ct_plain, uurl))
            tps = [tp for tp in topic_order if getattr(tp, "sec", None) in items]
            for n_, tp in enumerate(tps):
                build_topic(site, tp, txt, upage, tps[n_ - 1] if n_ else None, tps[n_ + 1] if n_ + 1 < len(tps) else None)
        elif kind == "paper":
            pid = None
            for sg in items:
                q = site.questions.get(sg["qid"], {})
                pid = pid or q.get("paper")
            purl = f"paper-{slugify(pid or stem, 20)}.html"
            what = ("questions with answers and links to the full solutions (archive)"
                    if site.ch_kind.get(stem) == "pyq_older" else "every question solved")
            ppage = Page(purl, "paper", f"{S} {site.paper_label(pid)} paper — {what} | {SITE_TAG}")
            m = re.search(r"\\label\{(ch:[^}]*)\}", txt[:cstart + 5])
            if m:
                site.register_label(m.group(1), ppage, "", title=ct_plain)
            parts, last = [], cstart
            for sg in sorted(items, key=lambda z: z["start"]):
                parts.append(txt[last:sg["start"]])
                parts.append(f"\n\n\\sgwebpyqlink{{{sg['qid']}}}\n\n")
                last = sg["end"]
            parts.append(txt[last:])
            cv = Conv(site, ppage)
            pbody = cv.blocks("".join(parts))
            ppage.body = f"<h1>{esc(ct_plain)}</h1>{pbody}"
            ppage.desc = f"{S} {sc} {site.papers.get(pid, {}).get('year', '')}: all questions of the paper, verbatim, with full solutions."
            ppage.search_text = strip_tags(pbody)
            site.pages.append((ppage, [("Home", "index.html"), (ct_plain, None)]))
            papers_pages.append((ct_plain, purl, pid))
            segs = sorted(items, key=lambda z: z["start"])
            for n_, sg in enumerate(segs):
                prev = site.pyq_pages.get(segs[n_ - 1]["qid"]) if n_ else None
                nxt = site.pyq_pages.get(segs[n_ + 1]["qid"]) if n_ + 1 < len(segs) else None
                build_pyq(site, site.pyq_pages[sg["qid"]], txt, ppage, ct_plain, prev, nxt)
        else:
            curl = f"ch-{slugify(stem, 50)}.html"
            cpage = Page(curl, "chapter", f"{ct_plain} — {S} {sc} | {SITE_TAG}")
            m = re.search(r"\\label\{(ch:[^}]*)\}", txt[:cstart + 5])
            if m:
                site.register_label(m.group(1), cpage, "", title=ct_plain)
            cv = Conv(site, cpage)
            cbody = cv.blocks(txt[cstart:])
            cpage.body = f"<h1>{esc(ct_plain)}</h1>{cbody}"
            cpage.desc = f"{S} {sc}: {ct_plain}."
            cpage.search_text = strip_tags(cbody)
            site.pages.append((cpage, [("Home", "index.html"), (ct_plain, None)]))
            index_extra.append(("chapter", ct_plain, curl))
    site.index_extra, site.papers_pages, site.topic_order = index_extra, papers_pages, topic_order


def build_topic(site, pg, txt, upage, prev, nxt):
    x = pg.sec
    tid = pg.tid
    cv = Conv(site, pg, head_base=1)
    body = cv.blocks(txt[x["body"]:x["end"]])
    t = site.topics.get(tid, {})
    qs = [q for q in site.questions.values() if q.get("topic") == tid and q.get("in_scope", True)]
    qs.sort(key=lambda q: (-(site.papers.get(q.get("paper"), {}).get("year") or 0), q.get("qno", "")))
    pyq = ""
    if qs:
        li = []
        for q in qs:
            qp = site.pyq_pages.get(q["id"])
            head = esc(site.qlabel(q["id"]))
            head = f'<a href="{qp.url}">{head} (solved)</a>' if qp else head
            li.append(f'<li id="pyq-{html_id(q["id"])}"><div class="qcard-h">{head} {pill("mks", str(q.get("marks", "?")) + " M")}</div>'
                      f'<div class="qcard-t">{esc(q.get("text", ""))}</div></li>')
        pyq = f'<h2 id="past-questions">Past questions on this topic</h2><ul class="qlist">{"".join(li)}</ul>'
    cls = [c for c in site.clusters.values() if c.get("topic") == tid]
    forms = ""
    if cls:
        li = []
        for c in cls:
            cid = c.get("id") or c.get("cluster")
            lab = esc(c.get("label", cid))
            info = site.labels.get(f"iq:{cid}")
            if info:
                lab = site.ref_link(f"iq:{cid}", pg, text=lab)
            li.append(f"<li>{lab} {site.cluster_badge(cid)}</li>")
        forms = f'<h2>Question forms to practise</h2><ul class="forms">{"".join(li)}</ul>'
    cards = ""
    if pg.flashcards:
        cv2 = Conv(site, pg, allow_fallback=False)
        items = []
        for f, b in pg.flashcards:
            try:
                items.append(f'<details class="card ans"><summary>{cv2.inline(f)}</summary><div>{cv2.inline(b)}</div></details>')
            except Unsupported:
                items.append(f'<details class="card ans"><summary>{esc(latex_to_text(f))}</summary><div>{esc(latex_to_text(b))}</div></details>')
        cards = f'<h2 id="self-test">Self-test (tap to reveal)</h2><div class="cards">{"".join(items)}</div>'
    nav = '<nav class="pn">' + (f'<a rel="prev" href="{prev.url}">← {esc(prev.plain)}</a>' if prev else "<span></span>") + \
        (f'<a rel="next" href="{nxt.url}">{esc(nxt.plain)} →</a>' if nxt else "<span></span>") + "</nav>"
    tools = '<div class="tools"><button class="toggle-ans" type="button">Show all answers</button></div>'
    pg.body = (f'<h1 id="{html_id(x["label"])}">{esc(pg.plain)}</h1><p class="meta">{site.topic_badge(tid)} '
               f'<span class="unit">{esc(upage.unit.get("title", ""))}</span></p>{tools}{body}{pyq}{forms}{cards}{nav}')
    first = re.search(r"<p>(.*?)</p>", body, re.S)
    pg.desc = f"{site.S} {site.scope} notes: {pg.plain}. " + (strip_tags(first.group(1)) if first else "")
    pg.search_text = strip_tags(body + pyq)
    site.pages.append((pg, [("Home", "index.html"), (strip_tags(upage.unit.get("title", "")), upage.url), (pg.plain, None)]))


def build_pyq(site, pg, txt, ppage, ptitle, prev, nxt):
    sg = pg.seg
    qid = pg.qid
    q = site.questions.get(qid, {})
    pp = site.papers.get(q.get("paper"), {})
    cv = Conv(site, pg, head_base=1, open_solutions=True)
    qsrc = txt[sg["qstart"]:sg["qend"]]
    # the solution = the block after the question box (labels inside it are stripped)
    rest = txt[sg["qend"]:sg["end"]]
    rest = rest.replace(f"\\label{{q:{qid}}}", "")
    rest = re.sub(r"\\receipt\s*\{\s*" + re.escape(qid) + r"\s*\}", "", rest)   # shown once, above the solution
    qtext = q.get("text")
    if qtext:
        qhtml = f'<blockquote class="qtext">{esc(qtext)}</blockquote>'
    else:
        qhtml = cv.blocks(qsrc)
        site.issues.append(("pyq text from chapter (not in bank)", pg.url, qid))
    receipt = site.receipt_html(qid) if (site.scoped / "receipts" / f"{qid}.png").exists() else ""
    sol = cv.blocks(rest)
    if 'class="box box-sol' not in sol:
        sol = (f'<details class="box box-sol ans" open><summary>{"Answer" if getattr(pg, "archive", False) else "Solution"}'
               f'</summary><div class="box-b">{sol}</div></details>')
    tp = site.topic_pages.get(q.get("topic"))
    links = []
    if tp:
        links.append(f'<a href="{tp.url}">Notes: {esc(tp.plain)}</a>')
    cid = q.get("cluster")
    if cid and cid in site.solve_ids and not re.search(r"\\begin\{solvedidea\}\s*\{\s*" + re.escape(cid) + r"\s*\}", rest):
        links.append("Full model solution of this idea: " + site.ref_link(f"solve:{cid}", pg))
    same = [x for x in (site.clusters.get(cid, {}).get("question_ids") or
                        [k for k, v in site.questions.items() if v.get("cluster") == cid]) if x != qid]
    sm = []
    for x in same:
        xp = site.pyq_pages.get(x)
        lab = esc(site.qlabel(x))
        if xp:
            sm.append(f'<a href="{xp.url}">{lab}</a>')
        elif x in site.questions and tp:
            sm.append(f'<a href="{tp.url}#pyq-{html_id(x)}">{lab}</a>')
        else:
            sm.append(lab)
    if sm:
        links.append("Same idea asked in: " + ", ".join(sm))
    links.append(f'<a href="{ppage.url}">Whole {esc(site.paper_label(q.get("paper")))} paper</a>')
    nav = '<nav class="pn">' + (f'<a rel="prev" href="{prev.url}">← Q{esc(site.questions.get(prev.qid, {}).get("qno", ""))}</a>' if prev else "<span></span>") + \
        (f'<a rel="next" href="{nxt.url}">Q{esc(site.questions.get(nxt.qid, {}).get("qno", ""))} →</a>' if nxt else "<span></span>") + "</nav>"
    h1 = f"{esc(site.paper_label(q.get('paper')))} Q{esc(q.get('qno', qid))}"
    badge = site.cluster_badge(cid) if cid else ""
    tools = '<div class="tools"><button class="toggle-ans" type="button">Hide answers (self-test)</button></div>'
    pg.body = (f'<h1>{h1} <span class="sub">{esc(site.subject)}</span></h1>'
               f'<p class="meta">{pill("mks", str(q.get("marks", "?")) + " M")} {badge}</p>'
               f'<h2 class="vh">Question (verbatim)</h2>{qhtml}{receipt}{tools}{sol}'
               f'<div class="rel">{"<br>".join(links)}</div>{nav}')
    pg.desc = (f"{'Answer' if getattr(pg, 'archive', False) else 'Solved'}: {site.S} {site.paper_label(q.get('paper'))} "
               f"Q{q.get('qno', '')} ({q.get('marks', '?')} marks). " + (qtext or ""))
    pg.search_text = (qtext or "") + " " + strip_tags(sol)
    site.pages.append((pg, [("Home", "index.html"), (ptitle, ppage.url), (f"Q{q.get('qno', qid)}", None)]))


def build_index(site):
    S, sc = site.S, site.scope
    pg = Page("index.html", "index", f"{site.subject} ({S}) {sc} — notes, solved PYQs, animations | {SITE_TAG}")
    plans = site.iq.get("plans") or {}
    ph = []
    for name, p in plans.items():
        if not isinstance(p, dict):
            continue
        cl = p.get("clusters") or []
        tids = []
        for cid in cl:
            t = site.clusters.get(cid, {}).get("topic")
            if t and t not in tids:
                tids.append(t)
        extra = []
        if p.get("expected_marks") is not None:
            extra.append(f"expected {p['expected_marks']} marks")
        if p.get("p_safe") is not None:
            extra.append(f"p_safe {round(p['p_safe'] * 100)}%")
        if p.get("minutes"):
            extra.append(f"{p['minutes']} min")
        lis = []
        for cid in cl:
            c = site.clusters.get(cid, {})
            tp = site.topic_pages.get(c.get("topic"))
            lab = esc(c.get("label", cid))
            info = site.labels.get(f"iq:{cid}")
            if info:
                lab = site.ref_link(f"iq:{cid}", pg, text=lab)
            elif tp:
                lab = f'<a href="{tp.url}">{lab}</a>'
            lis.append(f"<li>{lab}</li>")
        ph.append(f'<details class="plan"><summary><b>{esc(name)} plan</b> <span class="meta">{esc(", ".join(extra))}'
                  f' · {len(cl)} ideas, {len(tids)} topics</span></summary><ol>{"".join(lis)}</ol></details>')
    plans_html = f'<h2>Study plans</h2>{"".join(ph)}' if ph else ""
    if ph and site.n_relevant < 4:
        plans_html += f'<p class="note">Built from {site.n_relevant} past papers: P is shown as a band (low / med / high), not a percentage.</p>'
    th = []
    for u in site.units:
        if not u.get("in_scope", True):
            continue
        li = []
        for t in u.get("topics", []):
            tp = site.topic_pages.get(t["id"])
            name = esc(t.get("title", t["id"]))
            name = f'<a href="{tp.url}">{name}</a>' if tp else f'<span class="dim">{name}</span>'
            li.append(f"<li>{name} {site.topic_badge(t['id'])}</li>")
        uu = next((x for k, ttl, x in site.index_extra if k == "unit" and ttl.lower().startswith(u.get("title", "").lower()[:12])), None)
        ut = esc(u.get("title", u["id"]))
        if uu:
            ut = f'<a href="{uu}">{ut}</a>'
        th.append(f'<h3>{ut}</h3><ul class="tlist">{"".join(li)}</ul>')
    pp = "".join(f'<li><a href="{u}">{esc(t)}</a></li>' for t, u, _ in site.papers_pages)
    other = "".join(f'<li><a href="{u}">{esc(t)}</a></li>' for k, t, u in site.index_extra if k == "chapter")
    subj_file = re.sub(r"[^A-Za-z0-9]+", "_", site.subject).strip("_")
    pdfb = site.args.pdf_base.rstrip("/") + "/" if site.args.pdf_base else "pdf/"
    dls = []
    for label, suf in (("Print guide (PDF)", "Guide"), ("Phone edition (PDF)", "Guide_Phone"),
                       ("Interactive guide (PDF, Acrobat)", "Guide_Interactive"), ("Cheatsheet (PDF)", "Cheatsheet")):
        fn = f"{subj_file}_{sc}_{suf}.pdf"
        if (site.subj / fn).exists() or suf in ("Guide", "Cheatsheet"):
            dls.append(f'<li><a class="dl" data-file="{fn}" href="{esc(pdfb + fn)}">{label}</a></li>')
    site.downloads = [re.search(r'data-file="([^"]+)"', d).group(1) for d in dls]
    body = (f'<h1>{esc(site.subject)} <span class="sub">{esc(site.code)} · {esc(sc)}</span></h1>'
            f'<p class="lede">Unofficial exam notes, every solved past-paper question, step-by-step animations '
            f'and self-tests for {esc(site.subject)} ({esc(S)}) {esc(sc.lower())}, built from the instructor\'s notes and the real papers.</p>'
            f'<div class="quick"><a class="btn" href="drill.html">Q1 rapid-fire</a> <a class="btn" href="flashcards.html">Flashcards</a></div>'
            f'{plans_html}<h2>Topics</h2>{"".join(th)}'
            + (f'<h2>Past papers, solved</h2><ul>{pp}</ul>' if pp else "")
            + (f'<h2>More</h2><ul>{other}</ul>' if other else "")
            + f'<h2>Downloads</h2><ul class="dls">{"".join(dls)}</ul>')
    pg.body = body
    pg.desc = (f"Unofficial {site.subject} {site.code} {sc} notes for KIIT students: topic notes with animations, "
               f"verbatim past-paper questions with full solutions, Q1 drill and flashcards.")
    pg.search_text = ""
    site.pages.insert(0, (pg, None))


def build_drill(site):
    pg = Page("drill.html", "drill", f"{site.S} {site.scope} Q1 rapid-fire drill (one-mark questions) | {SITE_TAG}")
    d = site.iq.get("q1_drill")
    qids, cids, src = [], [], "important_questions.json q1_drill"
    if isinstance(d, dict):
        for k, v in d.items():
            for x in (v if isinstance(v, list) else [v]):
                xid = x.get("id") if isinstance(x, dict) else x
                if xid in site.questions:
                    qids.append(xid)
                elif xid in site.clusters:
                    cids.append(xid)
    elif isinstance(d, list):
        for x in d:
            xid = x.get("id") if isinstance(x, dict) else x
            (qids if xid in site.questions else cids if xid in site.clusters else []).append(xid)
    if not d:
        src = "the bank's one-mark questions (q1_drill not in important_questions.json yet)"
        qids = [q["id"] for q in site.questions.values() if (q.get("marks") or 0) <= 1 and q.get("in_scope", True)]
        qids.sort(key=lambda x: (-(site.papers.get(site.questions[x].get("paper"), {}).get("year") or 0), x))
    items = []
    for n, qid in enumerate(qids, 1):
        q = site.questions[qid]
        qp = site.pyq_pages.get(qid)
        tp = site.topic_pages.get(q.get("topic"))
        if qp:
            ans = f'<a href="{qp.url}">Full solution →</a>'
            sol = extract_answer(qp)
            if sol:
                ans = sol + "<p>" + ans + "</p>"
        elif tp:
            ans = f'<a href="{tp.url}">Revise: {esc(tp.plain)} →</a>'
        else:
            ans = "Not solved in this guide yet."
        items.append(f'<li><div class="qcard-h">{esc(site.qlabel(qid))} {pill("mks", str(q.get("marks", 1)) + " M")}</div>'
                     f'<div class="qcard-t">{esc(q.get("text", ""))}</div><details class="ans"><summary>Answer</summary>'
                     f'<div>{ans}</div></details></li>')
    for cid in cids:
        c = site.clusters.get(cid, {})
        tp = site.topic_pages.get(c.get("topic"))
        link = f'<a href="{tp.url}">Revise: {esc(tp.plain)} →</a>' if tp else ""
        items.append(f'<li><div class="qcard-h">Expected (not a past question) {site.cluster_badge(cid)}</div>'
                     f'<div class="qcard-t">{esc(c.get("label", cid))}</div><details class="ans"><summary>Where to revise</summary><div>{link}</div></details></li>')
    pg.has_math = any(getattr(site.pyq_pages.get(q), "has_math", False) for q in qids)
    pg.body = (f'<h1>Q1 rapid-fire</h1><p class="meta">One-mark questions; answer in your head, then tap. Source: {esc(src)}.</p>'
               f'<div class="tools"><button class="toggle-ans" type="button">Show all answers</button></div>'
               f'<ol class="drill">{"".join(items)}</ol>')
    pg.desc = f"{site.S} {site.scope}: one-mark (Q1) questions from past papers with hidden answers for self-testing."
    site.pages.append((pg, [("Home", "index.html"), ("Q1 drill", None)]))


def extract_answer(qp):
    m = re.search(r'<details class="box box-sol ans" open><summary>.*?</summary><div class="box-b">(.*)</div></details>', qp.body, re.S)
    return m.group(1) if m and len(m.group(1)) < 6000 else ""


def latex_to_text(s):
    """Plain-text rendering of a LaTeX snippet (used when HTML conversion is impossible)."""
    s = re.sub(r"\\(textbf|emph|textit|texttt|keyword|answer|text|mbox|textsf|underline)\{", "{", s)
    s = re.sub(r"\\[A-Za-z]+\*?(\[[^\]]*\])?", "", s)
    s = s.replace("{", "").replace("}", "").replace("$", "").replace("~", " ")
    return re.sub(r"\s+", " ", s).strip()


def write_flashcards_page(site, cards):
    """cards: list of dicts with front_html, back_html, topic."""
    pg = Page("flashcards.html", "flash", f"{site.S} {site.scope} flashcards (self-test) | {SITE_TAG}")
    pg.has_math = any('class="m' in c["front_html"] + c["back_html"] for c in cards)
    data = json.dumps([{"f": c["front_html"], "b": c["back_html"], "t": c.get("topic", "")} for c in cards],
                      ensure_ascii=False).replace("</", "<\\/")
    lst = "".join(f'<details class="card ans"><summary>{c["front_html"]}</summary><div>{c["back_html"]}</div></details>'
                  for c in cards)
    if cards:
        pg.body = (f'<h1>Flashcards</h1><p class="meta">{len(cards)} cards. Study mode shows one card at a time; '
                   f'"Again" puts it back in the pile. The same deck is in <code>flashcards.csv</code> for Anki.</p>'
                   f'<div id="fc" class="fc" hidden><div class="fc-card" tabindex="0"><div class="fc-f"></div><div class="fc-b" hidden></div></div>'
                   f'<div class="fc-ctl"><button class="fc-show">Show answer</button><button class="fc-again" hidden>Again</button>'
                   f'<button class="fc-good" hidden>Got it</button></div><p class="fc-n"></p></div>'
                   f'<script type="application/json" id="cards">{data}</script>'
                   f'<h2>All cards</h2><div class="cards">{lst}</div>')
    else:
        pg.body = '<h1>Flashcards</h1><p>No flashcards in this guide yet.</p>'
    pg.desc = f"{site.S} {site.scope}: flashcards for definitions, formulas and key facts."
    return pg


def collect_cards_html(site):
    try:
        import flashcards
    except ImportError:
        return []
    cards = flashcards.collect(site.scoped)
    out = []
    pg = Page("flashcards.html", "flash", "")
    for c in cards:
        cv = Conv(site, pg, allow_fallback=False)
        try:
            f, b = cv.inline(c["front"]), cv.inline(c["back"])
        except Unsupported:
            f, b = esc(latex_to_text(c["front"])), esc(latex_to_text(c["back"]))
        tp = site.topic_pages.get(c.get("topic"))
        if tp:
            b += f' <a class="xref" href="{tp.url}">→ {esc(tp.plain)}</a>'
        out.append({"front_html": f, "back_html": b, "topic": c.get("topic", "")})
    return out


def make_og(site):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), (27, 54, 93))
    d = ImageDraw.Draw(im)

    def font(sz, bold=False):
        for f in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"):
            try:
                return ImageFont.truetype(f, sz)
            except OSError:
                continue
        return ImageFont.load_default()
    d.rectangle([0, H - 18, W, H], fill=(217, 119, 6))
    d.text((70, 70), "UNOFFICIAL STUDY GUIDE", font=font(34, True), fill=(255, 200, 120))
    title = site.subject
    size = 92 if len(title) < 20 else 70
    d.text((70, 150), title, font=font(size, True), fill=(255, 255, 255))
    d.text((70, 150 + size + 30), f"{site.code}  ·  {site.scope}", font=font(48), fill=(200, 220, 240))
    d.text((70, 430), "Notes · solved past papers · animations · self-tests", font=font(38), fill=(230, 236, 244))
    d.text((70, 500), "Not issued by KIIT. Check against your instructor's notes.", font=font(28), fill=(170, 190, 210))
    im = im.quantize(colors=32)
    im.save(site.out / "og.png", optimize=True)


def write_report(site):
    lines = [f"# Web conversion report: {site.S} {site.scope.lower()}", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')} by tools/web.py.", "",
             f"- pages: {len(site.pages)}", f"- rendered SVG jobs: {len(site.jobs)} "
             f"(tikz {sum(1 for j in site.jobs.values() if j['kind'] == 'tikz')}, "
             f"animation frames {sum(1 for j in site.jobs.values() if j['kind'] == 'frame')}, "
             f"fallback blocks {sum(1 for j in site.jobs.values() if j['kind'] == 'fallback')})",
             f"- **fallbacks (blocks rendered as images): {len(site.fallbacks)}**",
             f"- render failures: {len(site.render_failed)}",
             f"- other issues: {len(site.issues) - len(site.render_failed)}", ""]
    lines += ["## Fallbacks", ""]
    if not site.fallbacks:
        lines.append("None.")
    else:
        lines += ["| page | reason | source (start) |", "|---|---|---|"]
        for f in site.fallbacks:
            src = re.sub(r"\s+", " ", f["src"])[:110].replace("|", "\\|")
            lines.append(f"| {f['page']} | {f['reason'].replace('|', '/')} | `{src}` |")
    lines += ["", "## Issues", ""]
    if not site.issues:
        lines.append("None.")
    else:
        lines += ["| kind | page | detail |", "|---|---|---|"]
        seen = set()
        for k, p, d in site.issues:
            if (k, p, d) in seen:
                continue
            seen.add((k, p, d))
            lines.append(f"| {k} | {p} | {str(d).replace('|', '/')[:160]} |")
    (site.out / "CONVERSION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_meta(site):
    base = site.args.base_url.rstrip("/") + "/" if site.args.base_url else "__BASE_URL__/"
    today = time.strftime("%Y-%m-%d")
    urls = "".join(f"<url><loc>{esc(base + p.url)}</loc><lastmod>{today}</lastmod></url>\n" for p, _ in site.pages)
    (site.out / "sitemap-fragment.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- fragment: the publish step merges these url entries '
        'into the site sitemap and replaces __BASE_URL__ (or reruns web.py with the base-url option) -->\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n', encoding="utf-8")
    idx = []
    for p, _ in site.pages:
        if p.kind == "index":
            continue
        t = re.sub(r"\s*\|\s*" + re.escape(SITE_TAG) + "$", "", p.title)
        idx.append({"t": t, "u": p.url, "k": p.kind, "x": shorten(p.search_text or p.desc, 700)})
    (site.out / "search.json").write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (site.out / "site.json").write_text(json.dumps({
        "subject": site.subject, "code": site.code, "short": site.S, "scope": site.scope,
        "katex": KATEX_VER, "generated": today,
        "pages": [{"url": p.url, "kind": p.kind, "title": p.title} for p, _ in site.pages],
        "downloads": getattr(site, "downloads", []),
        "pdf_href_prefix": site.args.pdf_base or "pdf/",
        "fallbacks": len(site.fallbacks), "render_failures": len(site.render_failed)}, indent=1), encoding="utf-8")


def copy_assets(out):
    a = out / "assets"
    a.mkdir(parents=True, exist_ok=True)
    for f in ("site.css", "site.js"):
        shutil.copyfile(WEBSRC / f, a / f)


def prepare_out(out):
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).exists():
            print(f"refusing to wipe {out}: it is not a web.py output folder (no {MARKER})", file=sys.stderr)
            raise SystemExit(2)
        for p in out.iterdir():        # empty it (the folder itself may be a server's cwd)
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("written by _pipeline/tools/web.py; the folder is wiped on every run\n", encoding="utf-8")


def main(argv=None):
    workdir.setup_stdout()
    ap = argparse.ArgumentParser(description="static web export of one subject and scope")
    ap.add_argument("subject")
    ap.add_argument("--scope")
    ap.add_argument("--out")
    ap.add_argument("--base-url", default="", help="absolute site URL of this folder (canonical, og:url, sitemap)")
    ap.add_argument("--pdf-base", default="", help="href prefix for the PDF downloads (default pdf/)")
    ap.add_argument("--no-render", action="store_true", help="skip pdflatex (figures stay unrendered; for quick checks)")
    ap.add_argument("--jobs", type=int, default=3, help="parallel pdflatex runs")
    args = ap.parse_args(argv)
    subj, shared, scoped = workdir.resolve(args.subject, args.scope)
    if not (scoped / "chapters").is_dir():
        print(f"no chapters in {scoped}", file=sys.stderr)
        print("RESULT BLOCKED: no chapters")
        return 1
    out = Path(args.out).resolve() if args.out else scoped / "web"
    prepare_out(out)
    site = Site(args.subject, subj, shared, scoped, out, args)
    if not site.bp:
        print("RESULT BLOCKED: blueprint.json missing")
        return 1
    t0 = time.time()
    build(site)
    build_index(site)
    build_drill(site)
    cards = collect_cards_html(site)
    fpage = write_flashcards_page(site, cards)
    site.pages.append((fpage, [("Home", "index.html"), ("Flashcards", None)]))
    if not args.no_render:
        render_jobs(site, args.jobs)
    else:
        site.render_failed = set()
    copy_assets(out)
    for p, crumbs in site.pages:
        write_page(site, p, crumbs)
    make_og(site)
    write_meta(site)
    write_report(site)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"web: {len(site.pages)} pages ({len(site.topic_pages)} topics, {len(site.pyq_pages)} PYQs), "
          f"{len(site.jobs)} SVG jobs, {len(site.fallbacks)} fallbacks, {len(site.render_failed)} render failures, "
          f"{size / 1024:.0f} KiB, {time.time() - t0:.0f}s -> {out}")
    print(f"report: {out / 'CONVERSION_REPORT.md'}")
    if site.render_failed and not args.no_render:
        print(f"RESULT BLOCKED: {len(site.render_failed)} figure(s) failed to render (see CONVERSION_REPORT.md)")
        return 1
    print(f"RESULT PASS ({len(site.fallbacks)} fallbacks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
