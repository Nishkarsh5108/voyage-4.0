// WebGL2 map renderer shared by the landing collapse and the workbench.
// Points carry a source shape and an optional merge target; edges are instanced quads (WebGL line width is 1px everywhere),
// so they can thicken, dash and follow their endpoints when records snap into a cluster. Positions are relative to an origin
// chosen on the CPU, so float32 stays precise at street zoom.

const PT_VS = `#version 300 es
precision highp float;
in vec2 a_pos; in vec2 a_tgt; in float a_tau; in float a_shape; in float a_state;
uniform vec2 u_center; uniform float u_scale; uniform vec2 u_res; uniform float u_t, u_dur, u_size, u_dpr;
out float v_shape; out float v_state; out float v_m; out float v_flash;
float mergeP(float tau){ if (tau < 0.0) return 0.0; float x = clamp((u_t - tau) / u_dur, 0.0, 1.0); return 1.0 - pow(1.0 - x, 3.0); }
void main(){
  float m = mergeP(a_tau);
  vec2 p = mix(a_pos, a_tgt, m);
  v_flash = 0.0;
  vec2 px = (p - u_center) * u_scale;
  gl_Position = vec4(px * 2.0 / u_res, 0.0, 1.0);
  float k = a_state == 2.0 ? 1.9 : (a_state == 1.0 ? 1.45 : (a_state == 3.0 ? 0.85 : 1.0));
  gl_PointSize = max(1.5, u_size * k * u_dpr);
  if (a_state < -0.5) gl_PointSize = 0.0;
  if (a_state == 4.0) {
    float vis = clamp((m - 0.8) / 0.2, 0.0, 1.0);
    gl_PointSize = u_size * 2.3 * u_dpr * vis;
    v_flash = 1.0 - clamp((u_t - a_tau - u_dur) / (u_dur * 0.45), 0.0, 1.0);
    m = 0.0;
  }
  v_shape = a_shape; v_state = a_state; v_m = m;
}`;
const PT_FS = `#version 300 es
precision highp float;
in float v_shape; in float v_state; in float v_m; in float v_flash;
uniform vec4 u_ink; uniform vec4 u_sig; uniform vec4 u_dim; uniform float u_alpha; uniform float u_fadeMerged;
out vec4 o;
void main(){
  vec2 q = gl_PointCoord * 2.0 - 1.0; q.y = -q.y;
  float s = v_shape; float inside;
  if (s < 0.5) inside = step(length(q), 0.92);
  else if (s < 1.5) inside = step(max(abs(q.x), abs(q.y)), 0.76);
  else if (s < 2.5) inside = step(-0.72, q.y) * step(q.y, 0.98) * step(abs(q.x), (0.98 - q.y) * 0.6);
  else if (s < 3.5) inside = step(abs(q.x) + abs(q.y), 1.0);
  else if (s < 4.5) { float r = length(q); inside = step(r, 0.92) * step(0.56, r); }
  else if (s < 5.5) { float m = max(abs(q.x), abs(q.y)); inside = step(m, 0.82) * step(0.52, m); }
  else if (s < 6.5) inside = max(step(abs(q.x), 0.2) * step(abs(q.y), 0.92), step(abs(q.y), 0.2) * step(abs(q.x), 0.92));
  else if (s < 7.5) inside = max(step(abs(q.x - q.y), 0.28), step(abs(q.x + q.y), 0.28)) * step(max(abs(q.x), abs(q.y)), 0.86);
  else { float r = length(q); inside = step(r, 0.96) * max(step(0.66, r), step(r, 0.3)); }
  if (inside < 0.5) discard;
  if (v_state == 4.0) { vec4 cc = mix(u_ink, u_sig, v_flash); o = vec4(cc.rgb * cc.a, cc.a); return; }
  vec4 c = v_state == 1.0 || v_state == 2.0 ? u_sig : (v_state == 3.0 ? u_dim : u_ink);
  float a = c.a * (v_state == 1.0 || v_state == 2.0 ? 1.0 : u_alpha) * (1.0 - u_fadeMerged * v_m);
  o = vec4(c.rgb * a, a);
}`;
const ED_VS = `#version 300 es
precision highp float;
in vec2 a_corner;
in vec2 a_pa; in vec2 a_pb; in vec2 a_ta; in vec2 a_tb; in float a_tau; in float a_w; in float a_col; in float a_alpha; in float a_pat;
uniform vec2 u_center; uniform float u_scale; uniform vec2 u_res; uniform float u_t, u_dur, u_lead, u_grow, u_dpr, u_wscale;
out float v_col; out float v_alpha; out float v_along; out float v_pat;
float mergeP(float tau){ if (tau < 0.0) return 0.0; float x = clamp((u_t - tau) / u_dur, 0.0, 1.0); return 1.0 - pow(1.0 - x, 3.0); }
void main(){
  float m = mergeP(a_tau);
  vec2 A = mix(a_pa, a_ta, m), B = mix(a_pb, a_tb, m);
  float g = 1.0;
  if (u_grow > 0.5 && a_tau >= 0.0) g = clamp((u_t - (a_tau - u_lead)) / u_lead, 0.0, 1.0);
  g = 1.0 - pow(1.0 - g, 2.0);
  B = mix(A, B, g);
  vec2 pa = (A - u_center) * u_scale, pb = (B - u_center) * u_scale;
  vec2 d = pb - pa; float L = length(d);
  vec2 dir = L > 1e-4 ? d / L : vec2(1.0, 0.0); vec2 n = vec2(-dir.y, dir.x);
  float w = max(a_w * u_wscale, 0.6);
  vec2 p = mix(pa, pb, a_corner.x) + n * a_corner.y * w * 0.5;
  gl_Position = vec4(p * 2.0 / u_res, 0.0, 1.0);
  float vis = (u_grow > 0.5 && a_tau >= 0.0 && g <= 0.0) ? 0.0 : 1.0;
  v_alpha = a_alpha * vis * (u_grow > 0.5 ? (1.0 - m) : 1.0);
  v_col = a_col; v_along = a_corner.x * L; v_pat = a_pat;
}`;
const ED_FS = `#version 300 es
precision highp float;
in float v_col; in float v_alpha; in float v_along; in float v_pat;
uniform vec4 u_ink; uniform vec4 u_sig; uniform vec4 u_dim;
out vec4 o;
void main(){
  if (v_pat > 0.5 && v_pat < 1.5 && mod(v_along, 9.0) > 5.5) discard;
  if (v_pat > 1.5 && mod(v_along, 5.0) > 1.8) discard;
  vec4 c = v_col < 0.5 ? u_ink : (v_col < 1.5 ? u_sig : u_dim);
  float a = c.a * v_alpha;
  if (a <= 0.002) discard;
  o = vec4(c.rgb * a, a);
}`;
const LN_VS = `#version 300 es
precision highp float;
in vec2 a_p; uniform vec2 u_center; uniform float u_scale; uniform vec2 u_res;
void main(){ gl_Position = vec4((a_p - u_center) * u_scale * 2.0 / u_res, 0.0, 1.0); }`;
const LN_FS = `#version 300 es
precision highp float; uniform vec4 u_col; out vec4 o; void main(){ o = vec4(u_col.rgb * u_col.a, u_col.a); }`;

function compile(gl, vs, fs) {
  const mk = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
  const p = gl.createProgram(); gl.attachShader(p, mk(gl.VERTEX_SHADER, vs)); gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const loc = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) { const u = gl.getActiveUniform(p, i); loc[u.name] = gl.getUniformLocation(p, u.name); }
  const att = {}; const na = gl.getProgramParameter(p, gl.ACTIVE_ATTRIBUTES);
  for (let i = 0; i < na; i++) { const a = gl.getActiveAttrib(p, i); att[a.name] = gl.getAttribLocation(p, a.name); }
  return { p, loc, att };
}

export function hexRGBA(hex, a = 1) {
  const h = hex.replace("#", ""); const v = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
  return [(v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255, a];
}

export class MapGL {
  constructor(canvas, palette) {
    this.canvas = canvas;
    const gl = canvas.getContext("webgl2", { antialias: true, premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: false });
    if (!gl) throw new Error("WebGL2 is not available in this browser.");
    this.gl = gl;
    this.pt = compile(gl, PT_VS, PT_FS); this.ed = compile(gl, ED_VS, ED_FS); this.ln = compile(gl, LN_VS, LN_FS);
    this.palette = palette;
    this.view = { cx: 0, cy: 0, scale: 1 };
    this.u = { t: 0, dur: 0.1, lead: 0.1, grow: 0, size: 3, alpha: 0.8, fadeMerged: 0, wscale: 1 };
    this.np = 0; this.ne = 0; this.lines = [];
    this.corner = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, this.corner);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([0, -1, 1, -1, 0, 1, 0, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    this.ptVAO = gl.createVertexArray(); this.edVAO = gl.createVertexArray();
    this.bufs = {};
    this.resize();
  }
  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    this.w = w; this.h = h; this.dpr = dpr;
    const W = Math.max(1, Math.round(w * dpr)), H = Math.max(1, Math.round(h * dpr));
    if (this.canvas.width !== W || this.canvas.height !== H) { this.canvas.width = W; this.canvas.height = H; }
  }
  _buf(name, data, usage) {
    const gl = this.gl; let b = this.bufs[name];
    if (!b) { b = this.bufs[name] = gl.createBuffer(); }
    gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, usage || gl.STATIC_DRAW); return b;
  }
  _attr(prog, name, buf, size, divisor = 0) {
    const gl = this.gl, loc = prog.att[name]; if (loc === undefined || loc < 0) return;
    gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0); gl.vertexAttribDivisor(loc, divisor);
  }
  // pos/tgt: Float32Array [x0,y0,x1,y1...]; tau, shape, state: Float32Array per point
  setPoints({ pos, tgt, tau, shape, state }) {
    const gl = this.gl; this.np = pos.length / 2;
    gl.bindVertexArray(this.ptVAO);
    this._attr(this.pt, "a_pos", this._buf("p_pos", pos), 2);
    this._attr(this.pt, "a_tgt", this._buf("p_tgt", tgt || pos), 2);
    this._attr(this.pt, "a_tau", this._buf("p_tau", tau || new Float32Array(this.np).fill(-1)), 1);
    this._attr(this.pt, "a_shape", this._buf("p_shape", shape), 1);
    this._attr(this.pt, "a_state", this._buf("p_state", state || new Float32Array(this.np), gl.DYNAMIC_DRAW), 1);
    gl.bindVertexArray(null);
  }
  updatePoints(name, data) { const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, this.bufs["p_" + name]); gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW); }
  // per-edge Float32Arrays: pa, pb, ta, tb (xy pairs); tau, w, col, alpha, pat (scalars)
  setEdges(e) {
    const gl = this.gl; this.ne = e.w.length;
    gl.bindVertexArray(this.edVAO);
    this._attr(this.ed, "a_corner", this.corner, 2, 0);
    this._attr(this.ed, "a_pa", this._buf("e_pa", e.pa), 2, 1);
    this._attr(this.ed, "a_pb", this._buf("e_pb", e.pb), 2, 1);
    this._attr(this.ed, "a_ta", this._buf("e_ta", e.ta || e.pa), 2, 1);
    this._attr(this.ed, "a_tb", this._buf("e_tb", e.tb || e.pb), 2, 1);
    this._attr(this.ed, "a_tau", this._buf("e_tau", e.tau || new Float32Array(this.ne).fill(-1)), 1, 1);
    this._attr(this.ed, "a_w", this._buf("e_w", e.w, gl.DYNAMIC_DRAW), 1, 1);
    this._attr(this.ed, "a_col", this._buf("e_col", e.col, gl.DYNAMIC_DRAW), 1, 1);
    this._attr(this.ed, "a_alpha", this._buf("e_alpha", e.alpha, gl.DYNAMIC_DRAW), 1, 1);
    this._attr(this.ed, "a_pat", this._buf("e_pat", e.pat || new Float32Array(this.ne), gl.DYNAMIC_DRAW), 1, 1);
    gl.bindVertexArray(null);
  }
  updateEdges(name, data) { const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, this.bufs["e_" + name]); gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW); }
  // static line layers for the basemap: segments as Float32Array [x0,y0,x1,y1,...] (gl.LINES)
  setLines(layers) {
    const gl = this.gl;
    this.lines = layers.map((L, i) => {
      const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
      const b = this._buf("ln" + i, L.segs); const loc = this.ln.att.a_p;
      gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      gl.bindVertexArray(null);
      return { vao, n: L.segs.length / 2, col: L.col };
    });
  }
  _common(prog) {
    const gl = this.gl, L = prog.loc, v = this.view;
    gl.uniform2f(L.u_center, v.cx, v.cy); gl.uniform1f(L.u_scale, v.scale); gl.uniform2f(L.u_res, this.w, this.h);
  }
  draw({ points = true, edges = true, lines = true } = {}) {
    const gl = this.gl, P = this.palette, u = this.u;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    if (lines && this.lines.length) {
      gl.useProgram(this.ln.p); this._common(this.ln);
      for (const l of this.lines) { gl.uniform4fv(this.ln.loc.u_col, l.col); gl.bindVertexArray(l.vao); gl.drawArrays(gl.LINES, 0, l.n); }
    }
    if (edges && this.ne) {
      const L = this.ed.loc; gl.useProgram(this.ed.p); this._common(this.ed);
      gl.uniform1f(L.u_t, u.t); gl.uniform1f(L.u_dur, u.dur); gl.uniform1f(L.u_lead, u.lead); gl.uniform1f(L.u_grow, u.grow); gl.uniform1f(L.u_dpr, this.dpr); gl.uniform1f(L.u_wscale, u.wscale);
      gl.uniform4fv(L.u_ink, P.ink); gl.uniform4fv(L.u_sig, P.sig); gl.uniform4fv(L.u_dim, P.dim);
      gl.bindVertexArray(this.edVAO); gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, this.ne);
    }
    if (points && this.np) {
      const L = this.pt.loc; gl.useProgram(this.pt.p); this._common(this.pt);
      gl.uniform1f(L.u_t, u.t); gl.uniform1f(L.u_dur, u.dur); gl.uniform1f(L.u_size, u.size); gl.uniform1f(L.u_dpr, this.dpr);
      gl.uniform1f(L.u_alpha, u.alpha); gl.uniform1f(L.u_fadeMerged, u.fadeMerged);
      gl.uniform4fv(L.u_ink, P.ink); gl.uniform4fv(L.u_sig, P.sig); gl.uniform4fv(L.u_dim, P.dim);
      gl.bindVertexArray(this.ptVAO); gl.drawArrays(gl.POINTS, 0, this.np);
    }
    gl.bindVertexArray(null);
  }
  // view helpers (y up in data space, y down on screen)
  toScreen(x, y) { const v = this.view; return [this.w / 2 + (x - v.cx) * v.scale, this.h / 2 - (y - v.cy) * v.scale]; }
  toData(sx, sy) { const v = this.view; return [v.cx + (sx - this.w / 2) / v.scale, v.cy - (sy - this.h / 2) / v.scale]; }
  fit(minx, miny, maxx, maxy, pad = 0, mode = "contain") {
    const w = Math.max(1, this.w - 2 * pad), h = Math.max(1, this.h - 2 * pad);
    const sx = w / Math.max(1e-9, maxx - minx), sy = h / Math.max(1e-9, maxy - miny);
    this.view = { cx: (minx + maxx) / 2, cy: (miny + maxy) / 2, scale: mode === "cover" ? Math.max(sx, sy) : Math.min(sx, sy) };
  }
}

// polyline list (flat [lon,lat,lon,lat...]) -> segment Float32Array in projected, origin-relative units
export function segmentsFrom(lines, proj, ox, oy) {
  let n = 0; for (const l of lines) n += Math.max(0, l.length / 2 - 1);
  const out = new Float32Array(n * 4); let k = 0;
  for (const l of lines) for (let i = 0; i + 3 < l.length; i += 2) {
    out[k++] = proj.x(l[i]) - ox; out[k++] = proj.y(l[i + 1]) - oy; out[k++] = proj.x(l[i + 2]) - ox; out[k++] = proj.y(l[i + 3]) - oy;
  }
  return out;
}
