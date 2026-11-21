/* Showcase interactions. No dependencies, no network calls, no inline styles in markup (CSP: self only). */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var el = function (tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var whenSeen = function (node, fn) {
    if (!("IntersectionObserver" in window) || calm) { fn(); return; }
    var io = new IntersectionObserver(function (es) { if (es.some(function (e) { return e.isIntersecting; })) { io.disconnect(); fn(); } }, { threshold: 0.25 });
    io.observe(node);
  };

  /* theme */
  $("#themeToggle").addEventListener("click", function () {
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
  });

  /* Table 1: numbers count up once, and carry their column label for the narrow layout */
  var heads = $$(".cover th").map(function (th) { return th.textContent; });
  $$(".cover td").forEach(function (td, i) {
    td.setAttribute("data-label", heads[i] || "");
    var target = +td.getAttribute("data-count");
    whenSeen(td, function () {
      if (calm) return;
      var t0 = null, dur = 900;
      var step = function (t) {
        if (t0 === null) t0 = t;
        var k = Math.min(1, (t - t0) / dur), eased = 1 - Math.pow(1 - k, 3);
        td.textContent = Math.round(target * eased).toLocaleString("en-US");
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  });

  /* Figure 1: single prompt vs gated pipeline */
  var RUBRIC = [["Fidelity", 0, 5], ["Correctness", 3, 4], ["Coverage", 1, 5], ["Usefulness", 1, 4], ["Visuals", 3, 4], ["Layout", 4, 4], ["Concision", 4, 4]];
  var rub = $("#rubric");
  RUBRIC.forEach(function (r) {
    var row = el("div", "rub-row"), bars = el("div", "rub-bars"), a = el("span", "rub-old"), b = el("span", "rub-new");
    bars.appendChild(a); bars.appendChild(b);
    row.appendChild(el("span", "", r[0])); row.appendChild(bars); row.appendChild(el("span", "rub-val", r[1] + " → " + r[2]));
    rub.appendChild(row);
    whenSeen(rub, function () { a.style.width = (r[1] / 5 * 100) + "%"; b.style.width = (r[2] / 5 * 100) + "%"; });
  });

  /* Figure 2: pipeline explorer */
  var STAGES = [
    { n: "Ingest", tool: "tools/ingest.py", gate: true,
      what: "Slides, documents and scanned papers become a page-tagged text corpus with OCR, page images and extracted figures.",
      check: "A health gate exits non-zero if any file was dropped or unreadable.",
      proof: "It found that an earlier run had silently lost 8 of one course's 16 slide decks." },
    { n: "Transcribe the papers", tool: "agent: pyq-transcriber", gate: false,
      what: "One agent per course reads the page images of each past paper and transcribes every question word for word, with marks and sub-parts.",
      check: "Its output is not trusted. It only counts once the next stage passes.",
      proof: "132 papers and 2,310 question blocks across 11 courses." },
    { n: "Receipts and the verbatim gate", tool: "tools/receipts.py · tools/verify_pyqs.py", gate: true,
      what: "Each banked question is aligned against its own paper and cropped from the page as a receipt, which is printed under it in the guide.",
      check: "Numbers and acronyms must match exactly, marks must add up, and the run stops unless it prints RESULT PASS.",
      proof: "The attack suite blocks 77 of 77 tampered banks." },
    { n: "Plan by expected marks", tool: "tools/score.py · tools/backtest.py", gate: false,
      what: "A marks model per topic feeds a Monte-Carlo coverage planner that respects the exam's choice rules and produces nested 3, 6 and 12-hour plans.",
      check: "Leave-one-year-out backtest on held-out papers. Likelihood is printed as a band when evidence is thin.",
      proof: "It never lost to a lecture-time baseline on any fold, though the margin is not yet conclusive." },
    { n: "Write, in parallel", tool: "prompts/02–04 · tools/pack.py", gate: false,
      what: "Writer agents produce small LaTeX pieces against one shared style. Each question idea is solved once and cross-linked everywhere else.",
      check: "Every writer owns named files, compiles only its own pieces, and writes a Python check for each numerical answer.",
      proof: "About 2,000 executable answer checks across the 12 guides." },
    { n: "Recall material", tool: "prompts/05 · prompts/07", gate: false,
      what: "A short-answer drill, flashcards, a cheatsheet and a night-before sheet are derived from the same plan.",
      check: "Sizes come from per-course targets, not from the writer's judgment.",
      proof: "About 2,300 Anki-importable flashcards." },
    { n: "Build", tool: "tools/build.py · lint_tex.py · layout_check.py", gate: true,
      what: "A one-second lint, then LaTeX. Each step-by-step figure is one TikZ source: a storyboard in print, an animation on screen.",
      check: "Overfull boxes are errors. A layout checker flags text outside the page, overlaps and tiny type, page by page.",
      proof: "Agents now look at about 9% of pages instead of reading every page image." },
    { n: "Metrics", tool: "tools/metrics.py", gate: true,
      what: "Objective counts for the finished guide: references, floats, chapters, receipts, check results, PDF freshness and leaked internal ids.",
      check: "Ten hard gates must all be zero, and the past-paper gate must have passed, before a PDF is copied out.",
      proof: "All 12 released guides: zero on every hard gate." },
    { n: "Independent review", tool: "prompts/06 · tools/plant_defects.py", gate: true,
      what: "Two fresh reviewer agents re-solve the numericals and grade correctness and teaching quality. A third answers a held-out paper from the guide alone.",
      check: "Each reviewer gets a copy with five planted defects, so recall is measured. At most two fix rounds.",
      proof: "Reviewers caught 3 to 5 of 5 planted defects; 94.5% answerability on a held-out paper." }
  ];
  var steps = $("#flowSteps"), panel = $("#flowPanel");
  var show = function (i, focus) {
    var s = STAGES[i];
    $$("button", steps).forEach(function (b, k) { b.setAttribute("aria-selected", k === i ? "true" : "false"); b.tabIndex = k === i ? 0 : -1; if (k === i && focus) b.focus(); });
    panel.textContent = "";
    var box = el("div", "swap"), where = el("p", "where", "Stage " + (i + 1) + " of " + STAGES.length);
    if (s.gate) { where.appendChild(document.createTextNode(" · ")); where.appendChild(el("em", "", "hard gate")); }
    box.appendChild(where);
    box.appendChild(el("h3", "", s.n));
    box.appendChild(el("code", "tool", s.tool));
    box.appendChild(el("p", "", s.what));
    var dl = el("dl");
    dl.appendChild(el("dt", s.gate ? "is-gate" : "", s.gate ? "Gate" : "Control")); dl.appendChild(el("dd", "", s.check));
    dl.appendChild(el("dt", "", "Evidence")); dl.appendChild(el("dd", "", s.proof));
    box.appendChild(dl);
    panel.appendChild(box);
  };
  STAGES.forEach(function (s, i) {
    var b = el("button");
    b.type = "button"; b.setAttribute("role", "tab");
    b.appendChild(el("span", "", s.n));
    if (s.gate) b.appendChild(el("span", "g", "gate"));
    b.addEventListener("click", function () { show(i); });
    b.addEventListener("keydown", function (e) {
      var d = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
      if (d) { e.preventDefault(); show((i + d + STAGES.length) % STAGES.length, true); }
    });
    steps.appendChild(b);
  });
  show(2);

  /* Figure 3: verbatim gate (simplified port of tools/verify_pyqs.py; the question is made up) */
  var SOURCE = "Q3 (a) A Go-Back-N sender uses 3-bit sequence numbers and a send window of 7 frames. The RTT is 40 ms. " +
               "Frames 0 to 6 are sent and the ACK for frame 2 is lost. Which frames does the sender retransmit after the timeout, and why? [5 marks]";
  var TAMPER = {
    number: function (t) { return t.replace("window of 7 frames", "window of 8 frames"); },
    paraphrase: function (t) { return t.replace("Which frames does the sender retransmit after the timeout, and why?", "Explain which frames are sent again once the timer expires."); },
    invent: function (t) { return t.replace(/\s*$/, "") + " (b) Compare this with Selective Repeat. [5 marks]"; },
    ocr: function (t) { return t.replace("Frames 0 to 6", "Frarnes 0 to 6").replace("Go-Back-N", "Go‐Back‐N"); },
    reset: function () { return SOURCE; }
  };
  var fold = function (w) { return w.toLowerCase().replace(/[‐-―]/g, "-").replace(/[‘’]/g, "'").replace(/rn/g, "m"); };
  var words = function (t) { return (t.match(/[A-Za-z0-9][A-Za-z0-9.\-‐-―']*[A-Za-z0-9]|[A-Za-z0-9]/g) || []); };
  var bag = function (list) { var m = {}; list.forEach(function (x) { m[x] = (m[x] || 0) + 1; }); return m; };
  var bagDiff = function (a, b) {
    var out = [], A = bag(a), B = bag(b);
    Object.keys(A).forEach(function (k) { if ((B[k] || 0) < A[k]) out.push("missing " + k); });
    Object.keys(B).forEach(function (k) { if ((A[k] || 0) < B[k]) out.push("extra " + k); });
    return out;
  };
  var diff = function (a, b) {                       // token LCS on folded words -> [op, word] with op in " ", "-", "+"
    var fa = a.map(fold), fb = b.map(fold), n = a.length, m = b.length, L = [], i, j;
    for (i = 0; i <= n; i++) { L.push(new Array(m + 1).fill(0)); }
    for (i = n - 1; i >= 0; i--) for (j = m - 1; j >= 0; j--) L[i][j] = fa[i] === fb[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    var out = []; i = 0; j = 0;
    while (i < n && j < m) {
      if (fa[i] === fb[j]) { out.push([" ", b[j], a[i] !== b[j]]); i++; j++; }
      else if (L[i + 1][j] >= L[i][j + 1]) { out.push(["-", a[i]]); i++; }
      else { out.push(["+", b[j]]); j++; }
    }
    while (i < n) out.push(["-", a[i++]]);
    while (j < m) out.push(["+", b[j++]]);
    return out;
  };
  var input = $("#gateInput"), verdict = $("#gateVerdict"), diffBox = $("#gateDiff"), reasons = $("#gateReasons"), last = null;
  var nums = function (ws) { return ws.filter(function (w) { return /^\d+(\.\d+)?$/.test(w); }); };
  var acr = function (ws) { return ws.filter(function (w) { return /^[A-Z]{2,}$/.test(w); }); };
  var judge = function () {
    var a = words(SOURCE), b = words(input.value), d = diff(a, b);
    var gone = d.filter(function (x) { return x[0] === "-"; }).length, added = d.filter(function (x) { return x[0] === "+"; }).length;
    var folded = d.filter(function (x) { return x[0] === " " && x[2]; }).length;
    var nd = bagDiff(nums(a), nums(b)), ad = bagDiff(acr(a), acr(b));
    var marks = function (t) { return (t.match(/\[(\d+)\s*marks?\]/gi) || []).join(" "); };
    var marksOk = marks(SOURCE) === marks(input.value);
    var checks = [
      [nd.length === 0, nd.length ? "Numbers differ from the paper: " + nd.join(", ") : "Every number matches the paper exactly"],
      [ad.length === 0, ad.length ? "Acronyms differ: " + ad.join(", ") : "Every acronym matches"],
      [gone === 0, gone ? gone + " word" + (gone > 1 ? "s" : "") + " on the paper " + (gone > 1 ? "are" : "is") + " missing from the transcription" : "No word of the paper is missing"],
      [added === 0, added ? added + " word" + (added > 1 ? "s" : "") + " in the transcription " + (added > 1 ? "are" : "is") + " not on the paper" : "Nothing was added"],
      [marksOk, marksOk ? "Marks match and add up" : "Marks do not match the paper"]
    ];
    var pass = checks.every(function (c) { return c[0]; });
    verdict.textContent = pass ? "Result pass" : "Result block";
    verdict.className = "stamp" + (pass ? " pass" : "");
    if (last !== null && last !== pass && !calm) { void verdict.offsetWidth; verdict.classList.add("hit"); }
    last = pass;
    diffBox.textContent = "";
    d.forEach(function (x) {
      diffBox.appendChild(x[0] === " " ? document.createTextNode(x[1]) : el(x[0] === "-" ? "del" : "ins", "", x[1]));
      diffBox.appendChild(document.createTextNode(" "));
    });
    reasons.textContent = "";
    checks.forEach(function (c) { reasons.appendChild(el("li", c[0] ? "ok" : "no", c[1])); });
    if (folded) reasons.appendChild(el("li", "ok", folded + " OCR look-alike" + (folded > 1 ? "s" : "") + " folded (rn read as m, hyphen variants, letter case): still the same words"));
    if (!pass) reasons.appendChild(el("li", "no", "Stopped here. Nothing is written from this bank until it passes."));
  };
  $("#gateSource").textContent = SOURCE;
  input.value = SOURCE;
  input.addEventListener("input", judge);
  $$("[data-tamper]").forEach(function (b) {
    b.addEventListener("click", function () { input.value = TAMPER[b.getAttribute("data-tamper")](input.value); judge(); });
  });
  judge();

  /* Figure 4: planner (illustrative numbers): one list in yield order, with a cut-off line that moves */
  var TOPICS = [["IPv4 fragmentation", 4, 0.5], ["Subnetting and CIDR", 7, 1], ["TCP congestion control", 6, 1], ["Sliding-window protocols", 8, 1.5],
    ["Error detection: CRC", 5, 1], ["Routing algorithms", 6, 1.5], ["DNS and HTTP", 4, 1], ["TCP connection management", 3, 1],
    ["Medium access: ALOHA, CSMA", 4, 1.5], ["Switching and delay", 2, 1], ["Line coding", 1, 1]];
  var list = $("#planTopics"), hours = $("#hours"), cut = el("li", "cut");
  var items = TOPICS.map(function (t) {
    var li = el("li");
    li.appendChild(el("span", "", t[0])); li.appendChild(el("span", "dots")); li.appendChild(el("span", "m", t[1] + (t[1] === 1 ? " mark" : " marks"))); li.appendChild(el("span", "h", t[2] + " h"));
    list.appendChild(li); return li;
  });
  cut.setAttribute("aria-live", "polite");
  var plan = function () {
    var budget = +hours.value, used = 0, marks = 0, count = 0;
    TOPICS.forEach(function (t, i) {
      var take = count === i && used + t[2] <= budget;
      if (take) { used += t[2]; marks += t[1]; count++; }
      items[i].classList.toggle("in", take);
    });
    $("#hoursOut").textContent = budget;
    cut.textContent = budget + "-hour line: " + marks + " of 50 expected marks";
    list.insertBefore(cut, items[count] || null);
  };
  hours.addEventListener("input", plan);
  plan();

  /* Figure 5: cost per course */
  var COST = [["Before (typical)", 250, 350, "250–350"], ["Data mining", 0, 221, "221"], ["AI", 0, 178, "178"], ["Distributed OS", 0, 171, "171"], ["Image processing", 0, 91, "91"]];
  var chart = $("#costChart");
  COST.forEach(function (c) {
    var row = el("div", "bar-row"), track = el("div", "bar-track"), bar = el("span", c[1] ? "base" : ""), label = el("em", "", c[3]);
    track.appendChild(bar); track.appendChild(label);
    row.appendChild(el("span", "", c[0])); row.appendChild(track); chart.appendChild(row);
    whenSeen(chart, function () {
      bar.style.left = (c[1] / 350 * 100) + "%";
      bar.style.width = ((c[2] - c[1]) / 350 * 100) + "%";
      label.style.left = (c[2] / 350 * 100) + "%";
    });
  });

  /* plates: lightbox */
  var lb = $("#lightbox"), lbImg = $("#lbImg");
  $$("#gallery button").forEach(function (b) {
    b.addEventListener("click", function () {
      lbImg.src = "img/page-" + b.getAttribute("data-page") + ".webp";
      lbImg.width = +b.getAttribute("data-w"); lbImg.height = +b.getAttribute("data-h");
      lbImg.alt = $("img", b).alt;
      if (lb.showModal) lb.showModal(); else window.open(lbImg.src, "_blank", "noopener");
    });
  });
  lb.addEventListener("click", function (e) { if (e.target === lb || e.target.closest(".lb-close")) lb.close(); });

  /* running head: mark the section being read */
  if ("IntersectionObserver" in window) {
    var links = $$(".runhead nav a"), spy = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) links.forEach(function (a) { a.classList.toggle("on", a.getAttribute("href") === "#" + e.target.id); }); });
    }, { rootMargin: "-40% 0px -55% 0px" });
    $$("main section[id]").forEach(function (s) { spy.observe(s); });
  }
})();
