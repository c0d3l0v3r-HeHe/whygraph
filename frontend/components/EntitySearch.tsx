"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { EntityRef } from "@/lib/api";
import { api } from "@/lib/api";
import { kindShort } from "./bits";

export default function EntitySearch({
  onPick,
  placeholder = "Search functions, classes, config keys…",
  autoFocus = false,
}: {
  onPick: (e: EntityRef) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<EntityRef[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const listId = useId();

  const visible = q.trim().length >= 2 ? items : [];

  useEffect(() => {
    if (q.trim().length < 2) return;
    const t = setTimeout(() => {
      api<{ e: EntityRef }[]>(`/api/entities/search?q=${encodeURIComponent(q.trim())}`)
        .then((r) => {
          setItems(r.map((x) => x.e));
          setActive(0);
          setOpen(true);
        })
        .catch(() => {});
    }, 150);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const h = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  function pick(e: EntityRef) {
    onPick(e);
    setQ("");
    setOpen(false);
  }

  return (
    <div ref={box} className="relative">
      <input
        value={q}
        autoFocus={autoFocus}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => visible.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, visible.length - 1));
          else if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          else if (e.key === "Enter" && visible[active]) {
            e.preventDefault();
            pick(visible[active]);
          } else if (e.key === "Escape") setOpen(false);
        }}
        placeholder={placeholder}
        className="focus-ring w-full rounded-lg border border-line bg-surface px-3 py-2 font-mono text-sm outline-none placeholder:font-sans placeholder:text-ink-3 focus:border-line-strong"
        role="combobox"
        aria-expanded={open && visible.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
      />
      {open && visible.length > 0 && (
        <ul id={listId} className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-lg border border-line bg-surface py-1 shadow-pop" role="listbox">
          {visible.map((it, i) => (
            <li key={it.id}>
              <button
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => pick(it)}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${i === active ? "bg-surface-2" : ""}`}
              >
                <span className="w-9 shrink-0 font-mono text-[10px] uppercase text-ink-3">{kindShort(it.kind)}</span>
                <span className="truncate font-mono">{it.qualname.replace("config:", "")}</span>
                <span className="ml-auto shrink-0 font-mono text-[11px] text-ink-3">{it.path}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
