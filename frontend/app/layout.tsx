import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import { Suspense } from "react";
import Nav from "@/components/Nav";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const instrument = Instrument_Serif({
  variable: "--font-instrument",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "WhyGraph — the reasoning behind the code",
  description:
    "Ask why code is the way it is. Answers come from a Neo4j graph of commits, pull requests, issues and design docs, with evidence and confidence attached.",
};

const themeScript = `try{var t=localStorage.getItem('wg-theme');if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${instrument.variable} h-full`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <Suspense fallback={<div className="h-14 border-b border-line" />}>
          <Nav />
        </Suspense>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-line mt-16">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 py-6 flex flex-wrap gap-x-6 gap-y-2 items-center justify-between text-xs text-ink-3">
            <span>
              WhyGraph · built for hackFront India 2026 · AI &amp; Developer Tools · Neo4j track
            </span>
            <span className="font-mono">Neo4j · GraphRAG · Gemini · bge-small · tree-sitter</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
