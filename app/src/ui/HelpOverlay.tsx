import { store, useViewer } from "../store/store";

const ROWS: [string, string][] = [
  ["double-click", "focus a sample (map or list)"],
  ["← / →", "step through samples"],
  ["Esc", "back to all samples · clear selection · leave lasso"],
  ["f", "fit the view"],
  ["l", "lasso tool on / off"],
  ["Enter", "focus the selected sample"],
  ["scroll / drag", "zoom / pan"],
  ["legend click", "toggle a category · double-click: solo"],
  ["shift-click platform", "add or remove a platform"],
  ["?", "this list"],
];

export function HelpOverlay() {
  const open = useViewer((s) => s.help);
  if (!open) return null;
  const close = () => store.getState().set({ help: false });
  return (
    <div className="help-backdrop" onClick={close}>
      <div className="help" onClick={(e) => e.stopPropagation()}>
        <h2>Keyboard and mouse</h2>
        <table>
          <tbody>
            {ROWS.map(([k, v]) => (
              <tr key={k}>
                <td>
                  <kbd>{k}</kbd>
                </td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">The URL always holds the full view state; use "copy link" in the panel header to share it.</p>
      </div>
    </div>
  );
}
