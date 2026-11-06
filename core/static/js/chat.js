// Chat UI shared by the inspection "Ask Ain" tab and the Live detection page.
window.AinChat = (() => {
  const AR = /[؀-ۿ]/;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");

  // Minimal, safe markdown: paragraphs, bullet / numbered lists, **bold**, `code`.
  function format(text) {
    const out = [];
    let list = null;
    String(text || "").split(/\n/).forEach(raw => {
      const line = raw.trim();
      const m = line.match(/^([-*•]|\d+[.)])\s+(.*)$/);
      if (m) {
        const tag = /\d/.test(m[1]) ? "ol" : "ul";
        if (!list || list.tag !== tag) { if (list) out.push(`</${list.tag}>`); list = { tag }; out.push(`<${tag}>`); }
        out.push(`<li>${inline(m[2])}</li>`);
        return;
      }
      if (list) { out.push(`</${list.tag}>`); list = null; }
      if (line) out.push(`<p>${inline(line.replace(/^#+\s*/, ""))}</p>`);
    });
    if (list) out.push(`</${list.tag}>`);
    return out.join("");
  }

  function render(el, text) {
    el.innerHTML = format(text);
    el.setAttribute("dir", AR.test(text) ? "rtl" : "ltr");
  }

  function addMsg(log, role, text, who, chip, error) {
    log.querySelector("#hello")?.remove();
    const d = document.createElement("div");
    d.className = `msg ${role}` + (error ? " error" : "");
    d.innerHTML = `<div class="who"></div><div class="body"></div>`;
    d.querySelector(".who").textContent = who;
    if (chip) d.querySelector(".who").insertAdjacentHTML("beforeend", `<span class="chip">${esc(chip)}</span>`);
    if (text === null) d.querySelector(".body").innerHTML = `<span class="typing"><span></span><span></span><span></span></span>`;
    else render(d.querySelector(".body"), text);
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  /** opts: {log, form, input, button, suggest, me, ask: async (question) => ({answer, mode}), chip: () => string|null} */
  function mount(opts) {
    const { log, form, input, button } = opts;
    log.querySelectorAll(".body[data-raw]").forEach(b => render(b, b.dataset.raw));
    log.scrollTop = log.scrollHeight;
    const grow = () => { input.style.height = "auto"; input.style.height = Math.min(160, input.scrollHeight) + "px"; };
    input.addEventListener("input", grow);
    input.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
    async function send(q) {
      q = (q || "").trim();
      if (!q || button.disabled) return;
      const chip = opts.chip ? opts.chip() : null;
      addMsg(log, "user", q, opts.me, chip);
      input.value = ""; grow(); button.disabled = true;
      const wait = addMsg(log, "assistant", null, "Ain Assistant");
      try {
        const r = await opts.ask(q);
        wait.remove();
        addMsg(log, "assistant", r.answer, "Ain Assistant", chip, r.mode === "error");
      } catch (e) {
        wait.remove();
        addMsg(log, "assistant", e.message, "Ain Assistant", null, true);
      }
      button.disabled = false; input.focus();
    }
    form.addEventListener("submit", e => { e.preventDefault(); send(input.value); });
    opts.suggest?.querySelectorAll("button").forEach(b => b.onclick = () => send(b.textContent));
    return { send };
  }

  // Inspection page
  function init(cfg) {
    let focus = cfg.focus;
    const chipBox = document.getElementById("focus"), list = document.getElementById("flist");
    const setFocus = f => {
      focus = f;
      chipBox.hidden = !f;
      if (f) document.getElementById("focus-code").textContent = f.code;
      list?.querySelectorAll("button").forEach(b => b.classList.toggle("on", f && +b.dataset.id === f.id));
    };
    list?.querySelectorAll("button").forEach(b => b.onclick = () => {
      setFocus(focus && focus.id === +b.dataset.id ? null : { id: +b.dataset.id, code: b.dataset.code });
      document.getElementById("q").focus();
    });
    document.getElementById("focus-clear").onclick = () => setFocus(null);
    mount({
      log: document.getElementById("log"), form: document.getElementById("chat-form"),
      input: document.getElementById("q"), button: document.getElementById("send"),
      suggest: document.getElementById("suggest"), me: cfg.me,
      chip: () => focus ? focus.code : null,
      ask: q => Ain.post(cfg.askUrl, { question: q, finding_id: focus ? focus.id : null }),
    });
  }

  return { format, mount, init, addMsg };
})();
