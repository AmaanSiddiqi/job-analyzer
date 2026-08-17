import { useEffect, useState } from "react";
import type { JobFilters, SkillTrend, SourceCount } from "../api/jobs";
import { sourceLabel } from "../lib/sources";

const WINDOWS = [
  { label: "Any time", value: undefined },
  { label: "Last 7 days", value: 7 },
  { label: "Last 30 days", value: 30 },
  { label: "Last 90 days", value: 90 },
];

interface Props {
  filters: JobFilters;
  sources: SourceCount[];
  skills: SkillTrend[];
  resultCount: number | null;
  onChange: (next: JobFilters) => void;
}

export default function FilterBar({ filters, sources, skills, resultCount, onChange }: Props) {
  // Local mirror so typing in the search box doesn't fire a request per keystroke.
  const [search, setSearch] = useState(filters.q ?? "");

  useEffect(() => {
    setSearch(filters.q ?? "");
  }, [filters.q]);

  useEffect(() => {
    const current = filters.q ?? "";
    if (search === current) return;
    const timer = setTimeout(() => onChange({ ...filters, q: search || undefined }), 350);
    return () => clearTimeout(timer);
  }, [search, filters, onChange]);

  const set = <K extends keyof JobFilters>(key: K, value: JobFilters[K]) =>
    onChange({ ...filters, [key]: value || undefined });

  const activeCount = Object.values(filters).filter((v) => v !== undefined && v !== "").length;
  const selectClass =
    "border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400";

  return (
    <section className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search titles…"
          aria-label="Search job titles"
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-52 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />

        <select
          value={filters.source_type ?? ""}
          onChange={(e) => set("source_type", e.target.value)}
          aria-label="Filter by source"
          className={selectClass}
        >
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.source_type} value={s.source_type}>
              {sourceLabel(s.source_type)} ({s.count.toLocaleString()})
            </option>
          ))}
        </select>

        <select
          value={filters.skill ?? ""}
          onChange={(e) => set("skill", e.target.value)}
          aria-label="Filter by skill"
          className={selectClass}
        >
          <option value="">Any skill</option>
          {skills.map((s) => (
            <option key={s.skill} value={s.skill}>
              {s.skill} ({s.count.toLocaleString()})
            </option>
          ))}
        </select>

        <input
          type="text"
          value={filters.location ?? ""}
          onChange={(e) => set("location", e.target.value)}
          placeholder="Location…"
          aria-label="Filter by location"
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-36 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />

        <select
          value={filters.since_days ?? ""}
          onChange={(e) =>
            set("since_days", e.target.value ? Number(e.target.value) : undefined)
          }
          aria-label="Filter by posting date"
          className={selectClass}
        >
          {WINDOWS.map((w) => (
            <option key={w.label} value={w.value ?? ""}>
              {w.label}
            </option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-sm text-gray-500">
            {resultCount === null
              ? "…"
              : `${resultCount.toLocaleString()} posting${resultCount === 1 ? "" : "s"}`}
          </span>
          {activeCount > 0 && (
            <button
              onClick={() => onChange({})}
              className="text-xs text-gray-600 hover:text-gray-900 underline"
            >
              Clear {activeCount} filter{activeCount === 1 ? "" : "s"}
            </button>
          )}
        </div>
      </div>

      {filters.company && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-xs text-gray-400">Company:</span>
          <button
            onClick={() => set("company", undefined)}
            className="flex items-center gap-1.5 text-xs bg-amber-100 text-amber-800 px-3 py-1 rounded-full hover:bg-amber-200 transition-colors"
          >
            {filters.company} <span className="font-bold">×</span>
          </button>
        </div>
      )}
    </section>
  );
}
