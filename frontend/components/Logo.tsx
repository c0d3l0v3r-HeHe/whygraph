/** Three linked nodes; the last one is open — the question the graph answers. */
export default function Logo({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} fill="none" aria-hidden>
      <path d="M8 22 L16 10 L24 22" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity="0.55" />
      <circle cx="8" cy="22" r="4" fill="currentColor" />
      <circle cx="16" cy="10" r="4" fill="currentColor" />
      <circle cx="24" cy="22" r="4" stroke="currentColor" strokeWidth="2.2" fill="var(--bg)" />
    </svg>
  );
}
