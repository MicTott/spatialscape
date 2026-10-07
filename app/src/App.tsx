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
import { SplitDivider } from "./ui/SplitDivider";
import { ScaleBar } from "./ui/ScaleBar";
import { PointSizeControls } from "./ui/PointSizeControl";
import { TopNav } from "./ui/TopNav";
import { useRegistry } from "./ui/registry";


export function App() {
  const mapRef = useRef<HTMLDivElement>(null);
  const ctrlRef = useRef<ViewerController | null>(null);
  const status = useViewer((s) => s.status);
  const error = useViewer((s) => s.error);
  const datasetUrl = useViewer((s) => s.datasetUrl);
  const sidebarOpen = useViewer((s) => s.sidebarOpen);
  const hasManifest = useViewer((s) => !!s.manifest);
  const hasNav = !!useRegistry()?.site;

  useEffect(() => {
    if (!mapRef.current || ctrlRef.current) return;
    const initial = readUrl();
    store.getState().set(initial);
    const ctrl = new ViewerController(mapRef.current);
    ctrlRef.current = ctrl;
    installTestHooks(ctrl);
    const unbind = bindUrl();
    if (initial.datasetUrl) void resolveDataset(initial.datasetUrl).then((u) => ctrl.load(u));
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
    <div className={`app${hasNav ? " with-nav" : ""}`}>
      <TopNav />
      <div className={`map${sidebarOpen && hasManifest ? " with-sidebar" : ""}`} ref={mapRef}>
        <SplitDivider mapRef={mapRef} />
        <ScaleBar />
        <PointSizeControls />
      </div>
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
    </div>
  );
}
