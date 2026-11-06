// Image viewer with an SVG overlay for detection boxes (shared by Results and Review).
class Viewer {
  constructor(root, payload, opts = {}) {
    this.root = root;
    this.p = payload;
    this.opts = opts;
    this.classes = Object.fromEntries(payload.classes.map(c => [c.name, c]));
    this.findings = new Map(payload.findings.map(f => [f.id, f]));
    this.frames = payload.frames;
    this.frameIdx = 0;
    this.selected = null;
    this.drawMode = null; // null | "redraw" | "add"
    this.showRejected = opts.showRejected ?? true;
    this.filter = opts.filter || (() => true);
    this.build();
  }

  color(name) { return (this.classes[name] || {}).color || "#888"; }
  label(name) { return (this.classes[name] || {}).en || name; }
  get frame() { return this.frames[this.frameIdx]; }

  build() {
    this.root.innerHTML = `
      <div class="viewer"><div class="stage" style="position:relative;margin:0 auto">
        <img alt="Inspection frame">
        <svg class="overlay" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg"></svg>
      </div></div>
      <div class="viewer-bar"><span class="fl"></span><span class="fr"></span></div>
      <div class="thumbs" role="listbox" aria-label="Frames"></div>`;
    this.stage = this.root.querySelector(".stage");
    this.img = this.root.querySelector("img");
    this.svg = this.root.querySelector("svg");
    this.bar = this.root.querySelector(".fl");
    this.barR = this.root.querySelector(".fr");
    this.thumbs = this.root.querySelector(".thumbs");
    this.renderThumbs();
    this.bindDraw();
    window.addEventListener("resize", () => this.fit());
    if (this.frames.length) this.showFrame(0);
  }

  renderThumbs() {
    this.thumbs.innerHTML = "";
    this.frames.forEach((fr, i) => {
      const n = fr.findings.filter(id => this.visible(this.findings.get(id))).length;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "thumb" + (i === this.frameIdx ? " active" : "");
      b.title = fr.label;
      b.innerHTML = `<img loading="lazy" alt=""><span class="n ${n ? "" : "zero"}">${n}</span>`;
      b.querySelector("img").src = fr.url;
      b.onclick = () => this.showFrame(i);
      this.thumbs.appendChild(b);
    });
    this.thumbs.style.display = this.frames.length > 1 ? "" : "none";
  }

  visible(f) {
    if (!f) return false;
    if (!this.showRejected && f.status === "rejected") return false;
    return this.filter(f);
  }

  fit() {
    const fr = this.frame;
    if (!fr) return;
    const w = fr.w || this.img.naturalWidth || 1, h = fr.h || this.img.naturalHeight || 1;
    this.stage.style.aspectRatio = `${w} / ${h}`;
    this.stage.style.width = `min(100%, calc(70vh * ${w / h}))`;
    this.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.W = w; this.H = h;
  }

  showFrame(i) {
    if (i < 0 || i >= this.frames.length) return;
    this.frameIdx = i;
    const fr = this.frame;
    this.img.src = fr.url;
    this.fit();
    this.thumbs.querySelectorAll(".thumb").forEach((t, j) => t.classList.toggle("active", j === i));
    this.thumbs.children[i]?.scrollIntoView({ block: "nearest", inline: "nearest" });
    const kind = fr.kind === "video" ? "Video frame" : "Image";
    this.bar.textContent = `${kind} ${i + 1} of ${this.frames.length} · ${fr.label}`;
    this.draw();
    this.opts.onFrame?.(fr);
  }

  showFinding(id) {
    const f = this.findings.get(id);
    if (!f) return;
    const i = this.frames.findIndex(fr => fr.id === f.frame_id);
    this.selected = id;
    if (i !== this.frameIdx) this.showFrame(i); else this.draw();
  }

  upsert(f) {
    const isNew = !this.findings.has(f.id);
    this.findings.set(f.id, f);
    if (isNew) this.frames.find(fr => fr.id === f.frame_id)?.findings.push(f.id);
    this.renderThumbs();
    this.draw();
  }

  draw() {
    const fr = this.frame;
    if (!fr) return;
    const W = this.W, H = this.H, fs = Math.max(12, Math.round(Math.min(W, H) / 42));
    const ns = "http://www.w3.org/2000/svg";
    this.svg.innerHTML = "";
    const ids = fr.findings.filter(id => this.visible(this.findings.get(id)));
    // draw selected last so it sits on top
    ids.sort((a, b) => (a === this.selected) - (b === this.selected));
    let shown = 0;
    ids.forEach(id => {
      const f = this.findings.get(id);
      const [x1, y1, x2, y2] = f.box;
      const col = this.color(f.class_name);
      const g = document.createElementNS(ns, "g");
      const r = document.createElementNS(ns, "rect");
      r.setAttribute("x", x1 * W); r.setAttribute("y", y1 * H);
      r.setAttribute("width", (x2 - x1) * W); r.setAttribute("height", (y2 - y1) * H);
      r.setAttribute("stroke", col);
      r.setAttribute("class", `box ${f.status} src-${f.source}` + (this.selected === id ? " sel" : "") +
        (this.selected && this.selected !== id ? " dim" : ""));
      r.addEventListener("click", e => { if (this.drawMode) return; e.stopPropagation(); this.selected = id; this.draw(); this.opts.onSelect?.(id); });
      const title = document.createElementNS(ns, "title");
      title.textContent = `${f.code} · ${this.label(f.class_name)} · ${f.confidence != null ? Math.round(f.confidence * 100) + "%" : "manual"} · ${f.status}`;
      r.appendChild(title);
      g.appendChild(r);
      if (!this.selected || this.selected === id) {
        const txt = `${f.code.replace("F-", "#")} ${this.label(f.class_name)}${f.confidence != null ? " " + f.confidence.toFixed(2) : ""}`;
        const tw = txt.length * fs * 0.56 + fs * 0.8, th = fs * 1.5;
        let ty = y1 * H - th - 2; if (ty < 0) ty = y1 * H + 2;
        const tg = document.createElementNS(ns, "g"); tg.setAttribute("class", "tag");
        const tr = document.createElementNS(ns, "rect");
        tr.setAttribute("x", x1 * W); tr.setAttribute("y", ty); tr.setAttribute("width", tw); tr.setAttribute("height", th);
        tr.setAttribute("fill", col); tr.setAttribute("rx", 2);
        const tt = document.createElementNS(ns, "text");
        tt.setAttribute("x", x1 * W + fs * 0.4); tt.setAttribute("y", ty + th * 0.72);
        tt.setAttribute("style", `font-size:${fs}px`);
        tt.textContent = txt;
        tg.append(tr, tt); g.appendChild(tg);
      }
      this.svg.appendChild(g);
      shown++;
    });
    this.barR.textContent = shown ? `${shown} finding${shown > 1 ? "s" : ""} on this ${fr.kind === "video" ? "frame" : "image"}` : "No findings on this frame";
    if (this.draft) this.svg.appendChild(this.draft);
  }

  // ---- box drawing ----
  setDrawMode(mode) {
    this.drawMode = mode;
    this.root.querySelector(".viewer").classList.toggle("drawing", !!mode);
    if (!mode && this.draft) { this.draft.remove(); this.draft = null; }
  }

  bindDraw() {
    const pt = e => {
      const r = this.svg.getBoundingClientRect();
      return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
    };
    let start = null;
    this.svg.addEventListener("pointerdown", e => {
      if (!this.drawMode) { if (e.target === this.svg) { this.selected = null; this.draw(); this.opts.onSelect?.(null); } return; }
      e.preventDefault();
      this.svg.setPointerCapture(e.pointerId);
      start = pt(e);
      this.draft = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      this.draft.setAttribute("class", "draft");
      this.svg.appendChild(this.draft);
    });
    this.svg.addEventListener("pointermove", e => {
      if (!start || !this.draft) return;
      const [x, y] = pt(e);
      this.draft.setAttribute("x", Math.min(x, start[0]) * this.W);
      this.draft.setAttribute("y", Math.min(y, start[1]) * this.H);
      this.draft.setAttribute("width", Math.abs(x - start[0]) * this.W);
      this.draft.setAttribute("height", Math.abs(y - start[1]) * this.H);
    });
    this.svg.addEventListener("pointerup", e => {
      if (!start) return;
      const [x, y] = pt(e);
      const box = [Math.min(x, start[0]), Math.min(y, start[1]), Math.max(x, start[0]), Math.max(y, start[1])];
      start = null;
      const mode = this.drawMode;
      if (box[2] - box[0] < 0.005 || box[3] - box[1] < 0.005) { this.draft?.remove(); this.draft = null; return; }
      this.opts.onBox?.(mode, box, this.frame);
    });
  }
}
window.Viewer = Viewer;
