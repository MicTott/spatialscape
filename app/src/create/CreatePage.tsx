/** Create: a dataset from data on the machine the server runs on, in three steps. Pick an object, a store or a
 *  folder of files by browsing the server's paths; read what `init` finds in it and tick what to show; build, watch
 *  the log, open. The yaml the choices make is shown throughout and written next to the bundle: the page is
 *  `init` and `build` with buttons, and the file is what to edit afterwards. */
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { platformLabel } from "../data/manifest";
import { browse, build, fmtSize, inspect, job, ping, render, type Browse, type BrowseEntry, type Choices, type CreatePing, type EntryChoice, type EntryInfo, type Inspection, type Job } from "./api";

const PLATFORMS = ["visium", "visium_hd", "xenium", "merfish", "codex", "other"];
type Step = "source" | "review" | "build";

export function CreatePage() {
  const [info, setInfo] = useState<CreatePing | null | undefined>(undefined);
  const [step, setStep] = useState<Step>("source");
  const [picked, setPicked] = useState<string[]>([]);
  const [platform, setPlatform] = useState("");
  const [table, setTable] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ins, setIns] = useState<Inspection | null>(null);
  const [choices, setChoices] = useState<Choices>({ entries: {} });
  const [jobId, setJobId] = useState<string | null>(null);

  useEffect(() => {
    ping()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

  const read = async () => {
    setBusy("reading the data (an R object is parsed whole; about as long as loading it in R)");
    setError(null);
    try {
      const r = await inspect(picked, { platform, table });
      setIns(r);
      setChoices({ id: r.id, name: r.name, names: {}, entries: Object.fromEntries(r.entries.map((e, i) => [String(i), defaultChoice(e)])) });
      setStep("review");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const start = async () => {
    if (!ins) return;
    setError(null);
    try {
      const r = await build(ins.token, choices);
      setJobId(r.job);
      setStep("build");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (info === undefined) return <div className="overlay create">...</div>;
  if (info === null)
    return (
      <div className="overlay">
        <h2>No Create page here</h2>
        <p>
          This server only shows bundles. To make one, run <code>spatialscape create</code> in a folder on the machine that holds your data and open the address it prints.
        </p>
        <a href="./">Back to the gallery</a>
      </div>
    );
  return (
    <div className="overlay create">
      <div className="create-head">
        <h1>Create a dataset</h1>
        <div className="steps">
          {(["source", "review", "build"] as Step[]).map((s, i) => (
            <span key={s} className={s === step ? "on" : ""}>
              {i + 1}. {s === "source" ? "Choose data" : s === "review" ? "Review" : "Build"}
              {i < 2 ? " ›" : ""}
            </span>
          ))}
        </div>
        <a className="back" href="./">
          gallery
        </a>
      </div>
      <p className="create-note">
        Reading files on <b>{info.host}</b>; the dataset yaml and bundle go to <code>{info.project}</code>. Nothing is uploaded.
      </p>
      {info.guard && <div className="create-warn">{info.guard}</div>}
      {error && <div className="create-err">{error}</div>}
      {step === "source" && <SourceStep info={info} picked={picked} setPicked={setPicked} platform={platform} setPlatform={setPlatform} table={table} setTable={setTable} busy={busy} onRead={() => void read()} />}
      {step === "review" && ins && <ReviewStep ins={ins} choices={choices} setChoices={setChoices} guard={info.guard} onBack={() => setStep("source")} onBuild={() => void start()} />}
      {step === "build" && jobId && <BuildStep id={jobId} />}
    </div>
  );
}

function defaultChoice(e: EntryInfo): EntryChoice {
  return { platform: e.platform, assay: e.assay ?? undefined, layer: e.layer, embedding: e.embedding_key ?? undefined, region: e.region ?? undefined, columns: e.columns.map((c) => ({ column: c.column, id: c.id, on: c.on })), meta: [] };
}

// ---------------------------------------------------------------- 1. choose data
function SourceStep(p: { info: CreatePing; picked: string[]; setPicked: Dispatch<SetStateAction<string[]>>; platform: string; setPlatform: (v: string) => void; table: string; setTable: (v: string) => void; busy: string | null; onRead: () => void }) {
  const [dir, setDir] = useState<Browse | null>(null);
  const [typed, setTyped] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const go = (path: string | null) =>
    browse(path)
      .then((d) => {
        setDir(d);
        setTyped(d.path);
        setErr(null);
      })
      .catch((e: Error) => setErr(e.message));
  useEffect(() => {
    void go(null);
  }, []);
  const add = (path: string) => p.setPicked((prev) => (prev.includes(path) ? prev : [...prev, path]));
  const remove = (path: string) => p.setPicked((prev) => prev.filter((x) => x !== path));
  const h5ads = dir?.entries.filter((e) => e.name.endsWith(".h5ad")).length ?? 0;
  const hasStore = p.picked.some((x) => x.endsWith(".zarr"));
  return (
    <div className="create-cols">
      <div className="create-panel">
        <h2>Files on {p.info.host}</h2>
        <div className="browse-bar">
          <button onClick={() => dir?.parent && void go(dir.parent)} disabled={!dir?.parent} title="up one folder">
            ↑
          </button>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void go(typed)} spellCheck={false} />
          <button onClick={() => void go(typed)}>Go</button>
        </div>
        <div className="browse-roots">
          {dir?.roots.map((r) => (
            <button key={r.path} className="chip" onClick={() => void go(r.path)} title={r.path}>
              {r.name}
            </button>
          ))}
          {h5ads > 1 && dir && (
            <button className="chip" onClick={() => add(`${dir.path}/*.h5ad`)} title="one sample per file">
              use all {h5ads} .h5ad files here
            </button>
          )}
        </div>
        {err && <div className="create-err">{err}</div>}
        <div className="browse-list">
          {dir?.entries.map((e) => (
            <Row key={e.path} e={e} picked={p.picked.includes(e.path)} onOpen={() => void go(e.path)} onPick={() => add(e.path)} />
          ))}
          {dir && !dir.entries.length && <div className="browse-row">empty folder</div>}
        </div>
        <p className="create-note">Click a folder to open it; click an object (.rds, .h5ad, a Zarr or SpatialData store) or a results table to add it. A folder of .h5ad files can be added whole.</p>
      </div>
      <div className="create-panel">
        <h2>Chosen</h2>
        {!p.picked.length && <p className="create-note">Nothing yet.</p>}
        <div className="picked-list">
          {p.picked.map((x) => (
            <div key={x} className="picked-row">
              <span>{x}</span>
              <button className="x" onClick={() => remove(x)} title="remove">
                ×
              </button>
            </div>
          ))}
        </div>
        <div className="create-opts">
          <label>platform</label>
          <select value={p.platform} onChange={(e) => p.setPlatform(e.target.value)} title="guessed from the data when left open">
            <option value="">guess from the data</option>
            {PLATFORMS.map((x) => (
              <option key={x} value={x}>
                {platformLabel(x)}
              </option>
            ))}
          </select>
          {hasStore && (
            <>
              <label>table</label>
              <input value={p.table} onChange={(e) => p.setTable(e.target.value)} placeholder="SpatialData store: the table to draw (when it has several)" />
            </>
          )}
        </div>
        <div className="create-actions">
          <button className="primary" disabled={!p.picked.length || !!p.busy} onClick={p.onRead}>
            Read the data
          </button>
          {p.busy && <span className="create-note">{p.busy}…</span>}
        </div>
      </div>
    </div>
  );
}

function Row({ e, picked, onOpen, onPick }: { e: BrowseEntry; picked: boolean; onOpen: () => void; onPick: () => void }) {
  const glyph = e.kind === "folder" ? "▸" : e.kind === "object" || e.kind === "store" ? "●" : e.kind === "table" ? "▦" : "·";
  const click = e.kind === "folder" ? onOpen : e.kind === "file" ? undefined : onPick;
  return (
    <div className={`browse-row ${e.kind}${picked ? " picked" : ""}`} onClick={click} title={e.kind === "store" ? `${e.hint} (click to add; double-click to look inside)` : e.hint || e.path} onDoubleClick={e.kind === "store" ? onOpen : undefined}>
      <span className="glyph">{glyph}</span>
      <span className="name">{e.name}</span>
      <span className="hint">{e.hint}</span>
      <span className="size">{fmtSize(e.size)}</span>
    </div>
  );
}

// ---------------------------------------------------------------- 2. review
function ReviewStep(p: { ins: Inspection; choices: Choices; setChoices: (c: Choices) => void; guard: string | null; onBack: () => void; onBuild: () => void }) {
  const { ins, choices, setChoices } = p;
  const [yaml, setYaml] = useState(ins.yaml);
  const [paths, setPaths] = useState({ yaml: ins.yaml_path, bundle: ins.bundle });
  const [renderErr, setRenderErr] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      render(ins.token, choices)
        .then((r) => {
          setYaml(r.yaml);
          setPaths({ yaml: r.yaml_path, bundle: r.bundle });
          setRenderErr(null);
        })
        .catch((e: Error) => setRenderErr(e.message));
    }, 250);
  }, [ins.token, choices]);
  const entry = (i: number) => choices.entries[String(i)] ?? {};
  const setEntry = (i: number, patch: Partial<EntryChoice>) => setChoices({ ...choices, entries: { ...choices.entries, [String(i)]: { ...entry(i), ...patch } } });
  const nOn = ins.entries.reduce((n, _e, i) => n + (entry(i).columns ?? []).filter((c) => c.on).length, 0);
  return (
    <>
      <div className="create-panel">
        <div className="dataset-fields">
          <label>name</label>
          <input value={choices.name ?? ""} onChange={(e) => setChoices({ ...choices, name: e.target.value })} />
          <label>id</label>
          <input value={choices.id ?? ""} onChange={(e) => setChoices({ ...choices, id: e.target.value.replace(/[^A-Za-z0-9_.-]+/g, "_") })} title="the bundle folder and ?d=<id>" />
        </div>
      </div>
      <div className="create-cols">
        <div className="create-panel">
          <h2>What was found</h2>
          {ins.entries.map((e, i) => (
            <EntryCard key={i} e={e} c={entry(i)} names={choices.names ?? {}} setNames={(names) => setChoices({ ...choices, names })} set={(patch) => setEntry(i, patch)} />
          ))}
          {ins.comparisons.length > 0 && (
            <div className="entry-card">
              <div className="line">
                <b>Results tables</b>
              </div>
              {ins.comparisons.map((c) => (
                <div key={c.id} className="line">
                  <span className="src">{c.source}</span>
                  <span className="create-note">
                    {c.kind === "markers" ? "markers" : "contrast"} · {c.n_rows.toLocaleString()} rows · {Object.entries(c.columns).map(([r, col]) => `${r} ← ${col}`).join(", ")}
                  </span>
                </div>
              ))}
            </div>
          )}
          {ins.log.length > 0 && <details><summary className="create-note">what the reader said ({ins.log.length} lines)</summary><pre className="build-log">{ins.log.join("\n")}</pre></details>}
        </div>
        <div className="create-panel">
          <h2>The dataset yaml this makes</h2>
          <p className="create-note">
            Written to <code>{paths.yaml}</code>; the bundle to <code>{paths.bundle}</code>. Edit the file and run <code>spatialscape build</code> to change the dataset later.
          </p>
          {renderErr && <div className="create-err">{renderErr}</div>}
          <pre className="yaml-pane">{yaml}</pre>
          <div className="create-actions">
            <button onClick={p.onBack}>‹ Back</button>
            <button className="primary" disabled={!!p.guard || !nOn || !!renderErr} onClick={p.onBuild} title={p.guard ?? (!nOn ? "tick at least one annotation" : "write the yaml and build the bundle")}>
              Build
            </button>
            <span className="create-note">
              {ins.entries.reduce((n, e) => n + e.samples.length, 0) || ins.entries.length} sample{ins.entries.reduce((n, e) => n + e.samples.length, 0) === 1 ? "" : "s"} · {nOn} annotation{nOn === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      </div>
    </>
  );
}

function EntryCard({ e, c, names, setNames, set }: { e: EntryInfo; c: EntryChoice; names: Record<string, string>; setNames: (n: Record<string, string>) => void; set: (patch: Partial<EntryChoice>) => void }) {
  const cols = c.columns ?? [];
  const toggle = (column: string, on: boolean) => set({ columns: cols.map((x) => (x.column === column ? { ...x, on } : x)) });
  const rename = (column: string, id: string) => set({ columns: cols.map((x) => (x.column === column ? { ...x, id } : x)) });
  const metaOn = new Set(c.meta ?? []);
  return (
    <div className="entry-card">
      <div className="src">{e.source}</div>
      <div className="line">
        <span className="create-note">{e.source_note}</span>
      </div>
      <div className="line">
        {e.embedding ? (
          <span>snRNA-seq embedding</span>
        ) : (
          <label>
            platform{" "}
            <select value={c.platform ?? e.platform} onChange={(ev) => set({ platform: ev.target.value })} title={e.platform_note}>
              {PLATFORMS.map((x) => (
                <option key={x} value={x}>
                  {platformLabel(x)}
                </option>
              ))}
            </select>
          </label>
        )}
        {e.n_obs != null && <span className="create-note">{e.n_obs.toLocaleString()} cells</span>}
        {e.samples.length > 1 && <span className="create-note">{e.samples.length} samples: {e.samples.slice(0, 4).join(", ")}{e.samples.length > 4 ? ", …" : ""}</span>}
        {e.r_object && e.assays.length > 1 && (
          <label>
            expression{" "}
            <select value={c.assay ?? e.assay ?? ""} onChange={(ev) => set({ assay: ev.target.value })}>
              {e.assays.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
        )}
        {!e.r_object && e.layers.length > 1 && (
          <label>
            expression{" "}
            <select value={c.layer ?? "X"} onChange={(ev) => set({ layer: ev.target.value })}>
              {e.layers.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
        )}
        {e.embedding && e.r_object && e.embeddings.length > 1 && (
          <label>
            embedding{" "}
            <select value={c.embedding ?? e.embedding_key ?? ""} onChange={(ev) => set({ embedding: ev.target.value })}>
              {e.embeddings.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
        )}
        {e.regions.length > 0 && (
          <label>
            element{" "}
            <select value={c.region ?? e.region ?? ""} onChange={(ev) => set({ region: ev.target.value })}>
              {[e.region ?? "", ...e.regions].filter(Boolean).map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      {e.store_note && <div className="create-note">{e.store_note}</div>}
      {Object.keys(e.layer_files).length > 0 && <div className="create-note">also found: {Object.entries(e.layer_files).map(([k, v]) => `${k} (${v})`).join(", ")}</div>}
      {e.sections && <div className="create-note">this file holds {e.sections[1].length} sections ({e.sections[0]}); they are drawn as one sample. Split them in the yaml with `subset:`.</div>}
      <table className="cols-table">
        <tbody>
          {e.columns.map((col) => {
            const ch = cols.find((x) => x.column === col.column);
            const on = ch?.on ?? col.on;
            const id = ch?.id ?? col.id;
            return (
              <tr key={col.column} className={on ? "" : "off"}>
                <td>
                  <input type="checkbox" checked={on} onChange={(ev) => toggle(col.column, ev.target.checked)} />
                </td>
                <td className="col" title="the column in the object">{col.column}</td>
                <td>
                  <input type="text" value={names[id] ?? ""} placeholder={pretty(id)} onChange={(ev) => setNames({ ...names, [id]: ev.target.value })} title="the name shown in the viewer" disabled={!on} />
                </td>
                <td>
                  <input type="text" value={id} onChange={(ev) => rename(col.column, ev.target.value.replace(/[^A-Za-z0-9_]+/g, "_"))} title="field id: the same id in every dataset means the same thing (domain, celltype, ...)" disabled={!on} style={{ width: 128 }} />
                </td>
                <td className="note">
                  {col.kind === "continuous" ? "numeric" : "categories"} · {col.note}
                </td>
              </tr>
            );
          })}
          {e.meta.map((m) => (
            <tr key={`meta-${m.column}`} className={metaOn.has(m.column) ? "" : "off"}>
              <td>
                <input type="checkbox" checked={metaOn.has(m.column)} onChange={(ev) => set({ meta: ev.target.checked ? [...metaOn, m.column] : [...metaOn].filter((x) => x !== m.column) })} />
              </td>
              <td className="col">{m.column}</td>
              <td colSpan={2} className="note">sample property: the canvas can be split by it</td>
              <td className="note">{m.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {e.skipped.length > 0 && <div className="create-note">not offered: {e.skipped.join(", ")} (ids and layout columns)</div>}
    </div>
  );
}

function pretty(id: string): string {
  const s = id.replace(/[_.]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------- 3. build
function BuildStep({ id }: { id: string }) {
  const [state, setState] = useState<Job | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const pre = useRef<HTMLPreElement>(null);
  useEffect(() => {
    let next = 0;
    let stop = false;
    const tick = async () => {
      try {
        const j = await job(id, next);
        if (stop) return;
        next = j.next;
        if (j.lines.length) setLines((l) => [...l, ...j.lines]);
        setState(j);
        if (j.status === "running") window.setTimeout(() => void tick(), 700);
      } catch (e) {
        if (!stop) setErr((e as Error).message);
      }
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [id]);
  useEffect(() => {
    if (pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [lines]);
  const open = () => {
    location.href = `?d=${encodeURIComponent(state?.dataset_id ?? "")}`;
  };
  return (
    <div className="create-panel">
      <h2>{state?.status === "done" ? "Built" : state?.status === "error" ? "The build stopped" : "Building"}</h2>
      {state && (
        <p className="create-note">
          yaml <code>{state.yaml}</code> · bundle <code>{state.bundle}</code> · {state.seconds}s
        </p>
      )}
      {err && <div className="create-err">{err}</div>}
      {state?.error && <div className="create-err">{state.error}</div>}
      <pre className="build-log" ref={pre}>
        {lines.join("\n")}
      </pre>
      <div className="create-actions">
        {state?.status === "done" && (
          <button className="primary" onClick={open}>
            Open the dataset
          </button>
        )}
        <a href="?create">Create another</a>
        <a href="./">gallery</a>
      </div>
    </div>
  );
}
