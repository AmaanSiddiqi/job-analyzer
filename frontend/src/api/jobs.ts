import { adminHeaders, clearStoredAdminKey } from "./adminKey";
import api from "./client";

export interface JobPosting {
  id: number;
  title: string;
  company: string;
  location: string;
  skills: string[];
  date_scraped: string;
  source_url: string;
  raw_description: string;
}

export interface SkillTrend {
  skill: string;
  count: number;
}

export interface RoleTrend {
  title: string;
  count: number;
}

export interface SkillTrendsResponse {
  total_jobs: number;
  top_skills: SkillTrend[];
}

export interface RoleTrendsResponse {
  total_jobs: number;
  top_roles: RoleTrend[];
}

export interface StatsResponse {
  total_jobs: number;
  total_companies: number;
  last_scraped: string | null;
}

export interface CompanyTrend {
  company: string;
  count: number;
}

export interface CompanyTrendsResponse {
  total_jobs: number;
  top_companies: CompanyTrend[];
}

export interface ScrapeResponse {
  fetched: number;
  inserted: number;
  skipped: number;
}

export const fetchJobs = (params?: { skip?: number; limit?: number; location?: string; company?: string }) =>
  api.get<JobPosting[]>("/jobs", { params }).then((r) => r.data);

export const fetchSkillTrends = (top_n = 20) =>
  api.get<SkillTrendsResponse>("/trends/skills", { params: { top_n } }).then((r) => r.data);

export const fetchRoleTrends = (top_n = 15) =>
  api.get<RoleTrendsResponse>("/trends/roles", { params: { top_n } }).then((r) => r.data);

export const fetchCompanyTrends = (top_n = 15) =>
  api.get<CompanyTrendsResponse>("/trends/companies", { params: { top_n } }).then((r) => r.data);

export const fetchStats = () =>
  api.get<StatsResponse>("/trends/stats").then((r) => r.data);

// Both scrape triggers are admin-gated server-side (X-Admin-Key, AUDIT.md §1).
// A 401 means the stored key was wrong/stale — clear it so the next click
// re-prompts instead of failing silently forever.
async function postWithAdminKey<T>(url: string, body: object): Promise<T> {
  const headers = adminHeaders();
  try {
    const r = await api.post<T>(url, body, { headers });
    return r.data;
  } catch (e) {
    if (typeof e === "object" && e && "response" in e && (e as { response?: { status?: number } }).response?.status === 401) {
      clearStoredAdminKey();
    }
    throw e;
  }
}

export const triggerScrape = (keywords: string, max_pages = 2, location = "Canada") =>
  postWithAdminKey<ScrapeResponse>("/scrape", { keywords, max_pages, location });

export interface BulkScrapeStarted {
  status: string;
  keywords: string[];
  max_pages: number;
  location: string;
}

export const triggerBulkScrape = (max_pages = 10, location = "Canada") =>
  postWithAdminKey<BulkScrapeStarted>("/scrape/bulk", { max_pages, location });

export interface SkillWeekPoint {
  week: string;
  count: number;
}

export interface SkillHistorySeries {
  skill: string;
  data: SkillWeekPoint[];
}

export interface SkillHistoryResponse {
  series: SkillHistorySeries[];
}

export const fetchSkillHistory = (skills: string[], weeks = 8) =>
  api
    .get<SkillHistoryResponse>("/trends/skills/history", {
      params: { skills, weeks },
      paramsSerializer: { indexes: null },
    })
    .then((r) => r.data);
