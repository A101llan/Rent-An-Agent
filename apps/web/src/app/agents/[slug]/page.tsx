"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Bot, Check, Shield, Star } from "lucide-react";
import { api, formatPricingModel } from "@/lib/api";

export default function AgentDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const router = useRouter();

  const { data, isLoading } = useQuery({
    queryKey: ["agent", slug],
    queryFn: () => api.getAgent(slug),
  });

  if (isLoading) {
    return <div className="flex flex-1 items-center justify-center py-24 text-zinc-400">Loading...</div>;
  }

  if (!data) {
    return <div className="flex flex-1 items-center justify-center py-24 text-zinc-400">Agent not found</div>;
  }

  const { agent, reviews } = data;
  const defaultPlan = agent.pricing_plans[0];

  return (
    <div className="mx-auto max-w-7xl px-6 py-12">
      <div className="grid gap-8 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="flex items-start gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-indigo-600/20">
              <Bot className="h-7 w-7 text-indigo-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-3xl font-bold">{agent.name}</h1>
                {agent.is_verified && (
                  <span className="rounded-full bg-green-900/30 px-2 py-0.5 text-xs text-green-400">Verified</span>
                )}
              </div>
              <p className="mt-1 text-zinc-400">
                by {agent.developer_name}
                {agent.developer_company && ` · ${agent.developer_company}`}
              </p>
              <div className="mt-2 flex items-center gap-2 text-sm">
                <Star className="h-4 w-4 fill-yellow-500 text-yellow-500" />
                <span>{agent.avg_rating.toFixed(1)}</span>
                <span className="text-zinc-500">({agent.review_count} reviews)</span>
                <span className="text-zinc-600">·</span>
                <span className="text-zinc-500 capitalize">{agent.category}</span>
              </div>
            </div>
          </div>

          <p className="mt-8 text-zinc-300 leading-relaxed">{agent.description}</p>

          <section className="mt-10">
            <h2 className="text-lg font-semibold">Capabilities</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {agent.capabilities.map((cap) => (
                <span key={cap} className="rounded-lg bg-zinc-800 px-3 py-1.5 text-sm capitalize">
                  {cap.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          </section>

          <section className="mt-8">
            <h2 className="text-lg font-semibold">Permissions Required</h2>
            <ul className="mt-3 space-y-2">
              {(agent.permissions.length ? agent.permissions : ["No special permissions"]).map((perm) => (
                <li key={perm} className="flex items-center gap-2 text-sm text-zinc-300">
                  <Check className="h-4 w-4 text-green-400" />
                  {perm === "No special permissions" ? perm : perm.replace(".", " — ")}
                </li>
              ))}
            </ul>
          </section>

          <section className="mt-8">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Customer Reviews</h2>
            </div>

            {/* Submit Review Form */}
            <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
              <h3 className="text-sm font-medium text-white mb-3">Leave a Review</h3>
              <ReviewForm agentId={agent.id} onSubmitted={() => window.location.reload()} />
            </div>

            <div className="mt-6 space-y-4">
              {reviews.length === 0 ? (
                <p className="text-xs text-zinc-500">No reviews yet. Be the first to leave one!</p>
              ) : (
                reviews.map((r) => (
                  <div key={r.id} className="rounded-lg border border-zinc-800 p-4">
                    <div className="flex items-center gap-2">
                      <span className="text-yellow-500 font-bold">{"★".repeat(r.rating)}</span>
                      <span className="font-medium">{r.title || "User Review"}</span>
                    </div>
                    <p className="mt-1 text-sm text-zinc-400">{r.body}</p>
                    <p className="mt-2 text-xs text-zinc-500">{r.customer_name}</p>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <div>
          <div className="sticky top-24 rounded-xl border border-zinc-800 bg-zinc-900/50 p-6">
            {defaultPlan && (
              <div className="mb-6">
                <p className="text-2xl font-bold text-indigo-400">
                  {formatPricingModel(defaultPlan.pricing_model, defaultPlan.price_minor)}
                </p>
                <p className="text-sm text-zinc-500">Standard plan</p>
              </div>
            )}

            <Link
              href={`/agents/${slug}/hire`}
              className="block w-full rounded-lg bg-indigo-600 py-3 text-center font-medium hover:bg-indigo-500"
            >
              HIRE AGENT
            </Link>

            <button
              onClick={() => router.push(`/agents/${slug}/hire?demo=1`)}
              className="mt-3 block w-full rounded-lg border border-zinc-700 py-3 text-center text-sm hover:bg-zinc-800"
            >
              TRY DEMO
            </button>

            <div className="mt-6 space-y-3 border-t border-zinc-800 pt-6 text-sm text-zinc-400">
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-indigo-400" />
                Isolated sandbox runtime
              </div>
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-indigo-400" />
                Source code never exposed
              </div>
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-indigo-400" />
                Session auto-expires
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ReviewForm({ agentId, onSubmitted }: { agentId: string; onSubmitted: () => void }) {
  const [rating, setRating] = useState(5);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await api.submitReview(agentId, { rating, title, body });
      onSubmitted();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit review");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {error && <p className="text-xs text-red-400">{error}</p>}
      <div className="flex items-center space-x-1">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onClick={() => setRating(star)}
            className={`text-lg transition-transform hover:scale-110 ${
              star <= rating ? "text-yellow-400" : "text-zinc-600"
            }`}
          >
            ★
          </button>
        ))}
      </div>
      <input
        type="text"
        placeholder="Review title (e.g. Great for support!)"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-xs text-white placeholder-zinc-500 outline-none focus:border-indigo-500"
      />
      <textarea
        rows={3}
        placeholder="Share your experience working with this agent..."
        value={body}
        onChange={(e) => setBody(e.target.value)}
        className="w-full rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-xs text-white placeholder-zinc-500 outline-none focus:border-indigo-500"
      />
      <button
        type="submit"
        disabled={isSubmitting}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
      >
        {isSubmitting ? "Submitting..." : "Submit Review"}
      </button>
    </form>
  );
}
