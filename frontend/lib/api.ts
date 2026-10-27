export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Status = "explicit" | "confirmed" | "authored" | "inferred" | "rejected";
export type Level = "high" | "medium" | "low" | "insufficient";

export interface Factor {
  label: string;
  delta: number;
  ok: boolean | null;
}
export interface Confidence {
  score: number;
  level: Level;
  factors: Factor[];
}
export interface Person {
  id: string;
  name: string;
  login?: string | null;
  url?: string | null;
  last_active?: number | null;
  roles: string[];
  score: number;
  active_recently: boolean;
}
export interface Source {
  type: "PullRequest" | "Commit" | "DesignDoc" | "Issue";
  number?: number;
  sha?: string;
  title?: string;
  url?: string;
  date?: string;
}
export interface IssueRef {
  number: number;
  title: string;
  url: string;
  is_incident: boolean;
  date?: string;
}
export interface CommitRef {
  sha?: string;
  short: string;
  subject: string;
  url: string;
  date: string;
  lines?: number;
  pr?: number | null;
  author?: string;
}
export interface DecisionLink {
  id: string;
  title: string;
  date?: string;
  reason?: string;
  method?: string;
}
export interface EntityRef {
  id: string;
  qualname: string;
  kind: string;
  path: string;
  live_lines?: number | null;
  mentioned?: boolean;
  match?: string;
  churn?: number;
}
export interface Decision {
  id: string;
  title: string;
  decision: string;
  rationale: string;
  alternatives?: string[] | null;
  quote?: string | null;
  quote_verified?: boolean;
  status: Status;
  kind: string;
  date?: string | null;
  epoch?: number | null;
  source_type: string;
  source_ref: string;
  source_url?: string;
  live_lines?: number | null;
  created_by?: string;
  reviewed_by?: string;
  inferred_from?: string | null;
  sources: Source[];
  issues: IssueRef[];
  commits: CommitRef[];
  entities: EntityRef[];
  superseded_by: DecisionLink[];
  supersedes: DecisionLink[];
  refines: DecisionLink[];
  people: Person[];
  superseded: boolean;
  confidence: Confidence;
  relevance?: number;
  match?: string;
  cite?: string;
}
export interface GraphNode {
  id: string;
  type: "question" | "entity" | "decision" | "source" | "issue" | "person";
  label: string;
  [k: string]: unknown;
}
export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}
export interface AskResult {
  question: string;
  answer: string;
  insufficient: boolean;
  confidence: Confidence;
  entities: EntityRef[];
  decisions: Decision[];
  cited: string[];
  fallback: {
    commits: CommitRef[];
    people: { name: string; url?: string; last_active?: number; lines: number }[];
  } | null;
  graph: { nodes: GraphNode[]; edges: GraphEdge[] };
  elapsed_ms: number;
}
export interface Overview {
  repo: string;
  counts: Record<string, number>;
  first_commit: string;
  last_commit: string;
}
export interface EntityDetail {
  entity: EntityRef & {
    name: string;
    start_line: number;
    end_line: number;
    doc?: string;
    signature?: string;
    churn?: number;
    author_count?: number;
    last_modified?: number;
    alive: boolean;
    github_url: string;
  };
  decisions: Decision[];
  owners: { name: string; url?: string; last_active?: number; lines: number }[];
  history: CommitRef[];
  code: string;
}
export interface Gaps {
  stats: {
    total: number;
    documented: number;
    busy: number;
    busy_documented: number;
    coverage: number;
    decisions: Record<string, number>;
    questions: { total: number; answered: number };
  };
  hotspots: {
    id: string;
    qualname: string;
    kind: string;
    path: string;
    churn: number;
    authors: number;
    last_modified: number;
    has_inferred: boolean;
  }[];
  concentration: {
    id: string;
    qualname: string;
    kind: string;
    path: string;
    lines: number;
    share: number;
    owner: string;
    owner_last_active: number;
  }[];
  silent_commits: (CommitRef & { ents: string[]; author: string })[];
  unanswered: { text: string; asked_at: number; entities: { id: string; qualname: string }[] }[];
}

function adminHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const t = window.localStorage.getItem("wg-admin-token");
    return t ? { "x-admin-token": t } : {};
  } catch {
    return {};
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...adminHeaders(), ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const fmtDate = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" }) : "undated";

export const fmtYear = (iso?: string | null) => (iso ? new Date(iso).getFullYear().toString() : "—");

export const fmtEpoch = (e?: number | null) => (e ? fmtDate(new Date(e * 1000).toISOString()) : "—");

export const timeAgo = (e?: number | null) => {
  if (!e) return "unknown";
  const days = (Date.now() / 1000 - e) / 86400;
  if (days < 1) return "today";
  if (days < 45) return `${Math.round(days)}d ago`;
  if (days < 540) return `${Math.round(days / 30)}mo ago`;
  return `${(days / 365).toFixed(1)}y ago`;
};

export const avatar = (login?: string | null, size = 64) =>
  login ? `https://github.com/${login}.png?size=${size}` : null;

export const entityHref = (id: string) => `/entity?id=${encodeURIComponent(id)}`;

export function sourceLabel(s?: Source | null): string {
  if (!s) return "Unknown source";
  if (s.type === "PullRequest") return `PR #${s.number}`;
  if (s.type === "Commit") return `Commit ${(s.sha ?? "").slice(0, 7)}`;
  if (s.type === "DesignDoc") return "docs/design.rst";
  if (s.type === "Issue") return `Issue #${s.number}`;
  return s.type;
}
