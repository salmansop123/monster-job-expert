import { useState } from "react";

import { enrichJob, type JobRecord } from "../api";

interface Props {
  job: JobRecord | null;
  onClose: () => void;
  onJobUpdated?: (job: JobRecord) => void;
}

export default function JobDetailModal({ job, onClose, onJobUpdated }: Props) {
  if (!job) return null;

  const e = job.enrichment;
  const [enriching, setEnriching] = useState(false);
  const [enrichError, setEnrichError] = useState<string | null>(null);

  async function handleEnrich() {
    if (!job?.id || enriching) return;
    try {
      setEnriching(true);
      setEnrichError(null);
      const updated = await enrichJob(job.id, job.search_id ?? undefined);
      onJobUpdated?.(updated);
    } catch (err) {
      setEnrichError((err as Error).message);
    } finally {
      setEnriching(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-8 backdrop-blur-sm">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-[0_0_0_1px_rgba(99,102,241,0.15)]">
        <div className="flex items-start justify-between gap-4 border-b border-white/10 bg-gradient-to-r from-accent/25 to-transparent px-6 py-5">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Structured view</p>
            <h2 className="mt-2 font-display text-2xl font-semibold text-white">{job.title}</h2>
            <p className="text-sm text-slate-400">
              {job.company || "Company"} • {job.location_display || "Location"}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-full border border-white/15 px-3 py-1 text-sm text-white transition hover:bg-white/10"
          >
            ✕
          </button>
        </div>

        <div className="space-y-6 overflow-y-auto px-6 py-6">
          <div className="flex flex-wrap gap-3 text-xs text-slate-300">
            <span className="rounded-full bg-white/10 px-3 py-1 text-slate-200">Monster.com</span>
            {job.relevance_score != null ? (
              <span className="rounded-full bg-indigo-500/20 px-3 py-1 text-indigo-100">
                Match {Math.round(Math.min(100, Math.max(0, job.relevance_score)))}%
              </span>
            ) : null}
            <span className="rounded-full bg-emerald-500/10 px-3 py-1 text-emerald-200">
              {job.posted_at_text || "Recent"}
            </span>
            {job.salary_text ? (
              <span className="rounded-full bg-amber-400/15 px-3 py-1 text-amber-100">{job.salary_text}</span>
            ) : null}
            {job.openai_model ? (
              <span className="rounded-full bg-white/5 px-3 py-1 text-slate-400">Model • {job.openai_model}</span>
            ) : null}
          </div>

          {e?.summary ? (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-accent">AI summary</h4>
              <p className="text-sm leading-relaxed text-slate-100">{e.summary}</p>
            </div>
          ) : (
            <div className="rounded-xl border border-white/10 bg-ink-950/40 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-accent">AI summary</h4>
                  <p className="mt-1 text-xs text-slate-400">
                    Not generated yet. Click to run one OpenAI call for this job only.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleEnrich}
                  disabled={enriching}
                  className="rounded-lg border border-indigo-400/40 bg-indigo-500/20 px-3 py-1.5 text-xs font-semibold text-indigo-100 transition hover:bg-indigo-500/30 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {enriching ? "Generating..." : "Generate AI summary"}
                </button>
              </div>
              {enrichError ? <p className="mt-2 text-xs text-rose-300">{enrichError}</p> : null}
            </div>
          )}

          <div className="grid gap-6 md:grid-cols-2">
            <div className="rounded-xl border border-white/10 bg-ink-950/40 p-4">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-accent">
                Numbers & facts
              </h4>
              <dl className="space-y-2 text-sm text-slate-200">
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-400">Location</dt>
                  <dd>{e?.numbers_facts?.location || job.location_display || "—"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-400">Job Type</dt>
                  <dd>{e?.numbers_facts?.job_type || "—"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-400">Industry</dt>
                  <dd>{e?.numbers_facts?.industry || "—"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-400">Company Size</dt>
                  <dd>{e?.numbers_facts?.company_size || "—"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-400">Year Founded</dt>
                  <dd>{e?.numbers_facts?.year_founded || "—"}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-400">Website</dt>
                  <dd className="truncate">
                    {e?.numbers_facts?.website ? (
                      <a
                        href={e.numbers_facts.website}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-300 hover:text-indigo-200"
                      >
                        {e.numbers_facts.website}
                      </a>
                    ) : (
                      "—"
                    )}
                  </dd>
                </div>
              </dl>
            </div>

            <div className="rounded-xl border border-white/10 bg-ink-950/40 p-4">
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-accent">
                About company
              </h4>
              <p className="text-sm leading-relaxed text-slate-200">
                {e?.about_company || "Not available in this posting."}
              </p>
            </div>
          </div>

          {e?.description ? (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-accent">
                Description
              </h4>
              <p className="text-sm leading-relaxed text-slate-100">{e.description}</p>
            </div>
          ) : null}

          {job.description_text ? (
            <details className="rounded-xl border border-white/10 bg-ink-950/40 p-4">
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-400">
                Raw job description ({job.description_text.length.toLocaleString()} chars)
              </summary>
              <pre className="mt-4 max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-300">
                {job.description_text}
              </pre>
            </details>
          ) : null}

          {job.job_url ? (
            <div className="flex justify-end">
              <a
                href={job.job_url}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-dim"
              >
                Apply on Monster
              </a>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
