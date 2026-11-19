// Boot: read numbers.json (the only source of quoted figures) and the story data, then start each section.
import { $, $$, getJSON, bindNumbers, derive, initReveal } from "./util.js";

const sections = [
  ["landing", () => import("./landing.js").then(m => m.initLanding(S.landing, S.N))],
  ["problem", () => import("./problem.js").then(m => m.initProblem(S.story, S.N))],
  ["how", () => import("./story.js").then(m => m.initStory(S.story, S.N))],
  ["workbench", () => import("./workbench.js").then(m => m.initWorkbench(S.N))],
  ["evidence", () => import("./evidence.js").then(m => m.initEvidence(S.N))],
];
const S = {};

async function boot() {
  initReveal();
  try {
    const [N, landing, story] = await Promise.all([getJSON("/numbers.json"), getJSON("data/landing.json"), getJSON("data/story.json")]);
    S.N = derive(N); S.landing = landing; S.story = story;
  } catch (e) {
    document.body.insertAdjacentHTML("afterbegin", `<p style="position:fixed;z-index:99;left:16px;top:56px;background:#ff4f00;color:#000;padding:8px 12px;font:13px monospace">Could not load site data: ${e.message}. Start the site with: .venv\\Scripts\\python.exe -X utf8 web\\serve.py</p>`);
    throw e;
  }
  bindNumbers(S.N);
  for (const [id, start] of sections) {
    try { await start(); } catch (e) { console.error(`section ${id} failed`, e); }
  }
  chrome();
}

function chrome() {
  const bar = $("#topbar"), links = $$("#topnav a");
  const ids = links.map(a => a.getAttribute("href").slice(1));
  const update = () => {
    const y = innerHeight * 0.3;
    let cur = ids[0];
    for (const id of ids) { const s = document.getElementById(id); if (s && s.getBoundingClientRect().top <= y) cur = id; }
    links.forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#" + cur));
    const wb = document.getElementById("workbench").getBoundingClientRect();
    const overWb = wb.top <= 44 && wb.bottom > 44;
    bar.classList.toggle("dark", overWb);
    bar.classList.toggle("solid", !overWb && document.getElementById("landing").getBoundingClientRect().bottom < innerHeight * 0.6);
  };
  addEventListener("scroll", update, { passive: true }); update();
}

boot();
