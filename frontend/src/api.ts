export interface SearchRequest {
  title: string;
  location: string;
  limit: number;
}

export interface JobNumbersFacts {
  location: string | null;
  job_type: string | null;
  industry: string | null;
  company_size: string | null;
  year_founded: string | null;
  website: string | null;
}

export interface JobEnrichment {
  summary: string;
  description: string;
  numbers_facts: JobNumbersFacts;
  about_company: string;
  confidence_notes?: string | null;
}

export interface JobRecord {
  id: number | null;
  search_id: number | null;
  title: string | null;
  company: string | null;
  location_display: string | null;
  salary_text: string | null;
  posted_at_text: string | null;
  job_url: string | null;
  source: string;
  relevance_score?: number | null;
  description_text?: string | null;
  job_type?: string | null;
  industry?: string | null;
  company_size?: string | null;
  year_founded?: string | null;
  website?: string | null;
  about_company?: string | null;
  enrichment: JobEnrichment | null;
  openai_model?: string | null;
}

export interface IngestMetadata {
  response_status: string;
  ingest_status?: string | null;
  feed_last_updated?: string | null;
  scraped_at?: string | null;
  message?: string | null;
}

export interface ScraperHealth {
  last_run_at: string;
  last_query: string;
  cards_found: number;
  selector_used: string;
  blocked: boolean;
  error: string;
  cookie_age_hours?: number | null;
  browser_mode?: "cdp" | "disabled";
}

export interface SelectorHistoryEntry {
  ts: string;
  query: string;
  selector: string;
  cards_found: number;
  blocked: boolean;
}

export interface ChromeStatus {
  connected: boolean;
  browser?: string;
  user_agent?: string;
  binary?: string;
  binary_found?: string;
  os?: "linux" | "darwin" | "windows" | string;
  cdp_url?: string;
  error?: string;
  hint?: string;
}

export interface ScrapeProgress {
  stage: string;
  current: number;
  total: number;
  message: string;
}

export interface SearchHistoryEntry {
  id: number;
  title: string;
  location: string;
  num_jobs: number;
  result_count: number;
  created_at: string;
}


export interface LiveJobDetail {
  title?: string | null;
  description_text?: string | null;
  location?: string | null;
  job_type?: string | null;
  industry?: string | null;
  salary?: string | null;
  company_size?: string | null;
  year_founded?: string | null;
  website?: string | null;
  about_company?: string | null;
}

export interface SearchStatusResponse {
  search_id: number;
  status: "queued" | "running" | "completed" | "failed";
  error_message: string | null;
  criteria: SearchRequest | null;
  created_at?: string | null;
  updated_at?: string | null;
  ingest?: IngestMetadata | null;
}

export interface JobListResponse {
  items: JobRecord[];
  total: number;
  offset: number;
  limit: number;
}

export async function postSearch(body: SearchRequest): Promise<{ search_id: number }> {
  const res = await fetch("/api/v1/search?force_refresh=true", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function getScraperHealth(): Promise<ScraperHealth> {
  const res = await fetch("/api/scraper/health");
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listDebugSnapshots(): Promise<string[]> {
  const res = await fetch("/debug/snapshots");
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSelectorHistory(): Promise<SelectorHistoryEntry[]> {
  const res = await fetch("/api/scraper/selector-history");
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function testSelector(body: {
  selector: string;
  url: string;
}): Promise<{ matched: number; page_title: string; snapshot_saved: string }> {
  const res = await fetch("/api/scraper/test-selector", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getChromeStatus(): Promise<ChromeStatus> {
  const res = await fetch("/api/scraper/chrome-status");
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function launchChrome(): Promise<{ status: string; error?: string }> {
  const res = await fetch("/api/scraper/launch-chrome", { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSearch(searchId: number): Promise<SearchStatusResponse> {
  const res = await fetch(`/api/v1/search/${searchId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getSearchHistory(): Promise<SearchHistoryEntry[]> {
  const res = await fetch("/api/search/history");
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export type JobsQueryOptions = { sort?: "relevance" | "id" };

export async function getJobs(
  searchId: number,
  opts?: JobsQueryOptions
): Promise<JobListResponse> {
  const params = new URLSearchParams();
  if (opts?.sort) params.set("sort", opts.sort);
  const qs = params.toString();
  const url = `/api/v1/search/${searchId}/jobs${qs ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function enrichJob(jobId: number, searchId?: number): Promise<JobRecord> {
  const params = new URLSearchParams();
  if (searchId != null) params.set("search_id", String(searchId));
  const qs = params.toString();
  const url = `/api/v1/jobs/${jobId}/enrich${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function scrapeJobDetailLive(url: string): Promise<LiveJobDetail> {
  const res = await fetch("/api/scraper/job-detail", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return (data?.detail ?? {}) as LiveJobDetail;
}
