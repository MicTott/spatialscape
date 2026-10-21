import { useEffect, useRef } from "react";
import { store, useViewer } from "./store/store";
import { ViewerController } from "./views/ViewerController";
import { bindUrl, readUrl } from "./url/urlState";
import { installTestHooks } from "./testHooks";
import { Sidebar } from "./ui/Sidebar";
import { Tooltip } from "./ui/Tooltip";
import { StatusBar } from "./ui/StatusBar";
import { Landing, resolveDataset } from "./ui/Landing";
import { PlatformBar } from "./ui/PlatformBar";
import { PaneDividers } from "./ui/PaneDividers";
import { PaneHeaders } from "./ui/PaneHeaders";
import { ScaleBars } from "./ui/ScaleBar";
import { PointSizeControls } from "./ui/PointSizeControl";
import { HelpOverlay } from "./ui/HelpOverlay";
import { TopNav } from "./ui/TopNav";
import { GenomePanel } from "./genome/GenomePanel";
import { useRegistry } from "./ui/registry";


export function App() {
  const mapRef = useRef<HTMLDivElement>(null);
  const ctrlRef = useRef<ViewerController | null>(null);
  const status = useViewer((s) => s.status);
  const error = useViewer((s) => s.error);
  const datasetUrl = useViewer((s) => s.datasetUrl);
  const sidebarOpen = useViewer((s) => s.sidebarOpen);
  const hasManifest = useViewer((s) => !!s.manifest);
  const hasGenome = useViewer((s) => s.genome && !!s.manifest?.samples.some((x) => x.tracks));
  const genomeHeight = useViewer((s) => s.genomeHeight);
  const hasNav = !!useRegistry()?.site;

  useEffect(() => {
    if (!mapRef.current || ctrlRef.current) return;
    const initial = readUrl();
    store.getState().set(initial);
    const ctrl = new ViewerController(mapRef.current);
    ctrlRef.current = ctrl;
    installTestHooks(ctrl);
    const unbind = bindUrl(); // the dataset itself is loaded by the effect below, once, when datasetUrl is set
    return () => {
      unbind();
      ctrl.destroy();
      ctrlRef.current = null;
    };
  }, []);

  useEffect(() => {
    const ctrl = ctrlRef.current;
    if (ctrl && datasetUrl && status === "idle") void resolveDataset(datasetUrl).then((u) => ctrl.load(u));
  }, [datasetUrl, status]);

  return (
    <div className={`app${hasNav ? " with-nav" : ""}`} style={hasGenome ? ({ "--genome-h": `${genomeHeight}px` } as React.CSSProperties) : undefined}>
      <TopNav />
      <div className={`map${sidebarOpen && hasManifest ? " with-sidebar" : ""}${hasGenome ? " with-genome" : ""}`} ref={mapRef}>
        <PaneHeaders />
        <PaneDividers mapRef={mapRef} />
        <ScaleBars />
        <PointSizeControls />
      </div>
      <GenomePanel />
      {status === "idle" && !datasetUrl && <Landing />}
      {status === "error" && (
        <div className="overlay error">
          <h2>Could not load dataset</h2>
          <p>{error}</p>
          <button onClick={() => store.getState().set({ status: "idle", datasetUrl: null, datasetRef: null, manifest: null })}>Back</button>
        </div>
      )}
      <PlatformBar />
      <Sidebar />
      <Tooltip />
      <StatusBar />
      <HelpOverlay />
    </div>
  );
}
