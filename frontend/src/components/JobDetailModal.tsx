import { useEffect, useRef, useState } from "react";
import type { JobRecord } from "../api";

interface Props {
  job: JobRecord | null;
  onClose: () => void;
}

/** Cookie/consent vendors — never treat as company homepage. */
function isPlausibleCompanyWebsiteUrl(url: string): boolean {
  const u = url.trim().toLowerCase();
  if (!u.startsWith("http://") && !u.startsWith("https://")) return false;
  const bad =
    /onetrust|privacyportal|privacy-choice|cookie|consent\.|trustarc|doubleclick|googleadservices|googlesyndication|facebook\.com|twitter\.com|youtube\.com|tiktok\.com|monster\.com|indeed\.com|apps\.apple\.com|itunes\.apple\.com|play\.google\.com/i;
  return !bad.test(u);
}

export default function JobDetailModal({ job, onClose }: Props) {
  if (!job) return null;
  const e = job.enrichment;
  const numbersRef = useRef<HTMLDivElement>(null);

  const resolvedLocation = e?.numbers_facts?.location || job.location_display || "";
  const resolvedJobType = e?.numbers_facts?.job_type || job.job_type || "";
  const resolvedIndustry = e?.numbers_facts?.industry || job.industry || "";
  const resolvedSalary = job.salary_text || "";
  const resolvedCompanySize = e?.numbers_facts?.company_size || job.company_size || "";
  const resolvedYearFounded = e?.numbers_facts?.year_founded || job.year_founded || "";
  const resolvedWebsite = e?.numbers_facts?.website || job.website || "";
  const websiteUrl =
    resolvedWebsite.trim() && isPlausibleCompanyWebsiteUrl(resolvedWebsite) ? resolvedWebsite.trim() : "";
  const jobAny = job as JobRecord & {
    description?: string | null;
    raw_description?: string | null;
    job_description?: string | null;
    body?: string | null;
  };
  // Prefer stored job text over any short enrichment snippet so the modal matches Monster.
  const displayDescription =
    jobAny.description ||
    jobAny.raw_description ||
    jobAny.job_description ||
    jobAny.body ||
    job.description_text ||
    e?.description ||
    "";
  const hasCompanyData =
    !!resolvedIndustry || !!resolvedCompanySize || !!resolvedYearFounded || !!websiteUrl;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      numbersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [job?.id]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-8 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-5xl min-h-0 flex-col overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-[0_0_0_1px_rgba(99,102,241,0.15)]">
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-white/10 bg-gradient-to-r from-accent/25 to-transparent px-6 py-5">
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

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-6 py-6">
          <div className="sticky top-1 z-20 ml-auto w-fit">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-white/20 bg-ink-950/90 px-3 py-1 text-xs font-semibold text-white hover:bg-ink-900"
            >
              Close
            </button>
          </div>
          <div className="text-xs text-slate-400">
            <a
              href="#numbers-facts"
              onClick={(evt) => {
                evt.preventDefault();
                numbersRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              className="cursor-pointer text-indigo-300 underline hover:text-indigo-200"
            >
              Jump to company info
            </a>
          </div>
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
          </div>

          <div className="grid min-h-0 gap-5 lg:grid-cols-5">
            <div className="min-h-0 space-y-4 lg:col-span-2">
              <div
                id="numbers-facts"
                ref={numbersRef}
                className="rounded-xl border border-white/10 bg-ink-950/40 p-4"
              >
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-accent">Numbers & facts</h4>
                <dl className="space-y-2 text-sm text-slate-200">
                  <Fact label="Location" value={resolvedLocation} />
                  <Fact label="Job Type" value={resolvedJobType} />
                  <Fact label="Industry" value={resolvedIndustry} />
                  <Fact label="Salary" value={resolvedSalary} salary />
                  <Fact label="Company Size" value={resolvedCompanySize} />
                  <Fact label="Year Founded" value={resolvedYearFounded} />
                  <Fact label="Website" value={websiteUrl} website />
                </dl>
                {!hasCompanyData ? (
                  <div className="pt-2 text-xs text-slate-400">
                    Company details not available for this posting. Run a fresh search to re-scrape, or open the posting on
                    Monster for the full page.
                  </div>
                ) : null}
                {resolvedWebsite && !websiteUrl ? (
                  <p className="pt-2 text-xs text-amber-200/90">
                    Company website link from the listing looked like a cookie or privacy URL and was hidden. Use{" "}
                    <span className="font-medium">Open posting</span> on the card for official links.
                  </p>
                ) : null}
              </div>
            </div>
            <div className="min-h-0 pr-1 lg:col-span-3">
              <JobDescription text={displayDescription} />
            </div>
          </div>

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

function Fact({
  label,
  value,
  salary = false,
  website = false,
}: {
  label: string;
  value: string | null | undefined;
  salary?: boolean;
  website?: boolean;
}) {
  const normalized = (value || "").trim();
  const empty = !normalized;
  return (
    <div className="flex justify-between gap-4 border-b border-white/5 py-1.5">
      <dt className="text-slate-400">{label}</dt>
      <dd
        className={`truncate text-right ${empty ? "text-slate-500" : salary ? "text-emerald-300" : "text-slate-100"}`}
      >
        {website && !empty ? (
          <a href={normalized} target="_blank" rel="noreferrer" className="text-indigo-300 hover:text-indigo-200">
            {normalized.replace(/^https?:\/\//, "")}
          </a>
        ) : (
          normalized || "—"
        )}
      </dd>
    </div>
  );
}

function JobDescription({ text }: { text: string }) {
  if (!text || text.trim().length === 0) {
    return (
      <div className="mt-5 rounded-xl border border-white/10 bg-ink-950/40 p-4 text-sm text-slate-400">
        No job description available for this posting. Run a fresh search to re-scrape detail pages, or use{" "}
        <span className="text-slate-300">Open posting</span> on the job card.
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
    <div className="mt-5 min-h-0">
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
      {isLong ? (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="mt-2 w-full rounded-md border border-white/20 bg-black/20 px-3 py-2 text-sm font-medium text-slate-100 hover:bg-white/5"
        >
          {expanded ? "Show less" : `Show full description (${text.length.toLocaleString()} chars)`}
        </button>
      ) : null}
    </div>
  );
}
