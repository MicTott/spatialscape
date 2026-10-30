/** The side panel's containers: a `Group` is one of the five bars (open state remembered per browser), a `LayerRow`
 * one drawn thing inside a group, with a switch or a dot and a one-line summary. */
import { useState } from "react";
import type React from "react";

function groupOpenKey(id: string) {
  return `sscape.group.${id}`;
}

export function Group({ id, title, summary, on, onToggle, defaultOpen = false, children }: { id: string; title: string; summary?: string; on?: boolean; onToggle?: (v: boolean) => void; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(groupOpenKey(id));
      return v == null ? defaultOpen : v === "1";
    } catch {
      return defaultOpen;
    }
  });
  const toggle = () => {
    setOpen((o) => {
      try {
        localStorage.setItem(groupOpenKey(id), o ? "0" : "1");
      } catch {
        /* private mode */
      }
      return !o;
    });
  };
  return (
    <div className={`group${open ? " open" : ""}${on === false ? " off" : ""}`}>
      <div className="group-head" role="button" tabIndex={0} aria-expanded={open} onClick={toggle} onKeyDown={(e) => (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ") ? (e.preventDefault(), toggle()) : undefined)}>
        <span className="chev" aria-hidden="true"><svg viewBox="0 0 16 16"><path d="M5.5 3.5 10 8l-4.5 4.5" /></svg></span>
        <span className="group-title">{title}</span>
        {!open && summary && <span className="group-summary">{summary}</span>}
        {onToggle && (
          <input type="checkbox" className="group-switch" aria-label={title} checked={!!on} onClick={(e) => e.stopPropagation()} onChange={(e) => onToggle(e.target.checked)} title={`${on ? "hide" : "show"} ${title.toLowerCase()}`} />
        )}
      </div>
      {open && <div className="group-body">{children}</div>}
    </div>
  );
}

export function LayerRow({ name, on, onToggle, summary, title, children }: { name: string; on?: boolean; onToggle?: (v: boolean) => void; summary?: string; title?: string; children?: React.ReactNode }) {
  const open = onToggle ? on : true;
  return (
    <div className={`layer${open ? " on" : ""}`} title={title}>
      <label className="layer-head">
        {onToggle ? <input type="checkbox" checked={!!on} onChange={(e) => onToggle(e.target.checked)} /> : <span className="layer-dot" />}
        <span className="layer-name">{name}</span>
        {summary && <span className="muted small">{summary}</span>}
      </label>
      {open && children && <div className="layer-body">{children}</div>}
    </div>
  );
}
