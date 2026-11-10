/** window.__sscape test/automation hooks (dev + e2e builds). */
import { loadMatrix } from "./compare/data";
import { runRegionTest, type TestOptions } from "./compare/live";
import type { MatrixData } from "./compare/model";
import { store, type ViewerState } from "./store/store";
import type { GenomeView } from "./genome/GenomeView";
import type { ViewerController } from "./views/ViewerController";

declare global {
  interface Window {
    __sscape?: {
      ready: Promise<void>;
      readyAtMs: number | null;
      store: typeof store;
      controller: ViewerController;
      genome?: GenomeView | null; // the genome panel's canvas, while shown
      setGene: (gene: string) => Promise<number>;
      getState: () => ViewerState;
      pixelProbe: () => Promise<{ nonBackground: number; total: number }>;
      drawn: () => { points: number; shapes: number; molecules: number }; // what the last layer build put on screen
      regionTest: (opts: TestOptions) => Promise<void>; // the region test, as the panel's button runs it
      liveMatrix: () => Promise<MatrixData> | null; // its result, as the Compare panel reads it
    };
  }
}

export function installTestHooks(controller: ViewerController) {
  const ready = new Promise<void>((resolve) => {
    const check = (s: ViewerState) => {
      if (s.status === "error") {
        resolve(); // callers inspect getState().status / error
        return;
      }
      if (s.status === "ready" && s.pending === 0) {
        if (window.__sscape && window.__sscape.readyAtMs == null) window.__sscape.readyAtMs = performance.now();
        resolve();
      }
    };
    check(store.getState());
    const unsub = store.subscribe((s) => {
      check(s);
      if (s.status === "ready" && s.pending === 0) unsub();
    });
  });
  window.__sscape = {
    ready,
    readyAtMs: null,
    store,
    controller,
    getState: () => store.getState(),
    setGene: (gene: string) => {
      const t0 = performance.now();
      store.getState().setColor({ kind: "gene", gene });
      return controller.whenIdle().then(() => performance.now() - t0);
    },
    pixelProbe: () => controller.pixelProbe(),
    drawn: () => controller.drawn,
    regionTest: (opts) => runRegionTest(controller, opts),
    liveMatrix: () => {
      const live = controller.regions.live;
      const url = store.getState().datasetUrl;
      return live && url ? loadMatrix(url, live) : null;
    },
  };
}
