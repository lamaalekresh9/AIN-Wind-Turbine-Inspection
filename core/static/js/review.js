// Human review: accept / reject / uncertain, edit class/severity/box, add missed defects.
(() => {
  const { payload, canEdit, updateUrl, addUrl, agreedUrl, minFused, vlmModel, assistantUrl } = window.REVIEW;
  const VLM = { confirmed: ["VLM confirms", "vlm-confirmed"], relabeled: ["VLM: other type", "vlm-relabeled"],
                rejected: ["VLM disagrees", "vlm-rejected"], added: ["Found by VLM", "vlm-added"] };
  const vlmTag = f => f.vlm_verdict ? `<span class="badge ${VLM[f.vlm_verdict][1]}" style="margin-left:6px">${VLM[f.vlm_verdict][0]}</span>` : "";
  const STATUS = {
    accepted: ["Accepted", "check"], rejected: ["Rejected", "x"],
    uncertain: ["Uncertain", "question"], pending: ["Pending", "clock"],
  };
  const SEV = { low: "Low", medium: "Medium", high: "High" };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = n => ({
    check: '<path d="M5 12.5 10 17 19 7"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>',
    question: '<path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.5v.7M12 17.5h.01"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  })[n];
  const badge = s => `<span class="badge b-${s}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">${icon(STATUS[s][1])}</svg>${STATUS[s][0]}</span>`;

  let counts = payload.counts;
  let listFilter = "all";
  let pendingNew = null; // {box, frame}

  // Show frames that have findings first, then the rest (so reviewers can add missed defects anywhere).
  const withHits = payload.frames.filter(f => f.findings.length), rest = payload.frames.filter(f => !f.findings.length);
  const viewer = new Viewer(document.getElementById("viewer"), { ...payload, frames: [...withHits, ...rest] }, {
    onSelect: id => { renderEditor(); renderList(); },
    onBox: (mode, box, frame) => onBox(mode, box, frame),
  });

  const ordered = () => [...viewer.findings.values()].sort((a, b) => {
    const fa = viewer.frames.findIndex(f => f.id === a.frame_id), fb = viewer.frames.findIndex(f => f.id === b.frame_id);
    return fa - fb || a.id - b.id;
  });
  const cls = n => viewer.classes[n] || { en: n, color: "#888" };
  const classOptions = sel => payload.classes.map(c => `<option value="${esc(c.name)}" ${c.name === sel ? "selected" : ""}>${esc(c.en)}</option>`).join("");
  const sevOptions = sel => Object.entries(SEV).map(([k, v]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${v}</option>`).join("");

  // ---------- tally & gate ----------
  const agreeable = () => [...viewer.findings.values()].filter(f => f.status === "pending" && f.source === "ai"
    && (f.vlm_verdict === "confirmed" || f.vlm_verdict === "relabeled") && (f.fused_confidence || 0) >= minFused);
  function renderTally() {
    const ab = document.getElementById("btn-agreed");
    if (ab) { const n = agreeable().length; ab.disabled = !canEdit || !n; document.getElementById("agreed-n").textContent = `(${n})`; }
    document.getElementById("tally").innerHTML = ["accepted", "rejected", "uncertain", "pending"]
      .map(s => `<div><b class="num" style="color:var(--${{ accepted: "ok", rejected: "bad", uncertain: "warn", pending: "muted" }[s]})">${counts[s] || 0}</b><span>${STATUS[s][0]}</span></div>`).join("");
    const btn = document.getElementById("btn-complete"), msg = document.getElementById("gate-msg");
    if (!btn) return;
    if (counts.pending) {
      btn.disabled = true;
      msg.innerHTML = `<b>${counts.pending} finding${counts.pending > 1 ? "s" : ""} still pending.</b> Decide every finding to unlock the report.`;
    } else {
      btn.disabled = false;
      msg.innerHTML = counts.total ? `All ${counts.total} findings decided. ${counts.accepted} will go into the Arabic report.`
        : "The model found no defects. Add any it missed, or confirm and approve with no findings.";
    }
  }

  // ---------- list ----------
  function renderList() {
    const el = document.getElementById("flist");
    const items = ordered().filter(f => listFilter === "all" || (listFilter === "disputed" ? f.vlm_verdict === "rejected" : f.status === listFilter));
    if (!items.length) { el.innerHTML = `<div class="empty small">No ${listFilter === "all" ? "" : listFilter + " "}findings.</div>`; return; }
    el.innerHTML = items.map(f => {
      const c = cls(f.class_name);
      const fr = viewer.frames.find(x => x.id === f.frame_id);
      const sub = [f.confidence != null ? `${Math.round(f.confidence * 100)}%` : (f.source === "vlm" ? "VLM" : "Manual"),
        f.fused_confidence != null ? `combined ${Math.round(f.fused_confidence * 100)}%` : "", SEV[f.severity], fr ? fr.label : ""].filter(Boolean).join(" · ");
      return `<button type="button" class="fitem ${viewer.selected === f.id ? "sel" : ""}" data-id="${f.id}">
        <span class="dot" style="background:${c.color}"></span>
        <span><span class="t1">${esc(f.code)} ${esc(c.en)}${f.edited ? ' <span class="muted small">edited</span>' : ""}${vlmTag(f)}</span><span class="t2" style="display:block">${esc(sub)}</span></span>
        ${badge(f.status)}</button>`;
    }).join("");
    el.querySelectorAll(".fitem").forEach(b => b.onclick = () => { viewer.showFinding(+b.dataset.id); renderEditor(); renderList(); });
    el.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
  }
  document.querySelectorAll("#list-filter button").forEach(b => b.onclick = () => {
    listFilter = b.dataset.f;
    document.querySelectorAll("#list-filter button").forEach(x => x.classList.toggle("btn-primary", x === b));
    renderList();
  });

  // ---------- editor ----------
  function renderEditor() {
    const title = document.getElementById("ed-title"), st = document.getElementById("ed-status"), body = document.getElementById("ed-body");
    if (pendingNew) {
      title.textContent = "New finding"; st.innerHTML = "";
      body.innerHTML = `
        <p class="small muted" style="margin-top:0">Added by you on ${esc(pendingNew.frame.label)}. Manual findings are saved as accepted.</p>
        <div class="field"><label for="n-cls">Defect type</label><select id="n-cls">${classOptions(payload.classes[0]?.name)}</select></div>
        <div class="field"><label for="n-sev">Severity</label><select id="n-sev">${sevOptions("medium")}</select></div>
        <div class="field"><label for="n-note">Note</label><textarea id="n-note" rows="2" style="min-height:60px" placeholder="Why the model missed it, size estimate, etc."></textarea></div>
        <div class="btn-row"><button class="btn btn-primary" id="n-save">Save finding</button><button class="btn btn-ghost" id="n-cancel">Cancel</button></div>`;
      document.getElementById("n-save").onclick = saveNew;
      document.getElementById("n-cancel").onclick = () => { pendingNew = null; viewer.setDrawMode(null); renderEditor(); };
      return;
    }
    const f = viewer.findings.get(viewer.selected);
    if (!f) {
      title.textContent = "Select a finding"; st.innerHTML = "";
      body.innerHTML = `<p class="muted" style="margin:0">Click a box on the image or a finding in the list.</p>`;
      return;
    }
    const c = cls(f.class_name);
    title.innerHTML = `${esc(f.code)} <span class="muted" style="font-weight:500">${esc(c.en)}</span>`;
    st.innerHTML = badge(f.status);
    const ai = f.source === "ai"
      ? `YOLO: <b>${esc(cls(f.ai_class_name).en)}</b> at <b>${Math.round(f.confidence * 100)}%</b> confidence`
      : f.source === "vlm" ? "Not detected by YOLO. The VLM found this one." : "Added manually by a reviewer";
    let vbox = "";
    if (f.vlm_verdict) {
      const what = { confirmed: `confirms the ${esc(cls(f.ai_class_name || f.class_name).en.toLowerCase())}`,
                     relabeled: `sees a defect, but thinks it is <b>${esc(cls(f.vlm_class).en)}</b>`,
                     rejected: "doesn't see a defect here", added: `found a <b>${esc(cls(f.vlm_class).en)}</b> YOLO missed` }[f.vlm_verdict];
      const useBtn = canEdit && f.vlm_verdict === "relabeled" && f.class_name !== f.vlm_class
        ? `<button class="btn btn-sm" id="e-usevlm" style="margin-top:8px">Use ${esc(cls(f.vlm_class).en)}</button>` : "";
      vbox = `<div class="vlm-box"><b>${esc(vlmModel)}</b> ${what} (${Math.round((f.vlm_confidence || 0) * 100)}% sure).
        ${f.vlm_reason ? `<div class="muted" style="margin-top:4px">“${esc(f.vlm_reason)}”</div>` : ""}
        ${f.fused_confidence != null ? `<div style="margin-top:4px">Combined score: <b>${Math.round(f.fused_confidence * 100)}%</b>${f.vlm_verdict === "rejected" && f.fused_confidence < minFused ? ' <span class="badge vlm-rejected">likely false alarm</span>' : ""}</div>` : ""}${useBtn}</div>`;
    }
    const seen = f.occurrences > 1 ? `<br>Seen in ${f.occurrences} video frames` : "";
    const dis = canEdit ? "" : "disabled";
    body.innerHTML = `
      <p class="small" style="margin-top:0">${ai}${seen}${f.reviewed_by ? `<br><span class="muted">Last decision by ${esc(f.reviewed_by)}, ${esc(f.reviewed_at)}</span>` : ""}</p>
      ${vbox}
      <p class="small" style="margin:-6px 0 12px"><a href="${assistantUrl}?finding=${f.id}">Ask Ain about ${esc(f.code)} →</a></p>
      <div class="grid-2" style="gap:0 10px">
        <div class="field"><label for="e-cls">Defect type</label><select id="e-cls" ${dis}>${classOptions(f.class_name)}</select></div>
        <div class="field"><label for="e-sev">Severity</label><select id="e-sev" ${dis}>${sevOptions(f.severity)}</select></div>
      </div>
      <div class="field"><label for="e-note">Reviewer note</label><textarea id="e-note" rows="2" style="min-height:60px" ${dis} placeholder="Optional. Goes into the report.">${esc(f.reviewer_note)}</textarea></div>
      ${canEdit ? `
      <div class="decide">
        <button class="btn ${f.status === "accepted" ? "on-accepted" : ""}" data-s="accepted">Accept <span class="kbd">A</span></button>
        <button class="btn ${f.status === "rejected" ? "on-rejected" : ""}" data-s="rejected">Reject <span class="kbd">R</span></button>
        <button class="btn ${f.status === "uncertain" ? "on-uncertain" : ""}" data-s="uncertain">Unsure <span class="kbd">U</span></button>
      </div>
      <div class="btn-row" style="margin-top:10px;justify-content:space-between">
        <button class="btn btn-sm btn-ghost" id="e-save">Save edits only</button>
        ${f.status !== "pending" ? `<button class="btn btn-sm btn-ghost" id="e-reset">Reset to pending</button>` : ""}
      </div>` : ""}`;
    if (!canEdit) return;
    body.querySelectorAll(".decide button").forEach(b => b.onclick = () => decide(b.dataset.s));
    document.getElementById("e-save").onclick = () => save({});
    const r = document.getElementById("e-reset"); if (r) r.onclick = () => save({ status: "pending" });
    const u = document.getElementById("e-usevlm"); if (u) u.onclick = () => save({ class_name: f.vlm_class });
  }

  function fields() {
    return {
      class_name: document.getElementById("e-cls")?.value,
      severity: document.getElementById("e-sev")?.value,
      note: document.getElementById("e-note")?.value ?? "",
    };
  }

  async function save(extra) {
    const id = viewer.selected;
    if (!id) return;
    try {
      const r = await Ain.post(updateUrl + id, { ...fields(), ...extra });
      counts = r.counts;
      viewer.upsert(r.finding);
      renderTally(); renderEditor(); renderList();
      return r.finding;
    } catch (e) { Ain.toast(e.message, "error"); }
  }

  async function decide(status) {
    const f = await save({ status });
    if (f && status !== "pending") next(true);
  }

  function next(onlyPending, dir = 1) {
    const list = ordered();
    if (!list.length) return;
    const i = list.findIndex(f => f.id === viewer.selected);
    for (let k = 1; k <= list.length; k++) {
      const cand = list[(i + dir * k + list.length * 2) % list.length];
      if (!onlyPending || cand.status === "pending") { viewer.showFinding(cand.id); renderEditor(); renderList(); return; }
    }
    if (onlyPending) Ain.toast(counts.pending ? "Moved through all findings." : "Every finding is decided. You can confirm the findings and approve.", "success");
  }

  // ---------- drawing ----------
  const hint = document.getElementById("draw-hint");
  function startDraw(mode) {
    if (!canEdit) return;
    if (mode === "redraw" && !viewer.selected) { Ain.toast("Select a finding first, then redraw its box.", "info"); return; }
    viewer.setDrawMode(mode);
    hint.style.display = "flex";
    hint.querySelector("span").textContent = mode === "redraw"
      ? "Drag on the image to draw the corrected box."
      : "Drag on the image around the defect the model missed. Use the thumbnails to switch frames first.";
  }
  function stopDraw() { viewer.setDrawMode(null); hint.style.display = "none"; }
  document.getElementById("draw-cancel").onclick = () => { stopDraw(); pendingNew = null; renderEditor(); };
  document.getElementById("btn-redraw")?.addEventListener("click", () => startDraw("redraw"));
  document.getElementById("btn-add")?.addEventListener("click", () => startDraw("add"));

  async function onBox(mode, box, frame) {
    hint.style.display = "none";
    if (mode === "redraw") {
      viewer.setDrawMode(null);
      await save({ box });
      Ain.toast("Box updated. Accept the finding to confirm it.", "success");
    } else {
      viewer.drawMode = null;
      viewer.root.querySelector(".viewer").classList.remove("drawing");
      pendingNew = { box, frame };
      renderEditor();
      document.getElementById("n-cls")?.focus();
    }
  }

  async function saveNew() {
    try {
      const r = await Ain.post(addUrl, {
        frame_id: pendingNew.frame.id, box: pendingNew.box,
        class_name: document.getElementById("n-cls").value,
        severity: document.getElementById("n-sev").value,
        note: document.getElementById("n-note").value,
      });
      pendingNew = null;
      viewer.setDrawMode(null);
      counts = r.counts;
      viewer.upsert(r.finding);
      viewer.showFinding(r.finding.id);
      renderTally(); renderEditor(); renderList();
      Ain.toast(`${r.finding.code} added and accepted.`, "success");
    } catch (e) { Ain.toast(e.message, "error"); }
  }

  // ---------- keyboard ----------
  document.addEventListener("keydown", e => {
    if (!canEdit || e.target.matches("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "escape") { stopDraw(); pendingNew = null; renderEditor(); return; }
    if (pendingNew) return;
    if (viewer.selected && k === "a") decide("accepted");
    else if (viewer.selected && k === "r") decide("rejected");
    else if (viewer.selected && k === "u") decide("uncertain");
    else if (k === "j" || k === "arrowdown") { e.preventDefault(); next(false, 1); }
    else if (k === "k" || k === "arrowup") { e.preventDefault(); next(false, -1); }
    else if (k === "b") startDraw("redraw");
    else if (k === "n") startDraw("add");
  });

  document.getElementById("btn-agreed")?.addEventListener("click", async () => {
    const n = agreeable().length;
    if (!n || !confirm(`Accept ${n} finding${n > 1 ? "s" : ""} that YOLO and the VLM both agree on? You can still change any of them afterwards.`)) return;
    try {
      const r = await Ain.post(agreedUrl, {});
      r.findings.forEach(f => viewer.findings.set(f.id, f));
      counts = r.counts; viewer.renderThumbs(); viewer.draw();
      renderTally(); renderEditor(); renderList();
      Ain.toast(`${r.accepted} finding${r.accepted !== 1 ? "s" : ""} accepted. Review the rest one by one.`, "success");
    } catch (e) { Ain.toast(e.message, "error"); }
  });

  document.getElementById("complete-form")?.addEventListener("submit", e => {
    if (counts.pending) { e.preventDefault(); Ain.toast("Decide every pending finding first.", "error"); }
  });

  // start on the first pending finding
  const firstPending = ordered().find(f => f.status === "pending") || ordered()[0];
  if (firstPending) viewer.showFinding(firstPending.id);
  renderTally(); renderEditor(); renderList();
})();
