// Live detection: camera, streamed video, single image.
(() => {
  const CLS = Object.fromEntries(window.LIVE.classes.map(c => [c.name, c]));
  const color = n => (CLS[n] || {}).color || "#888";
  const label = n => (CLS[n] || {}).en || n;
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- shared state & side panel ----------
  const confEl = $("conf"), confOut = $("conf-out");
  const conf = () => Number(confEl.value);
  let mode = "camera";
  let session = {};

  function showStats({ count, ms, fps, fpsLabel }) {
    $("st-count").textContent = count ?? 0;
    $("st-ms").textContent = ms != null ? Math.round(ms) : "–";
    $("st-fps").textContent = fps != null ? fps.toFixed(1) : "–";
    $("st-fps-l").textContent = fpsLabel || "Frames / s";
  }
  function showDets(dets) {
    const el = $("det-list");
    if (!dets.length) { el.innerHTML = `<div class="empty small">Nothing detected${conf() > 0.5 ? " — try a lower threshold" : ""}.</div>`; return; }
    const TAG = { confirmed: ["VLM confirms", "vlm-confirmed"], relabeled: ["VLM: other type", "vlm-relabeled"],
                  rejected: ["VLM disagrees", "vlm-rejected"], added: ["Found by VLM", "vlm-added"] };
    const sc = d => d.fused != null ? d.fused : (d.confidence || 0);
    el.innerHTML = [...dets].sort((a, b) => sc(b) - sc(a)).map(d => `
      <div class="det"${d.vlm_reason ? ` title="${esc(d.vlm_reason)}"` : ""}><span class="cls"><span class="dot" style="background:${color(d.class_name)}"></span>${esc(label(d.class_name))}${d.vlm_verdict ? ` <span class="badge ${TAG[d.vlm_verdict][1]}">${TAG[d.vlm_verdict][0]}</span>` : ""}</span>
        <span class="bar"><span style="width:${Math.round(sc(d) * 100)}%;background:${color(d.class_name)}"></span></span>
        <b class="num">${Math.round(sc(d) * 100)}%</b></div>`).join("") +
      (dets.some(d => d.fused != null) ? `<div class="small muted" style="padding:8px 18px">Score = combined YOLO + VLM. Hover a row to see the VLM's reason.</div>` : "");
  }
  function addSession(dets) { dets.forEach(d => session[d.class_name] = (session[d.class_name] || 0) + 1); renderSession(session); }
  function renderSession(counts) {
    document.querySelectorAll(".sess-row").forEach(r => r.querySelector("b").textContent = counts[r.dataset.cls] || 0);
    Object.keys(counts).filter(k => !document.querySelector(`.sess-row[data-cls="${CSS.escape(k)}"]`)).forEach(k => {
      $("session").insertAdjacentHTML("afterbegin", `<div class="sess-row" data-cls="${esc(k)}"><span class="cls"><span class="dot" style="background:${color(k)}"></span>${esc(label(k))}</span><b class="num">${counts[k]}</b></div>`);
    });
  }
  $("reset-counts").onclick = () => { session = {}; renderSession(session); };

  function drawBoxes(ctx, dets, W, H, scale = 1) {
    const lw = Math.max(2, Math.round(Math.min(W, H) / 260)) * scale;
    const fs = Math.max(12, Math.round(Math.min(W, H) / 38)) * scale;
    ctx.lineWidth = lw;
    ctx.font = `600 ${fs}px Barlow, system-ui, sans-serif`;
    dets.forEach(d => {
      const [x1, y1, x2, y2] = d.box;
      const rej = d.vlm_verdict === "rejected", add = d.vlm_verdict === "added";
      const c = rej ? "#8a97a3" : add ? "#6250d6" : color(d.class_name);
      ctx.strokeStyle = c;
      ctx.setLineDash(rej || add ? [lw * 3, lw * 2] : []);
      ctx.strokeRect(x1 * W, y1 * H, (x2 - x1) * W, (y2 - y1) * H);
      ctx.setLineDash([]);
      const score = d.fused != null ? d.fused : d.confidence;
      const t = `${d.class_name} ${score != null ? score.toFixed(2) : ""}${rej ? " ✗" : add ? " +VLM" : d.vlm_verdict ? " ✓" : ""}`;
      const tw = ctx.measureText(t).width + fs * 0.6, th = fs * 1.45;
      let ty = y1 * H - th; if (ty < 0) ty = y1 * H;
      ctx.fillStyle = c; ctx.fillRect(x1 * W - lw / 2, ty, tw, th);
      ctx.fillStyle = "#fff"; ctx.fillText(t, x1 * W + fs * 0.3 - lw / 2, ty + th * 0.74);
    });
  }

  async function detectBlob(blob) {
    const fd = new FormData();
    fd.append("image", blob, "frame.jpg");
    fd.append("conf", conf());
    const r = await fetch("/live/detect", { method: "POST", body: fd, headers: { "X-CSRFToken": Ain.csrf() } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `Detection failed (${r.status})`);
    return data;
  }

  function download(canvas, name) {
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `${name}_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.png`;
    a.click();
  }

  // ---------- mode switching ----------
  document.querySelectorAll(".seg button").forEach(b => b.onclick = () => setMode(b.dataset.mode));
  function setMode(m, rerun = true) {
    if (m === mode) return;
    if (mode === "camera") cam.stop();
    if (mode === "video") vid.stop();
    mode = m;
    document.querySelectorAll(".seg button").forEach(b => b.setAttribute("aria-selected", b.dataset.mode === m));
    document.querySelectorAll(".mode").forEach(p => p.hidden = p.dataset.pane !== m);
    showStats({}); showDets([]); session = {}; renderSession(session);
    if (rerun && m === "image" && img.file) img.run();
  }

  // ---------- camera ----------
  const cam = (() => {
    const video = $("cam-video"), overlay = $("cam-overlay"), sel = $("cam-select");
    const grab = document.createElement("canvas");
    let stream = null, running = false, last = [], times = [];

    async function listCams() {
      try {
        const devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
        const cur = sel.value;
        sel.innerHTML = `<option value="">Default camera</option>` + devs.map((d, i) => `<option value="${esc(d.deviceId)}">${esc(d.label || `Camera ${i + 1}`)}</option>`).join("");
        sel.value = cur;
      } catch (e) { /* ignore */ }
    }

    async function start() {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        Ain.toast("The browser only allows the camera on https:// or http://localhost. Open the app at http://127.0.0.1:5000 on this computer.", "error");
        return;
      }
      stop();
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: sel.value ? { deviceId: { exact: sel.value } } : { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
      } catch (e) {
        Ain.toast(e.name === "NotAllowedError" ? "Camera access was blocked. Allow it in the browser's address bar, then try again."
          : e.name === "NotFoundError" ? "No camera was found on this device." : `Couldn't start the camera: ${e.message}`, "error");
        return;
      }
      video.srcObject = stream;
      await video.play();
      listCams();
      running = true; times = []; last = [];
      $("cam-empty").hidden = true; $("cam-live").hidden = false;
      $("cam-start").disabled = true; $("cam-stop").disabled = false; $("cam-snap").disabled = false;
      $("cam-vlm").disabled = !window.LIVE.ai.configured;
      loop();
    }

    function stop() {
      running = false;
      stream?.getTracks().forEach(t => t.stop());
      stream = null; video.srcObject = null; last = [];
      overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);
      $("cam-empty").hidden = false; $("cam-live").hidden = true;
      $("cam-start").disabled = false; $("cam-stop").disabled = true; $("cam-snap").disabled = true; $("cam-vlm").disabled = true;
    }

    function paint() {
      const r = video.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      if (overlay.width !== Math.round(r.width * dpr) || overlay.height !== Math.round(r.height * dpr)) {
        overlay.width = Math.round(r.width * dpr); overlay.height = Math.round(r.height * dpr);
      }
      const ctx = overlay.getContext("2d");
      ctx.clearRect(0, 0, overlay.width, overlay.height);
      drawBoxes(ctx, last, overlay.width, overlay.height);
    }

    async function loop() {
      while (running) {
        if (!video.videoWidth) { await new Promise(r => setTimeout(r, 100)); continue; }
        const k = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
        grab.width = Math.round(video.videoWidth * k); grab.height = Math.round(video.videoHeight * k);
        grab.getContext("2d").drawImage(video, 0, 0, grab.width, grab.height);
        const blob = await new Promise(r => grab.toBlob(r, "image/jpeg", 0.8));
        try {
          const res = await detectBlob(blob);
          if (!running) break;
          last = res.detections;
          const now = performance.now();
          times.push(now); times = times.filter(t => now - t < 2000);
          showStats({ count: last.length, ms: res.ms, fps: times.length / 2, fpsLabel: "Detections / s" });
          showDets(last); addSession(last); paint();
        } catch (e) {
          Ain.toast(e.message, "error"); await new Promise(r => setTimeout(r, 1500));
        }
      }
    }

    function snap() {
      const c = document.createElement("canvas");
      c.width = video.videoWidth; c.height = video.videoHeight;
      const ctx = c.getContext("2d");
      ctx.drawImage(video, 0, 0);
      drawBoxes(ctx, last, c.width, c.height);
      download(c, "ain_camera");
    }

    $("cam-vlm").onclick = () => {
      const c = document.createElement("canvas");
      c.width = video.videoWidth; c.height = video.videoHeight;
      c.getContext("2d").drawImage(video, 0, 0);
      c.toBlob(b => sendToImage(b, "Camera frame"), "image/jpeg", 0.92);
    };
    $("cam-start").onclick = start;
    $("cam-stop").onclick = stop;
    $("cam-snap").onclick = snap;
    sel.onchange = () => { if (running) start(); };
    window.addEventListener("resize", () => running && paint());
    listCams();
    return { stop };
  })();

  // ---------- video ----------
  const vid = (() => {
    const imgEl = $("vid-stream");
    let token = null, timer = null, info = null, lastProcessed = 0, lastT = 0;

    function upload(file) {
      if (!/\.(mp4|mov|avi|mkv)$/i.test(file.name)) { Ain.toast("Upload an MP4, MOV, AVI or MKV video.", "error"); return; }
      stop();
      const fd = new FormData(); fd.append("video", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/live/video");
      xhr.setRequestHeader("X-CSRFToken", Ain.csrf());
      $("vid-upload").hidden = false; $("vid-upload-msg").textContent = `Uploading ${file.name}…`;
      xhr.upload.onprogress = e => { if (e.lengthComputable) $("vid-upload-bar").style.width = (e.loaded / e.total * 100) + "%"; };
      xhr.onload = () => {
        $("vid-upload").hidden = true;
        let data = {}; try { data = JSON.parse(xhr.responseText); } catch (e) { /* */ }
        if (xhr.status !== 200) { Ain.toast(data.error || "Upload failed.", "error"); return; }
        token = data.token; info = { ...data, name: file.name };
        $("vid-name").textContent = `${file.name}${data.duration ? ` · ${data.duration} s at ${data.fps} fps` : ""}`;
        play();
      };
      xhr.onerror = () => { $("vid-upload").hidden = true; Ain.toast("Upload failed. Check the connection and try again.", "error"); };
      xhr.send(fd);
    }

    async function settings(body) {
      if (!token) return;
      try { await Ain.post(`/live/video/${token}/settings`, body); } catch (e) { /* session may have expired */ }
    }

    async function play() {
      if (!token) return;
      await settings({ conf: conf(), realtime: $("vid-realtime").checked });
      $("vid-stage").hidden = false; $("vid-timeline").hidden = false; $("vid-drop").hidden = true;
      $("vid-live").hidden = false; $("vid-live").textContent = "Live";
      imgEl.src = `/live/video/${token}/stream?t=${Date.now()}`;
      ["vid-replay", "vid-stop", "vid-snap"].forEach(id => $(id).disabled = false);
      $("vid-vlm").disabled = !window.LIVE.ai.configured;
      lastProcessed = 0; lastT = performance.now();
      clearInterval(timer); timer = setInterval(poll, 400);
    }

    async function poll() {
      if (!token) return;
      let s;
      try { s = await fetch(`/live/video/${token}/stats`).then(r => r.json()); } catch (e) { return; }
      const now = performance.now(), fps = (s.processed - lastProcessed) / ((now - lastT) / 1000);
      lastProcessed = s.processed; lastT = now;
      showStats({ count: s.detections.length, ms: s.ms, fps: Math.max(0, fps), fpsLabel: "Frames analyzed / s" });
      showDets(s.detections);
      renderSession(s.counts);
      if (s.total) $("vid-bar").style.width = Math.min(100, (s.frame + 1) / s.total * 100) + "%";
      $("vid-time").textContent = s.time != null ? `${s.time.toFixed(1)} s${info?.duration ? ` / ${info.duration} s` : ""}` : "";
      if (s.done && s.processed) { clearInterval(timer); $("vid-live").textContent = "Finished"; }
    }

    function stop() {
      clearInterval(timer);
      if (token) settings({ stop: true });
      imgEl.removeAttribute("src");
      $("vid-live").hidden = true;
      $("vid-stop").disabled = true;
    }

    function snap() {
      if (!imgEl.naturalWidth) return;
      const c = document.createElement("canvas");
      c.width = imgEl.naturalWidth; c.height = imgEl.naturalHeight;
      c.getContext("2d").drawImage(imgEl, 0, 0);
      download(c, "ain_video");
    }

    const drop = $("vid-drop"), input = $("vid-file");
    input.onchange = () => input.files[0] && upload(input.files[0]);
    ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
    $("vid-replay").onclick = play;
    $("vid-stop").onclick = stop;
    $("vid-snap").onclick = snap;
    $("vid-vlm").onclick = () => {
      if (!imgEl.naturalWidth) return;
      const c = document.createElement("canvas");
      c.width = imgEl.naturalWidth; c.height = imgEl.naturalHeight;
      c.getContext("2d").drawImage(imgEl, 0, 0);
      Ain.toast("The VLM sees the frame with YOLO's boxes drawn on it. For a clean check, upload the original photo in the Image tab.", "info");
      c.toBlob(b => sendToImage(b, `Video frame at ${$("vid-time").textContent.split(" /")[0]}`), "image/jpeg", 0.92);
    };
    $("vid-realtime").onchange = () => settings({ realtime: $("vid-realtime").checked });
    window.addEventListener("beforeunload", () => token && stop());
    return {
      stop,
      conf: () => settings({ conf: conf() }),
      newFile: () => { stop(); token = null; $("vid-drop").hidden = false; $("vid-stage").hidden = true; $("vid-timeline").hidden = true; input.value = ""; input.click(); },
    };
  })();

  // ---------- image ----------
  const img = (() => {
    const canvas = $("img-canvas"), input = $("img-file"), drop = $("img-drop");
    const state = { file: null, bitmap: null, dets: [] };

    async function load(file, autoVlm = false) {
      if (!/^image\//.test(file.type) && !/\.(jpe?g|png|bmp|webp)$/i.test(file.name || "")) { Ain.toast("Choose a JPG, PNG, BMP or WEBP image.", "error"); return; }
      state.file = file;
      try { state.bitmap = await createImageBitmap(file); } catch (e) { Ain.toast("That image couldn't be read.", "error"); return; }
      $("img-name").textContent = file.name;
      drop.hidden = true; $("img-stage").hidden = false; $("img-snap").disabled = false;
      $("img-chat").hidden = false; liveHistory.length = 0; $("live-log").innerHTML = "";
      $("img-vlm").disabled = !window.LIVE.ai.configured;
      if (autoVlm) vlmCheck(); else run();
    }

    async function vlmCheck() {
      if (!state.file) return;
      const b = $("img-vlm"), txt = b.innerHTML;
      b.disabled = true; b.textContent = "Asking the VLM…";
      try {
        const fd = new FormData();
        fd.append("image", state.file, state.file.name || "frame.jpg");
        fd.append("conf", conf());
        const r = await fetch("/live/vlm", { method: "POST", body: fd, headers: { "X-CSRFToken": Ain.csrf() } });
        const res = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(res.error || `VLM check failed (${r.status})`);
        state.dets = res.detections;
        render();
        const v = res.detections.filter(d => d.vlm_verdict);
        showStats({ count: res.detections.filter(d => d.vlm_verdict !== "rejected").length, ms: res.ms, fps: null, fpsLabel: "Image size" });
        $("st-fps").textContent = `${res.width}×${res.height}`;
        showDets(state.dets);
        const ok = v.filter(d => d.vlm_verdict === "confirmed" || d.vlm_verdict === "relabeled").length,
              no = v.filter(d => d.vlm_verdict === "rejected").length, add = v.filter(d => d.vlm_verdict === "added").length;
        Ain.toast(`${res.model}: ${ok} confirmed, ${no} rejected, ${add} added.`, "success");
      } catch (e) { Ain.toast(e.message, "error"); }
      b.innerHTML = txt; b.disabled = false;
    }

    async function run() {
      if (!state.file) return;
      try {
        const res = await detectBlob(state.file);
        state.dets = res.detections;
        render();
        showStats({ count: state.dets.length, ms: res.ms, fps: null, fpsLabel: "Image size" });
        $("st-fps").textContent = `${res.width}×${res.height}`;
        showDets(state.dets); addSession(state.dets);
      } catch (e) { Ain.toast(e.message, "error"); }
    }

    function render() {
      const b = state.bitmap, k = Math.min(1, 1600 / Math.max(b.width, b.height));
      canvas.width = Math.round(b.width * k); canvas.height = Math.round(b.height * k);
      const ctx = canvas.getContext("2d");
      ctx.drawImage(b, 0, 0, canvas.width, canvas.height);
      drawBoxes(ctx, state.dets, canvas.width, canvas.height);
    }

    input.onchange = () => input.files[0] && load(input.files[0]);
    $("img-pick").onclick = () => { input.value = ""; input.click(); };
    ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => e.dataTransfer.files[0] && load(e.dataTransfer.files[0]));
    $("img-stage").addEventListener("dragover", e => e.preventDefault());
    $("img-stage").addEventListener("drop", e => { e.preventDefault(); e.dataTransfer.files[0] && load(e.dataTransfer.files[0]); });
    $("img-snap").onclick = () => download(canvas, "ain_image");
    $("img-vlm").onclick = vlmCheck;
    return { run, load, get file() { return state.file; }, get dets() { return state.dets; } };
  })();

  // chat about the image in the Image tab (history lives in the browser only)
  const liveHistory = [];
  AinChat.mount({
    log: $("live-log"), form: $("live-form"), input: $("live-q"), button: $("live-send"),
    suggest: $("live-suggest"), me: "You",
    ask: async q => {
      if (!img.file) throw new Error("Load an image first.");
      const fd = new FormData();
      fd.append("image", img.file, img.file.name || "image.jpg");
      fd.append("question", q);
      fd.append("detections", JSON.stringify(img.dets || []));
      fd.append("history", JSON.stringify(liveHistory));
      const r = await fetch("/live/chat", { method: "POST", body: fd, headers: { "X-CSRFToken": Ain.csrf() } });
      const res = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(res.error || `Request failed (${r.status})`);
      liveHistory.push({ role: "user", content: q }, { role: "assistant", content: res.answer });
      return res;
    },
  });

  function sendToImage(blob, name) {
    const file = new File([blob], `${name.replace(/[^\w-]+/g, "_")}.jpg`, { type: "image/jpeg" });
    setMode("image", false);
    $("img-name").textContent = name;
    img.load(file, true);
  }

  // ---------- threshold ----------
  let confTimer;
  const syncConf = () => confOut.textContent = conf().toFixed(2);
  confEl.addEventListener("input", () => {
    syncConf();
    clearTimeout(confTimer);
    confTimer = setTimeout(() => { if (mode === "video") vid.conf(); if (mode === "image") img.run(); }, 250);
  });
  syncConf();

  $("vid-new").onclick = () => vid.newFile();
})();
