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

export interface ScrapeResponse {
  fetched: number;
  inserted: number;
  skipped: number;
}

export const fetchJobs = (params?: { skip?: number; limit?: number; location?: string }) =>
  api.get<JobPosting[]>("/jobs", { params }).then((r) => r.data);

export const fetchSkillTrends = (top_n = 20) =>
  api.get<SkillTrendsResponse>("/trends/skills", { params: { top_n } }).then((r) => r.data);

export const fetchRoleTrends = (top_n = 15) =>
  api.get<RoleTrendsResponse>("/trends/roles", { params: { top_n } }).then((r) => r.data);

export const fetchStats = () =>
  api.get<StatsResponse>("/trends/stats").then((r) => r.data);

export const triggerScrape = (keywords: string, max_pages = 2) =>
  api.post<ScrapeResponse>("/scrape", { keywords, max_pages }).then((r) => r.data);
