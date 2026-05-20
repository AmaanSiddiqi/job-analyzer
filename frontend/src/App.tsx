import { useEffect, useState } from "react";
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
  JobPosting,
  SkillTrend,
  RoleTrend,
  CompanyTrend,
  SkillHistorySeries,
  StatsResponse,
} from "./api/jobs";

type ScrapeStatus = "idle" | "loading" | "done" | "error";

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
  const [skills, setSkills] = useState<SkillTrend[]>([]);
  const [roles, setRoles] = useState<RoleTrend[]>([]);
  const [companies, setCompanies] = useState<CompanyTrend[]>([]);
  const [history, setHistory] = useState<SkillHistorySeries[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [dataLoading, setDataLoading] = useState(true);

  const [keywords, setKeywords] = useState("software engineer");
  const [scrapeStatus, setScrapeStatus] = useState<ScrapeStatus>("idle");
  const [scrapeResult, setScrapeResult] = useState<string>("");

  const loadData = () => {
    setDataLoading(true);
    Promise.all([
      fetchJobs({ limit: 50 }),
      fetchSkillTrends(20),
      fetchRoleTrends(15),
      fetchCompanyTrends(15),
      fetchSkillHistory([], 8),
      fetchStats(),
    ])
      .then(([jobsData, skillsData, rolesData, companiesData, historyData, statsData]) => {
        setJobs(jobsData);
        setSkills(skillsData.top_skills);
        setRoles(rolesData.top_roles);
        setCompanies(companiesData.top_companies);
        setHistory(historyData.series);
        setStats(statsData);
      })
      .finally(() => setDataLoading(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleScrape = async () => {
    setScrapeStatus("loading");
    setScrapeResult("");
    try {
      const result = await triggerScrape(keywords, 2);
      setScrapeResult(`+${result.inserted} new · ${result.skipped} dupes · ${result.fetched} fetched`);
      setScrapeStatus("done");
      loadData();
    } catch {
      setScrapeResult("Scrape failed — check backend logs.");
      setScrapeStatus("error");
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
            <h1 className="text-xl font-bold text-gray-900">Vancouver Job Analyzer</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Tracks Vancouver tech hiring trends — auto-scraped every 6 hours
            </p>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={keywords}
              onChange={(e) => setKeywords(e.target.value)}
              placeholder="keywords…"
              className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <button
              onClick={handleScrape}
              disabled={scrapeStatus === "loading"}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
            >
              {scrapeStatus === "loading" ? "Scraping…" : "Scrape now"}
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
                <p className="text-xs text-gray-400 mb-4">Companies with the most postings indexed</p>
                <CompaniesChart data={companies} />
              </section>
            </div>

            {/* Job table */}
            <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <h2 className="text-base font-semibold text-gray-800 mb-4">Recent Postings</h2>
              <JobTable jobs={jobs} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
