import { useState } from "react";
import { store } from "../store/store";
import { thumbnailUrl, useRegistry, type RegistryEntry } from "./registry";
export { resolveDataset } from "./registry";

const PLATFORM_LABEL: Record<string, string> = { visium: "Visium", visium_hd: "Visium HD", xenium: "Xenium", merfish: "MERFISH", snrnaseq: "snRNA-seq" };

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
        <h1>spatialscape</h1>
        <p>{reg?.intro ?? "A static, reactive browser for spatial transcriptomics and snRNA-seq."}</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            go(url);
          }}
        >
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="open any bundle: https://host/path/to/bundle  or  http://127.0.0.1:8787/amygdala" />
          <button type="submit">Open</button>
        </form>
      </header>
      {reg && (
        <section className="cards">
          {reg.datasets.map((d) => {
            const openable = !!d.url;
            return (
              <article key={d.id} className={`card ${openable ? "" : "soon"}`} style={{ ["--accent" as any]: d.accent ?? "#40c4ff" }} onClick={() => openable && go(d.url)}>
                <div className="card-art">
                  <CardArt d={d} />
                  <span className={`status ${d.status.replace(" ", "-")}`}>{d.status}</span>
                </div>
                <div className="card-body">
                  <h2>{d.name}</h2>
                  <p>{d.description}</p>
                  <div className="meta">
                    {d.platforms.map((p) => (
                      <span key={p} className="pill">
                        {PLATFORM_LABEL[p] ?? p}
                      </span>
                    ))}
                  </div>
                  <div className="nums">
                    <span>
                      <b>{d.samples}</b> samples
                    </span>
                    <span>
                      <b>{d.cells.toLocaleString()}</b> cells
                    </span>
                    {d.genes != null && (
                      <span>
                        <b>{d.genes.toLocaleString()}</b> genes
                      </span>
                    )}
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
          })}
        </section>
      )}
      <footer className="gallery-foot muted">
        Datasets are static bundles built with <code>spatialscape build</code>; the registry is <code>datasets.json</code> next to the app. Share any view by copying the URL.
      </footer>
    </div>
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
