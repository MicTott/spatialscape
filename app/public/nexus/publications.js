/* Publications page: year / venue / region facets, keyword search, URL state. */
(async function () {
  const pubs = (await (await fetch("publications.json")).json()).publications;
  const KEYS = ["year", "venue", "region"];
  const q = document.getElementById("q");
  const list = document.getElementById("list");
  const countEl = document.getElementById("count");
  const chipsEl = document.getElementById("chips");
  const emptyEl = document.getElementById("empty");
  const state = { q: "", year: new Set(), venue: new Set(), region: new Set() };
  const params = new URLSearchParams(location.search);
  state.q = params.get("q") || "";
  for (const k of KEYS) for (const v of (params.get(k) || "").split("|").filter(Boolean)) state[k].add(v);
  q.value = state.q;
  const vals = (p, k) => (k === "region" ? p.region.split(";").map((s) => s.trim()) : [String(p[k])]);
  const text = (p) => [p.title, p.authors, p.venue, p.year, p.region, p.summary, ...(p.datasets || []).map((d) => d.name)].join(" ").toLowerCase();
  function matches(p, ignore) {
    const words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.every((w) => text(p).includes(w))) return false;
    for (const k of KEYS) if (k !== ignore && state[k].size && !vals(p, k).some((v) => state[k].has(v))) return false;
    return true;
  }
  function writeUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    for (const k of KEYS) if (state[k].size) p.set(k, [...state[k]].join("|"));
    history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
  }
  function renderFacets() {
    for (const k of KEYS) {
      const box = document.querySelector(`.facet[data-key="${k}"]`);
      const all = [...new Set(pubs.flatMap((p) => vals(p, k)))].sort((a, b) => (k === "year" ? Number(b) - Number(a) : a.localeCompare(b)));
      const counts = {};
      for (const p of pubs) if (matches(p, k)) for (const v of vals(p, k)) counts[v] = (counts[v] || 0) + 1;
      box.querySelectorAll("label").forEach((n) => n.remove());
      for (const v of all) {
        const n = counts[v] || 0;
        const on = state[k].has(v);
        const lab = document.createElement("label");
        lab.className = "opt" + (n === 0 && !on ? " zero" : "");
        lab.innerHTML = `<input type="checkbox" ${on ? "checked" : ""}><span class="name">${v}</span><span class="n">${n}</span>`;
        lab.querySelector("input").addEventListener("change", (e) => {
          e.target.checked ? state[k].add(v) : state[k].delete(v);
          update();
        });
        box.appendChild(lab);
      }
    }
  }
  const icon = (via) => ({ Globus: "⇄", S3: "☁", Bioconductor: "⬢" })[via] || "↓";
  function item(p) {
    const doi = p.doi ? `<a class="doi" href="https://doi.org/${p.doi}" target="_blank" rel="noreferrer">doi:${p.doi}</a>` : "";
    const ds = (p.datasets || []).map((d) => `<a class="pill ${d.live ? "red" : ""}" href="${d.url}">${d.live ? "▶ " : ""}${d.name}</a>`).join("");
    const dl = (p.downloads || []).map((d) => `<a class="dl" href="${d.href}" title="via ${d.via}"><span class="via">${icon(d.via)} ${d.via}</span><span class="lab">${d.label}</span><span class="size">${d.size}</span></a>`).join("");
    const code = (p.code || []).map((c) => `<a class="code" href="${c.href}" target="_blank" rel="noreferrer">⌥ ${c.label}</a>`).join("");
    const acc = (p.accessions || []).map((c) => `<a class="code" href="${c.href}" target="_blank" rel="noreferrer">${c.label}</a>`).join("");
    return `<article class="pubitem">
      <div class="pub-main">
        <div class="venue">${p.venue} · ${p.year}</div>
        <h3>${p.title}</h3>
        <p class="authors">${p.authors}</p>
        <p class="summary">${p.summary}</p>
        <div class="pub-links">${doi}${code}${acc}</div>
      </div>
      <div class="pub-side">
        <h4>Datasets</h4><div class="pills">${ds || '<span class="muted">—</span>'}</div>
        <h4>Downloads</h4><div class="dls">${dl || '<span class="muted">—</span>'}</div>
      </div></article>`;
  }
  function renderChips() {
    const chips = [];
    if (state.q) chips.push(["q", state.q, `“${state.q}”`]);
    for (const k of KEYS) for (const v of state[k]) chips.push([k, v, v]);
    chipsEl.innerHTML = chips.map(([k, v, l]) => `<button class="chip" data-k="${k}" data-v="${v}">${l} <span>×</span></button>`).join("");
    chipsEl.querySelectorAll(".chip").forEach((b) =>
      b.addEventListener("click", () => {
        if (b.dataset.k === "q") (state.q = ""), (q.value = "");
        else state[b.dataset.k].delete(b.dataset.v);
        update();
      }),
    );
  }
  function update() {
    const rows = pubs.filter((p) => matches(p)).sort((a, b) => b.year - a.year);
    list.innerHTML = rows.map(item).join("");
    emptyEl.hidden = rows.length > 0;
    countEl.textContent = `${rows.length} of ${pubs.length} publications`;
    renderFacets();
    renderChips();
    writeUrl();
  }
  let t;
  q.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => ((state.q = q.value.trim()), update()), 120);
  });
  document.getElementById("clear").addEventListener("click", () => {
    state.q = "";
    q.value = "";
    for (const k of KEYS) state[k].clear();
    update();
  });
  update();
})();
