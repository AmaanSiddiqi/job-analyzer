import { useCallback, useEffect, useState } from "react";
import SkillsChart from "./components/SkillsChart";
import RolesChart from "./components/RolesChart";
import CompaniesChart from "./components/CompaniesChart";
import JobTable from "./components/JobTable";
import SkillHistoryChart from "./components/SkillHistoryChart";
import FilterBar from "./components/FilterBar";
import SourceBreakdown from "./components/SourceBreakdown";
import {
  fetchJobs,
  fetchJobCount,
  fetchSkillTrends,
  fetchRoleTrends,
  fetchCompanyTrends,
  fetchSkillHistory,
  fetchSourceTrends,
  fetchStats,
  triggerBoardIngest,
  JobFilters,
  JobPosting,
  SkillTrend,
  RoleTrend,
  CompanyTrend,
  SkillHistorySeries,
  SourceCount,
  StatsResponse,
} from "./api/jobs";

type IngestStatus = "idle" | "loading" | "started" | "error";

const PAGE_SIZE = 100;

function describeAdminError(e: unknown): string {
  const status = (e as { response?: { status?: number } })?.response?.status;
  if (status === 401) return "Wrong admin key — click again to re-enter it.";
  if (status === 429) return "Rate limited — wait a minute and try again.";
  if (status === 503) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return detail ?? "Ingestion is currently disabled.";
  }
  return "Request failed — check backend logs.";
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-5 py-4">
      <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-800 mt-1">{value}</p>
      {hint && <p className="text-xs text-gray-400 mt-0.5">{hint}</p>}
    </div>
  );
}

export default function App() {
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [resultCount, setResultCount] = useState<number | null>(null);
  const [page, setPage] = useState(0);

  const [skills, setSkills] = useState<SkillTrend[]>([]);
  const [roles, setRoles] = useState<RoleTrend[]>([]);
  const [companies, setCompanies] = useState<CompanyTrend[]>([]);
  const [history, setHistory] = useState<SkillHistorySeries[]>([]);
  const [sources, setSources] = useState<SourceCount[]>([]);
  const [recentSources, setRecentSources] = useState<SourceCount[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [dataLoading, setDataLoading] = useState(true);

  const [filters, setFilters] = useState<JobFilters>({});
  const [ingestStatus, setIngestStatus] = useState<IngestStatus>("idle");
  const [ingestMessage, setIngestMessage] = useState("");

  // Refetch the postings list and its count whenever filters or page change.
  useEffect(() => {
    let cancelled = false;
    setJobsLoading(true);
    Promise.all([
      fetchJobs({ ...filters, limit: PAGE_SIZE, skip: page * PAGE_SIZE }),
      fetchJobCount(filters),
    ])
      .then(([rows, total]) => {
        if (cancelled) return;
        setJobs(rows);
        setResultCount(total);
      })
      .finally(() => {
        if (!cancelled) setJobsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters, page]);

  const loadAggregates = useCallback(() => {
    setDataLoading(true);
    Promise.all([
      fetchSkillTrends(20),
      fetchRoleTrends(15),
      fetchCompanyTrends(15),
      fetchSkillHistory([], 8),
      fetchSourceTrends(),
      fetchStats(),
    ])
      .then(([skillsData, rolesData, companiesData, historyData, sourcesData, statsData]) => {
        setSkills(skillsData.top_skills);
        setRoles(rolesData.top_roles);
        setCompanies(companiesData.top_companies);
        setHistory(historyData.series);
        setSources(sourcesData.sources);
        setRecentSources(sourcesData.recent_sources);
        setStats(statsData);
      })
      .finally(() => setDataLoading(false));
  }, []);

  useEffect(() => {
    loadAggregates();
  }, [loadAggregates]);

  // Any filter change resets pagination — otherwise page 3 of a narrower
  // result set silently shows nothing.
  const updateFilters = useCallback((next: JobFilters) => {
    setFilters(next);
    setPage(0);
  }, []);

  const toggleFilter = useCallback(
    <K extends keyof JobFilters>(key: K, value: JobFilters[K]) => {
      setFilters((current) => ({
        ...current,
        [key]: current[key] === value ? undefined : value,
      }));
      setPage(0);
    },
    []
  );

  const handleIngest = async () => {
    setIngestStatus("loading");
    setIngestMessage("");
    try {
      const result = await triggerBoardIngest();
      setIngestMessage(result.detail);
      setIngestStatus("started");
    } catch (e) {
      setIngestMessage(describeAdminError(e));
      setIngestStatus("error");
    }
  };

  const lastIngest = stats?.last_scraped
    ? new Date(stats.last_scraped).toLocaleString("en-CA", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "—";

  const freshThisWeek = recentSources.reduce((sum, s) => sum + s.count, 0);
  const hasFilters = Object.values(filters).some((v) => v !== undefined && v !== "");
  const totalPages = resultCount ? Math.ceil(resultCount / PAGE_SIZE) : 1;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-gray-900">
              Landed<span className="text-indigo-600">.</span>
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Canadian tech hiring intelligence — {sources.length} sources, refreshed every 6 hours
            </p>
          </div>

          <div className="flex flex-col items-end gap-1">
            <button
              onClick={handleIngest}
              disabled={ingestStatus === "loading"}
              title="Fetch every configured company board now (runs in the background, ~2 min)"
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium px-4 py-1.5 rounded-lg transition-colors"
            >
              {ingestStatus === "loading" ? "Starting…" : "Ingest now"}
            </button>
            {ingestMessage && (
              <span
                className={`text-xs max-w-xs text-right ${
                  ingestStatus === "error" ? "text-red-500" : "text-gray-500"
                }`}
              >
                {ingestMessage}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Postings indexed"
            value={stats?.total_jobs.toLocaleString() ?? "—"}
          />
          <StatCard label="Companies" value={stats?.total_companies.toLocaleString() ?? "—"} />
          <StatCard
            label="New this week"
            value={dataLoading ? "—" : freshThisWeek.toLocaleString()}
            hint={freshThisWeek === 0 ? "no new postings — check ingestion" : undefined}
          />
          <StatCard label="Last ingest" value={lastIngest} />
        </div>

        <FilterBar
          filters={filters}
          sources={sources}
          skills={skills}
          resultCount={resultCount}
          onChange={updateFilters}
        />

        {/* Postings first: the filters above act on this list, so it belongs
            directly beneath them rather than below the charts. */}
        <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-gray-800">Postings</h2>
            {totalPages > 1 && (
              <div className="flex items-center gap-2 text-sm">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="px-2 py-1 rounded border border-gray-200 disabled:opacity-40 hover:bg-gray-50"
                >
                  ←
                </button>
                <span className="text-gray-500 tabular-nums">
                  {page + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="px-2 py-1 rounded border border-gray-200 disabled:opacity-40 hover:bg-gray-50"
                >
                  →
                </button>
              </div>
            )}
          </div>
          {jobsLoading ? (
            <p className="text-gray-400 text-sm py-4">Loading…</p>
          ) : (
            <JobTable
              jobs={jobs}
              hasFilters={hasFilters}
              activeSkill={filters.skill}
              onSelectSkill={(skill) => toggleFilter("skill", skill)}
              onSelectCompany={(company) => toggleFilter("company", company)}
            />
          )}
        </section>

        {dataLoading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
            Loading trends…
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Where postings come from</h2>
                <p className="text-xs text-gray-400 mb-4">Click a source to filter the list</p>
                <SourceBreakdown
                  sources={sources}
                  recentSources={recentSources}
                  activeSource={filters.source_type}
                  onSelect={(source) => updateFilters({ ...filters, source_type: source })}
                />
              </section>

              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 lg:col-span-2">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Skill demand over time</h2>
                <p className="text-xs text-gray-400 mb-4">Weekly posting count for top skills — last 8 weeks</p>
                <SkillHistoryChart series={history} />
              </section>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Top skills in demand</h2>
                <p className="text-xs text-gray-400 mb-4">All-time frequency across indexed postings</p>
                <SkillsChart data={skills} />
              </section>

              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Most common roles</h2>
                <p className="text-xs text-gray-400 mb-4">Most frequently posted job titles</p>
                <RolesChart data={roles} />
              </section>

              <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                <h2 className="text-base font-semibold text-gray-800 mb-1">Most active companies</h2>
                <p className="text-xs text-gray-400 mb-4">Click a bar to filter postings by company</p>
                <CompaniesChart
                  data={companies}
                  activeCompany={filters.company ?? null}
                  onBarClick={(company) => toggleFilter("company", company)}
                />
              </section>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
