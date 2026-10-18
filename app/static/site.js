"use strict";
/* Landing and sign-in motion: reveals on scroll, a scroll-scrubbed statement, count-ups, the sticky 8-step story
   and a pointer-tilted card. Everything is progressive: with reduced motion or no JS the content is simply shown. */
(() => {
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // split headlines into words that slide up one after another
  document.querySelectorAll(".words").forEach((el) => {
    let i = 0;
    const walk = (node) => [...node.childNodes].forEach((n) => {
      if (n.nodeType === 3) {
        const frag = document.createDocumentFragment();
        n.textContent.split(/(\s+)/).forEach((part) => {
          if (!part) return;
          if (/^\s+$/.test(part)) { frag.append(" "); return; }
          const w = document.createElement("span"), inner = document.createElement("span");
          w.className = "w"; inner.textContent = part; inner.style.setProperty("--i", i++);
          w.append(inner); frag.append(w);
        });
        n.replaceWith(frag);
      } else if (n.nodeType === 1 && n.tagName !== "BR") walk(n);
    });
    walk(el);
  });

  // reveal once on entering the viewport
  const seen = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (!e.isIntersecting) return;
    e.target.classList.add("in");
    seen.unobserve(e.target);
    const n = e.target.querySelector("[data-count]") || (e.target.dataset.count !== undefined && e.target);
    if (n) count(n);
  }), { threshold: 0.18, rootMargin: "0px 0px -6% 0px" });
  document.querySelectorAll("[data-reveal], .words, .reveal-group, .paycard, .stat").forEach((el) => seen.observe(el));

  function count(el) {
    const end = Number(el.dataset.count), t0 = performance.now(), dur = calm ? 0 : 1400;
    const tick = (t) => {
      const p = dur ? Math.min(1, (t - t0) / dur) : 1;
      el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3))).toLocaleString("en-IN");
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // statement: words light up as the reader scrolls through it
  const stmt = document.querySelector("[data-scrub]");
  let parts = [];
  if (stmt) {
    const walk = (node) => [...node.childNodes].forEach((n) => {
      if (n.nodeType === 3) {
        const frag = document.createDocumentFragment();
        n.textContent.split(/(\s+)/).forEach((p) => {
          if (!p) return;
          if (/^\s+$/.test(p)) { frag.append(" "); return; }
          const s = document.createElement("span"); s.className = "s"; s.textContent = p; frag.append(s);
        });
        n.replaceWith(frag);
      } else if (n.nodeType === 1) walk(n);
    });
    walk(stmt);
    parts = [...stmt.querySelectorAll(".s")];
  }

  // sticky story: the step nearest the middle of the screen drives the visual
  const story = document.querySelector(".story-visual");
  const items = [...document.querySelectorAll(".story-steps li")];
  let current = -1;
  function setStep(i) {
    if (i === current || !story) return;
    current = i;
    const li = items[i];
    items.forEach((x, j) => x.classList.toggle("on", j === i));
    story.querySelectorAll(".story-dots i").forEach((d, j) => d.classList.toggle("on", j === i));
    story.style.setProperty("--sc", li.dataset.c1);
    story.style.setProperty("--sc2", li.dataset.c2);
    story.classList.add("swap");
    setTimeout(() => {
      story.querySelector(".sn").textContent = String(i + 1).padStart(2, "0");
      story.querySelector(".st").textContent = li.querySelector("h3").textContent;
      story.querySelector(".sd").textContent = li.dataset.short;
      story.classList.remove("swap");
    }, calm ? 0 : 220);
  }

  // nav: solid after the hero, hidden while scrolling down
  const nav = document.querySelector(".site-nav");
  let lastY = scrollY, ticking = false;
  function onScroll() {
    ticking = false;
    const y = scrollY;
    if (nav) {
      nav.classList.toggle("scrolled", y > 20);
      nav.classList.toggle("hide", y > 500 && y > lastY + 4);
      if (y < lastY - 4) nav.classList.remove("hide");
    }
    lastY = y;
    if (parts.length) {
      const r = stmt.getBoundingClientRect();
      const p = Math.min(1, Math.max(0, (innerHeight * 0.85 - r.top) / (r.height + innerHeight * 0.35)));
      const lit = Math.round(p * parts.length);
      parts.forEach((s, i) => s.classList.toggle("lit", i < lit));
    }
    if (items.length) {
      const mid = innerHeight / 2;
      let best = 0, dist = Infinity;
      items.forEach((li, i) => {
        const r = li.getBoundingClientRect(), d = Math.abs(r.top + r.height / 2 - mid);
        if (d < dist) { dist = d; best = i; }
      });
      setStep(best);
    }
  }
  addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  addEventListener("resize", onScroll);
  onScroll();

  // card follows the pointer
  const card = document.querySelector(".paycard");
  const area = card && card.closest(".stage3d");
  if (card && area && !calm && matchMedia("(pointer: fine)").matches) {
    area.addEventListener("pointermove", (e) => {
      const r = area.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      card.style.setProperty("--ry", (x * 22).toFixed(2) + "deg");
      card.style.setProperty("--rx", (-y * 18).toFixed(2) + "deg");
      card.style.setProperty("--sheen", (x * 120).toFixed(0) + "%");
    });
    area.addEventListener("pointerleave", () => ["--rx", "--ry", "--sheen"].forEach((p) => card.style.removeProperty(p)));
  }
})();
