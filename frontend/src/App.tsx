import { useEffect, useState } from "react";
import SkillsChart from "./components/SkillsChart";
import RolesChart from "./components/RolesChart";
import JobTable from "./components/JobTable";
import {
  fetchJobs,
  fetchSkillTrends,
  fetchRoleTrends,
  triggerScrape,
  JobPosting,
  SkillTrend,
  RoleTrend,
} from "./api/jobs";

type ScrapeStatus = "idle" | "loading" | "done" | "error";

export default function App() {
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [skills, setSkills] = useState<SkillTrend[]>([]);
  const [roles, setRoles] = useState<RoleTrend[]>([]);
  const [totalJobs, setTotalJobs] = useState(0);
  const [dataLoading, setDataLoading] = useState(true);

  const [keywords, setKeywords] = useState("software engineer");
  const [scrapeStatus, setScrapeStatus] = useState<ScrapeStatus>("idle");
  const [scrapeResult, setScrapeResult] = useState<string>("");

  const loadData = () => {
    setDataLoading(true);
    Promise.all([fetchJobs({ limit: 50 }), fetchSkillTrends(20), fetchRoleTrends(15)])
      .then(([jobsData, skillsData, rolesData]) => {
        setJobs(jobsData);
        setSkills(skillsData.top_skills);
        setRoles(rolesData.top_roles);
        setTotalJobs(skillsData.total_jobs);
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

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Vancouver Job Analyzer</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {totalJobs} postings indexed
            </p>
          </div>

          {/* Scrape controls */}
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
              {scrapeStatus === "loading" ? "Scraping…" : "Scrape"}
            </button>
            {scrapeResult && (
              <span
                className={`text-xs ${scrapeStatus === "error" ? "text-red-500" : "text-gray-500"}`}
              >
                {scrapeResult}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        {dataLoading ? (
          <div className="flex items-center justify-center h-64 text-gray-400">
            Loading…
          </div>
        ) : (
          <>
            {/* Charts row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-4">
                  Top Skills in Demand
                </h2>
                <SkillsChart data={skills} />
              </section>

              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-4">
                  Most Common Roles
                </h2>
                <RolesChart data={roles} />
              </section>
            </div>

            {/* Job list */}
            <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <h2 className="text-base font-semibold text-gray-800 mb-4">
                Recent Postings
              </h2>
              <JobTable jobs={jobs} />
            </section>
          </>
        )}
      </main>
    </div>
  );
}
