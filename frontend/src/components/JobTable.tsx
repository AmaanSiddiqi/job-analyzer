import { useMemo, useState } from "react";
import { JobPosting } from "../api/jobs";

interface Props {
  jobs: JobPosting[];
}

export default function JobTable({ jobs }: Props) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return jobs;
    return jobs.filter(
      (j) =>
        j.title.toLowerCase().includes(q) ||
        j.company.toLowerCase().includes(q) ||
        j.skills.some((s) => s.includes(q))
    );
  }, [jobs, query]);

  return (
    <div>
      <div className="mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter by title, company, or skill…"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
      </div>

      {filtered.length === 0 && (
        <p className="text-gray-400 text-sm py-4">
          {jobs.length === 0
            ? "No postings yet — trigger a scrape to get started."
            : `No results for "${query}".`}
        </p>
      )}

      <div className="divide-y divide-gray-100">
        {filtered.map((job) => (
          <div key={job.id} className="py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <a
                  href={job.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-indigo-600 hover:underline truncate block"
                >
                  {job.title}
                </a>
                <p className="text-sm text-gray-500 mt-0.5">
                  {job.company} · {job.location}
                </p>
              </div>
              <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">
                {new Date(job.date_scraped).toLocaleDateString()}
              </span>
            </div>
            {job.skills.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {job.skills.map((skill) => (
                  <span
                    key={skill}
                    className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded-full text-xs"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {filtered.length > 0 && (
        <p className="text-xs text-gray-400 pt-2 text-right">
          {filtered.length} of {jobs.length} postings
        </p>
      )}
    </div>
  );
}
