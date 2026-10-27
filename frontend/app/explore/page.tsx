"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EntityChip, StatusPill } from "@/components/bits";
import EntitySearch from "@/components/EntitySearch";
import type { Status } from "@/lib/api";
import { api, entityHref, fmtDate } from "@/lib/api";

type Row = {
  d: {
    id: string;
    title: string;
    decision: string;
    status: Status;
    date?: string;
    superseded?: boolean;
    source_type: string;
    source_ref: string;
    source_url?: string;
    kind: string;
  };
  ents: { id: string; qualname: string; kind: string }[];
  superseded_by: string[];
};

const FILTERS: { key: string; label: string; status?: string; superseded?: boolean }[] = [
  { key: "all", label: "All" },
  { key: "explicit", label: "Stated in source", status: "explicit" },
  { key: "inferred", label: "AI-inferred", status: "inferred" },
  { key: "confirmed", label: "Confirmed", status: "confirmed" },
  { key: "authored", label: "Maintainer notes", status: "authored" },
  { key: "superseded", label: "Superseded", superseded: true },
];

export default function ExplorePage() {
  const router = useRouter();
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);

  useEffect(() => {
    const f = FILTERS.find((x) => x.key === filter)!;
    const p = new URLSearchParams({ limit: "80" });
    if (f.status) p.set("status", f.status);
    if (f.superseded) p.set("superseded", "true");
    if (q.trim()) p.set("q", q.trim());
    const t = setTimeout(() => api<Row[]>(`/api/decisions?${p}`).then(setRows).catch(() => setRows([])), 150);
    return () => clearTimeout(t);
  }, [filter, q]);

  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
      <div className="kicker">Explore</div>
      <h1 className="mt-2 font-serif text-4xl tracking-tight sm:text-5xl">The decision ledger</h1>
      <p className="mt-3 max-w-2xl text-ink-2">
        Every decision WhyGraph found in the history, newest first. Open any piece of code to see its full timeline, who owns it,
        and which reasons are still current.
      </p>

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <div className="card p-4">
          <div className="kicker mb-2">Jump to code</div>
          <EntitySearch onPick={(e) => router.push(entityHref(e.id))} />
        </div>
        <div className="card p-4">
          <div className="kicker mb-2">Search decisions</div>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="session, async, JSON, deprecate…"
            className="focus-ring w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm outline-none placeholder:text-ink-3"
          />
        </div>
      </div>

      <div className="mt-6 flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`focus-ring rounded-full border px-3 py-1 text-[13px] transition-colors ${
              filter === f.key ? "border-ink bg-ink text-bg" : "border-line bg-surface text-ink-2 hover:border-line-strong"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="mt-5 divide-y divide-line overflow-hidden rounded-[14px] border border-line bg-surface">
        {rows === null &&
          Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="p-4">
              <div className="skeleton h-4 w-2/3" />
              <div className="skeleton mt-2 h-3 w-1/2" />
            </div>
          ))}
        {rows?.length === 0 && <div className="p-8 text-center text-sm text-ink-3">No decisions match.</div>}
        {rows?.map(({ d, ents, superseded_by }) => (
          <div key={d.id} className="grid gap-2 p-4 sm:grid-cols-[110px_1fr] hover:bg-surface-2/40">
            <div className="font-mono text-xs text-ink-3">{fmtDate(d.date)}</div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/?q=${encodeURIComponent(`Why: ${d.title}?`)}`}
                  className={`font-medium hover:text-accent-ink ${d.superseded ? "line-through decoration-superseded/50" : ""}`}
                >
                  {d.title}
                </Link>
                <StatusPill status={d.status} superseded={d.superseded} />
              </div>
              <p className="mt-1 line-clamp-2 text-sm text-ink-2">{d.decision}</p>
              {superseded_by.length > 0 && (
                <p className="mt-1 text-xs text-superseded">→ superseded by “{superseded_by[0]}”</p>
              )}
              {ents.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {ents.map((e) => <EntityChip key={e.id} {...e} />)}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
