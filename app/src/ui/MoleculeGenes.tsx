import { store, useViewer } from "../store/store";
import { GeneSearch } from "./GeneSearch";
import { onScreenColor, pinColor } from "../views/molecules";

/** The molecule row's body: the gene on screen (or the blend's sets) in its colour, the pinned genes in theirs with
 * a way to unpin, and a search box to pin one more. Under an annotation every other molecule draws in grey. */
export function MoleculeGenes({ genes }: { genes: string[] }) {
  const color = useViewer((s) => s.color);
  const colormap = useViewer((s) => s.colormap);
  const geneMin = useViewer((s) => s.geneMin);
  const pins = useViewer((s) => s.moleculeGenes);
  const pinColors = useViewer((s) => s.moleculePinColors);
  const size = useViewer((s) => s.moleculeSize);
  const mode = useViewer((s) => s.moleculeColors);
  const set = store.getState().set;
  const top = onScreenColor({ colormap, geneMin });
  const pin = (g: string) => {
    if (!pins.includes(g)) set({ moleculeGenes: [...pins, g] });
  };
  return (
    <div className="molecule-genes">
      <div className="tabs" title="selected genes: the gene or blend on screen and the pinned genes, other molecules grey under an annotation. all genes: every gene in its own colour">
        <button className={mode === "selected" ? "on" : ""} onClick={() => set({ moleculeColors: "selected" })}>
          selected genes
        </button>
        <button className={mode === "all" ? "on" : ""} onClick={() => set({ moleculeColors: "all" })}>
          all genes
        </button>
      </div>
      <ul className="cats">
        {color?.kind === "gene" && !pins.includes(color.gene) && (
          <li title="the gene coloured on screen; change it above">
            <span className="swatch" style={{ background: `rgb(${top.join(",")})` }} />
            <span className="cat-name">{color.gene}</span>
            <span className="cat-n">on screen</span>
          </li>
        )}
        {color?.kind === "blend" && (
          <li title="the blend's two gene sets, in the blend's colours">
            <span className="swatch blend-swatch" />
            <span className="cat-name">blend sets</span>
            <span className="cat-n">on screen</span>
          </li>
        )}
        {pins.map((g, i) => (
          <li key={g} title="pinned: click the colour to change it, × to unpin">
            <input
              type="color"
              className="swatch swatch-pick"
              value={pinColors[g] ?? pinColor(i)}
              onChange={(e) => set({ moleculePinColors: { ...pinColors, [g]: e.target.value } })}
              aria-label={`colour of ${g}`}
            />
            <span className="cat-name">{g}</span>
            <button
              className="unpin"
              onClick={() => {
                const { [g]: _gone, ...rest } = pinColors;
                set({ moleculeGenes: pins.filter((x) => x !== g), moleculePinColors: rest });
              }}
              aria-label={`unpin ${g}`}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <GeneSearch
        key={pins.length}
        genes={genes}
        value={null}
        onPick={pin}
        onSubmit={(text) => {
          // a molecule feature the expression matrix lacks (dropped as all-zero, or never measured) is pinned by name
          const name = text.trim();
          if (!name || /[\s,;]/.test(name)) return false;
          pin(name);
          return true;
        }}
        placeholder={pins.length ? "pin another gene…" : "pin a gene… (Enter pins any name)"}
      />
      {mode === "all" ? <div className="muted small">every other gene in its own colour</div> : !color || color.kind === "field" ? <div className="muted small">other genes draw in grey</div> : null}
      <label title="double-click to reset">
        size <small>×{size.toFixed(2)}</small>
        <input type="range" min={0.25} max={4} step={0.05} value={size} onChange={(e) => set({ moleculeSize: +e.target.value })} onDoubleClick={() => set({ moleculeSize: 1 })} />
      </label>
    </div>
  );
}
