// 02 · The problem in one picture. The real "hotels near Dubai Marina" result as four feeds deliver it, then the same offers
// stacked under nine canonical hotels. Names and matches: real (submission/round1/demo/data.js ← clusters). Prices and policies: simulated.

import { $, el, esc, fmt, reduced, mark, labelOf } from "./util.js";

export function initProblem(S) {
  const box = $("#cards"), seg = $("#problemSeg"), meter = $("#problemMeter");
  const hotels = S.marina.cards;
  const offers = hotels.flatMap((h, hi) => h.offers.map(o => ({ ...o, hotel: hi })));
  const rawOrder = offers.map((o, i) => i).sort((a, b) => offers[a].price - offers[b].price);
  let mode = "raw";

  const cardEls = offers.map((o, i) => {
    const c = el("div", "card", `<div class="nm raw">${esc(o.listed_as)}</div>
      <div class="row"><span class="src">${mark(o.src)}${esc(labelOf(o.src))}</span><span class="pr hatched-soft"><small>AED</small>${fmt.int(o.price)}</span></div>
      <div class="pol">${esc(o.policy)} · ${esc(o.pay)}</div>`);
    c.dataset.h = o.hotel;
    c.addEventListener("pointerenter", () => { if (mode !== "raw") return; box.classList.add("hovering"); cardEls.forEach(x => x.classList.toggle("twin", x.dataset.h === c.dataset.h)); });
    c.addEventListener("pointerleave", () => { box.classList.remove("hovering"); cardEls.forEach(x => x.classList.remove("twin")); });
    box.append(c); return c;
  });
  const best = hotels.map(h => h.offers.reduce((b, o) => (o.price < b.price ? o : b)));
  const headEls = hotels.map((h, hi) => {
    const names = [...new Set(h.offers.map(o => o.listed_as))];
    const c = el("div", "ccard", `<div class="cn canon-name">${esc(h.name)}</div>
      <div class="cm"><span class="tiny">${h.offers.length} suppliers · ${names.length} spelling${names.length > 1 ? "s" : ""}</span><span class="from"><small class="tiny">from AED </small>${fmt.int(best[hi].price)}</span></div>`);
    c.style.opacity = 0; c.style.pointerEvents = "none"; box.append(c); return c;
  });

  function place(node, x, y, w, h, delay = 0) {
    node.style.transitionDelay = reduced() ? "0ms" : delay + "ms";
    node.style.transform = `translate(${x}px, ${y}px)`; node.style.width = w + "px"; node.style.height = h + "px";
  }
  function layout(animate = true) {
    const W = box.clientWidth, gap = 10;
    box.querySelectorAll(".card, .ccard").forEach(n => n.style.transition = animate && !reduced()
      ? "transform .8s var(--ease), width .8s var(--ease), height .8s var(--ease), opacity .4s var(--ease), border-color .15s, box-shadow .15s" : "none");
    if (mode === "raw") {
      const cols = Math.max(2, Math.floor((W + gap) / 238)), cw = (W - gap * (cols - 1)) / cols, ch = W < 560 ? 132 : 122;
      rawOrder.forEach((oi, k) => { const r = Math.floor(k / cols), c = k % cols; place(cardEls[oi], c * (cw + gap), r * (ch + gap), cw, ch, 0); cardEls[oi].classList.remove("fanned", "best"); });
      headEls.forEach(h => { h.style.opacity = 0; });
      box.style.height = Math.ceil(offers.length / cols) * (ch + gap) + "px";
    } else {
      const cols = Math.max(1, Math.floor((W + 18) / 330)), cw = (W - 18 * (cols - 1)) / cols, hh = 84, oh = 50, og = 4;
      const colY = new Array(cols).fill(0);
      hotels.forEach((h, hi) => {
        const c = colY.indexOf(Math.min(...colY)), x = c * (cw + 18), y = colY[c];
        place(headEls[hi], x, y, cw, hh, 0); headEls[hi].style.opacity = 1;
        let yy = y + hh + og;
        h.offers.forEach((o) => {
          const oi = offers.findIndex(q => q.hotel === hi && q.src === o.src && q.listed_as === o.listed_as);
          const n = cardEls[oi]; n.classList.add("fanned"); n.classList.toggle("best", o === best[hi]);
          place(n, x + 14, yy, cw - 14, oh, 60 + hi * 45); yy += oh + og;
        });
        colY[c] = yy + 22;
      });
      box.style.height = Math.max(...colY) + "px";
    }
    meter.innerHTML = mode === "raw"
      ? `<span class="m"><b>${offers.length}</b><span class="tiny">cards</span></span><span class="m"><b>${hotels.length}</b><span class="tiny">hotels behind them</span></span><span class="m"><b>${fmt.pct0(1 - hotels.length / offers.length)}</b><span class="tiny">of the page is repetition</span></span>`
      : `<span class="m"><b>${hotels.length}</b><span class="tiny">canonical hotels</span></span><span class="m"><b>${offers.length}</b><span class="tiny">offers kept underneath</span></span><span class="m"><b>0</b><span class="tiny">duplicate cards</span></span>`;
  }
  seg.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return; mode = b.dataset.v;
    seg.querySelectorAll("button").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-selected", x === b); });
    box.classList.remove("hovering"); cardEls.forEach(x => x.classList.remove("twin"));
    layout(true);
  });
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => layout(false), 120); });
  layout(false);
}
