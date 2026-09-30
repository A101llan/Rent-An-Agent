"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Bot, Search, Star } from "lucide-react";
import { useState } from "react";
import { api, formatPricingModel } from "@/lib/api";

export default function MarketplacePage() {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("newest");

  const { data, isLoading } = useQuery({
    queryKey: ["marketplace", search, category, sort],
    queryFn: () =>
      api.listAgents({
        ...(search && { search }),
        ...(category && { category }),
        sort,
        page_size: "20",
      }),
  });

  return (
    <div className="mx-auto max-w-7xl px-6 py-12">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Marketplace</h1>
        <p className="mt-2 text-zinc-400">Discover and hire specialized AI agents</p>
      </div>

      <div className="mb-8 flex flex-wrap gap-4">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            placeholder="Search agents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-2.5 pl-10 pr-4 text-sm outline-none focus:border-indigo-500"
          />
        </div>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm outline-none"
        >
          <option value="">All categories</option>
          <option value="finance">Finance</option>
          <option value="research">Research</option>
          <option value="hr">HR</option>
          <option value="support">Support</option>
          <option value="operations">Operations</option>
        </select>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-sm outline-none"
        >
          <option value="newest">Newest</option>
          <option value="rating">Top rated</option>
          <option value="popular">Most reviewed</option>
          <option value="name">Name</option>
        </select>
      </div>

      {isLoading ? (
        <p className="text-zinc-400">Loading agents...</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data?.items.map((agent) => (
            <Link
              key={agent.id}
              href={`/agents/${agent.slug}`}
              className="group rounded-xl border border-zinc-800 bg-zinc-900/50 p-6 transition-colors hover:border-indigo-600/50"
            >
              <div className="mb-4 flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-600/20">
                  <Bot className="h-5 w-5 text-indigo-400" />
                </div>
                {agent.is_verified && (
                  <span className="rounded-full bg-green-900/30 px-2 py-0.5 text-xs text-green-400">Verified</span>
                )}
              </div>
              <h3 className="font-semibold group-hover:text-indigo-300">{agent.name}</h3>
              <p className="mt-1 line-clamp-2 text-sm text-zinc-400">{agent.description}</p>
              <div className="mt-3 flex flex-wrap gap-1">
                {agent.capabilities.slice(0, 3).map((cap) => (
                  <span key={cap} className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                    {cap.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="flex items-center gap-1 text-zinc-300">
                  <Star className="h-3.5 w-3.5 fill-yellow-500 text-yellow-500" />
                  {agent.avg_rating.toFixed(1)} ({agent.review_count})
                </span>
                {agent.starting_price_minor && agent.pricing_model && (
                  <span className="font-medium text-indigo-400">
                    {formatPricingModel(agent.pricing_model, agent.starting_price_minor)}
                  </span>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
