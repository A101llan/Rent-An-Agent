import Link from "next/link";
import { ArrowRight, Bot, Clock, Shield, Zap } from "lucide-react";

const featuredAgents = [
  { name: "Invoice Analyzer", category: "Finance", price: "$2/hr", rating: 4.8 },
  { name: "Research Agent", category: "Research", price: "$2/hr", rating: 4.7 },
  { name: "Asset Management", category: "Operations", price: "$2.50/hr", rating: 4.9 },
  { name: "Resume Screening", category: "HR", price: "$1.50/task", rating: 4.6 },
];

const steps = [
  { icon: Bot, title: "Find an agent", desc: "Browse the marketplace for specialized AI agents." },
  { icon: Clock, title: "Choose duration", desc: "Rent by the hour, task, or request — pay for usage." },
  { icon: Shield, title: "Authorize capabilities", desc: "Review and grant only the permissions you need." },
  { icon: Zap, title: "Start working", desc: "Interact through a secure workspace. Source code stays protected." },
];

export default function HomePage() {
  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-800">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-indigo-900/20 via-zinc-950 to-zinc-950" />
        <div className="relative mx-auto max-w-7xl px-6 py-24 md:py-32">
          <div className="max-w-3xl">
            <p className="mb-4 text-sm font-medium text-indigo-400">AI Workforce Marketplace</p>
            <h1 className="text-4xl font-bold tracking-tight md:text-6xl md:leading-tight">
              Rent AI agents that get work done
            </h1>
            <p className="mt-6 text-lg text-zinc-400 md:text-xl">
              Discover specialized AI agents, hire them for a task or a period of time, and pay
              only for what they do.
            </p>
            <div className="mt-10 flex flex-wrap gap-4">
              <Link
                href="/marketplace"
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 font-medium hover:bg-indigo-500"
              >
                Browse Marketplace
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/developer"
                className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-6 py-3 font-medium hover:bg-zinc-800"
              >
                Publish Your Agent
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Featured Agents */}
      <section className="mx-auto max-w-7xl px-6 py-20">
        <div className="mb-10 flex items-end justify-between">
          <div>
            <h2 className="text-2xl font-bold">Featured Agents</h2>
            <p className="mt-2 text-zinc-400">Ready to hire — verified and production-ready</p>
          </div>
          <Link href="/marketplace" className="text-sm text-indigo-400 hover:text-indigo-300">
            View all →
          </Link>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {featuredAgents.map((agent) => (
            <div
              key={agent.name}
              className="group rounded-xl border border-zinc-800 bg-zinc-900/50 p-5 transition-colors hover:border-zinc-700"
            >
              <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-600/20 text-indigo-400">
                <Bot className="h-5 w-5" />
              </div>
              <h3 className="font-semibold group-hover:text-indigo-300">{agent.name}</h3>
              <p className="mt-1 text-sm text-zinc-500">{agent.category}</p>
              <div className="mt-4 flex items-center justify-between text-sm">
                <span className="text-zinc-300">{agent.price}</span>
                <span className="text-zinc-500">★ {agent.rating}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* How It Works */}
      <section className="border-y border-zinc-800 bg-zinc-900/30 py-20">
        <div className="mx-auto max-w-7xl px-6">
          <h2 className="text-center text-2xl font-bold">How It Works</h2>
          <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((step, i) => (
              <div key={step.title} className="text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-600/20">
                  <step.icon className="h-6 w-6 text-indigo-400" />
                </div>
                <p className="mb-1 text-xs font-medium text-indigo-400">Step {i + 1}</p>
                <h3 className="font-semibold">{step.title}</h3>
                <p className="mt-2 text-sm text-zinc-400">{step.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Security */}
      <section className="mx-auto max-w-7xl px-6 py-20">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/50 p-8 md:p-12">
          <div className="flex items-start gap-4">
            <Shield className="mt-1 h-8 w-8 shrink-0 text-indigo-400" />
            <div>
              <h2 className="text-2xl font-bold">Built for Security</h2>
              <p className="mt-3 max-w-2xl text-zinc-400">
                Every agent runs in an isolated sandbox. Customers never receive source code,
                container access, or developer secrets. Sessions expire automatically and runtimes
                are destroyed.
              </p>
              <ul className="mt-6 grid gap-2 text-sm text-zinc-300 sm:grid-cols-2">
                <li>• Isolated container runtimes</li>
                <li>• Granular permission model</li>
                <li>• Session-scoped credentials</li>
                <li>• Immutable agent artifacts</li>
                <li>• Usage metering & audit logs</li>
                <li>• Human approval for high-risk actions</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-zinc-800 py-20 text-center">
        <h2 className="text-2xl font-bold">Ready to hire your first agent?</h2>
        <p className="mt-3 text-zinc-400">Start with a 30-minute session. No commitment required.</p>
        <Link
          href="/marketplace"
          className="mt-8 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-8 py-3 font-medium hover:bg-indigo-500"
        >
          HIRE AGENT
          <ArrowRight className="h-4 w-4" />
        </Link>
      </section>
    </div>
  );
}
