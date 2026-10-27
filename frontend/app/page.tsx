import { Suspense } from "react";
import AskView from "@/components/AskView";

export default function Home() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-3xl px-6 pt-24"><div className="skeleton h-16 w-full" /></div>}>
      <AskView />
    </Suspense>
  );
}
