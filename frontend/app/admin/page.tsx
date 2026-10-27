import { Suspense } from "react";
import AdminView from "@/components/AdminView";

export default function AdminPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-6xl px-6 py-10"><div className="skeleton h-12 w-1/2" /></div>}>
      <AdminView />
    </Suspense>
  );
}
