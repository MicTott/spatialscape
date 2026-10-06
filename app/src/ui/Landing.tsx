import { useState } from "react";
import { store } from "../store/store";

export function Landing() {
  const [url, setUrl] = useState("");
  const go = (u: string) => {
    const clean = u.trim().replace(/\/manifest\.json$/, "");
    if (!clean) return;
    store.getState().set({ datasetUrl: clean, status: "idle" });
  };
  const demo = new URL("examples/synthetic", window.location.href.replace(/[^/]*$/, "")).toString();
  return (
    <div className="overlay landing">
      <h1>spatialscape</h1>
      <p>A static, reactive browser for spatial transcriptomics and snRNA-seq. Open a bundle built with <code>spatialscape build</code>.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          go(url);
        }}
      >
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://host/path/to/bundle  or  http://localhost:8787/synthetic" />
        <button type="submit">Open</button>
      </form>
      <p className="muted">
        Local: run <code>spatialscape serve examples</code> and open <a href={`?d=http://127.0.0.1:8787/synthetic`}>the synthetic demo</a>.
        {" "}Hosted demo: <a href={`?d=${demo}`}>{demo.replace(/^https?:\/\//, "")}</a>
      </p>
    </div>
  );
}
