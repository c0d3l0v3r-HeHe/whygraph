"use client";

import { useState } from "react";
import type { Decision } from "@/lib/api";
import { fmtDate, sourceLabel } from "@/lib/api";
import { Avatar, ConfidenceMeter, EntityChip, ExtLink, STATUS_RAIL, StatusPill } from "./bits";

export default function DecisionCard({
  d,
  highlight = false,
  onJump,
  defaultOpen = false,
}: {
  d: Decision;
  highlight?: boolean;
  onJump?: (id: string) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const src = d.sources[0];
  const rail = STATUS_RAIL[d.superseded ? "superseded" : d.status];

  return (
    <article
      id={`dec-${d.id}`}
      className={`card relative overflow-hidden transition-all ${highlight ? "ring-2 ring-accent/60" : ""} ${
        d.superseded ? "opacity-80" : ""
      }`}
    >
      <span className={`absolute inset-y-0 left-0 w-1 ${rail}`} aria-hidden />
      <div className="p-5 pl-6">
        <header className="flex flex-wrap items-center gap-2">
          {d.cite && (
            <span className="rounded-md bg-accent-soft px-1.5 py-0.5 font-mono text-[11px] font-medium text-accent-ink">{d.cite}</span>
          )}
          <StatusPill status={d.status} superseded={d.superseded} />
          <span className="text-xs text-ink-3">{d.date ? fmtDate(d.date) : d.source_type === "doc" ? "current design docs" : "undated"}</span>
          <span className="text-xs text-ink-3">·</span>
          <ExtLink href={src?.url ?? d.source_url} className="text-xs text-ink-2">
            {src ? sourceLabel(src) : d.source_type === "human" ? `by ${d.created_by}` : d.source_ref}
          </ExtLink>
          <span className="ml-auto">
            <ConfidenceMeter c={d.confidence} compact />
          </span>
        </header>

        <h3 className={`mt-3 font-serif text-[22px] leading-tight ${d.superseded ? "line-through decoration-superseded/50" : ""}`}>
          {d.title}
        </h3>
        <p className="mt-1.5 text-[15px] leading-relaxed text-ink">{d.decision}</p>

        {d.rationale && (
          <div className="mt-3">
            <div className="kicker mb-1">Why</div>
            <p className="text-[15px] leading-relaxed text-ink-2">{d.rationale}</p>
          </div>
        )}

        {d.quote && d.status !== "authored" && (
          <blockquote className="mt-4 rounded-lg border border-line bg-surface-2/60 px-4 py-3">
            <p className="font-serif text-[17px] italic leading-snug text-ink">“{d.quote}”</p>
            <footer className="mt-2 flex items-center gap-2 text-xs text-ink-3">
              {d.quote_verified ? (
                <span className="inline-flex items-center gap-1 text-explicit">
                  <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor"><path d="M6.5 11.2 3.3 8l1-1 2.2 2.2 5.2-5.2 1 1z" /></svg>
                  verbatim, verified against source
                </span>
              ) : (
                <span className="text-inferred">quote not found verbatim in source</span>
              )}
              {src && <span>· {sourceLabel(src)}</span>}
            </footer>
          </blockquote>
        )}

        {d.superseded_by.length > 0 && (
          <div className="mt-4 rounded-lg border border-superseded/25 bg-superseded-soft px-4 py-3 text-sm">
            <div className="font-medium text-superseded">Superseded — this is no longer how the code works</div>
            {d.superseded_by.map((s) => (
              <button
                key={s.id}
                onClick={() => onJump?.(s.id)}
                className="focus-ring mt-1 block text-left text-ink hover:underline"
              >
                → <span className="font-medium">{s.title}</span>{" "}
                <span className="text-ink-3">({fmtDate(s.date)})</span>
                {s.reason && <span className="block text-xs text-ink-2">{s.reason}</span>}
              </button>
            ))}
          </div>
        )}
        {d.supersedes.length > 0 && (
          <div className="mt-3 text-sm text-ink-2">
            <span className="kicker mr-2">Replaces</span>
            {d.supersedes.map((s) => (
              <button key={s.id} onClick={() => onJump?.(s.id)} className="focus-ring mr-3 text-left line-through decoration-superseded/50 hover:text-ink">
                {s.title} <span className="no-underline text-ink-3">({fmtDate(s.date)})</span>
              </button>
            ))}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          {d.people.slice(0, 4).length > 0 && (
            <div className="flex items-center gap-2">
              <div className="flex -space-x-1.5">
                {d.people.slice(0, 4).map((p) => (
                  <Avatar key={p.id} login={p.login} name={p.name} size={22} />
                ))}
              </div>
              <span className="text-xs text-ink-2">
                {d.people[0].name}
                {d.people.length > 1 && <span className="text-ink-3"> +{d.people.length - 1}</span>}
              </span>
            </div>
          )}
          {d.issues.slice(0, 3).map((i) => (
            <ExtLink key={i.number} href={i.url} className="text-xs text-ink-2">
              {i.is_incident ? "⚠ " : ""}#{i.number}
            </ExtLink>
          ))}
          <button onClick={() => setOpen(!open)} className="focus-ring ml-auto text-xs font-medium text-ink-2 hover:text-ink">
            {open ? "Hide evidence" : "Full evidence"} {open ? "↑" : "↓"}
          </button>
        </div>

        {open && (
          <div className="rise mt-4 grid gap-5 border-t border-line pt-4 md:grid-cols-2">
            <div className="space-y-4">
              <section>
                <div className="kicker mb-2">Confidence breakdown</div>
                <ConfidenceMeter c={d.confidence} />
              </section>
              {d.alternatives && d.alternatives.length > 0 && (
                <section>
                  <div className="kicker mb-1.5">Alternatives considered</div>
                  <ul className="list-disc space-y-1 pl-4 text-sm text-ink-2">
                    {d.alternatives.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                </section>
              )}
            </div>
            <div className="space-y-4">
              {d.entities.length > 0 && (
                <section>
                  <div className="kicker mb-2">Code it governs</div>
                  <div className="flex flex-wrap gap-1.5">
                    {d.entities.slice(0, 8).map((e) => <EntityChip key={e.id} {...e} />)}
                  </div>
                </section>
              )}
              {d.issues.length > 0 && (
                <section>
                  <div className="kicker mb-1.5">Motivating issues</div>
                  <ul className="space-y-1 text-sm">
                    {d.issues.map((i) => (
                      <li key={i.number} className="flex gap-2">
                        <ExtLink href={i.url} className="font-mono text-xs text-ink-2">#{i.number}</ExtLink>
                        <span className="text-ink-2">{i.title}</span>
                        {i.is_incident && <span className="rounded bg-superseded-soft px-1 text-[10px] text-superseded">bug</span>}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {d.commits.length > 0 && (
                <section>
                  <div className="kicker mb-1.5">Implementing commits</div>
                  <ul className="space-y-1 text-sm">
                    {d.commits.slice(0, 5).map((c) => (
                      <li key={c.short} className="flex gap-2">
                        <ExtLink href={c.url} className="font-mono text-xs text-ink-2">{c.short?.slice(0, 7)}</ExtLink>
                        <span className="truncate text-ink-2">{c.subject}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
