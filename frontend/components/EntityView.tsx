"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { EntityDetail } from "@/lib/api";
import { api, fmtDate, fmtYear, timeAgo } from "@/lib/api";
import { ExtLink, STATUS_RAIL, kindShort } from "./bits";
import DecisionCard from "./DecisionCard";

export default function EntityView() {
  const id = useSearchParams().get("id") ?? "";
  const [loaded, setLoaded] = useState<{ id: string; data?: EntityDetail; error?: string } | null>(null);

  useEffect(() => {
    if (!id) return;
    api<EntityDetail>(`/api/entities/${encodeURIComponent(id)}`)
      .then((data) => setLoaded({ id, data }))
      .catch((e) => setLoaded({ id, error: String(e.message) }));
  }, [id]);

  const current = loaded?.id === id ? loaded : null;
  const data = current?.data ?? null;
  const error = current?.error ?? null;

  if (!id) return <Empty msg="No entity selected." />;
  if (error) return <Empty msg={error} />;
  if (!data)
    return (
      <div className="mx-auto max-w-7xl space-y-4 px-4 sm:px-6 py-10">
        <div className="skeleton h-10 w-1/2" />
        <div className="skeleton h-64 w-full" />
      </div>
    );

  const e = data.entity;
  const totalLines = data.owners.reduce((s, o) => s + o.lines, 0) || 1;
  const live = data.decisions.filter((d) => !d.superseded);

  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6 py-8">
      <div className="kicker">
        <Link href="/explore" className="hover:text-ink">Explore</Link> / {e.path}
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-2">
        <h1 className="font-mono text-2xl font-medium tracking-tight sm:text-3xl">{e.qualname.replace("config:", "")}</h1>
        <span className="rounded-md bg-surface-2 px-2 py-0.5 font-mono text-xs text-ink-2">{e.kind}</span>
        {!e.alive && <span className="rounded-md bg-superseded-soft px-2 py-0.5 text-xs text-superseded">removed from HEAD</span>}
        <ExtLink href={e.github_url} className="ml-auto text-sm text-ink-2">View on GitHub ↗</ExtLink>
      </div>
      {e.doc && <p className="mt-2 max-w-3xl text-ink-2">{e.doc}</p>}

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat value={data.decisions.length} label="Decisions" note={`${live.length} still current`} />
        <Stat value={e.churn ?? 0} label="Commits changed it" note={`last ${timeAgo(e.last_modified)}`} />
        <Stat value={e.author_count ?? 0} label="Authors" note={data.owners[0] ? `top: ${data.owners[0].name}` : ""} />
        <Stat value={`L${e.start_line}–${e.end_line}`} label="Location" note={e.path} mono />
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-12">
        <section className="lg:col-span-7">
          <h2 className="kicker mb-3">Decision timeline</h2>
          {data.decisions.length === 0 ? (
            <div className="card border-dashed p-6 text-sm text-ink-2">
              <div className="font-serif text-xl text-ink">No recorded reasoning</div>
              <p className="mt-1">
                Nobody wrote down why this code is the way it is. It has changed {e.churn} times across {e.author_count} authors.
              </p>
              <Link
                href={`/admin?tab=write&entity=${encodeURIComponent(e.id)}`}
                className="focus-ring mt-4 inline-flex rounded-lg bg-ink px-3 py-2 text-xs font-medium text-bg"
              >
                Document this decision →
              </Link>
            </div>
          ) : (
            <ol className="relative space-y-4 border-l border-line pl-6">
              {data.decisions.map((d) => (
                <li key={d.id} className="relative">
                  <span className={`absolute -left-[31px] top-6 h-3 w-3 rounded-full ring-4 ring-bg ${STATUS_RAIL[d.superseded ? "superseded" : d.status]}`} />
                  <div className="mb-1.5 font-mono text-xs text-ink-3">{fmtYear(d.date)}</div>
                  <DecisionCard d={d} onJump={(id) => document.getElementById(`dec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })} />
                </li>
              ))}
            </ol>
          )}
        </section>

        <aside className="space-y-5 lg:col-span-5">
          {data.code && (
            <section className="card overflow-hidden">
              <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
                <span className="kicker">Current code</span>
                <span className="font-mono text-[11px] text-ink-3">{kindShort(e.kind)} · {e.path}</span>
              </div>
              <pre className="max-h-[420px] overflow-auto bg-surface-2/50 py-3 text-[12.5px] leading-[1.6]">
                {data.code.split("\n").map((line, i) => (
                  <div key={i} className="flex px-4 hover:bg-surface-3/60">
                    <span className="w-10 shrink-0 select-none pr-3 text-right font-mono text-ink-3">{e.start_line + i}</span>
                    <code className="font-mono whitespace-pre text-ink">{line || " "}</code>
                  </div>
                ))}
              </pre>
            </section>
          )}

          <section className="card p-4">
            <div className="kicker mb-3">Who owns the live lines (git blame)</div>
            <ul className="space-y-2.5">
              {data.owners.map((o) => (
                <li key={o.name}>
                  <div className="flex items-baseline justify-between text-sm">
                    <ExtLink href={o.url}>{o.name}</ExtLink>
                    <span className="text-xs text-ink-3">
                      {Math.round((100 * o.lines) / totalLines)}% · active {timeAgo(o.last_active)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface-2">
                    <div className="h-1.5 rounded-full bg-accent" style={{ width: `${(100 * o.lines) / totalLines}%` }} />
                  </div>
                </li>
              ))}
              {data.owners.length === 0 && <li className="text-sm text-ink-3">No live lines.</li>}
            </ul>
          </section>

          <section className="card p-4">
            <div className="kicker mb-3">Change history</div>
            <ul className="space-y-2">
              {data.history.map((c) => (
                <li key={c.short} className="grid grid-cols-[64px_1fr] gap-2 text-sm">
                  <ExtLink href={c.url} className="font-mono text-xs text-ink-2">{c.short.slice(0, 7)}</ExtLink>
                  <div className="min-w-0">
                    <div className="truncate">{c.subject}</div>
                    <div className="text-xs text-ink-3">
                      {fmtDate(c.date)} · {c.author}
                      {c.pr ? ` · PR #${c.pr}` : ""} · {c.lines} lines
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}

function Stat({ value, label, note, mono }: { value: number | string; label: string; note?: string; mono?: boolean }) {
  return (
    <div className="card p-4">
      <div className={mono ? "font-mono text-lg" : "font-serif text-3xl leading-none"}>{value}</div>
      <div className="mt-1.5 text-sm font-medium">{label}</div>
      {note && <div className="truncate text-xs text-ink-3">{note}</div>}
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return <div className="mx-auto max-w-3xl px-6 py-24 text-center text-ink-2">{msg}</div>;
}

