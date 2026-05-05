import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { JobRecord, ScrapeProgress, SearchHistoryEntry, SearchRequest } from "./api";
import { getJobs, getSearch, getSearchHistory, postSearch } from "./api";
import JobCard from "./components/JobCard";
import JobDetailModal from "./components/JobDetailModal";
import ScraperHealthPanel from "./components/ScraperHealthPanel";
import SearchForm from "./components/SearchForm";

/** Completed searches may attach an informational note (e.g. empty results, cache hit). */
function completedMessageIsInformative(msg: string | null): boolean {
  if (!msg) return false;
  const m = msg.toLowerCase();
  return (
    m.includes("empty result") ||
    m.includes("cache ttl") ||
    m.includes("no live fetch") ||
    m.includes("no monster.com listings") ||
    m.includes("scheduled in the background")
  );
}

export default function App() {
  const [searchId, setSearchId] = useState<number | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [infoNote, setInfoNote] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [jobSort, setJobSort] = useState<"relevance" | "id">("relevance");
  const [pollTick, setPollTick] = useState(0);
  const [selected, setSelected] = useState<JobRecord | null>(null);
  const [progress, setProgress] = useState<ScrapeProgress>({ stage: "", current: 0, total: 0, message: "" });
  const [history, setHistory] = useState<SearchHistoryEntry[]>([]);

  const isTerminal = status === "completed" || status === "failed";
  const mutation = useMutation({
    mutationFn: postSearch,
    onMutate: () => {
      setError(null);
      setInfoNote(null);
      setJobs([]);
      setSelected(null);
      setStatus("running");
    },
    onSuccess: (res) => {
      setSearchId(res.search_id);
      setStatus("running");
      setJobs([]);
    },
    onError: (err: Error) => setError(err.message),
  });

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const data = await getSearchHistory();
        if (!cancelled) setHistory(data);
      } catch {
        if (!cancelled) setHistory([]);
      }
    };
    run();
    const id = window.setInterval(run, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!searchId || isTerminal) return undefined;
    let cancelled = false;
    const id = window.setInterval(() => {
      if (!cancelled) setPollTick((t) => t + 1);
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [searchId, isTerminal]);

  useEffect(() => {
    if (!searchId) return;
    let cancelled = false;
    (async () => {
      try {
        const s = await getSearch(searchId);
        if (cancelled) return;
        setStatus(s.status);

        const msg = s.error_message;
        if (s.status === "failed") {
          setError(msg || "Search failed");
          setInfoNote(null);
        } else if (s.status === "completed" && msg && completedMessageIsInformative(msg)) {
          setInfoNote(msg);
          setError(null);
        } else if (s.status === "completed" && msg) {
          setError(msg);
          setInfoNote(null);
        } else {
          setError(null);
          setInfoNote(null);
        }

        const list = await getJobs(searchId, { sort: jobSort });
        if (cancelled) return;
        setJobs(list.items);
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchId, pollTick, jobSort]);

  useEffect(() => {
    if (status !== "running" && status !== "queued") return;
    const es = new EventSource("/api/scraper/progress");
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as ScrapeProgress;
        setProgress(data);
      } catch {
        // ignore malformed payload
      }
    };
    return () => es.close();
  }, [status]);

  const banner = useMemo(() => {
    if (!searchId) return null;
    if (status === "running" || status === "queued") {
      return "Building your result set from the Monster job feed (listing/detail work runs in ingestion, not in the HTTP worker).";
    }
    if (status === "completed") {
      return `Search #${searchId} finished — ${jobs.length} role${jobs.length !== 1 ? "s" : ""} listed below.`;
    }
    return null;
  }, [jobs.length, searchId, status]);

  function runHistorySearch(item: SearchHistoryEntry) {
    const payload: SearchRequest = {
      title: item.title,
      location: item.location,
      limit: item.num_jobs || 1,
    };
    mutation.mutate(payload);
  }

  function exportCSV(currentSearchId: number) {
    window.open(`/api/search/${currentSearchId}/export-csv`, "_blank");
  }

  return (
    <div className="min-h-full">
      <header className="border-b border-white/5 bg-ink-900/40 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Monster Job Expert</p>
            <h1 className="font-display text-3xl font-semibold text-white">AI-assisted job intelligence</h1>
            <p className="text-sm text-slate-400">
              Monster-only data plane: ingestion keeps a shared SQLite feed (title + location) with TTL, retries, and
              scheduled refresh; the API reads that feed for each search.
            </p>
          </div>
          <div className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs text-slate-300">
            API • FastAPI + SQLite + OpenAI + Monster.com
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-10">
        <SearchForm
          onSubmit={(body) => mutation.mutate(body)}
          busy={mutation.isPending}
        />
        {status === "running" && progress.total > 0 ? (
          <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
            <div className="mb-2 text-sm text-slate-300">{progress.message}</div>
            <div className="h-1.5 overflow-hidden rounded bg-white/10">
              <div
                className="h-full rounded bg-emerald-400 transition-all"
                style={{ width: `${Math.min(100, (progress.current / progress.total) * 100)}%` }}
              />
            </div>
            <div className="mt-1 text-xs text-slate-400">
              {progress.current} of {progress.total} jobs
            </div>
          </div>
        ) : null}
        <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Recent searches</p>
          <div className="space-y-2">
            {history.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => runHistorySearch(s)}
                className="flex w-full items-center justify-between rounded-md border border-white/10 bg-slate-900/40 px-3 py-2 text-left hover:bg-slate-900/70"
              >
                <div>
                  <div className="text-sm font-medium text-slate-100">{s.title}</div>
                  <div className="text-xs text-slate-400">
                    {s.location} · {s.result_count} jobs
                  </div>
                </div>
                <span className="text-[11px] text-slate-500">
                  {new Date(s.created_at).toLocaleDateString()}
                </span>
              </button>
            ))}
            {history.length === 0 ? <p className="text-xs text-slate-500">No recent searches yet.</p> : null}
          </div>
        </div>

        {infoNote ? (
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-50">
            <p className="font-semibold text-amber-200">Note</p>
            <p className="mt-1 leading-relaxed text-amber-100/95">{infoNote}</p>
          </div>
        ) : null}

        {error ? (
          <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
            {error}
          </div>
        ) : null}

        {banner ? (
          <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">{banner}</div>
        ) : null}

        {status === "completed" && searchId && jobs.length > 0 ? (
          <div className="rounded-xl border border-sky-500/35 bg-sky-500/[0.08] px-4 py-3 text-xs leading-relaxed text-sky-100/95">
            All roles on this board are from <span className="font-semibold">Monster.com</span> for this search run.
          </div>
        ) : null}

        <ScraperHealthPanel />

        <section className="space-y-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="font-display text-xl font-semibold text-white">Dashboard</h2>
              <p className="text-xs text-slate-500">Sorted by relevance to your query (lexical + optional AI score).</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-500">{jobs.length} shown</span>
              {jobs.length > 0 && searchId ? (
                <button
                  type="button"
                  onClick={() => exportCSV(searchId)}
                  className="rounded-md border border-white/20 bg-slate-900/40 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-900/70"
                >
                  Export CSV
                </button>
              ) : null}
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <span className="whitespace-nowrap">Sort</span>
                <select
                  value={jobSort}
                  onChange={(e) => setJobSort(e.target.value as "relevance" | "id")}
                  disabled={!!searchId && status === "running"}
                  className="rounded-lg border border-white/15 bg-slate-900/80 px-2 py-1.5 text-slate-200"
                >
                  <option value="relevance">Relevance</option>
                  <option value="id">Newest inserted</option>
                </select>
              </label>
            </div>
          </div>
          {jobs.length === 0 && status !== "running" ? (
            <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 px-6 py-12 text-center text-sm text-slate-400">
              Run a search to populate this board with enriched postings.
            </div>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {jobs.map((job, index) => (
                <JobCard
                  key={job.id ?? job.job_url ?? `job-${index}`}
                  job={job}
                  onOpen={() => setSelected(job)}
                />
              ))}
            </div>
          )}
        </section>
      </main>

      <JobDetailModal job={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
