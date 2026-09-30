import { Suspense } from "react";
import EmbedChatPage from "./chat-content";

export default function Page() {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center text-sm text-zinc-500">Loading…</div>}>
      <EmbedChatPage />
    </Suspense>
  );
}
