import type { FormEvent } from "react";
import { useState } from "react";

import type { SearchRequest } from "../api";

interface Props {
  onSubmit: (body: SearchRequest) => void;
  busy: boolean;
}

export default function SearchForm({ onSubmit, busy }: Props) {
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("remote");
  const [limit, setLimit] = useState(8);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit({
      title: title.trim(),
      location: location.trim(),
      limit,
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-white/10 bg-ink-900/70 p-6 shadow-card backdrop-blur-md"
    >
      <div className="mb-6 flex flex-col gap-1">
        <h2 className="font-display text-xl font-semibold text-white">Monster.com search + AI enrichment</h2>
        <p className="text-sm text-slate-400">
          Runs a Playwright scrape of <span className="text-slate-300">Monster.com</span> listings and job pages,
          then OpenAI extracts structured fields when a description is available.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1.5 md:col-span-2">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Job title</span>
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Artificial Intelligence"
            className="rounded-xl border border-white/10 bg-ink-950/80 px-4 py-2.5 text-sm text-white outline-none ring-accent/40 transition focus:border-accent/50 focus:ring-2"
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Location or remote
          </span>
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="e.g. remote, US, Cambridge, MA"
            className="rounded-xl border border-white/10 bg-ink-950/80 px-4 py-2.5 text-sm text-white outline-none ring-accent/40 transition focus:border-accent/50 focus:ring-2"
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            How many latest jobs
          </span>
          <input
            type="number"
            min={1}
            max={50}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded-xl border border-white/10 bg-ink-950/80 px-4 py-2.5 text-sm text-white outline-none ring-accent/40 transition focus:border-accent/50 focus:ring-2"
          />
        </label>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={busy}
          className="inline-flex items-center justify-center rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/25 transition hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Running search…" : "Run Monster.com search"}
        </button>
        <span className="max-w-xl text-xs text-slate-500">
          Only Monster.com is used — if the site blocks automation, the search fails with an explanation (no other job
          boards).
        </span>
      </div>
    </form>
  );
}
