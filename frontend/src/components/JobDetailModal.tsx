import { useEffect, useRef, useState } from "react";
import { enrichJob, scrapeJobDetailLive, type JobRecord, type LiveJobDetail } from "../api";

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
  const [liveDetail, setLiveDetail] = useState<LiveJobDetail | null>(null);
  const [liveLoading, setLiveLoading] = useState(false);
  const numbersRef = useRef<HTMLDivElement>(null);

  const resolvedLocation = e?.numbers_facts?.location || liveDetail?.location || job.location_display || "";
  const resolvedJobType = e?.numbers_facts?.job_type || liveDetail?.job_type || job.job_type || "";
  const resolvedIndustry = e?.numbers_facts?.industry || liveDetail?.industry || job.industry || "";
  const resolvedSalary = liveDetail?.salary || job.salary_text || "";
  const resolvedCompanySize = e?.numbers_facts?.company_size || liveDetail?.company_size || job.company_size || "";
  const resolvedYearFounded = e?.numbers_facts?.year_founded || liveDetail?.year_founded || job.year_founded || "";
  const resolvedWebsite = e?.numbers_facts?.website || liveDetail?.website || job.website || "";
  const websiteUrl = resolvedWebsite;
  const jobAny = job as JobRecord & {
    description?: string | null;
    raw_description?: string | null;
    job_description?: string | null;
    body?: string | null;
  };
  const displayDescription =
    e?.description ||
    liveDetail?.description_text ||
    jobAny.description ||
    jobAny.raw_description ||
    jobAny.job_description ||
    jobAny.body ||
    job.description_text ||
    "";
  const hasCompanyData = !!resolvedIndustry || !!resolvedCompanySize || !!resolvedYearFounded || !!resolvedWebsite;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      numbersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [job?.id]);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!job?.job_url) {
        setLiveDetail(null);
        return;
      }
      setLiveLoading(true);
      try {
        const detail = await scrapeJobDetailLive(job.job_url);
        if (!cancelled) setLiveDetail(detail);
      } catch {
        if (!cancelled) setLiveDetail(null);
      } finally {
        if (!cancelled) setLiveLoading(false);
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [job?.id, job?.job_url]);

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
      <div className="max-h-[90vh] w-full max-w-5xl overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-[0_0_0_1px_rgba(99,102,241,0.15)]">
        <div className="flex items-start justify-between gap-4 border-b border-white/10 bg-gradient-to-r from-accent/25 to-transparent px-6 py-5">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Structured view</p>
            <h2 className="mt-2 font-display text-2xl font-semibold text-white">{job.title}</h2>
            <p className="text-sm text-slate-400">{job.company || "Company"} • {job.location_display || "Location"}</p>
          </div>
          <button type="button" aria-label="Close" onClick={onClose} className="rounded-full border border-white/15 px-3 py-1 text-sm text-white transition hover:bg-white/10">✕</button>
        </div>

        <div className="space-y-6 overflow-y-auto px-6 py-6">
          <div className="text-xs text-slate-400">
            <a
              href="#numbers-facts"
              onClick={(evt) => {
                evt.preventDefault();
                numbersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              className="cursor-pointer underline text-indigo-300 hover:text-indigo-200"
            >
              Jump to company info
            </a>
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-slate-300">
            <span className="rounded-full bg-white/10 px-3 py-1 text-slate-200">Monster.com</span>
            {job.relevance_score != null ? <span className="rounded-full bg-indigo-500/20 px-3 py-1 text-indigo-100">Match {Math.round(Math.min(100, Math.max(0, job.relevance_score)))}%</span> : null}
            <span className="rounded-full bg-emerald-500/10 px-3 py-1 text-emerald-200">{job.posted_at_text || "Recent"}</span>
            {job.salary_text ? <span className="rounded-full bg-amber-400/15 px-3 py-1 text-amber-100">{job.salary_text}</span> : null}
            {job.openai_model ? <span className="rounded-full bg-white/5 px-3 py-1 text-slate-400">Model • {job.openai_model}</span> : null}
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
                  <p className="mt-1 text-xs text-slate-400">Not generated yet. Click to run one OpenAI call for this job only.</p>
                </div>
                <button type="button" onClick={handleEnrich} disabled={enriching} className="rounded-lg border border-indigo-400/40 bg-indigo-500/20 px-3 py-1.5 text-xs font-semibold text-indigo-100 transition hover:bg-indigo-500/30 disabled:cursor-not-allowed disabled:opacity-60">
                  {enriching ? "Generating..." : "Generate AI summary"}
                </button>
              </div>
              {enrichError ? <p className="mt-2 text-xs text-rose-300">{enrichError}</p> : null}
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-5">
            <div className="space-y-4 lg:col-span-2">
              <div id="numbers-facts" ref={numbersRef} className="rounded-xl border border-white/10 bg-ink-950/40 p-4">
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-accent">Numbers & facts</h4>
                <dl className="space-y-2 text-sm text-slate-200">
                  <Fact label="Location" value={resolvedLocation} />
                  <Fact label="Job Type" value={resolvedJobType} />
                  <Fact label="Industry" value={resolvedIndustry} />
                  <Fact label="Salary" value={resolvedSalary} salary />
                  <Fact label="Company Size" value={resolvedCompanySize} />
                  <Fact label="Year Founded" value={resolvedYearFounded} />
                  <Fact label="Website" value={resolvedWebsite} website />
                </dl>
                {liveLoading ? <p className="pt-2 text-xs text-slate-500">Loading live detail facts...</p> : null}
                {!hasCompanyData ? <div className="pt-2 text-xs text-slate-400">Company details not available for this posting.</div> : null}
              </div>
              {websiteUrl ? <CompanyWebsitePanel websiteUrl={websiteUrl} /> : null}
            </div>
            <div className="lg:col-span-3">
              <JobDescription text={displayDescription} />
            </div>
          </div>

          {job.job_url ? (
            <div className="flex justify-end">
              <a href={job.job_url} target="_blank" rel="noreferrer" className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-dim">Apply on Monster</a>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Fact({ label, value, salary = false, website = false }: { label: string; value: string | null | undefined; salary?: boolean; website?: boolean }) {
  const normalized = (value || "").trim();
  const empty = !normalized;
  return (
    <div className="flex justify-between gap-4 border-b border-white/5 py-1.5">
      <dt className="text-slate-400">{label}</dt>
      <dd className={`truncate text-right ${empty ? "text-slate-500" : salary ? "text-emerald-300" : "text-slate-100"}`}>
        {website && !empty ? (
          <a href={normalized} target="_blank" rel="noreferrer" className="text-indigo-300 hover:text-indigo-200">
            {normalized.replace(/^https?:\/\//, "")}
          </a>
        ) : normalized || "—"}
      </dd>
    </div>
  );
}

function CompanyWebsitePanel({ websiteUrl }: { websiteUrl: string }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!websiteUrl) return;
    setLoading(true);
    setData(null);
    setError("");
    fetch("/api/company/fetch-website", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: websiteUrl }),
    }).then((r) => r.json()).then((d) => {
      if (d.status === "ok") setData(d);
      else setError(d.error || "Could not load website");
    }).catch(() => setError("Network error")).finally(() => setLoading(false));
  }, [websiteUrl]);
  if (!websiteUrl) return null;
  return (
    <div className="mt-4 rounded-xl border border-white/10 bg-ink-950/40 p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-sm font-medium text-white">Company Website</span>
        <a href={websiteUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-300 hover:text-indigo-200">
          {websiteUrl.replace(/^https?:\/\//, "")}
        </a>
      </div>
      {loading ? <div className="animate-pulse text-sm text-slate-400">Fetching company info...</div> : null}
      {error ? <div className="text-sm text-rose-300">{error}</div> : null}
      {data ? (
        <div className="flex flex-col gap-3">
          {data.title ? <div className="text-sm font-medium text-slate-100">{data.title}</div> : null}
          {data.meta_description ? (
            <div className="rounded-md border-l-2 border-white/20 bg-black/20 p-3 text-sm leading-relaxed text-slate-300">
              {data.meta_description}
            </div>
          ) : null}
          {data.body_preview && !data.meta_description ? (
            <div className="text-sm leading-relaxed text-slate-300">{String(data.body_preview).slice(0, 400)}...</div>
          ) : null}
          {Array.isArray(data.useful_links) && data.useful_links.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {data.useful_links.map((link: { text?: string; href?: string }, i: number) => (
                <a
                  key={`${link.href || "link"}-${i}`}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-full border border-white/20 bg-black/20 px-3 py-1 text-xs text-indigo-200 hover:bg-white/10"
                >
                  {link.text || "Link"}
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function JobDescription({ text }: { text: string }) {
  if (!text || text.trim().length === 0) {
    return (
      <div className="mt-5 rounded-xl border border-white/10 bg-ink-950/40 p-4 text-sm text-slate-400">
        No job description available for this posting.
      </div>
    );
  }
  const [expanded, setExpanded] = useState(false);
  const PREVIEW_LENGTH = 800;
  const isLong = text.length > PREVIEW_LENGTH;
  const displayed = expanded ? text : text.substring(0, PREVIEW_LENGTH);
  const formatted = displayed.replace(/\*\*(.*?)\*\*/g, "$1").replace(/#{1,3} /g, "").trim();
  const paragraphs = formatted.split(/\n{2,}/).filter((p) => p.trim().length > 0);
  return (
    <div className="mt-5">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[15px] font-medium text-white">Job Description</span>
        <span className="text-xs text-slate-500">{text.length.toLocaleString()} characters</span>
      </div>
      <div className="rounded-xl border border-white/10 bg-ink-950/40 p-5 text-[15px] leading-[1.8] text-slate-100">
        {paragraphs.map((para, i) => {
          const trimmed = para.trim();
          if (trimmed.startsWith("- ") || trimmed.startsWith("• ")) {
            const lines = trimmed.split("\n").filter(Boolean);
            return (
              <ul key={i} className="mb-3 list-disc pl-5">
                {lines.map((line, j) => (
                  <li key={j} className="mb-1 text-[15px] leading-[1.7]">
                    {line.replace(/^[-•]\s*/, "")}
                  </li>
                ))}
              </ul>
            );
          }
          return (
            <p key={i} className="mb-3 text-[15px] leading-[1.8]">
              {trimmed}
            </p>
          );
        })}
        {!expanded && isLong ? (
          <div className="-mt-10 h-14 rounded-b-xl bg-gradient-to-b from-transparent to-ink-950/95" />
        ) : null}
      </div>
      {isLong ? <button onClick={() => setExpanded(!expanded)} className="mt-2 w-full rounded-md border border-white/20 bg-black/20 px-3 py-2 text-sm font-medium text-slate-100 hover:bg-white/5">{expanded ? "Show less" : `Show full description (${text.length.toLocaleString()} chars)`}</button> : null}
    </div>
  );
}
