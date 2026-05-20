import { useEffect, useState, useCallback } from "react";
import SkillsChart from "./components/SkillsChart";
import RolesChart from "./components/RolesChart";
import CompaniesChart from "./components/CompaniesChart";
import JobTable from "./components/JobTable";
import SkillHistoryChart from "./components/SkillHistoryChart";
import {
  fetchJobs,
  fetchSkillTrends,
  fetchRoleTrends,
  fetchCompanyTrends,
  fetchSkillHistory,
  fetchStats,
  triggerScrape,
  triggerBulkScrape,
  JobPosting,
  SkillTrend,
  RoleTrend,
  CompanyTrend,
  SkillHistorySeries,
  StatsResponse,
} from "./api/jobs";

type ScrapeStatus = "idle" | "loading" | "done" | "error";
type BulkStatus = "idle" | "loading" | "started";

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-5 py-4">
      <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-800 mt-1">{value}</p>
    </div>
  );
}

export default function App() {
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [skills, setSkills] = useState<SkillTrend[]>([]);
  const [roles, setRoles] = useState<RoleTrend[]>([]);
  const [companies, setCompanies] = useState<CompanyTrend[]>([]);
  const [history, setHistory] = useState<SkillHistorySeries[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [dataLoading, setDataLoading] = useState(true);

  const [selectedCompany, setSelectedCompany] = useState<string | null>(null);

  const [keywords, setKeywords] = useState("software engineer");
  const [scrapeCompany, setScrapeCompany] = useState("");
  const [scrapeStatus, setScrapeStatus] = useState<ScrapeStatus>("idle");
  const [scrapeResult, setScrapeResult] = useState<string>("");
  const [bulkStatus, setBulkStatus] = useState<BulkStatus>("idle");

  const loadJobs = useCallback((company?: string | null) => {
    setJobsLoading(true);
    fetchJobs({ limit: 200, company: company ?? undefined })
      .then(setJobs)
      .finally(() => setJobsLoading(false));
  }, []);

  const loadData = useCallback(() => {
    setDataLoading(true);
    Promise.all([
      fetchSkillTrends(20),
      fetchRoleTrends(15),
      fetchCompanyTrends(15),
      fetchSkillHistory([], 8),
      fetchStats(),
    ])
      .then(([skillsData, rolesData, companiesData, historyData, statsData]) => {
        setSkills(skillsData.top_skills);
        setRoles(rolesData.top_roles);
        setCompanies(companiesData.top_companies);
        setHistory(historyData.series);
        setStats(statsData);
      })
      .finally(() => setDataLoading(false));
    loadJobs(selectedCompany);
  }, [loadJobs, selectedCompany]);

  useEffect(() => {
    loadData();
  }, []);

  const handleCompanyClick = (company: string) => {
    const next = selectedCompany === company ? null : company;
    setSelectedCompany(next);
    loadJobs(next);
  };

  const clearCompanyFilter = () => {
    setSelectedCompany(null);
    loadJobs(null);
  };

  const handleScrape = async () => {
    setScrapeStatus("loading");
    setScrapeResult("");
    const kw = scrapeCompany.trim()
      ? `${keywords} ${scrapeCompany.trim()}`
      : keywords;
    try {
      const result = await triggerScrape(kw, 2);
      setScrapeResult(`+${result.inserted} new · ${result.skipped} dupes · ${result.fetched} fetched`);
      setScrapeStatus("done");
      loadData();
    } catch {
      setScrapeResult("Scrape failed — check backend logs.");
      setScrapeStatus("error");
    }
  };

  const handleBulkScrape = async () => {
    setBulkStatus("loading");
    try {
      await triggerBulkScrape(10);
      setBulkStatus("started");
    } catch {
      setBulkStatus("idle");
    }
  };

  const lastScraped = stats?.last_scraped
    ? new Date(stats.last_scraped).toLocaleString("en-CA", {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      })
    : "—";

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Canada Job Analyzer</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Tracks Canadian tech hiring trends — auto-scraped every 6 hours
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap justify-end">
            <input
              type="text"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="keywords…"
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <input
              type="text"
              value={scrapeCompany}
              onChange={(e) => setScrapeCompany(e.target.value)}
              placeholder="company (optional)…"
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-44 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <button
              onClick={handleScrape}
              disabled={scrapeStatus === "loading"}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
            >
              {scrapeStatus === "loading" ? "Scraping…" : "Scrape now"}
            </button>
            <button
              onClick={handleBulkScrape}
              disabled={bulkStatus === "loading" || bulkStatus === "started"}
              title="Scrape all preset keywords across Canada at high page depth — runs in background"
              className="bg-gray-700 hover:bg-gray-800 disabled:opacity-50 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
            >
              {bulkStatus === "loading" ? "Starting…" : bulkStatus === "started" ? "Running in bg…" : "Full scrape"}
            </button>
            {scrapeResult && (
              <span className={`text-xs ${scrapeStatus === "error" ? "text-red-500" : "text-gray-500"}`}>
                {scrapeResult}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        {dataLoading ? (
          <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
            Loading…
          </div>
        ) : (
          <>
            {/* Stats row */}
            <div className="grid grid-cols-3 gap-4">
              <StatCard label="Postings indexed" value={stats?.total_jobs.toLocaleString() ?? "—"} />
              <StatCard label="Companies" value={stats?.total_companies.toLocaleString() ?? "—"} />
              <StatCard label="Last scraped" value={lastScraped} />
            </div>

            {/* Skill trend over time */}
            <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <h2 className="text-base font-semibold text-gray-800 mb-1">
                Skill Demand Over Time
              </h2>
              <p className="text-xs text-gray-400 mb-4">Weekly posting count for top skills — last 8 weeks</p>
              <SkillHistoryChart series={history} />
            </section>

            {/* Bar charts row */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Top Skills in Demand</h2>
                <p className="text-xs text-gray-400 mb-4">All-time frequency across indexed postings</p>
                <SkillsChart data={skills} />
              </section>

              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Most Common Roles</h2>
                <p className="text-xs text-gray-400 mb-4">Most frequently posted job titles</p>
                <RolesChart data={roles} />
              </section>

              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Most Active Companies</h2>
                <p className="text-xs text-gray-400 mb-4">Click a bar to filter postings by company</p>
                <CompaniesChart
                  data={companies}
                  activeCompany={selectedCompany}
                  onBarClick={handleCompanyClick}
                />
              </section>
            </div>

            {/* Job table */}
            <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-base font-semibold text-gray-800">
                  {selectedCompany ? `Postings — ${selectedCompany}` : "Recent Postings"}
                </h2>
                {selectedCompany && (
                  <button
                    onClick={clearCompanyFilter}
                    className="flex items-center gap-1.5 text-xs bg-amber-100 text-amber-800 px-3 py-1 rounded-full hover:bg-amber-200 transition-colors"
                  >
                    {selectedCompany} <span className="font-bold">×</span>
                  </button>
                )}
              </div>
              {jobsLoading ? (
                <p className="text-gray-400 text-sm py-4">Loading…</p>
              ) : (
                <JobTable jobs={jobs} />
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
