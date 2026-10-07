import { useEffect, useMemo, useRef, useState } from "react";

interface Props {
  genes: string[];
  value: string | null;
  onPick: (gene: string) => void;
  /** When given, Enter on a comma/space/newline separated list adds every gene at once. */
  onPickMany?: (genes: string[]) => void;
  placeholder?: string;
}

export function GeneSearch({ genes, value, onPick, onPickMany, placeholder }: Props) {
  const [q, setQ] = useState(value ?? "");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => setQ(value ?? ""), [value]);

  const matches = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return [] as string[];
    const pre: string[] = [];
    const sub: string[] = [];
    for (const g of genes) {
      const gl = g.toLowerCase();
      if (gl.startsWith(s)) pre.push(g);
      else if (gl.includes(s)) sub.push(g);
      if (pre.length >= 40) break;
    }
    return [...pre, ...sub].slice(0, 40);
  }, [q, genes]);

  const pick = (g: string) => {
    onPick(g);
    setQ(g);
    setOpen(false);
    ref.current?.blur();
  };

  return (
    <div className="genesearch">
      <input
        ref={ref}
        value={q}
        placeholder={placeholder ?? "search gene…"}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setHi(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            setHi((h) => Math.min(matches.length - 1, h + 1));
            e.preventDefault();
          } else if (e.key === "ArrowUp") {
            setHi((h) => Math.max(0, h - 1));
            e.preventDefault();
          } else if (e.key === "Enter" && onPickMany && /[\s,;]/.test(q.trim())) {
            const byLower = new Map(genes.map((g) => [g.toLowerCase(), g]));
            const list = [...new Set(q.split(/[\s,;]+/).map((g) => g.trim()).filter(Boolean).map((g) => byLower.get(g.toLowerCase()) ?? g))];
            if (list.length) onPickMany(list);
            setQ("");
            setOpen(false);
            e.preventDefault();
          } else if (e.key === "Enter") {
            const exact = genes.find((g) => g.toLowerCase() === q.trim().toLowerCase());
            const g = exact ?? matches[hi];
            if (g) pick(g);
          } else if (e.key === "Escape") {
            setOpen(false);
            ref.current?.blur();
          }
        }}
        spellCheck={false}
        autoComplete="off"
      />
      {open && matches.length > 0 && (
        <ul className="gs-list">
          {matches.map((g, i) => (
            <li key={g} className={i === hi ? "hi" : ""} onMouseDown={() => pick(g)} onMouseEnter={() => setHi(i)}>
              {g}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
