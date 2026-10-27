"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AskResult, Overview, Person } from "@/lib/api";
import { api, fmtDate, timeAgo } from "@/lib/api";
import { AnswerText, ConfidenceMeter, EntityChip, ExtLink, PersonRow } from "./bits";
import DecisionCard from "./DecisionCard";
import EvidenceGraph from "./EvidenceGraph";

const STEPS = [
  "Resolving code entities in your question",
  "Walking the decision graph in Neo4j",
  "Checking which decisions were superseded",
  "Scoring evidence from git blame and sources",
  "Writing a cited answer",
];

export default function AskView() {
  const params = useSearchParams();
  const router = useRouter();
  const q = params.get("q") ?? "";
  const [input, setInput] = useState(q);
  const [prevQ, setPrevQ] = useState(q);
  if (q !== prevQ) {
    // the URL changed (example clicked, back button): show that question in the box
    setPrevQ(q);
    setInput(q);
  }
  const [res, setRes] = useState<{ q: string; result?: AskResult; error?: string } | null>(null);
  const [tick, setTick] = useState<{ q: string; n: number }>({ q: "", n: 0 });
  const [examples, setExamples] = useState<string[]>([]);
  const [ov, setOv] = useState<Overview | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api<{ examples: string[] }>("/api/examples").then((r) => setExamples(r.examples)).catch(() => {});
    api<Overview>("/api/overview").then(setOv).catch(() => {});
  }, []);

  useEffect(() => {
    if (!q) return;
    let alive = true;
    const timer = setInterval(() => setTick((t) => ({ q, n: t.q === q ? t.n + 1 : 1 })), 1100);
    api<AskResult>("/api/ask", { method: "POST", body: JSON.stringify({ question: q }) })
      .then((result) => alive && setRes({ q, result }))
      .catch((e) => alive && setRes({ q, error: String(e.message ?? e) }))
      .finally(() => clearInterval(timer));
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [q]);

  const current = res?.q === q ? res : null;
  const loading = !!q && !current;
  const result = current?.result ?? null;
  const error = current?.error ?? null;
  const step = tick.q === q ? Math.min(tick.n, STEPS.length - 1) : 0;

  function submit(text: string) {
    const t = text.trim();
    if (t.length < 3) return;
    router.push(`/?q=${encodeURIComponent(t)}`);
  }

  const jump = useCallback((id: string) => {
    const el = document.getElementById(`dec-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlight(id);
      setTimeout(() => setHighlight(null), 1800);
    }
  }, []);

  const jumpCite = useCallback(
    (cite: string) => {
      const d = result?.decisions.find((x) => x.cite === cite);
      if (d) jump(d.id);
    },
    [result, jump],
  );

  const people = useMemo(() => {
    if (!result) return [] as Person[];
    const seen = new Map<string, Person>();
    for (const d of result.decisions.filter((d) => !d.superseded)) {
      for (const p of d.people) {
        const prev = seen.get(p.id);
        if (!prev || prev.score < p.score) seen.set(p.id, p);
      }
    }
    return [...seen.values()].sort((a, b) => Number(b.active_recently) - Number(a.active_recently) || b.score - a.score).slice(0, 5);
  }, [result]);

  const askBox = (big: boolean) => (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit(input);
      }}
      className={`card flex items-end gap-2 p-2 transition-shadow focus-within:shadow-pop focus-within:border-line-strong ${big ? "p-2.5" : ""}`}
    >
      <textarea
        ref={inputRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit(input);
          }
        }}
        rows={big ? 2 : 1}
        style={{ fieldSizing: "content" } as React.CSSProperties}
        placeholder="Why is MAX_COOKIE_SIZE 4093?  Why are async views run in a thread?"
        className={`max-h-40 min-w-0 flex-1 resize-none bg-transparent px-3 py-2 outline-none placeholder:text-ink-3 ${big ? "min-h-16 text-lg" : "text-[15px]"}`}
        aria-label="Ask why the code is like this"
      />
      <button
        type="submit"
        disabled={loading || input.trim().length < 3}
        className="focus-ring shrink-0 rounded-[10px] bg-ink px-4 py-2.5 text-sm font-medium text-bg transition-opacity hover:opacity-90 disabled:opacity-40"
      >
        {loading ? "Tracing…" : "Ask why"}
      </button>
    </form>
  );

  // ---------- idle: hero ----------
  if (!q) {
    return (
      <div className="paper">
        <section className="mx-auto max-w-3xl px-4 sm:px-6 pt-16 pb-12 sm:pt-24">
          <div className="kicker rise">
            {ov ? `${ov.repo} · ${fmtDate(ov.first_commit).split(" ").pop()}–${fmtDate(ov.last_commit).split(" ").pop()}` : "pallets/flask"}
          </div>
          <h1 className="rise mt-3 font-serif text-[44px] leading-[1.02] tracking-tight sm:text-[64px]">
            Why is the code <em className="text-accent">like this?</em>
          </h1>
          <p className="rise mt-5 max-w-2xl text-[17px] leading-relaxed text-ink-2">
            Ask about any function, config key or behaviour. Every answer is traced through a graph of commits, pull requests,
            issues and design notes, and cites the decision behind the code. It tells you when that decision was later overruled,
            and it says so when nobody wrote the reason down.
          </p>
          <div className="rise mt-8">{askBox(true)}</div>
          {examples.length > 0 && (
            <div className="rise mt-4 flex flex-wrap gap-2">
              {examples.map((e) => (
                <button
                  key={e}
                  onClick={() => submit(e)}
                  className="focus-ring rounded-full border border-line bg-surface px-3 py-1.5 text-left text-[13px] text-ink-2 transition-colors hover:border-accent hover:text-ink"
                >
                  {e}
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="mx-auto max-w-5xl px-4 sm:px-6 pb-8">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { k: "decisions", label: "Decisions extracted", note: "with verified quotes" },
              { k: "supersessions", label: "Overrides detected", note: "older reasoning flagged" },
              { k: "prs", label: "Pull requests read", note: ov ? `+ ${ov.counts.issues?.toLocaleString()} issues` : "" },
              { k: "pending", label: "Awaiting review", note: "AI-inferred reasons" },
            ].map((s) => (
              <div key={s.k} className="card p-4">
                <div className="font-serif text-4xl leading-none">{ov ? (ov.counts[s.k] ?? 0).toLocaleString() : "—"}</div>
                <div className="mt-2 text-sm font-medium">{s.label}</div>
                <div className="text-xs text-ink-3">{s.note}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="mx-auto max-w-5xl px-4 sm:px-6 pb-16">
          <div className="kicker mb-4">How an answer is built</div>
          <ol className="grid gap-3 md:grid-cols-4">
            {[
              ["Resolve", "Names in your question are matched to functions, classes and config keys parsed with tree-sitter."],
              ["Traverse", "Neo4j walks from code to the commits that changed it, the PRs and issues behind them, and the people involved."],
              ["Supersede", "git blame shows whose code is still live; reverts and later decisions mark old reasoning as overruled."],
              ["Score", "Confidence comes from graph facts: stated vs inferred, verified quote, live code, linked issues."],
            ].map(([t, d], i) => (
              <li key={t} className="card p-4">
                <div className="flex items-center gap-2">
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-accent-soft font-mono text-xs text-accent-ink">{i + 1}</span>
                  <span className="font-medium">{t}</span>
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-2">{d}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>
    );
  }

  // ---------- question asked ----------
  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6 py-6">
      <div className="mx-auto max-w-3xl">{askBox(false)}</div>

      {loading && (
        <div className="mx-auto mt-8 max-w-3xl">
          <div className="card p-6">
            <div className="kicker mb-4">Tracing the reasoning</div>
            <ol className="space-y-2.5">
              {STEPS.map((s, i) => (
                <li key={s} className={`flex items-center gap-3 text-sm transition-opacity ${i <= step ? "opacity-100" : "opacity-35"}`}>
                  <span
                    className={`grid h-5 w-5 place-items-center rounded-full text-[10px] ${
                      i < step ? "bg-explicit-soft text-explicit" : i === step ? "bg-accent-soft text-accent-ink" : "bg-surface-2 text-ink-3"
                    }`}
                  >
                    {i < step ? "✓" : i + 1}
                  </span>
                  {s}
                  {i === step && <span className="ml-1 h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />}
                </li>
              ))}
            </ol>
            <div className="mt-6 space-y-2">
              <div className="skeleton h-4 w-11/12" />
              <div className="skeleton h-4 w-10/12" />
              <div className="skeleton h-4 w-7/12" />
            </div>
          </div>
        </div>
      )}

      {error && !loading && (
        <div className="mx-auto mt-8 max-w-3xl card border-superseded/40 p-5 text-sm">
          <div className="font-medium text-superseded">Something went wrong</div>
          <p className="mt-1 text-ink-2">{error}. Is the API running on port 8000?</p>
        </div>
      )}

      {result && !loading && (
        <div className="rise mt-6 grid gap-6 lg:grid-cols-12">
          <div className="space-y-5 lg:col-span-7">
            <section className={`card p-6 ${result.insufficient ? "border-dashed border-line-strong bg-surface-2/40 shadow-none" : ""}`}>
              <div className="kicker">Answer</div>
              <h2 className="mt-1.5 font-serif text-[28px] leading-tight">{result.question}</h2>
              <div className="prose-answer mt-4 text-[16.5px] leading-[1.7] text-ink">
                <AnswerText text={result.answer} onCite={jumpCite} citeIds={result.decisions.map((d) => d.cite!)} />
              </div>
              {!result.insufficient && (
                <div className="mt-6 border-t border-line pt-5">
                  <ConfidenceMeter c={result.confidence} />
                </div>
              )}
              {result.insufficient && (
                <div className="mt-6 grid gap-5 border-t border-line pt-5 sm:grid-cols-2">
                  <div>
                    <div className="kicker mb-2">Last changed by</div>
                    {result.fallback?.commits.length ? (
                      <ul className="space-y-1.5 text-sm">
                        {result.fallback.commits.map((c) => (
                          <li key={c.short} className="flex gap-2">
                            <ExtLink href={c.url} className="font-mono text-xs text-ink-2">{c.short.slice(0, 7)}</ExtLink>
                            <span className="truncate text-ink-2">{c.subject}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-ink-3">No code entity matched this question.</p>
                    )}
                  </div>
                  <div>
                    <div className="kicker mb-2">Owns the live lines</div>
                    <ul className="space-y-1 text-sm">
                      {result.fallback?.people.map((p) => (
                        <li key={p.name} className="flex justify-between gap-2">
                          <ExtLink href={p.url}>{p.name}</ExtLink>
                          <span className="text-xs text-ink-3">{p.lines} lines · {timeAgo(p.last_active)}</span>
                        </li>
                      ))}
                    </ul>
                    {result.entities[0] && (
                      <Link
                        href={`/admin?tab=write&entity=${encodeURIComponent(result.entities[0].id)}`}
                        className="focus-ring mt-4 inline-flex rounded-lg bg-ink px-3 py-2 text-xs font-medium text-bg hover:opacity-90"
                      >
                        Document this decision →
                      </Link>
                    )}
                  </div>
                </div>
              )}
            </section>

            {result.decisions.length > 0 && (
              <section>
                <div className="mb-3 flex items-baseline justify-between">
                  <h3 className="kicker">
                    Evidence chain · {result.decisions.length} decision{result.decisions.length === 1 ? "" : "s"}
                  </h3>
                  <span className="text-xs text-ink-3">{(result.elapsed_ms / 1000).toFixed(1)}s</span>
                </div>
                <div className="space-y-4">
                  {result.decisions.map((d, i) => (
                    <DecisionCard key={d.id} d={d} highlight={highlight === d.id} onJump={jump} defaultOpen={i === 0 && !result.insufficient} />
                  ))}
                </div>
              </section>
            )}
          </div>

          <aside className="space-y-5 lg:col-span-5">
            <div className="lg:sticky lg:top-20 space-y-5">
              <section className="card overflow-hidden">
                <div className="flex items-center justify-between border-b border-line px-4 py-3">
                  <div className="kicker">Evidence graph</div>
                  <div className="flex gap-3 text-[11px] text-ink-3">
                    <Legend cls="bg-explicit" label="stated" />
                    <Legend cls="bg-inferred" label="inferred" />
                    <Legend cls="bg-superseded" label="superseded" />
                  </div>
                </div>
                <EvidenceGraph nodes={result.graph.nodes} edges={result.graph.edges} onSelectDecision={jump} height={400} />
                <div className="border-t border-line px-4 py-2 text-[11px] text-ink-3">
                  Click a decision to jump to it · entities open their history · sources open on GitHub
                </div>
              </section>

              {people.length > 0 && (
                <section className="card p-4">
                  <div className="kicker mb-2">Who to ask</div>
                  <div className="-mx-2">{people.map((p) => <PersonRow key={p.id} p={p} />)}</div>
                </section>
              )}

              {result.entities.length > 0 && (
                <section className="card p-4">
                  <div className="kicker mb-2">Code in question</div>
                  <div className="flex flex-wrap gap-1.5">
                    {result.entities.map((e) => <EntityChip key={e.id} {...e} />)}
                  </div>
                </section>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

function Legend({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`h-2 w-2 rounded-sm ${cls}`} />
      {label}
    </span>
  );
}
