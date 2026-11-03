/** Create: a dataset from data on the machine the server runs on, in three screens written in sentences. Your
 *  data (a Finder-like picker over the server's paths), what we found (the object in words, with switches for the
 *  annotations), build (steps ticking off, then open). The mechanism, field ids and the yaml the choices make, sits
 *  under "Advanced"; the yaml is written next to the bundle and is what to edit afterwards. */
import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { platformLabel } from "../data/manifest";
import { REGION_COLORS } from "../store/store";
import { thumbnailUrl } from "../ui/registry";
import { browse, build, fmtSize, inspect, job, ping, render, type Browse, type BrowseEntry, type Choices, type ColumnRow, type CreatePing, type EntryChoice, type EntryInfo, type Inspection, type Job } from "./api";

const PLATFORMS = ["visium", "visium_hd", "xenium", "merfish", "codex", "other"];
const RECENT_KEY = "sscape.create.recent";
type Step = "source" | "found" | "build";

const slug = (name: string) => name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "dataset";
const n = (v: number | null | undefined) => (v == null ? "?" : v.toLocaleString());
const plural = (k: number, one: string, many = `${one}s`) => (k === 1 ? one : many);

/** A path as people read it: "Home › Documents › R › spatialAmygdala". */
function crumbsOf(path: string, home: string): { label: string; path: string }[] {
  const out: { label: string; path: string }[] = [];
  let rest = path;
  if (home && (path === home || path.startsWith(home + "/"))) {
    out.push({ label: "Home", path: home });
    rest = path.slice(home.length);
  } else out.push({ label: "/", path: "/" });
  let acc = out[0].path === "/" ? "" : out[0].path;
  for (const part of rest.split("/").filter(Boolean)) {
    acc = `${acc}/${part}`;
    out.push({ label: part, path: acc });
  }
  return out;
}
const shortPath = (path: string, home: string) =>
  crumbsOf(path, home)
    .map((c) => c.label)
    .join(" › ");
const parentOf = (path: string) => path.replace(/\/[^/]+$/, "") || "/";

export function CreatePage() {
  const [info, setInfo] = useState<CreatePing | null | undefined>(undefined);
  const [step, setStep] = useState<Step>("source");
  const [picked, setPicked] = useState<string[]>([]);
  const [platform, setPlatform] = useState("");
  const [table, setTable] = useState("");
  const [busy, setBusy] = useState(false);
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
    setBusy(true);
    setError(null);
    try {
      const r = await inspect(picked, { platform, table });
      setIns(r);
      setChoices({ id: r.id, name: r.name, names: {}, entries: Object.fromEntries(r.entries.map((e, i) => [String(i), defaultChoice(e)])) });
      rememberPlaces(picked);
      setStep("found");
      window.scrollTo(0, 0);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const start = async () => {
    if (!ins) return;
    setError(null);
    try {
      const r = await build(ins.token, choices);
      setJobId(r.job);
      setStep("build");
      window.scrollTo(0, 0);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (info === undefined) return <div className="overlay create" />;
  if (info === null)
    return (
      <div className="overlay">
        <h2>Nothing to create here</h2>
        <p>
          This address only shows datasets. To make one from your own data, run <code>spatialscape create</code> on the computer that holds it and open the address it prints.
        </p>
        <a href="./">Back to the datasets</a>
      </div>
    );
  const steps: [Step, string][] = [
    ["source", "Your data"],
    ["found", "What we found"],
    ["build", "Build"],
  ];
  const order = steps.findIndex(([s]) => s === step);
  return (
    <div className="overlay create">
      <div className="bar">
        <b>spatialscape</b>
        <span className="crumb">
          <a href="./">Datasets</a> › Create
        </span>
        <span className="right">this computer · {info.host}</span>
      </div>
      <div className="wrap">
        {step === "source" && (
          <>
            <h1>Create a dataset</h1>
            <p className="lead">Point spatialscape at your data. It reads what it can and asks about the rest. Nothing leaves this computer.</p>
          </>
        )}
        {step === "found" && (
          <>
            <h1>Here is what we found</h1>
            <p className="lead">Switch off anything you do not want to show. Names can be changed by clicking them.</p>
          </>
        )}
        {step === "build" && (
          <>
            <h1>Building {choices.name || ins?.name}</h1>
            <p className="lead">You can leave this page; the build carries on and the dataset appears among your datasets when it is done.</p>
          </>
        )}
        <div className="steps">
          {steps.map(([s, label], i) => (
            <span key={s} className={s === step ? "on" : i < order ? "done" : ""}>
              <i>{i < order ? "✓" : i + 1}</i>
              {label}
            </span>
          ))}
        </div>
        {info.guard && <div className="warn">{info.guard}</div>}
        {error && <div className="err">{error}</div>}
        {step === "source" && <SourceScreen info={info} picked={picked} setPicked={setPicked} platform={platform} setPlatform={setPlatform} table={table} setTable={setTable} busy={busy} onRead={() => void read()} />}
        {step === "found" && ins && <FoundScreen info={info} ins={ins} choices={choices} setChoices={setChoices} onBack={() => setStep("source")} onBuild={() => void start()} />}
        {step === "build" && jobId && <BuildScreen id={jobId} info={info} />}
      </div>
    </div>
  );
}

function defaultChoice(e: EntryInfo): EntryChoice {
  return { platform: e.platform, assay: e.assay ?? undefined, layer: e.layer, embedding: e.embedding_key ?? undefined, region: e.region ?? undefined, columns: e.columns.map((c) => ({ column: c.column, id: c.id, on: c.on })), meta: [] };
}

function recentPlaces(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as string[];
  } catch {
    return [];
  }
}
function rememberPlaces(paths: string[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([...new Set([...paths.map(parentOf), ...recentPlaces()])].slice(0, 5)));
  } catch {
    /* private mode */
  }
}

// ---------------------------------------------------------------- 1. your data
function SourceScreen(p: { info: CreatePing; picked: string[]; setPicked: Dispatch<SetStateAction<string[]>>; platform: string; setPlatform: (v: string) => void; table: string; setTable: (v: string) => void; busy: boolean; onRead: () => void }) {
  const [dir, setDir] = useState<Browse | null>(null);
  const [typing, setTyping] = useState(false);
  const [typed, setTyped] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [storeKinds, setStoreKinds] = useState<Record<string, boolean>>({});
  const go = (path: string | null) =>
    browse(path)
      .then((d) => {
        setDir(d);
        setTyped(d.path);
        setTyping(false);
        setErr(null);
      })
      .catch((e: Error) => setErr(e.message));
  useEffect(() => {
    void go(recentPlaces()[0] ?? p.info.home);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const add = (e: BrowseEntry | string) => {
    const path = typeof e === "string" ? e : e.path;
    if (typeof e !== "string" && e.kind === "store") setStoreKinds((k) => ({ ...k, [path]: true }));
    p.setPicked((prev) => (prev.includes(path) ? prev : [...prev, path]));
  };
  const remove = (path: string) => p.setPicked((prev) => prev.filter((x) => x !== path));
  const h5ads = dir?.entries.filter((e) => e.name.endsWith(".h5ad")).length ?? 0;
  const hasStore = p.picked.some((x) => storeKinds[x]);
  const recent = recentPlaces().filter((r) => r !== dir?.path);
  return (
    <>
      <div className="card">
        <h2>What do you have?</h2>
        <div className="tiles">
          <div className="tile">
            <div className="ic">◉</div>
            <b>An R object</b>
            <span>SpatialExperiment, SingleCellExperiment or Seurat, saved as .rds</span>
          </div>
          <div className="tile">
            <div className="ic">◍</div>
            <b>An AnnData file</b>
            <span>.h5ad or a Zarr store, from scanpy or squidpy</span>
          </div>
          <div className="tile">
            <div className="ic">▣</div>
            <b>A folder from the instrument</b>
            <span>Space Ranger or Xenium output with its .h5ad, or a SpatialData store</span>
          </div>
        </div>
      </div>
      <div className="card">
        <h2>
          Find it <small>on this computer</small>
        </h2>
        <div className="crumbs">
          {!typing &&
            dir &&
            crumbsOf(dir.path, p.info.home).map((c, i, all) =>
              i < all.length - 1 ? (
                <span key={c.path}>
                  <button onClick={() => void go(c.path)}>{c.label}</button> ›
                </span>
              ) : (
                <span key={c.path} className="here">
                  {c.label}
                </span>
              ),
            )}
          {typing && <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void go(typed)} onBlur={() => setTyping(false)} spellCheck={false} />}
          {!typing && (
            <button className="pill" onClick={() => setTyping(true)} title="type or paste a path">
              type a path
            </button>
          )}
        </div>
        <div className="recent">
          {recent.length > 0 && <span className="hint">Recent:</span>}
          {recent.map((r) => (
            <button key={r} className="pill" onClick={() => void go(r)} title={r}>
              {r.split("/").pop()}
            </button>
          ))}
          {dir?.roots
            .filter((r) => r.name !== "home" && r.name !== "project")
            .map((r) => (
              <button key={r.path} className="pill" onClick={() => void go(r.path)} title={r.path}>
                {r.name}
              </button>
            ))}
          {h5ads > 1 && dir && (
            <button className="pill" onClick={() => add(`${dir.path}/*.h5ad`)} title="one sample per file">
              use all {h5ads} .h5ad files in this folder
            </button>
          )}
        </div>
        {err && <div className="err">{err}</div>}
        <div className="files">
          {dir?.entries.map((e) => (
            <Row key={e.path} e={e} picked={p.picked.includes(e.path)} onOpen={() => void go(e.path)} onPick={() => add(e)} />
          ))}
          {dir && !dir.entries.length && <div className="f">empty folder</div>}
        </div>
        {p.picked.map((x) => (
          <div key={x} className="picked">
            <span className="ic">{x.endsWith("*.h5ad") ? "◍" : "◉"}</span>
            <div>
              <b>{x.split("/").pop()}</b>
              <span>{shortPath(parentOf(x), p.info.home)}</span>
            </div>
            <button className="x" onClick={() => remove(x)}>
              remove
            </button>
          </div>
        ))}
        {p.picked.length > 0 && (
          <div className="actions" style={{ marginTop: 10 }}>
            <select value={p.platform} onChange={(e) => p.setPlatform(e.target.value)} title="leave it to spatialscape unless you know better">
              <option value="">We will work out the platform</option>
              {PLATFORMS.map((x) => (
                <option key={x} value={x}>
                  It is {x === "other" ? "something else" : platformLabel(x)}
                </option>
              ))}
            </select>
            {hasStore && <input className="path" value={p.table} onChange={(e) => p.setTable(e.target.value)} placeholder="which table of the store (when it has several)" />}
          </div>
        )}
        <div className="actions">
          <button className="btn primary" disabled={!p.picked.length || p.busy} onClick={p.onRead}>
            {p.busy ? "Reading…" : "Read it"}
          </button>
          <span className="hint">{p.busy ? "An R object is read whole, about as long as loading it in R." : "Click a folder to open it, a file to choose it. You can choose several."}</span>
        </div>
      </div>
    </>
  );
}

function Row({ e, picked, onOpen, onPick }: { e: BrowseEntry; picked: boolean; onOpen: () => void; onPick: () => void }) {
  const glyph = e.kind === "folder" ? "▸" : e.kind === "object" || e.kind === "store" ? "◉" : e.kind === "table" ? "▦" : "·";
  const click = e.kind === "folder" ? onOpen : e.kind === "file" ? undefined : onPick;
  return (
    <div className={`f ${e.kind}${picked ? " sel" : ""}`} onClick={click} onDoubleClick={e.kind === "store" ? onOpen : undefined} title={e.kind === "store" ? "click to choose, double-click to look inside" : undefined}>
      <span className="ic">{glyph}</span>
      <span>{e.name}</span>
      <span className="k">{e.kind === "folder" ? e.hint || "folder" : e.hint}</span>
      <span className="s">{fmtSize(e.size)}</span>
    </div>
  );
}

// ---------------------------------------------------------------- 2. what we found
function unitOf(e: EntryInfo): string {
  return e.embedding ? "nuclei" : e.platform === "visium" ? "spots" : e.platform === "visium_hd" ? "bins" : "cells";
}

function Summary({ ins }: { ins: Inspection }) {
  return (
    <p className="summary">
      {ins.entries.map((e, i) => {
        const k = e.samples.length;
        const imgs = e.found.find((f) => f.present && /image/i.test(f.title));
        return (
          <span key={i}>
            {i > 0 && (i === ins.entries.length - 1 ? ", and " : ", ")}
            {i === 0 ? "A" : "a"} <b>{e.object_class || "file"}</b> with{" "}
            {e.embedding ? (
              <>
                <b>{n(e.n_obs)} nuclei</b> on an embedding
              </>
            ) : (
              <>
                <b>
                  {k || 1} {platformLabel(e.platform)} {plural(k || 1, "section")}
                </b>
                , <b>{n(e.n_obs)} {unitOf(e)}</b>
              </>
            )}
            {e.n_vars != null && (
              <>
                {" "}
                and <b>{n(e.n_vars)} genes</b>
              </>
            )}
            {imgs && <>, with {imgs.title.toLowerCase().replace(/^image:/, "an image:")}</>}
          </span>
        );
      })}
      .
    </p>
  );
}

function FoundScreen(p: { info: CreatePing; ins: Inspection; choices: Choices; setChoices: (c: Choices) => void; onBack: () => void; onBuild: () => void }) {
  const { ins, choices, setChoices } = p;
  const [yaml, setYaml] = useState(ins.yaml);
  const [paths, setPaths] = useState({ yaml: ins.yaml_path, bundle: ins.bundle });
  const [renderErr, setRenderErr] = useState<string | null>(null);
  const [idTouched, setIdTouched] = useState(false);
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
  const setName = (name: string) => setChoices({ ...choices, name, id: idTouched ? choices.id : slug(name) });
  const onRows = ins.entries.flatMap((e, i) => (entry(i).columns ?? []).filter((c) => c.on).map((c) => ({ ...c, i })));
  const nOn = onRows.length;
  return (
    <>
      <div className="card">
        <Summary ins={ins} />
        <p className="sub">{ins.entries.map((e) => e.source.split("/").pop()).join(", ")}</p>
        <div className="name-row">
          <span>Call it</span>
          <input value={choices.name ?? ""} onChange={(e) => setName(e.target.value)} />
          <span className="hint">
            opens at <code>?d={choices.id}</code>
          </span>
        </div>
      </div>
      {ins.entries.map((e, i) => (
        <EntryCards key={i} e={e} c={entry(i)} many={ins.entries.length > 1} names={choices.names ?? {}} setNames={(names) => setChoices({ ...choices, names })} set={(patch) => setEntry(i, patch)} />
      ))}
      {ins.comparisons.length > 0 && (
        <div className="card">
          <h2>
            Results tables <small>shown in the Compare panel</small>
          </h2>
          <div className="found">
            {ins.comparisons.map((c) => (
              <div key={c.id} className="fnd">
                <span className="ok">✓</span>
                <span>
                  {c.source.split("/").pop()}
                  <small>
                    {c.kind === "markers" ? "marker table" : "contrast"} · {c.n_rows.toLocaleString()} genes · {Object.entries(c.columns).map(([r, col]) => `${r}: ${col}`).join(", ")}
                  </small>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="card">
        <details>
          <summary>Advanced: the address, field ids and the configuration file</summary>
          <div className="adv">
            <span>address</span>
            <span>
              ?d=
              <input
                value={choices.id ?? ""}
                onChange={(e) => {
                  setIdTouched(true);
                  setChoices({ ...choices, id: e.target.value.replace(/[^A-Za-z0-9_.-]+/g, "_") });
                }}
              />
            </span>
            {onRows.map((r) => (
              <span key={`${r.i}-${r.column}`} style={{ display: "contents" }}>
                <span>{(choices.names ?? {})[r.id] || pretty(r.id)}</span>
                <span>
                  field id <input value={r.id} onChange={(ev) => setEntry(r.i, { columns: (entry(r.i).columns ?? []).map((x) => (x.column === r.column ? { ...x, id: ev.target.value.replace(/[^A-Za-z0-9_]+/g, "_") } : x)) })} title="the same id in every dataset means the same thing (domain, celltype, total_counts)" />
                </span>
              </span>
            ))}
          </div>
          <p className="hint" style={{ marginTop: 12 }}>
            These choices are saved as <code>{paths.yaml.split("/").pop()}</code> in {shortPath(parentOf(paths.yaml), p.info.home)}. In a terminal, <code>spatialscape build {paths.yaml.split("/").pop()}</code> rebuilds the dataset after edits.
          </p>
          {renderErr && <div className="err">{renderErr}</div>}
          <pre>{yaml}</pre>
        </details>
      </div>
      <div className="actions">
        <button className="btn" onClick={p.onBack}>
          ‹ Back
        </button>
        <button className="btn primary" disabled={!!p.info.guard || !nOn || !!renderErr} onClick={p.onBuild} title={p.info.guard ?? (!nOn ? "switch on at least one annotation" : "")}>
          Build the dataset
        </button>
        <span className="hint">saved in {shortPath(paths.bundle, p.info.home)}</span>
      </div>
    </>
  );
}

function EntryCards({ e, c, many, names, setNames, set }: { e: EntryInfo; c: EntryChoice; many: boolean; names: Record<string, string>; setNames: (n: Record<string, string>) => void; set: (patch: Partial<EntryChoice>) => void }) {
  const cols = c.columns ?? [];
  const isOn = (col: ColumnRow) => cols.find((x) => x.column === col.column)?.on ?? col.on;
  const idOf = (col: ColumnRow) => cols.find((x) => x.column === col.column)?.id ?? col.id;
  const toggle = (col: ColumnRow) => set({ columns: cols.map((x) => (x.column === col.column ? { ...x, on: !x.on } : x)) });
  const on = e.columns.filter(isOn);
  const off = e.columns.filter((col) => !isOn(col));
  const shown = [...on, ...off.slice(0, 3)];
  const hidden = off.slice(3);
  const metaOn = (c.meta ?? []).length > 0;
  const expressionOptions = e.r_object ? e.assays : e.layers;
  const label = (a: string) => (a === "logcounts" || a === "data" ? `${a} — log-normalised, the usual choice` : a === "counts" ? `${a} — raw counts; spatialscape log-normalises them` : a === "X" ? "X — the main matrix" : a);
  const title = many ? ` · from ${e.source.split("/").pop()}` : "";
  const chosenPlatform = c.platform ?? e.platform;
  const why = e.platform_note === "given" ? `${platformLabel(e.platform)}, as you said.` : chosenPlatform !== e.platform ? "" : `We think ${platformLabel(e.platform)}: ${e.platform_note.replace(/^guessed from /, "")}.`;
  const row = (col: ColumnRow) => <AnnotationRow key={col.column} col={col} on={isOn(col)} id={idOf(col)} name={names[idOf(col)] ?? ""} setName={(v) => setNames({ ...names, [idOf(col)]: v })} toggle={() => toggle(col)} />;
  return (
    <>
      {!e.embedding && e.samples.length > 0 && (
        <div className="card">
          <h2>
            {plural(e.samples.length, "Section")}
            <small>
              {e.sample_col === "image" ? "one per Seurat slice" : e.sample_col ? `one per ${e.sample_col}` : "one per file"}
              {title}
            </small>
          </h2>
          <div className="chips">
            {e.samples.slice(0, 40).map((s) => (
              <span key={s} className="pill plain">
                {s}
              </span>
            ))}
            {e.samples.length > 40 && <span className="hint">and {e.samples.length - 40} more</span>}
          </div>
          {e.sections && <div className="why">This file holds {e.sections[1].length} sections in its {e.sections[0]} column; they are drawn as one sample. To split them, list the file once per section in the yaml with `subset:`.</div>}
        </div>
      )}
      {!e.embedding && (
        <div className="card">
          <h2>
            Platform<small>{title}</small>
          </h2>
          <div className="plat">
            {PLATFORMS.map((x) => (
              <label key={x} className={chosenPlatform === x ? "on" : ""} onClick={() => set({ platform: x })}>
                <span className="dot" />
                {x === "other" ? "Something else" : platformLabel(x)}
              </label>
            ))}
          </div>
          {why && <div className="why">{why}</div>}
        </div>
      )}
      <div className="card">
        <h2>
          Annotations to show
          <small>
            {on.length} on · {off.length} more available{title}
          </small>
        </h2>
        <div className="rows">{shown.map(row)}</div>
        {hidden.length > 0 && (
          <details>
            <summary>{hidden.length} more columns</summary>
            <div className="rows">{hidden.map(row)}</div>
          </details>
        )}
        {e.skipped.length > 0 && (
          <div className="hint" style={{ marginTop: 8 }}>
            Not offered: {e.skipped.join(", ")} (ids and layout columns).
          </div>
        )}
      </div>
      {(e.found.length > 0 || e.meta.length > 0) && (
        <div className="card">
          <h2>
            Also in the {e.r_object ? "object" : "data"}
            <small>{title}</small>
          </h2>
          <div className="found">
            {e.found.map((f, k) => (
              <div key={k} className="fnd">
                <span className={f.present ? "ok" : "no"}>{f.present ? "✓" : "◯"}</span>
                <span>
                  {f.title}
                  <small>{f.detail}</small>
                </span>
              </div>
            ))}
            {e.meta.length > 0 && (
              <div className="fnd">
                <span className={metaOn ? "ok" : "no"}>{metaOn ? "✓" : "◯"}</span>
                <span>
                  Sample properties
                  <small>
                    {e.meta.map((m) => m.column).join(", ")} {e.meta.length === 1 ? "has" : "have"} one value per section.{" "}
                    <button className="link" onClick={() => set({ meta: metaOn ? [] : e.meta.map((m) => m.column) })}>
                      {metaOn ? "leave them out" : "use them to split the view"}
                    </button>
                  </small>
                </span>
              </div>
            )}
          </div>
        </div>
      )}
      {(expressionOptions.length > 1 || (e.embedding && e.embeddings.length > 1) || e.regions.length > 0) && (
        <div className="card">
          <h2>
            Expression values<small>{title}</small>
          </h2>
          <div className="actions" style={{ marginTop: 0 }}>
            {expressionOptions.length > 1 && (
              <select value={e.r_object ? (c.assay ?? e.assay ?? "") : (c.layer ?? "X")} onChange={(ev) => set(e.r_object ? { assay: ev.target.value } : { layer: ev.target.value })}>
                {expressionOptions.map((a) => (
                  <option key={a} value={a}>
                    {label(a)}
                  </option>
                ))}
              </select>
            )}
            {e.embedding && e.embeddings.length > 1 && (
              <label>
                drawn on{" "}
                <select value={c.embedding ?? e.embedding_key ?? ""} onChange={(ev) => set({ embedding: ev.target.value })}>
                  {e.embeddings.map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
              </label>
            )}
            {e.regions.length > 0 && (
              <label>
                cells of{" "}
                <select value={c.region ?? e.region ?? ""} onChange={(ev) => set({ region: ev.target.value })}>
                  {[e.region ?? "", ...e.regions].filter(Boolean).map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function AnnotationRow({ col, on, id, name, setName, toggle }: { col: ColumnRow; on: boolean; id: string; name: string; setName: (v: string) => void; toggle: () => void }) {
  const categorical = col.kind === "categorical";
  const src = categorical ? `${col.levels} ${plural(col.levels, "category", "categories")}` : col.lo != null && col.hi != null ? `numbers ${fmtNum(col.lo)} to ${fmtNum(col.hi)}` : "numbers";
  const scale = col.scale ? ` · shown ×${col.scale}` : "";
  const na = col.na ? ` · ${col.na.toLocaleString()} missing` : "";
  return (
    <div className={`row${on ? "" : " off"}`}>
      <button className={`sw${on ? " on" : ""}`} onClick={toggle} aria-label={on ? "switch off" : "switch on"} />
      <div className="name">
        <input value={name} placeholder={pretty(id)} onChange={(e) => setName(e.target.value)} title="the name shown in the viewer; click to change it" />
        <span className="src">
          {src} · from <code>{col.column}</code>
          {scale}
          {na}
          {col.note ? ` · ${col.note}` : ""}
        </span>
      </div>
      <div className="kind">
        {categorical && col.named && (
          <span className="dots">
            {col.examples.slice(0, 6).map((_, k) => (
              <i key={k} style={{ background: REGION_COLORS[k % REGION_COLORS.length] }} />
            ))}
          </span>
        )}
        {categorical ? `${col.examples.slice(0, 4).join(", ")}${col.levels > 4 ? ", …" : ""}` : "colour scale"}
      </div>
    </div>
  );
}

function fmtNum(v: number): string {
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
  if (Math.abs(v) >= 10) return v.toFixed(0);
  return (+v.toPrecision(2)).toString();
}
function pretty(id: string): string {
  const s = id.replace(/[_.]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------- 3. build
interface PStep {
  key: string;
  label: string;
  state: "done" | "now" | "todo" | "fail";
}
/** The log as steps: reading, one per sample (its lines come prefixed with its id), the gallery card. */
function stepsOf(lines: string[], status: Job["status"]): PStep[] {
  const ids: string[] = [];
  const first: Record<string, number> = {};
  lines.forEach((l, i) => {
    const m = /^\[([^\]]+)\]/.exec(l);
    if (m && !(m[1] in first)) {
      first[m[1]] = i;
      ids.push(m[1]);
    }
  });
  const out: PStep[] = [{ key: "read", label: "Read the data", state: ids.length || status !== "running" ? "done" : "now" }];
  ids.forEach((id, k) => {
    const cellsLine = lines.slice(first[id]).find((l) => l.startsWith(`[${id}] writing expression (`));
    const m = cellsLine && /x (\d+) obs/.exec(cellsLine);
    const last = k === ids.length - 1;
    out.push({ key: id, label: `${id}${m ? ` · ${Number(m[1]).toLocaleString()} cells` : ""}`, state: !last ? "done" : status === "running" ? "now" : status === "error" ? "fail" : "done" });
  });
  const thumb = lines.some((l) => l.startsWith("thumbnail:"));
  out.push({ key: "thumb", label: "Gallery card and thumbnail", state: status === "done" ? "done" : status === "error" ? (thumb ? "fail" : "todo") : thumb ? "now" : "todo" });
  if (status === "error") {
    const now = out.find((s) => s.state === "now");
    if (now) now.state = "fail";
  }
  return out;
}

function BuildScreen({ id, info }: { id: string; info: CreatePing }) {
  const [state, setState] = useState<Job | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [entry, setEntry] = useState<{ samples?: number; cells?: number; genes?: number; name?: string; url?: string; thumbnail?: string } | null>(null);
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
        else if (j.status === "done") {
          const reg = await fetch(`${new URL("datasets.json", document.baseURI)}?t=${Date.now()}`)
            .then((r) => r.json())
            .catch(() => null);
          const hit = reg?.datasets?.find((d: { id: string }) => d.id === j.dataset_id);
          if (hit) setEntry(hit);
        }
      } catch (e) {
        if (!stop) setErr((e as Error).message);
      }
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [id]);
  const steps = useMemo(() => stepsOf(lines, state?.status ?? "running"), [lines, state?.status]);
  const open = () => {
    location.href = `?d=${encodeURIComponent(state?.dataset_id ?? "")}`;
  };
  const thumb = entry ? thumbnailUrl({ id: state?.dataset_id ?? "", name: entry.name ?? "", url: entry.url ?? state?.dataset_id ?? "", thumbnail: entry.thumbnail }) : null;
  return (
    <>
      <div className="card">
        <div className="progress">
          {steps.map((s) => (
            <div key={s.key} className={`pstep ${s.state}`}>
              <i>{s.state === "done" ? "✓" : s.state === "fail" ? "!" : ""}</i>
              {s.label}
            </div>
          ))}
        </div>
        {state && (
          <div className="hint" style={{ marginTop: 12 }}>
            {state.seconds}s{state.status === "running" ? " so far…" : ""}
          </div>
        )}
        {err && <div className="err">{err}</div>}
        {state?.error && (
          <div className="warn" style={{ marginTop: 12 }}>
            {state.error}
            <div className="hint" style={{ marginTop: 6 }}>
              The yaml is saved at {shortPath(state.yaml, info.home)}; fix the cause and run <code>spatialscape build</code> on it, or start again.
            </div>
          </div>
        )}
        <details>
          <summary>Show the full log</summary>
          <pre>{lines.join("\n")}</pre>
        </details>
      </div>
      {state?.status === "done" && (
        <div className="card">
          <div className="result">
            {thumb ? <img src={thumb} alt="" /> : <div className="thumb" />}
            <div>
              <h3>{entry?.name ?? state.dataset_id}</h3>
              <p>
                {entry ? `${entry.samples ?? 0} ${plural(entry.samples ?? 0, "section")} · ${(entry.cells ?? 0).toLocaleString()} cells · ${(entry.genes ?? 0).toLocaleString()} genes` : ""}
                <br />
                saved in {shortPath(state.bundle, info.home)}
              </p>
              <button className="btn primary" onClick={open}>
                Open it
              </button>
              <a href="?create" style={{ marginLeft: 16 }}>
                Create another
              </a>
            </div>
          </div>
        </div>
      )}
      {state?.status === "error" && (
        <div className="actions">
          <a className="btn" href="?create">
            ‹ Start again
          </a>
        </div>
      )}
    </>
  );
}
