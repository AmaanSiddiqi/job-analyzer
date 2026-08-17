import type { JobPosting } from "../api/jobs";
import { SOURCE_BADGE, sourceLabel } from "../lib/sources";

interface Props {
  jobs: JobPosting[];
  hasFilters: boolean;
  activeSkill?: string;
  onSelectSkill: (skill: string) => void;
  onSelectCompany: (company: string) => void;
}

export default function JobTable({
  jobs,
  hasFilters,
  activeSkill,
  onSelectSkill,
  onSelectCompany,
}: Props) {
  if (jobs.length === 0) {
    return (
      <p className="text-gray-400 text-sm py-4">
        {hasFilters
          ? "No postings match these filters — try clearing one."
          : "No postings yet — run an ingest to get started."}
      </p>
    );
  }

  return (
    <div className="divide-y divide-gray-100">
      {jobs.map((job) => (
        <div key={job.id} className="py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <a
                href={job.source_url}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-indigo-600 hover:underline block"
              >
                {job.title}
              </a>
              <p className="text-sm text-gray-500 mt-0.5">
                <button
                  onClick={() => onSelectCompany(job.company)}
                  className="hover:text-gray-900 hover:underline"
                  title={`Show only ${job.company}`}
                >
                  {job.company}
                </button>
                {job.location && <> · {job.location}</>}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span
                className={`px-2 py-0.5 rounded-full text-xs ${
                  SOURCE_BADGE[job.source_type] ?? "bg-gray-100 text-gray-600"
                }`}
              >
                {sourceLabel(job.source_type)}
              </span>
              <span className="text-xs text-gray-400 whitespace-nowrap">
                {new Date(job.date_scraped).toLocaleDateString("en-CA", {
                  month: "short",
                  day: "numeric",
                })}
              </span>
            </div>
          </div>
          {job.skills.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {job.skills.map((skill) => (
                <button
                  key={skill}
                  onClick={() => onSelectSkill(skill)}
                  title={`Filter by ${skill}`}
                  className={`px-2 py-0.5 rounded-full text-xs transition-colors ${
                    activeSkill === skill
                      ? "bg-indigo-600 text-white"
                      : "bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                  }`}
                >
                  {skill}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
