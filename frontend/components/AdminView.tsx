"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { Decision, EntityDetail, EntityRef, Gaps } from "@/lib/api";
import { api, entityHref, fmtDate, timeAgo } from "@/lib/api";
import { EntityChip, ExtLink, StatusPill } from "./bits";
import DecisionCard from "./DecisionCard";
import EntitySearch from "./EntitySearch";

type Tab = "review" | "gaps" | "write";

function useLocal(key: string, initial: string) {
  const [v, setV] = useState(() => {
    try {
      return (typeof window !== "undefined" && localStorage.getItem(key)) || initial;
    } catch {
      return initial;
    }
  });
  const set = (x: string) => {
    setV(x);
    try {
      localStorage.setItem(key, x);
    } catch {}
  };
  return [v, set] as const;
}

export default function AdminView() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) || "review";
  const [reviewer, setReviewer] = useLocal("wg-reviewer", "");
  const [queue, setQueue] = useState<Decision[] | null>(null);
  const [gaps, setGaps] = useState<Gaps | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadQueue = useCallback(() => api<Decision[]>("/api/admin/review").then(setQueue).catch((e) => setErr(e.message)), []);
  const loadGaps = useCallback(() => api<Gaps>("/api/admin/gaps").then(setGaps).catch((e) => setErr(e.message)), []);

  useEffect(() => {
    loadQueue();
    loadGaps();
  }, [loadQueue, loadGaps]);

  const go = (t: Tab, extra = "") => router.push(`/admin?tab=${t}${extra}`);

  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="kicker">Admin console</div>
          <h1 className="mt-2 font-serif text-4xl tracking-tight sm:text-5xl">Keep the reasoning honest</h1>
          <p className="mt-2 max-w-2xl text-ink-2">
            Review reasons the AI inferred, write down decisions that only live in someone&apos;s head, and see where the codebase
            has no recorded reasoning at all.
          </p>
        </div>
        <label className="text-sm">
          <span className="kicker mb-1 block">Reviewing as</span>
          <input
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            placeholder="your name"
            className="focus-ring w-44 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm outline-none"
          />
        </label>
      </div>

      <div className="mt-8 flex gap-1 border-b border-line">
        {(
          [
            ["review", `Review queue${queue ? ` · ${queue.length}` : ""}`],
            ["gaps", "Knowledge gaps"],
            ["write", "Write a decision"],
          ] as [Tab, string][]
        ).map(([t, label]) => (
          <button
            key={t}
            onClick={() => go(t)}
            className={`focus-ring -mb-px border-b-2 px-4 py-2.5 text-sm transition-colors ${
              tab === t ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {err && <div className="mt-6 card p-4 text-sm text-superseded">{err}</div>}

      <div className="mt-6">
        {tab === "review" && <ReviewQueue queue={queue} reviewer={reviewer} onDone={() => { loadQueue(); loadGaps(); }} />}
        {tab === "gaps" && <GapsPanel gaps={gaps} onDocument={(id) => go("write", `&entity=${encodeURIComponent(id)}`)} />}
        {tab === "write" && (
          <WriteForm
            initialEntity={params.get("entity")}
            author={reviewer}
            onSaved={(d) => {
              loadGaps();
              router.push(`/?q=${encodeURIComponent(`Why: ${d.title}?`)}`);
            }}
          />
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ review queue

function ReviewQueue({ queue, reviewer, onDone }: { queue: Decision[] | null; reviewer: string; onDone: () => void }) {
  if (!queue) return <div className="skeleton h-48 w-full" />;
  if (!queue.length)
    return (
      <div className="card border-dashed p-10 text-center">
        <div className="font-serif text-2xl">Queue is clear</div>
        <p className="mt-1 text-sm text-ink-2">Every AI-inferred reason has been reviewed.</p>
      </div>
    );
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-2">
        These reasons were <span className="font-medium text-inferred">inferred by AI</span>, either from code where nobody wrote the
        reason down, or from text where the quote couldn&apos;t be verified. Confirming one raises its confidence. Editing it records
        your wording.
      </p>
      {queue.map((d) => (
        <ReviewCard key={d.id} d={d} reviewer={reviewer} onDone={onDone} />
      ))}
    </div>
  );
}

function ReviewCard({ d, reviewer, onDone }: { d: Decision; reviewer: string; onDone: () => void }) {
  const [title, setTitle] = useState(d.title);
  const [decision, setDecision] = useState(d.decision);
  const [rationale, setRationale] = useState(d.rationale);
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const edited = title !== d.title || decision !== d.decision || rationale !== d.rationale;

  async function act(action: "confirm" | "edit" | "reject") {
    setBusy(action);
    try {
      await api(`/api/admin/decisions/${encodeURIComponent(d.id)}/review`, {
        method: "POST",
        body: JSON.stringify({ action, reviewer: reviewer || "maintainer", title, decision, rationale }),
      });
      setDone(action);
      setTimeout(onDone, 700);
    } finally {
      setBusy(null);
    }
  }

  if (done)
    return (
      <div className="card rise p-4 text-sm text-ink-2">
        {done === "reject" ? "Rejected" : "Confirmed"} · <span className="text-ink">{title}</span>
      </div>
    );

  const src = d.sources[0];
  return (
    <article className="card relative overflow-hidden">
      <span className="absolute inset-y-0 left-0 w-1 bg-inferred" />
      <div className="grid gap-5 p-5 pl-6 md:grid-cols-[1fr_260px]">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={d.status} />
            <span className="text-xs text-ink-3">
              {d.inferred_from === "code" ? "inferred from code + commit" : "inferred from discussion"} · {fmtDate(d.date)}
            </span>
          </div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="focus-ring w-full rounded-md border border-transparent bg-transparent font-serif text-[22px] leading-tight outline-none hover:border-line focus:border-line-strong"
          />
          <Field label="What the code does deliberately" value={decision} onChange={setDecision} rows={2} />
          <Field label="Why (AI's hypothesis)" value={rationale} onChange={setRationale} rows={3} />
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              disabled={!!busy}
              onClick={() => act(edited ? "edit" : "confirm")}
              className="focus-ring rounded-lg bg-ink px-3.5 py-2 text-sm font-medium text-bg hover:opacity-90 disabled:opacity-50"
            >
              {busy === "confirm" || busy === "edit" ? "Saving…" : edited ? "Save edits & confirm" : "Confirm reason"}
            </button>
            <button
              disabled={!!busy}
              onClick={() => act("reject")}
              className="focus-ring rounded-lg border border-line px-3.5 py-2 text-sm text-ink-2 hover:border-superseded hover:text-superseded disabled:opacity-50"
            >
              {busy === "reject" ? "Rejecting…" : "Reject"}
            </button>
          </div>
        </div>
        <aside className="space-y-4 border-t border-line pt-4 text-sm md:border-l md:border-t-0 md:pl-5 md:pt-0">
          {d.entities.length > 0 && (
            <div>
              <div className="kicker mb-1.5">Code</div>
              <div className="flex flex-wrap gap-1.5">
                {d.entities.slice(0, 4).map((e) => <EntityChip key={e.id} {...e} />)}
              </div>
            </div>
          )}
          <div>
            <div className="kicker mb-1.5">Evidence</div>
            <ExtLink href={src?.url ?? d.source_url} className="text-ink-2">
              {src?.title ?? d.source_ref}
            </ExtLink>
            {d.commits[0] && <div className="mt-1 font-mono text-xs text-ink-3">{d.commits[0].short.slice(0, 7)} · {fmtDate(d.commits[0].date)}</div>}
          </div>
          {d.people.length > 0 && (
            <div>
              <div className="kicker mb-1.5">Ask to verify</div>
              {d.people.slice(0, 2).map((p) => (
                <div key={p.id} className="text-ink-2">
                  <ExtLink href={p.url ?? undefined}>{p.name}</ExtLink>{" "}
                  <span className="text-xs text-ink-3">{p.active_recently ? "active" : timeAgo(p.last_active)}</span>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>
    </article>
  );
}

function Field({ label, value, onChange, rows = 2 }: { label: string; value: string; onChange: (v: string) => void; rows?: number }) {
  return (
    <label className="block">
      <span className="kicker mb-1 block">{label}</span>
      <textarea
        value={value}
        rows={rows}
        onChange={(e) => onChange(e.target.value)}
        className="focus-ring w-full resize-y rounded-lg border border-line bg-surface-2/40 px-3 py-2 text-[15px] leading-relaxed outline-none focus:border-line-strong"
      />
    </label>
  );
}

// ------------------------------------------------------------------ gaps

function GapsPanel({ gaps, onDocument }: { gaps: Gaps | null; onDocument: (id: string) => void }) {
  if (!gaps) return <div className="skeleton h-64 w-full" />;
  const s = gaps.stats;
  const answeredPct = s.questions.total ? Math.round((100 * s.questions.answered) / s.questions.total) : 0;
  return (
    <div className="space-y-8">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="card flex items-center gap-4 p-4">
          <Donut pct={s.coverage} />
          <div>
            <div className="text-sm font-medium">Busy code with reasons</div>
            <div className="text-xs text-ink-3">{s.busy_documented} of {s.busy} entities changed 3+ times</div>
          </div>
        </div>
        <Tile value={gaps.hotspots.length} label="Undocumented hotspots" note="high churn, no recorded reason" tone="inferred" />
        <Tile value={gaps.concentration.length} label="Single-owner code" note="≥80% of live lines from one person" tone="superseded" />
        <Tile value={`${answeredPct}%`} label="Questions answered" note={`${s.questions.answered} of ${s.questions.total} asked`} />
      </div>

      {gaps.unanswered.length > 0 && (
        <Section title="Questions nobody could answer" note="Each one is a decision someone should write down.">
          <ul className="divide-y divide-line">
            {gaps.unanswered.map((q, i) => (
              <li key={i} className="flex flex-wrap items-center gap-3 py-3">
                <span className="flex-1 text-sm">“{q.text}”</span>
                <span className="text-xs text-ink-3">{timeAgo(q.asked_at)}</span>
                {q.entities[0] && (
                  <button onClick={() => onDocument(q.entities[0].id)} className="focus-ring rounded-md border border-line px-2.5 py-1 text-xs hover:border-accent">
                    Answer it →
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Undocumented hotspots" note="Code that keeps changing, but nothing in the history says why. Highest churn first.">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-ink-3">
                <th className="py-2 font-normal">Entity</th>
                <th className="py-2 font-normal">Changes</th>
                <th className="py-2 font-normal">Authors</th>
                <th className="py-2 font-normal">Last touched</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {gaps.hotspots.map((h) => (
                <tr key={h.id}>
                  <td className="py-2.5 pr-3">
                    <Link href={entityHref(h.id)} className="font-mono hover:text-accent-ink">{h.qualname.replace("config:", "")}</Link>
                    <div className="font-mono text-[11px] text-ink-3">{h.path}</div>
                  </td>
                  <td className="py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 rounded-full bg-surface-2">
                        <div className="h-1.5 rounded-full bg-inferred" style={{ width: `${Math.min(100, (h.churn / (gaps.hotspots[0]?.churn || 1)) * 100)}%` }} />
                      </div>
                      <span className="font-mono text-xs">{h.churn}</span>
                    </div>
                  </td>
                  <td className="py-2.5 font-mono text-xs">{h.authors}</td>
                  <td className="py-2.5 text-xs text-ink-2">{timeAgo(h.last_modified)}</td>
                  <td className="py-2.5 text-right">
                    {h.has_inferred && <span className="mr-2 rounded bg-inferred-soft px-1.5 py-0.5 text-[10px] text-inferred">AI guess pending</span>}
                    <button onClick={() => onDocument(h.id)} className="focus-ring rounded-md border border-line px-2.5 py-1 text-xs hover:border-accent">
                      Document
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Knowledge concentration" note="If this person leaves, the reasoning leaves with them.">
          <ul className="divide-y divide-line">
            {gaps.concentration.map((c) => (
              <li key={c.id} className="flex items-center gap-3 py-2.5 text-sm">
                <Link href={entityHref(c.id)} className="min-w-0 flex-1 truncate font-mono hover:text-accent-ink">
                  {c.qualname.replace("config:", "")}
                </Link>
                <span className="text-xs text-ink-2">{c.owner}</span>
                <span className="rounded bg-superseded-soft px-1.5 font-mono text-[11px] text-superseded">{c.share}%</span>
                <span className="w-16 text-right text-[11px] text-ink-3">{timeAgo(c.owner_last_active)}</span>
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Silent commits" note="Real code changes with no PR, no issue and a one-line message.">
          <ul className="divide-y divide-line">
            {gaps.silent_commits.map((c) => (
              <li key={c.short} className="py-2.5 text-sm">
                <div className="flex gap-2">
                  <ExtLink href={c.url} className="font-mono text-xs text-ink-2">{c.short.slice(0, 7)}</ExtLink>
                  <span className="truncate">{c.subject}</span>
                </div>
                <div className="mt-0.5 text-xs text-ink-3">
                  {c.author} · {fmtDate(c.date)} · {c.lines} lines · {c.ents.join(", ")}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="font-serif text-2xl leading-tight">{title}</h2>
      {note && <p className="mt-0.5 text-sm text-ink-2">{note}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Tile({ value, label, note, tone }: { value: number | string; label: string; note: string; tone?: "inferred" | "superseded" }) {
  return (
    <div className="card p-4">
      <div className={`font-serif text-4xl leading-none ${tone === "inferred" ? "text-inferred" : tone === "superseded" ? "text-superseded" : ""}`}>{value}</div>
      <div className="mt-2 text-sm font-medium">{label}</div>
      <div className="text-xs text-ink-3">{note}</div>
    </div>
  );
}

function Donut({ pct }: { pct: number }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 56 56" className="h-14 w-14 shrink-0" aria-label={`${pct}% coverage`}>
      <circle cx="28" cy="28" r={r} fill="none" stroke="var(--surface-3)" strokeWidth="6" />
      <circle
        cx="28" cy="28" r={r} fill="none" stroke="var(--explicit)" strokeWidth="6" strokeLinecap="round"
        strokeDasharray={`${(pct / 100) * c} ${c}`} transform="rotate(-90 28 28)"
      />
      <text x="28" y="32" textAnchor="middle" fill="var(--ink)" fontSize="12" fontFamily="var(--font-geist-mono)">
        {pct}%
      </text>
    </svg>
  );
}

// ------------------------------------------------------------------ write

function WriteForm({ initialEntity, author, onSaved }: { initialEntity: string | null; author: string; onSaved: (d: Decision) => void }) {
  const [entities, setEntities] = useState<EntityRef[]>([]);
  const [existing, setExisting] = useState<Decision[]>([]);
  const [replaces, setReplaces] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [decision, setDecision] = useState("");
  const [rationale, setRationale] = useState("");
  const [alts, setAlts] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!initialEntity) return;
    api<EntityDetail>(`/api/entities/${encodeURIComponent(initialEntity)}`)
      .then((r) => setEntities((prev) => (prev.some((e) => e.id === r.entity.id) ? prev : [...prev, r.entity])))
      .catch(() => {});
  }, [initialEntity]);

  useEffect(() => {
    Promise.all(entities.map((e) => api<EntityDetail>(`/api/entities/${encodeURIComponent(e.id)}`)))
      .then((rs) => {
        const seen = new Map<string, Decision>();
        rs.forEach((r) => r.decisions.forEach((d) => !d.superseded && seen.set(d.id, d)));
        setExisting([...seen.values()]);
      })
      .catch(() => {});
  }, [entities]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const d = await api<Decision>("/api/admin/decisions", {
        method: "POST",
        body: JSON.stringify({
          title,
          decision,
          rationale,
          alternatives: alts.split("\n").map((s) => s.trim()).filter(Boolean),
          author: author || "maintainer",
          entity_ids: entities.map((e) => e.id),
          supersedes: replaces,
        }),
      });
      onSaved(d);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setSaving(false);
    }
  }

  const valid = title.trim().length >= 3 && decision.trim().length >= 3 && entities.length > 0;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="card space-y-4 p-6">
        <div>
          <span className="kicker mb-1.5 block">Code this decision governs</span>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {entities.map((e) => (
              <span key={e.id} className="inline-flex items-center gap-1">
                <EntityChip {...e} />
                <button onClick={() => setEntities(entities.filter((x) => x.id !== e.id))} className="text-ink-3 hover:text-superseded" aria-label="remove">
                  ×
                </button>
              </span>
            ))}
          </div>
          <EntitySearch onPick={(e) => setEntities((p) => (p.some((x) => x.id === e.id) ? p : [...p, e]))} />
        </div>
        <label className="block">
          <span className="kicker mb-1 block">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Cap cookie size at 4093 bytes"
            className="focus-ring w-full rounded-lg border border-line bg-surface px-3 py-2 font-serif text-xl outline-none focus:border-line-strong"
          />
        </label>
        <Field label="What was decided" value={decision} onChange={setDecision} rows={2} />
        <Field label="Why" value={rationale} onChange={setRationale} rows={4} />
        <Field label="Alternatives considered (one per line)" value={alts} onChange={setAlts} rows={2} />

        {existing.length > 0 && (
          <div>
            <span className="kicker mb-1.5 block">Does this replace an existing decision?</span>
            <ul className="space-y-1.5">
              {existing.map((d) => (
                <li key={d.id}>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={replaces.includes(d.id)}
                      onChange={(e) => setReplaces(e.target.checked ? [...replaces, d.id] : replaces.filter((x) => x !== d.id))}
                      className="mt-1 accent-[var(--accent)]"
                    />
                    <span>
                      {d.title} <span className="text-xs text-ink-3">({fmtDate(d.date)})</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        )}

        {error && <div className="text-sm text-superseded">{error}</div>}
        <div className="flex items-center gap-3 pt-2">
          <button
            disabled={!valid || saving}
            onClick={save}
            className="focus-ring rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-bg hover:opacity-90 disabled:opacity-40"
          >
            {saving ? "Saving…" : "Record decision"}
          </button>
          <span className="text-xs text-ink-3">Saved as a maintainer note by {author || "maintainer"}; it&apos;s searchable straight away.</span>
        </div>
      </div>

      <aside className="space-y-4">
        <div className="card p-5 text-sm text-ink-2">
          <div className="font-serif text-xl text-ink">Why write it down here?</div>
          <p className="mt-2 leading-relaxed">
            A maintainer note becomes a <span className="font-medium text-authored">first-class decision</span> in the graph. It is
            linked to the code, embedded for search, and scored with the highest source confidence. Questions about this code
            stop coming back with “no recorded decision”.
          </p>
        </div>
        {existing.length > 0 && (
          <div className="space-y-3">
            <div className="kicker">Current reasoning on this code</div>
            {existing.slice(0, 2).map((d) => <DecisionCard key={d.id} d={d} />)}
          </div>
        )}
      </aside>
    </div>
  );
}
