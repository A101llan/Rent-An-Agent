import { Suspense } from "react";
import HirePageContent from "./hire-content";

export default function HirePage() {
  return (
    <Suspense fallback={<div className="flex flex-1 items-center justify-center py-24 text-zinc-400">Loading...</div>}>
      <HirePageContent />
    </Suspense>
  );
}
