// Workbench worker: re-forms clusters for a new accept threshold off the UI thread.
// A port of canon/cascade.py `route` + `constrained_union_find`: key matches weigh 2.0, model accepts weigh p, merged in descending
// weight order (stable, ties by candidate position), never joining two different Wikidata QIDs; pairs without coordinates
// on both sides are never auto-accepted. Precision and recall are computed against the run's weak labels (y in {0, 1}).

let D = null;
const KEY_MATCH = 0, KEY_REJECT = 1, MODEL_ACCEPT = 2, MODEL_REJECT = 3, UNCERTAIN = 4, NO_COORDS = 5;

self.onmessage = e => {
  const m = e.data;
  if (m.type === "init") { D = m; self.postMessage({ type: "ready" }); return; }
  if (m.type === "recluster") self.postMessage({ type: "clusters", t: m.t, ...recluster(m.t, D.t_reject) });
};

function recluster(t, tReject) {
  const { n, ra, rb, p, y, dist, qid } = D, ne = ra.length;
  const route = new Uint8Array(ne);
  for (let k = 0; k < ne; k++) {
    const yy = y[k], pp = p[k], xy = dist[k] === dist[k]; // NaN distance: a side has no coordinates
    route[k] = yy === 1 ? KEY_MATCH : yy === 0 ? KEY_REJECT : pp < tReject ? MODEL_REJECT : (xy ? (pp >= t ? MODEL_ACCEPT : UNCERTAIN) : NO_COORDS);
  }
  const acc = [];
  for (let k = 0; k < ne; k++) if (route[k] === KEY_MATCH || route[k] === MODEL_ACCEPT) acc.push(k);
  const w = k => route[k] === KEY_MATCH ? 2.0 : p[k];
  acc.sort((a, b) => (w(b) - w(a)) || (a - b));
  const parent = new Int32Array(n); for (let i = 0; i < n; i++) parent[i] = i;
  const q = Int32Array.from(qid);
  const find = x => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  let blocked = 0;
  for (const k of acc) {
    const a = find(ra[k]), b = find(rb[k]);
    if (a === b) continue;
    if (q[a] >= 0 && q[b] >= 0 && q[a] !== q[b]) { blocked++; continue; }
    parent[a] = b; if (q[b] < 0) q[b] = q[a];
  }
  const root = new Int32Array(n); const size = new Map();
  for (let i = 0; i < n; i++) { root[i] = find(i); size.set(root[i], (size.get(root[i]) || 0) + 1); }
  let multi = 0, largest = 1; for (const s of size.values()) { if (s > 1) multi++; if (s > largest) largest = s; }
  // weak-label evaluation of the pair model alone (key-labelled pairs are the truth, so the key rules are not scored against themselves)
  let tp = 0, fp = 0, fn = 0, pos = 0, neg = 0;
  for (let k = 0; k < ne; k++) {
    const yy = y[k]; if (yy !== 1 && yy !== 0) continue;
    const hit = p[k] >= t && dist[k] === dist[k];
    if (yy === 1) { pos++; hit ? tp++ : fn++; } else { neg++; if (hit) fp++; }
  }
  const counts = [0, 0, 0, 0, 0, 0]; for (let k = 0; k < ne; k++) counts[route[k]]++;
  return { root, route, entities: size.size, multi, largest, blocked, counts, pr: { tp, fp, fn, pos, neg } };
}
