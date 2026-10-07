/* Catalog page: facets + keyword search + sort, state mirrored in the URL. Vanilla JS, no build step. */
(async function () {
  const data = (await (await fetch("catalog.json")).json()).datasets;
  const KEYS = ["technologies", "species", "region", "status"];
  const q = document.getElementById("q");
  const sortEl = document.getElementById("sort");
  const cardsEl = document.getElementById("cards");
  const countEl = document.getElementById("count");
  const chipsEl = document.getElementById("chips");
  const emptyEl = document.getElementById("empty");

  // ---- state <-> URL
  const state = { q: "", sort: "newest", technologies: new Set(), species: new Set(), region: new Set(), status: new Set() };
  const params = new URLSearchParams(location.search);
  state.q = params.get("q") || "";
  state.sort = params.get("sort") || "newest";
  for (const k of KEYS) for (const v of (params.get(k) || "").split("|").filter(Boolean)) state[k].add(v);
  q.value = state.q;
  sortEl.value = state.sort;
  function writeUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.sort !== "newest") p.set("sort", state.sort);
    for (const k of KEYS) if (state[k].size) p.set(k, [...state[k]].join("|"));
    history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
  }

  // ---- matching
  const valuesOf = (d, k) => (Array.isArray(d[k]) ? d[k] : [d[k]]);
  const text = (d) => [d.name, d.description, d.region, d.species, (d.tags || []).join(" "), (d.technologies || []).join(" "), d.paper && d.paper.title, String(d.year)].join(" ").toLowerCase();
  function matches(d, ignoreKey) {
    const words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    const t = text(d);
    if (!words.every((w) => t.includes(w))) return false;
    for (const k of KEYS) {
      if (k === ignoreKey || !state[k].size) continue;
      if (!valuesOf(d, k).some((v) => state[k].has(v))) return false;
    }
    return true;
  }

  // ---- facets (counts computed with the facet's own filter ignored, so options never vanish)
  const ORDER = { technologies: ["Visium", "Visium HD", "Visium-SPG", "Xenium", "snRNA-seq"], status: ["live", "coming soon"] };
  function renderFacets() {
    for (const k of KEYS) {
      const box = document.querySelector(`.facet[data-key="${k}"]`);
      const all = [...new Set(data.flatMap((d) => valuesOf(d, k)))];
      const order = ORDER[k] || all.slice().sort((a, b) => a.localeCompare(b));
      const counts = {};
      for (const d of data) if (matches(d, k)) for (const v of valuesOf(d, k)) counts[v] = (counts[v] || 0) + 1;
      box.querySelectorAll("label").forEach((n) => n.remove());
      for (const v of order) {
        if (!all.includes(v)) continue;
        const n = counts[v] || 0;
        const on = state[k].has(v);
        const lab = document.createElement("label");
        lab.className = "opt" + (n === 0 && !on ? " zero" : "");
        lab.innerHTML = `<input type="checkbox" ${on ? "checked" : ""}><span class="name">${v}</span><span class="n">${n}</span>`;
        lab.querySelector("input").addEventListener("change", (e) => {
          if (e.target.checked) state[k].add(v);
          else state[k].delete(v);
          update();
        });
        box.appendChild(lab);
      }
    }
  }

  // ---- cards
  const fmt = (n) => (n >= 1e6 ? (n / 1e6).toFixed(2).replace(/\.?0+$/, "") + " M" : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e5 ? 0 : 1).replace(/\.0$/, "") + " k" : String(n));
  function card(d) {
    const live = d.status === "live" && d.url;
    const art = d.thumbnail ? `<img src="${d.thumbnail}" alt="${d.name} example section">` : `<div class="ph" style="--c:${d.accent || "#7b5074"}"></div>`;
    const pills = d.technologies.map((t) => `<span class="pill ${t === "snRNA-seq" ? "" : "red"}">${t}</span>`).join("");
    const paper = d.paper ? (d.paper.url ? `<a class="paper" href="${d.paper.url}" target="_blank" rel="noreferrer">${d.paper.title}</a>` : `<span class="paper">${d.paper.title}</span>`) : "";
    return `<a class="card ${live ? "" : "soon"}" href="${live ? d.url : "#"}" ${live ? "" : 'aria-disabled="true"'}>
      <div class="art">${art}<span class="badge ${live ? "" : "soon"}">${live ? "Explore" : "Coming soon"}</span><span class="region">${d.species} · ${d.region}</span></div>
      <div class="body">
        <h3>${d.name}</h3>
        <p class="desc">${d.description}</p>
        <div class="pills">${pills}</div>
        <div class="nums"><span><b>${d.samples}</b> samples</span><span><b>${fmt(d.cells)}</b> cells</span><span><b>${d.donors}</b> donors</span><span><b>${d.year}</b></span></div>
        ${paper}
      </div></a>`;
  }
  const sorters = {
    newest: (a, b) => b.year - a.year || a.name.localeCompare(b.name),
    name: (a, b) => a.name.localeCompare(b.name),
    cells: (a, b) => b.cells - a.cells,
    samples: (a, b) => b.samples - a.samples,
  };
  function renderChips() {
    const chips = [];
    if (state.q) chips.push(["q", state.q, `“${state.q}”`]);
    for (const k of KEYS) for (const v of state[k]) chips.push([k, v, v]);
    chipsEl.innerHTML = chips.map(([k, v, label]) => `<button class="chip" data-k="${k}" data-v="${v}">${label} <span>×</span></button>`).join("");
    chipsEl.querySelectorAll(".chip").forEach((b) =>
      b.addEventListener("click", () => {
        const k = b.dataset.k;
        if (k === "q") {
          state.q = "";
          q.value = "";
        } else state[k].delete(b.dataset.v);
        update();
      }),
    );
  }
  function update() {
    const rows = data.filter((d) => matches(d)).sort(sorters[state.sort] || sorters.newest);
    cardsEl.innerHTML = rows.map(card).join("");
    emptyEl.hidden = rows.length > 0;
    countEl.textContent = `${rows.length} of ${data.length} datasets`;
    renderFacets();
    renderChips();
    writeUrl();
  }

  let t;
  q.addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.q = q.value.trim();
      update();
    }, 120);
  });
  sortEl.addEventListener("change", () => {
    state.sort = sortEl.value;
    update();
  });
  document.getElementById("clear").addEventListener("click", () => {
    state.q = "";
    q.value = "";
    for (const k of KEYS) state[k].clear();
    update();
  });
  update();
})();
