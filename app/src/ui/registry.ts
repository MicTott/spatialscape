import { useEffect, useState } from "react";

export interface RegistryEntry {
  id: string;
  name: string;
  description: string;
  platforms: string[];
  samples: number;
  cells: number;
  genes?: number;
  url: string;
  thumbnail?: string; // defaults to <url>/thumbnail.png
  tags?: string[];
  status: "live" | "local" | "coming soon";
  paper?: { title: string; url?: string };
  accent?: string;
}
export interface Registry {
  title?: string;
  intro?: string;
  site?: { title?: string; logo?: string; links?: { label: string; url: string }[] };
  datasets: RegistryEntry[];
}

export function registryUrl() {
  return new URL("datasets.json", document.baseURI).toString();
}

let cached: Promise<Registry | null> | null = null;
export function loadRegistry(): Promise<Registry | null> {
  if (!cached) {
    cached = fetch(registryUrl())
      .then((r) => (r.ok ? (r.json() as Promise<Registry>) : null))
      .catch(() => null);
  }
  return cached;
}

export function useRegistry(): Registry | null {
  const [reg, setReg] = useState<Registry | null>(null);
  useEffect(() => {
    void loadRegistry().then(setReg);
  }, []);
  return reg;
}

/** Resolve `?d=<id>` against the registry; full URLs and paths pass through. Always absolute (the worker needs it). */
export async function resolveDataset(d: string): Promise<string> {
  const absolute = (u: string) => new URL(u, document.baseURI).toString().replace(/\/$/, "");
  if (/^(https?:)?\/\//.test(d) || d.includes("/")) return absolute(d);
  const reg = await loadRegistry();
  const hit = reg?.datasets.find((x) => x.id === d);
  return hit?.url ? absolute(hit.url) : d;
}

export function thumbnailUrl(d: RegistryEntry): string | null {
  if (d.thumbnail) return new URL(d.thumbnail, document.baseURI).toString();
  if (!d.url) return null;
  return `${new URL(d.url, document.baseURI).toString().replace(/\/$/, "")}/thumbnail.png`;
}
