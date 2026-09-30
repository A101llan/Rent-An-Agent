import { Suspense } from "react";
import EmbedDemoPage from "./demo-content";

export default function Page() {
  return (
    <Suspense fallback={<div className="p-8 text-zinc-500">Loading demo…</div>}>
      <EmbedDemoPage />
    </Suspense>
  );
}
