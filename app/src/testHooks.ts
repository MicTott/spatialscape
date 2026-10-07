/** window.__sscape test/automation hooks (dev + e2e builds). */
import { store, type ViewerState } from "./store/store";
import type { ViewerController } from "./views/ViewerController";

declare global {
  interface Window {
    __sscape?: {
      ready: Promise<void>;
      readyAtMs: number | null;
      store: typeof store;
      controller: ViewerController;
      setGene: (gene: string) => Promise<number>;
      getState: () => ViewerState;
      pixelProbe: () => Promise<{ nonBackground: number; total: number }>;
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
  };
}
