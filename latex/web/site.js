/* Study-guide web export (tools/web.py): math, animations, answer toggles, search, flashcards.
   Vanilla JS, no framework, no build step. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- math (KaTeX from cdnjs) */
  function renderMath(root) {
    if (!window.katex) return;
    var els = (root || document).querySelectorAll("span.m, div.md");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.getAttribute("data-k")) continue;
      try {
        katex.render(el.textContent, el, { displayMode: el.tagName === "DIV", throwOnError: false, strict: "ignore" });
        el.setAttribute("data-k", "1");
      } catch (e) { /* leave the TeX source visible */ }
    }
    fitInlineMath(root);
  }

  /* An inline formula with no operator to break at (e.g. a list of tuples) can be wider than a phone
     line: give just that formula its own horizontal scroller so the page never scrolls sideways. */
  function fitInlineMath(root) {
    var els = (root || document).querySelectorAll("span.m[data-k]");
    for (var i = 0; i < els.length; i++) {
      var el = els[i], box = el.parentElement;
      while (box && getComputedStyle(box).display.indexOf("inline") === 0) box = box.parentElement;
      if (!box) continue;
      var w = box.clientWidth, bases = el.querySelectorAll(".katex-html > .base");
      for (var j = 0; j < bases.length; j++) {
        if (bases[j].getBoundingClientRect().width > w) { el.classList.add("m-wide"); break; }
      }
    }
  }

  /* ---------------------------------------------------------------- animations */
  function initAnim(fig) {
    var stage = fig.querySelector(".anim-stage");
    var frames = stage.querySelectorAll("img");
    var n = frames.length, k = 0, timer = null;
    var ctl = fig.querySelector(".anim-ctl");
    var play = ctl.querySelector(".play"), cnt = ctl.querySelector(".cnt");
    var dots = ctl.querySelectorAll(".dot");
    ctl.hidden = false;
    for (var i = 0; i < n; i++) frames[i].loading = "eager";
    function show(j) {
      k = (j + n) % n;
      for (var i = 0; i < n; i++) {
        frames[i].classList.toggle("on", i === k);
        if (dots[i]) dots[i].classList.toggle("on", i === k);
      }
      cnt.textContent = (k + 1) + " / " + n;
    }
    function stop() { if (timer) { clearInterval(timer); timer = null; } play.innerHTML = "&#9654; Play"; play.setAttribute("aria-label", "Play"); }
    function start() {
      stop();
      if (k === n - 1) show(0);
      timer = setInterval(function () { if (k === n - 1) { stop(); return; } show(k + 1); }, 1600);
      play.innerHTML = "&#10074;&#10074; Pause"; play.setAttribute("aria-label", "Pause");
    }
    play.addEventListener("click", function () { timer ? stop() : start(); });
    ctl.querySelector(".prev").addEventListener("click", function () { stop(); show(k - 1); });
    ctl.querySelector(".next").addEventListener("click", function () { stop(); show(k + 1); });
    for (var d = 0; d < dots.length; d++) dots[d].addEventListener("click", function (e) { stop(); show(+e.currentTarget.getAttribute("data-k")); });
    stage.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { stop(); show(k + 1); e.preventDefault(); }
      else if (e.key === "ArrowLeft") { stop(); show(k - 1); e.preventDefault(); }
      else if (e.key === " ") { timer ? stop() : start(); e.preventDefault(); }
    });
    var x0 = null, y0 = null;
    stage.addEventListener("touchstart", function (e) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
    stage.addEventListener("touchend", function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) { stop(); show(dx < 0 ? k + 1 : k - 1); }
      x0 = null;
    });
    stage.addEventListener("click", function () { stop(); show(k + 1); });
    show(0);
    if (!reduce && "IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (en) { if (!en.isIntersecting && timer) stop(); });
      });
      io.observe(fig);
    }
  }

  /* ---------------------------------------------------------------- answers (self-test) */
  function initToggles() {
    var btns = document.querySelectorAll(".toggle-ans");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function (e) {
        var ds = document.querySelectorAll("details.ans");
        var anyClosed = false;
        for (var j = 0; j < ds.length; j++) if (!ds[j].open) anyClosed = true;
        for (j = 0; j < ds.length; j++) ds[j].open = anyClosed;
        var all = document.querySelectorAll(".toggle-ans");
        for (j = 0; j < all.length; j++) all[j].textContent = anyClosed ? "Hide answers (self-test)" : "Show all answers";
      });
    }
  }

  /* ---------------------------------------------------------------- search */
  function initSearch() {
    var q = document.getElementById("q"), res = document.getElementById("qres");
    if (!q) return;
    var idx = null, loading = false;
    function load(cb) {
      if (idx) return cb();
      if (loading) return;
      loading = true;
      fetch("search.json").then(function (r) { return r.json(); }).then(function (j) {
        idx = j.map(function (e) { e.l = (e.t + " " + e.x).toLowerCase(); e.tl = e.t.toLowerCase(); return e; });
        cb();
      }).catch(function () { loading = false; });
    }
    function run() {
      var s = q.value.trim().toLowerCase();
      if (!s) { res.hidden = true; res.innerHTML = ""; return; }
      var toks = s.split(/\s+/);
      var hits = [];
      idx.forEach(function (e) {
        var sc = 0;
        for (var i = 0; i < toks.length; i++) {
          var t = toks[i];
          if (e.l.indexOf(t) < 0) return;
          sc += e.tl.indexOf(t) >= 0 ? 5 : 1;
        }
        if (e.k === "pyq") sc += 1;
        hits.push([sc, e]);
      });
      hits.sort(function (a, b) { return b[0] - a[0]; });
      res.innerHTML = "";
      hits.slice(0, 8).forEach(function (h) {
        var li = document.createElement("li"), a = document.createElement("a"), sm = document.createElement("small");
        a.href = h[1].u; a.textContent = h[1].t;
        var x = h[1].x, p = x.toLowerCase().indexOf(toks[0]);
        sm.textContent = (p > 40 ? "…" : "") + x.substr(Math.max(0, p - 40), 120) + "…";
        a.appendChild(sm); li.appendChild(a); res.appendChild(li);
      });
      if (!hits.length) { var li = document.createElement("li"); li.innerHTML = "<a>No match</a>"; res.appendChild(li); }
      res.hidden = false;
    }
    q.addEventListener("focus", function () { load(function () {}); });
    q.addEventListener("input", function () { load(run); });
    q.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { res.hidden = true; q.blur(); }
      if (e.key === "Enter") { var a = res.querySelector("a[href]"); if (a) location.href = a.href; }
    });
    document.addEventListener("click", function (e) { if (!e.target.closest(".search")) res.hidden = true; });
  }

  /* ---------------------------------------------------------------- flashcards study mode */
  function initCards() {
    var box = document.getElementById("fc"), dataEl = document.getElementById("cards");
    if (!box || !dataEl) return;
    var cards = JSON.parse(dataEl.textContent);
    if (!cards.length) return;
    box.hidden = false;
    var pile = cards.map(function (c, i) { return i; });
    for (var i = pile.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = pile[i]; pile[i] = pile[j]; pile[j] = t; }
    var f = box.querySelector(".fc-f"), b = box.querySelector(".fc-b"), n = box.querySelector(".fc-n");
    var bs = box.querySelector(".fc-show"), ba = box.querySelector(".fc-again"), bg = box.querySelector(".fc-good");
    var done = 0;
    function next() {
      if (!pile.length) { f.textContent = "Deck done: " + done + " cards."; b.hidden = true; bs.hidden = true; ba.hidden = bg.hidden = true; n.textContent = ""; return; }
      var c = cards[pile[0]];
      f.innerHTML = c.f; b.innerHTML = c.b; b.hidden = true; bs.hidden = false; ba.hidden = bg.hidden = true;
      n.textContent = pile.length + " left";
      renderMath(box);
    }
    bs.addEventListener("click", function () { b.hidden = false; bs.hidden = true; ba.hidden = bg.hidden = false; });
    ba.addEventListener("click", function () { pile.push(pile.shift()); next(); });
    bg.addEventListener("click", function () { pile.shift(); done++; next(); });
    next();
  }

  function init() {
    renderMath();
    var figs = document.querySelectorAll("figure.anim");
    for (var i = 0; i < figs.length; i++) initAnim(figs[i]);
    initToggles();
    initSearch();
    initCards();
    // KaTeX is deferred too; if it arrived after us, render when it is there
    if (!window.katex && document.querySelector("span.m, div.md")) {
      var tries = 0, iv = setInterval(function () { if (window.katex || ++tries > 50) { clearInterval(iv); renderMath(); } }, 100);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
