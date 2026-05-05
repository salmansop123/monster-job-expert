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
  enrichment: JobEnrichment | null;
  openai_model?: string | null;
}

export interface IngestMetadata {
  response_status: string;
  ingest_status?: string | null;
  feed_last_updated?: string | null;
  message?: string | null;
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
  const res = await fetch("/api/v1/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function getSearch(searchId: number): Promise<SearchStatusResponse> {
  const res = await fetch(`/api/v1/search/${searchId}`);
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
