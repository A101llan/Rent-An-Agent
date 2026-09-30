"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Bot, Plus, Trash2, Code2, Sparkles, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";

export default function NewAgentPage() {
  const router = useRouter();
  const [step, setStep] = useState<"info" | "manifest">("info");

  // Basic Info
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("support");

  // Manifest fields
  const [systemPrompt, setSystemPrompt] = useState(
    "You are a helpful AI customer support agent. Answer questions accurately and concisely."
  );
  const [questions, setQuestions] = useState<Array<{ id: string; question: string; placeholder: string }>>([
    { id: "company", question: "What is your company name?", placeholder: "Acme Corp" },
    { id: "workflow", question: "What is your main workflow?", placeholder: "Customer onboarding" },
  ]);

  const [capabilities, setCapabilities] = useState("text_chat, document_analysis");
  const [priceMinor, setPriceMinor] = useState(200); // $2.00
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function addQuestion() {
    const id = `q_${Date.now()}`;
    setQuestions([...questions, { id, question: "", placeholder: "" }]);
  }

  function removeQuestion(index: number) {
    setQuestions(questions.filter((_, i) => i !== index));
  }

  function updateQuestion(index: number, field: string, val: string) {
    const updated = [...questions];
    updated[index] = { ...updated[index], [field]: val };
    setQuestions(updated);
  }

  async function handlePublish() {
    setError(null);
    setIsSubmitting(true);
    try {
      // 1. Create agent
      const agent = await api.createAgent({
        name,
        slug: slug.toLowerCase().replace(/[^a-z0-9-]/g, "-"),
        description,
        category,
      });

      // 2. Create manifest & version
      const manifest = {
        name,
        system_prompt: systemPrompt,
        capabilities: capabilities.split(",").map((c) => c.trim()),
        onboarding: {
          questions: questions.filter((q) => q.question.trim()),
        },
      };

      await api.createVersion(agent.id, {
        version: "1.0.0",
        manifest,
        image_name: "agenthub/standard-agent",
        image_digest: `sha256:${Date.now()}`,
        capabilities: capabilities.split(",").map((c) => c.trim()),
        pricing_model: "per_hour",
        price_minor: priceMinor,
      });

      // 3. Publish
      await api.publishAgent(agent.id);

      router.push("/developer");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to publish agent");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/developer" className="inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white mb-6">
        <ArrowLeft className="h-4 w-4" /> Back to Dashboard
      </Link>

      <div className="mb-8">
        <h1 className="text-3xl font-bold flex items-center gap-3">
          <Bot className="h-8 w-8 text-indigo-400" />
          Publish New AI Agent
        </h1>
        <p className="mt-2 text-zinc-400">Configure your agent's personality, manifest rules, and onboarding flow.</p>
      </div>

      {error && (
        <div className="mb-6 rounded-lg border border-red-800 bg-red-950/50 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Steps */}
      <div className="mb-8 flex gap-4 border-b border-zinc-800 pb-4">
        <button
          onClick={() => setStep("info")}
          className={`font-medium text-sm flex items-center gap-2 ${
            step === "info" ? "text-indigo-400 border-b-2 border-indigo-500 pb-2" : "text-zinc-500"
          }`}
        >
          1. Basic Details
        </button>
        <button
          onClick={() => setStep("manifest")}
          className={`font-medium text-sm flex items-center gap-2 ${
            step === "manifest" ? "text-indigo-400 border-b-2 border-indigo-500 pb-2" : "text-zinc-500"
          }`}
        >
          2. Manifest & System Prompt
        </button>
      </div>

      {step === "info" ? (
        <div className="space-y-6 rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
          <div>
            <label className="block text-sm font-medium text-zinc-300">Agent Name</label>
            <input
              type="text"
              placeholder="e.g. Customer Support Assistant"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]/g, "-"));
              }}
              className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-300">Slug</label>
            <input
              type="text"
              placeholder="customer-support-assistant"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm outline-none focus:border-indigo-500 font-mono text-xs"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium text-zinc-300">Category</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm outline-none focus:border-indigo-500"
              >
                <option value="support">Support</option>
                <option value="finance">Finance</option>
                <option value="research">Research</option>
                <option value="hr">HR</option>
                <option value="operations">Operations</option>
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-zinc-300">Price (USD per hour)</label>
              <input
                type="number"
                step="0.50"
                value={priceMinor / 100}
                onChange={(e) => setPriceMinor(Math.round(parseFloat(e.target.value || "0") * 100))}
                className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-zinc-300">Description</label>
            <textarea
              rows={4}
              placeholder="Describe what your agent does and who it helps..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mt-2 w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => setStep("manifest")}
              disabled={!name || !description}
              className="rounded-lg bg-indigo-600 px-6 py-2.5 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
            >
              Next: Configure Manifest →
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-8">
          {/* System Prompt */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-indigo-400" />
              System Prompt (Personality & Instructions)
            </h3>
            <p className="mt-1 text-xs text-zinc-400 mb-4">
              This system prompt defines how your agent responds to customer requests.
            </p>
            <textarea
              rows={6}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm font-mono text-zinc-200 outline-none focus:border-indigo-500"
            />
          </div>

          {/* Onboarding Questions */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold">Manifest Onboarding Questions</h3>
                <p className="text-xs text-zinc-400">Questions customers answer when connecting your agent.</p>
              </div>
              <button
                onClick={addQuestion}
                className="inline-flex items-center gap-1 text-xs bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600/30 px-3 py-1.5 rounded-lg border border-indigo-500/30"
              >
                <Plus className="h-3.5 w-3.5" /> Add Question
              </button>
            </div>

            <div className="space-y-3">
              {questions.map((q, idx) => (
                <div key={q.id || idx} className="flex gap-2 items-center bg-zinc-900/60 p-3 rounded-lg border border-zinc-800">
                  <input
                    type="text"
                    placeholder="Question prompt..."
                    value={q.question}
                    onChange={(e) => updateQuestion(idx, "question", e.target.value)}
                    className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 p-2 text-sm text-white"
                  />
                  <input
                    type="text"
                    placeholder="Placeholder..."
                    value={q.placeholder}
                    onChange={(e) => updateQuestion(idx, "placeholder", e.target.value)}
                    className="w-48 rounded-md border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-400"
                  />
                  <button onClick={() => removeQuestion(idx)} className="text-zinc-500 hover:text-red-400 p-2">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Capabilities */}
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6">
            <h3 className="text-lg font-semibold flex items-center gap-2">
              <Code2 className="h-5 w-5 text-indigo-400" /> Capabilities
            </h3>
            <p className="mt-1 text-xs text-zinc-400 mb-3">Comma separated capabilities (e.g. text_chat, api_calling, code_exec)</p>
            <input
              type="text"
              value={capabilities}
              onChange={(e) => setCapabilities(e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm outline-none focus:border-indigo-500"
            />
          </div>

          <div className="flex justify-between items-center pt-4">
            <button
              onClick={() => setStep("info")}
              className="text-sm text-zinc-400 hover:text-white"
            >
              ← Back to Details
            </button>

            <button
              onClick={handlePublish}
              disabled={isSubmitting}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-8 py-3 text-sm font-semibold hover:bg-indigo-500 disabled:opacity-50"
            >
              {isSubmitting ? "Publishing..." : <>Publish Agent <CheckCircle2 className="h-4 w-4" /></>}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
