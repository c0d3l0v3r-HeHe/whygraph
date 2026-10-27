"use client";

import Link from "next/link";
import type { Confidence, Level, Person, Status } from "@/lib/api";
import { avatar, entityHref, timeAgo } from "@/lib/api";

const STATUS: Record<Status | "superseded", { label: string; cls: string; hint: string }> = {
  explicit: { label: "Stated in source", cls: "bg-explicit-soft text-explicit", hint: "The reason is written in the PR, issue, commit or doc, and the quote was verified." },
  confirmed: { label: "Reviewer confirmed", cls: "bg-confirmed-soft text-confirmed", hint: "An AI-inferred reason that a maintainer reviewed and confirmed." },
  authored: { label: "Maintainer note", cls: "bg-authored-soft text-authored", hint: "Written directly by a maintainer in the admin console." },
  inferred: { label: "AI-inferred", cls: "bg-inferred-soft text-inferred", hint: "The reason was inferred by AI and has not been reviewed yet." },
  rejected: { label: "Rejected", cls: "bg-surface-2 text-ink-3", hint: "A reviewer rejected this inference." },
  superseded: { label: "Superseded", cls: "bg-superseded-soft text-superseded", hint: "A later decision overrode this one." },
};

export function StatusPill({ status, superseded }: { status: Status; superseded?: boolean }) {
  const s = STATUS[superseded ? "superseded" : status] ?? STATUS.inferred;
  return (
    <span title={s.hint} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${s.cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {s.label}
    </span>
  );
}

export const STATUS_RAIL: Record<string, string> = {
  explicit: "bg-explicit",
  confirmed: "bg-confirmed",
  authored: "bg-authored",
  inferred: "bg-inferred",
  rejected: "bg-ink-3",
  superseded: "bg-superseded",
};

const LEVEL: Record<Level, { label: string; cls: string; bar: string }> = {
  high: { label: "High confidence", cls: "text-explicit", bar: "bg-explicit" },
  medium: { label: "Medium confidence", cls: "text-confirmed", bar: "bg-confirmed" },
  low: { label: "Low confidence", cls: "text-inferred", bar: "bg-inferred" },
  insufficient: { label: "Not enough evidence", cls: "text-ink-3", bar: "bg-ink-3" },
};

export function ConfidenceMeter({ c, compact = false }: { c: Confidence; compact?: boolean }) {
  const lv = LEVEL[c.level] ?? LEVEL.insufficient;
  const segments = 10;
  const filled = Math.round(c.score / 10);
  return (
    <div className={compact ? "" : "space-y-3"}>
      <div className="flex items-center gap-3">
        <div className="flex gap-[3px]" aria-hidden>
          {Array.from({ length: segments }).map((_, i) => (
            <span key={i} className={`h-2.5 w-2 rounded-[2px] ${i < filled ? lv.bar : "bg-surface-3"}`} />
          ))}
        </div>
        <span className={`text-sm font-medium ${lv.cls}`}>{lv.label}</span>
        <span className="font-mono text-xs text-ink-3">{c.score}/100</span>
      </div>
      {!compact && c.factors.length > 0 && (
        <ul className="space-y-1.5">
          {c.factors.map((f, i) => (
            <li key={i} className="flex items-start gap-2 text-[13px] leading-snug text-ink-2">
              <span
                className={`mt-[3px] grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full text-[9px] font-bold ${
                  f.ok === true ? "bg-explicit-soft text-explicit" : f.ok === false ? "bg-superseded-soft text-superseded" : "bg-surface-2 text-ink-3"
                }`}
              >
                {f.ok === true ? "✓" : f.ok === false ? "!" : "·"}
              </span>
              <span className="flex-1">{f.label}</span>
              <span className="font-mono text-[11px] text-ink-3">{f.delta > 0 ? `+${f.delta}` : f.delta}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Avatar({ login, name, size = 24 }: { login?: string | null; name?: string; size?: number }) {
  const src = avatar(login, size * 2);
  const initials = (name ?? "?").slice(0, 2).toUpperCase();
  return src ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" width={size} height={size} className="rounded-full border border-line bg-surface-2" style={{ width: size, height: size }} />
  ) : (
    <span
      className="grid place-items-center rounded-full border border-line bg-surface-2 font-mono text-[9px] text-ink-3"
      style={{ width: size, height: size }}
    >
      {initials}
    </span>
  );
}

const ROLE: Record<string, string> = { AUTHORED: "author", REVIEWED: "reviewer", COMMENTED: "discussed" };

export function PersonRow({ p }: { p: Person }) {
  const body = (
    <div className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-surface-2">
      <Avatar login={p.login} name={p.name} size={28} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{p.name}</div>
        <div className="text-xs text-ink-3">{p.roles.map((r) => ROLE[r] ?? r.toLowerCase()).join(" · ")}</div>
      </div>
      <span
        className={`rounded-full px-2 py-0.5 text-[11px] ${p.active_recently ? "bg-explicit-soft text-explicit" : "bg-surface-2 text-ink-3"}`}
        title="Last activity in this repository"
      >
        {p.active_recently ? "active" : timeAgo(p.last_active)}
      </span>
    </div>
  );
  return p.url ? (
    <a href={p.url} target="_blank" rel="noreferrer" className="block focus-ring rounded-lg">
      {body}
    </a>
  ) : (
    body
  );
}

export function EntityChip({ id, qualname, kind }: { id: string; qualname: string; kind: string }) {
  return (
    <Link
      href={entityHref(id)}
      className="focus-ring inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 font-mono text-xs text-ink hover:border-accent hover:text-accent-ink"
    >
      <span className="text-[10px] uppercase tracking-wide text-ink-3">{kindShort(kind)}</span>
      {qualname.replace("config:", "")}
    </Link>
  );
}

export function kindShort(kind: string) {
  return ({ function: "fn", method: "fn", class: "cls", attribute: "attr", constant: "const", config: "cfg", module: "mod" } as Record<string, string>)[kind] ?? kind;
}

export function ExtLink({ href, children, className = "" }: { href?: string; children: React.ReactNode; className?: string }) {
  if (!href) return <span className={className}>{children}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer" className={`focus-ring underline decoration-line-strong underline-offset-2 hover:decoration-accent hover:text-accent-ink ${className}`}>
      {children}
    </a>
  );
}

/** Minimal markdown: **bold**, `code`, [D1] citation chips. */
export function AnswerText({ text, onCite, citeIds }: { text: string; onCite?: (cite: string) => void; citeIds?: string[] }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[D\d+(?:,\s*D\d+)*\])/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="font-semibold">{p.slice(2, -2)}</strong>;
        if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
        const m = p.match(/^\[(D\d+(?:,\s*D\d+)*)\]$/);
        if (m) {
          return m[1].split(/,\s*/).map((c) => (
            <button
              key={`${i}-${c}`}
              onClick={() => onCite?.(c)}
              disabled={citeIds && !citeIds.includes(c)}
              className="focus-ring mx-0.5 inline-flex -translate-y-px items-center rounded-md border border-accent/30 bg-accent-soft px-1.5 font-mono text-[11px] font-medium text-accent-ink hover:border-accent"
            >
              {c}
            </button>
          ));
        }
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}
