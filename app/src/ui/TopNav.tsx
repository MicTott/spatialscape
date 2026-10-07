import { useRegistry } from "./registry";
import { useViewer } from "../store/store";

/**
 * Optional slim site bar, shown only when datasets.json has a `site` block. Keeps the viewer a page
 * of a larger site: brand -> gallery, dataset switcher, configurable links.
 */
export function TopNav() {
  const reg = useRegistry();
  const datasetRef = useViewer((s) => s.datasetRef);
  const manifest = useViewer((s) => s.manifest);
  if (!reg?.site) return null;
  const site = reg.site;
  const base = new URL(".", document.baseURI).toString();
  const current = reg.datasets.find((d) => d.id === datasetRef || d.url === datasetRef)?.id ?? "";
  return (
    <nav className="topnav">
      <a className="brand" href={base} title="all datasets">
        {site.logo && <img src={site.logo} alt="" />}
        <span>{site.title ?? "spatialscape"}</span>
      </a>
      <span className="crumb">
        {manifest ? (
          <>
            <a href={base}>Datasets</a>
            <span className="sep">/</span>
            <select
              value={current}
              onChange={(e) => {
                if (e.target.value) window.location.href = `${base}?d=${encodeURIComponent(e.target.value)}`;
              }}
              title="switch dataset"
            >
              {!current && <option value="">{manifest.name}</option>}
              {reg.datasets
                .filter((d) => d.url)
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
            </select>
          </>
        ) : (
          <a href={base} className="on">
            Datasets
          </a>
        )}
      </span>
      <span className="grow" />
      {(site.links ?? []).map((l) => (
        <a key={l.url} href={l.url} target={l.url.startsWith("http") ? "_blank" : undefined} rel="noreferrer">
          {l.label}
        </a>
      ))}
    </nav>
  );
}
