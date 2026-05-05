import type { JobRecord } from "../api";

interface Props {
  job: JobRecord;
  onOpen: () => void;
}

export default function JobCard({ job, onOpen }: Props) {
  const posted = job.posted_at_text || "Recently posted";
  const rel = job.relevance_score;
  const relPct =
    rel != null && Number.isFinite(rel) ? Math.round(Math.min(100, Math.max(0, rel))) : null;

  return (
    <article className="group relative flex flex-col overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-slate-900/90 to-slate-950/90 pl-5 pr-5 pt-5 pb-5 shadow-card transition hover:border-accent/35 hover:shadow-accent/10">
      <div
        aria-hidden
        className="absolute inset-y-0 left-0 w-1 rounded-l-2xl bg-gradient-to-b from-accent via-indigo-400 to-purple-600 opacity-70 group-hover:opacity-100"
      />

      <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-white/5 pb-3 text-[11px] font-semibold uppercase tracking-wide">
        <span className="rounded-full bg-emerald-500/15 px-2.5 py-1 text-emerald-200">{posted}</span>
        <span className="rounded-full bg-white/10 px-2.5 py-1 text-slate-200">Monster.com</span>
        {relPct != null ? (
          <span
            title="Lexical relevance to your title/location (+ optional AI when enabled)"
            className="rounded-full bg-indigo-500/20 px-2.5 py-1 text-indigo-100"
          >
            Match {relPct}%
          </span>
        ) : null}
        {job.salary_text ? (
          <span className="rounded-full bg-amber-500/12 px-2.5 py-1 text-amber-50">{job.salary_text}</span>
        ) : (
          <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-slate-500">
            Salary not listed
          </span>
        )}
      </div>

      <h3 className="font-display text-lg font-semibold leading-snug text-white">
        {job.title || "Untitled role"}
      </h3>
      <p className="mt-1 text-sm font-medium text-slate-300">{job.company || "Company not listed"}</p>
      <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500">
        <span aria-hidden className="inline-block h-1 w-1 rounded-full bg-slate-500" />
        {job.location_display || "Location flexible / TBD"}
      </p>

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onOpen();
          }}
          className="rounded-lg border border-white/20 bg-accent/90 px-3 py-2 text-xs font-semibold text-white shadow-sm transition hover:bg-accent"
        >
          View intelligence
        </button>
        {job.job_url ? (
          <a
            href={job.job_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-white/15 bg-transparent px-3 py-2 text-xs font-semibold text-accent transition hover:border-accent/50 hover:bg-white/5 hover:text-indigo-200"
          >
            Open posting
          </a>
        ) : null}
      </div>
    </article>
  );
}
