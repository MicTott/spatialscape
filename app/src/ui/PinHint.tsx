import { useViewer } from "../store/store";
import { pinHint } from "../views/pins";

/** The pin tool's words next to the pointer: which section a click pins, and into which window. */
export function PinHint() {
  const tool = useViewer((s) => s.tool);
  const at = useViewer((s) => s.pinHover);
  const pins = useViewer((s) => s.pins);
  const manifest = useViewer((s) => s.manifest);
  if (tool !== "pin" || !at || !manifest) return null;
  const name = at.sampleId ? (manifest.samples.find((x) => x.id === at.sampleId)?.name ?? at.sampleId) : null;
  return (
    <div className={`pin-hint${name ? " over" : ""}`} style={{ left: at.x + 16, top: at.y + 18 }} role="status">
      {pinHint(pins, name)}
    </div>
  );
}
