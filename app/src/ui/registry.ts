import { useEffect, useState } from "react";

/** One gallery card. `spatialscape site build` writes every key; hand-written entries may leave the optional ones out. */
export interface RegistryEntry {
  id: string;
  name: string;
  description?: string;
  platforms?: string[];
  samples?: number;
  cells?: number;
  genes?: number;
  url: string; // empty for "coming soon" entries
  thumbnail?: string; // defaults to <url>/thumbnail.png
  tags?: string[];
  group?: string; // the heading this card sits under; cards without one come last
  status?: "live" | "local" | "coming soon";
  paper?: { title: string; url?: string };
  accent?: string;
}
export interface Registry {
  title?: string;
  intro?: string;
  site?: { title?: string; logo?: string; links?: { label: string; url: string }[] };
  datasets: RegistryEntry[];
}

/** The gallery's sections: cards under their `group` headings in order of first appearance, ungrouped cards last
 *  under no heading. A registry without groups is one section, which is the plain gallery. */
export function cardGroups(datasets: RegistryEntry[]): { name: string | null; items: RegistryEntry[] }[] {
  const named = new Map<string, RegistryEntry[]>();
  const rest: RegistryEntry[] = [];
  for (const d of datasets) {
    const g = d.group?.trim();
    if (!g) rest.push(d);
    else named.set(g, [...(named.get(g) ?? []), d]);
  }
  const out: { name: string | null; items: RegistryEntry[] }[] = [...named].map(([name, items]) => ({ name, items }));
  if (rest.length || !out.length) out.push({ name: null, items: rest });
  return out;
}

/** A card's pills: its platforms by name (`other` says nothing, so it is left out), then its tags, without repeats. */
export function cardPills(d: RegistryEntry, label: (platform: string) => string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const t of [...(d.platforms ?? []).filter((p) => p !== "other").map(label), ...(d.tags ?? [])]) {
    const k = t.trim().toLowerCase();
    if (k && !seen.has(k)) {
      seen.add(k);
      out.push(t.trim());
    }
  }
  return out;
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
  return absolute(hit?.url ?? d); // a bare folder name next to the page (`serve bundles`) is a URL too
}

export function thumbnailUrl(d: RegistryEntry): string | null {
  if (d.thumbnail) return new URL(d.thumbnail, document.baseURI).toString();
  if (!d.url) return null;
  return `${new URL(d.url, document.baseURI).toString().replace(/\/$/, "")}/thumbnail.png`;
}
