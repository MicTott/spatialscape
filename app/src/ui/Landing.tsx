import { useState } from "react";
import { platformLabel } from "../data/manifest";
import { store } from "../store/store";
import { cardGroups, cardPills, thumbnailUrl, useRegistry, wantsOpenBox, type RegistryEntry } from "./registry";
export { resolveDataset } from "./registry";


export function Landing() {
  const [url, setUrl] = useState("");
  const reg = useRegistry();
  const go = (u: string) => {
    const clean = u.trim().replace(/\/manifest\.json$/, "");
    if (!clean) return;
    history.replaceState(null, "", `?d=${encodeURIComponent(clean)}`);
    store.getState().set({ datasetUrl: clean, datasetRef: clean, status: "idle" });
  };
  return (
    <div className="overlay landing gallery">
      <header className="gallery-head">
        <h1>{reg?.title || "spatialscape"}</h1>
        <p>{reg?.intro ?? "A static, reactive browser for spatial transcriptomics and snRNA-seq."}</p>
        {wantsOpenBox(reg) && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              go(url);
            }}
          >
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="open any bundle: https://host/path/to/bundle  or  http://127.0.0.1:8787/my_atlas" />
            <button type="submit">Open</button>
          </form>
        )}
      </header>
      {reg &&
        cardGroups(reg.datasets).map((g) => (
          <div key={g.name ?? ""} className="card-group">
            {g.name && <h2 className="card-group-title">{g.name}</h2>}
            {/* a named group of up to three cards fills the row, so a few lead examples draw larger */}
            <section className={`cards${g.name && g.items.length <= 3 ? " few" : ""}`}>
              {g.items.map((d) => (
                <Card key={d.id} d={d} open={go} />
              ))}
            </section>
          </div>
        ))}
      <footer className="gallery-foot muted">
        Datasets are static bundles built with <code>spatialscape build</code>; the gallery comes from <code>site.yaml</code> (<code>spatialscape site build</code>). Share any view by copying the URL.
      </footer>
    </div>
  );
}

const count = (n: number, one: string) => (
  <span>
    <b>{n.toLocaleString()}</b> {n === 1 ? one : `${one}s`}
  </span>
);

function Card({ d, open }: { d: RegistryEntry; open: (url: string) => void }) {
  const openable = !!d.url;
  // entries written by hand may omit keys; the card still renders
  const status = d.status ?? (openable ? "live" : "coming soon");
  return (
    <article className={`card ${openable ? "" : "soon"}`} style={{ ["--accent" as any]: d.accent ?? "#40c4ff" }} onClick={() => openable && open(d.url)}>
      <div className="card-art">
        <CardArt d={d} />
        <span className={`status ${status.replace(" ", "-")}`}>{status}</span>
      </div>
      <div className="card-body">
        <h2>{d.name}</h2>
        <p>{d.description ?? ""}</p>
        <div className="meta">
          {cardPills(d, platformLabel).map((p) => (
            <span key={p} className="pill">
              {p}
            </span>
          ))}
        </div>
        <div className="nums">
          {count(d.samples ?? 0, "sample")}
          {count(d.cells ?? 0, "cell")}
          {d.genes != null && count(d.genes, "gene")}
        </div>
        {d.paper?.title && (
          <div className="paper">
            {d.paper.url ? (
              <a href={d.paper.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                {d.paper.title}
              </a>
            ) : (
              d.paper.title
            )}
          </div>
        )}
      </div>
    </article>
  );
}

/** Real thumbnail (<bundle>/thumbnail.png, rendered by `spatialscape build`) with an abstract fallback. */
function CardArt({ d }: { d: RegistryEntry }) {
  const [failed, setFailed] = useState(false);
  const src = thumbnailUrl(d);
  if (src && !failed) return <img src={src} alt={`${d.name} example section`} onError={() => setFailed(true)} loading="lazy" />;
  return <Thumb seed={d.id} accent={d.accent ?? "#40c4ff"} />;
}

/** Deterministic abstract "tissue" placeholder for entries without a bundle yet. */
function Thumb({ seed, accent }: { seed: string; accent: string }) {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const rnd = () => {
    h = (h * 1664525 + 1013904223) >>> 0;
    return h / 4294967296;
  };
  const blobs = Array.from({ length: 9 }, () => ({ cx: 20 + rnd() * 160, cy: 15 + rnd() * 80, r: 12 + rnd() * 26, o: 0.25 + rnd() * 0.5 }));
  const dots = Array.from({ length: 160 }, () => ({ x: rnd() * 200, y: rnd() * 110, r: 0.6 + rnd() * 1.2, o: 0.2 + rnd() * 0.8 }));
  return (
    <svg viewBox="0 0 200 110" preserveAspectRatio="xMidYMid slice">
      <defs>
        <radialGradient id={`g-${seed}`}>
          <stop offset="0" stopColor={accent} stopOpacity="0.9" />
          <stop offset="1" stopColor={accent} stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="200" height="110" fill="#11151b" />
      {blobs.map((b, i) => (
        <circle key={i} cx={b.cx} cy={b.cy} r={b.r} fill={`url(#g-${seed})`} opacity={b.o} />
      ))}
      {dots.map((d, i) => (
        <circle key={i} cx={d.x} cy={d.y} r={d.r} fill="#e6edf3" opacity={d.o * 0.6} />
      ))}
    </svg>
  );
}
