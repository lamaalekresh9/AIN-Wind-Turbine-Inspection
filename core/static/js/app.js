// Shared helpers
window.Ain = (() => {
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  async function post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(body || {}),
    });
    let data = {};
    try { data = await r.json(); } catch (e) { /* non-JSON */ }
    if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
    return data;
  }

  function toast(msg, kind = "info") {
    let box = document.querySelector(".flashes");
    if (!box) {
      box = document.createElement("div");
      box.className = "flashes";
      (document.querySelector(".main") || document.body).prepend(box);
    }
    const el = document.createElement("div");
    el.className = `flash flash-${kind}`;
    el.innerHTML = `<span></span><button type="button" aria-label="Dismiss">×</button>`;
    el.querySelector("span").textContent = msg;
    el.querySelector("button").onclick = () => el.remove();
    box.appendChild(el);
    setTimeout(() => el.remove(), 6000);
  }

  // confirm() on forms with data-confirm
  document.addEventListener("submit", (e) => {
    const m = e.target.dataset.confirm;
    if (m && !window.confirm(m)) e.preventDefault();
  });

  return { post, toast, csrf };
})();
