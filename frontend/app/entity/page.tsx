import { Suspense } from "react";
import EntityView from "@/components/EntityView";

export default function EntityPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-7xl px-6 py-10"><div className="skeleton h-10 w-1/2" /></div>}>
      <EntityView />
    </Suspense>
  );
}
