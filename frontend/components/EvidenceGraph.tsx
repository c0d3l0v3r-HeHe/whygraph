"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import type { GraphEdge, GraphNode } from "@/lib/api";
import { entityHref } from "@/lib/api";

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onSelectDecision?: (id: string) => void;
  height?: number;
};

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export default function EvidenceGraph({ nodes, edges, onSelectDecision, height = 440 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();

  useEffect(() => {
    let cy: import("cytoscape").Core | null = null;
    let cancelled = false;

    async function draw() {
      const cytoscape = (await import("cytoscape")).default;
      const dagre = (await import("cytoscape-dagre")).default;
      try {
        cytoscape.use(dagre);
      } catch {
        /* already registered */
      }
      if (cancelled || !ref.current) return;
      const c = {
        bg: cssVar("--surface"),
        bg2: cssVar("--surface-2"),
        ink: cssVar("--ink"),
        ink2: cssVar("--ink-2"),
        ink3: cssVar("--ink-3"),
        line: cssVar("--line-strong"),
        accent: cssVar("--accent"),
        explicit: cssVar("--explicit"),
        explicitSoft: cssVar("--explicit-soft"),
        confirmed: cssVar("--confirmed"),
        confirmedSoft: cssVar("--confirmed-soft"),
        authored: cssVar("--authored"),
        authoredSoft: cssVar("--authored-soft"),
        inferred: cssVar("--inferred"),
        inferredSoft: cssVar("--inferred-soft"),
        sup: cssVar("--superseded"),
        supSoft: cssVar("--superseded-soft"),
      };
      const font = getComputedStyle(document.body).fontFamily;
      const mono = cssVar("--font-geist-mono") || "monospace";

      const ids = new Set(nodes.map((n) => n.id));
      cy = cytoscape({
        container: ref.current,
        elements: [
          ...nodes.map((n) => ({
            data: {
              ...n,
              label: n.type === "decision" && n.cite ? `${n.cite} · ${trim(n.label, 34)}` : trim(n.label, 30),
            },
          })),
          ...edges
            .filter((e) => ids.has(e.source) && ids.has(e.target))
            .map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target, type: e.type } })),
        ],
        layout: { name: "dagre", rankDir: "LR", nodeSep: 14, rankSep: 46, padding: 16 } as never,
        minZoom: 0.3,
        maxZoom: 2.2,
        wheelSensitivity: 0.2,
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "font-family": font,
              "font-size": 11,
              color: c.ink,
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "wrap",
              "text-max-width": "130px",
              shape: "round-rectangle",
              width: "label",
              height: "label",
              padding: "8px",
              "background-color": c.bg,
              "border-width": 1,
              "border-color": c.line,
            },
          },
          {
            selector: 'node[type="question"]',
            style: { "background-color": c.accent, color: "#fff", "border-width": 0, "font-weight": 600, "text-max-width": "120px" },
          },
          { selector: 'node[type="entity"]', style: { "font-family": mono, "border-color": c.ink2, "border-width": 1.5 } },
          {
            selector: 'node[type="decision"]',
            style: { "background-color": c.explicitSoft, "border-color": c.explicit, "border-width": 1.5, "font-weight": 500, "text-max-width": "150px" },
          },
          { selector: 'node[type="decision"][status="inferred"]', style: { "background-color": c.inferredSoft, "border-color": c.inferred } },
          { selector: 'node[type="decision"][status="confirmed"]', style: { "background-color": c.confirmedSoft, "border-color": c.confirmed } },
          { selector: 'node[type="decision"][status="authored"]', style: { "background-color": c.authoredSoft, "border-color": c.authored } },
          {
            selector: 'node[type="decision"][?superseded]',
            style: { "background-color": c.supSoft, "border-color": c.sup, "border-style": "dashed", color: c.ink2 },
          },
          { selector: 'node[type="source"]', style: { "background-color": c.bg2, "font-size": 10, color: c.ink2, "font-family": mono } },
          { selector: 'node[type="issue"]', style: { "background-color": c.bg2, "font-size": 10, color: c.ink2, "font-family": mono, shape: "ellipse" } },
          { selector: 'node[type="issue"][?incident]', style: { "border-color": c.sup } },
          {
            selector: 'node[type="person"]',
            style: { shape: "ellipse", "background-color": c.bg, "font-size": 10, color: c.ink2, "border-style": "dotted" },
          },
          {
            selector: "edge",
            style: {
              width: 1.2,
              "line-color": c.line,
              "target-arrow-color": c.line,
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.7,
              "curve-style": "bezier",
            },
          },
          { selector: 'edge[type="SIMILAR"]', style: { "line-style": "dotted" } },
          {
            selector: 'edge[type="SUPERSEDES"]',
            style: { "line-color": c.sup, "target-arrow-color": c.sup, width: 2, "line-style": "dashed", label: "supersedes", "font-size": 9, color: c.sup, "text-background-color": c.bg, "text-background-opacity": 1, "text-background-padding": "2px" },
          },
          { selector: "node:active, node:selected", style: { "overlay-opacity": 0, "border-width": 2.5, "border-color": c.accent } },
        ],
      });
      cy.on("tap", "node", (evt) => {
        const d = evt.target.data();
        if (d.type === "decision") onSelectDecision?.(d.id);
        else if (d.type === "entity") router.push(entityHref(d.id));
        else if (d.url) window.open(d.url as string, "_blank", "noopener");
      });
      cy.on("mouseover", "node", () => ref.current && (ref.current.style.cursor = "pointer"));
      cy.on("mouseout", "node", () => ref.current && (ref.current.style.cursor = "default"));
    }

    draw();
    const obs = new MutationObserver(() => {
      cy?.destroy();
      draw();
    });
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      cancelled = true;
      obs.disconnect();
      cy?.destroy();
    };
  }, [nodes, edges, onSelectDecision, router]);

  return <div ref={ref} style={{ height }} className="w-full" role="img" aria-label="Evidence graph" />;
}

function trim(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
