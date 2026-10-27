"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Overview } from "@/lib/api";
import Logo from "./Logo";

const links = [
  { href: "/", label: "Ask" },
  { href: "/explore", label: "Explore" },
  { href: "/admin", label: "Admin" },
];

export default function Nav() {
  const path = usePathname();
  const [ov, setOv] = useState<Overview | null>(null);
  useEffect(() => {
    api<Overview>("/api/overview").then(setOv).catch(() => {});
  }, [path]);

  function toggleTheme() {
    const current =
      document.documentElement.dataset.theme ??
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("wg-theme", next);
    } catch {}
  }

  const pending = ov?.counts?.pending ?? 0;

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 h-14 flex items-center gap-4">
        <Link href="/" className="flex items-center gap-2 focus-ring rounded-md">
          <Logo className="h-6 w-6 text-accent" />
          <span className="hidden font-serif text-[22px] leading-none tracking-tight min-[400px]:inline">WhyGraph</span>
        </Link>
        {ov && (
          <a
            href={`https://github.com/${ov.repo}`}
            target="_blank"
            rel="noreferrer"
            className="hidden md:inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-ink-2 hover:border-line-strong"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-explicit" />
            <span className="font-mono">{ov.repo}</span>
            <span className="text-ink-3">· {ov.counts.commits?.toLocaleString()} commits</span>
          </a>
        )}
        <nav className="ml-auto flex items-center gap-0.5 sm:gap-1">
          {links.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={`focus-ring relative whitespace-nowrap rounded-lg px-2.5 py-1.5 text-sm transition-colors sm:px-3 ${
                  active ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink"
                }`}
              >
                {l.label}
                {l.href === "/admin" && pending > 0 && (
                  <span className="ml-1.5 inline-flex min-w-5 justify-center rounded-full bg-inferred-soft px-1.5 text-[11px] font-medium text-inferred">
                    {pending}
                  </span>
                )}
              </Link>
            );
          })}
          <button
            onClick={toggleTheme}
            aria-label="Toggle colour theme"
            className="focus-ring ml-1 grid h-8 w-8 place-items-center rounded-lg text-ink-2 hover:bg-surface-2 hover:text-ink"
          >
            <svg viewBox="0 0 24 24" className="theme-sun h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <svg viewBox="0 0 24 24" className="theme-moon h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />
            </svg>
          </button>
        </nav>
      </div>
    </header>
  );
}
