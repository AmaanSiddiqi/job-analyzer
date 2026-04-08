import { JobPosting } from "../api/jobs";

interface Props {
  jobs: JobPosting[];
}

export default function JobTable({ jobs }: Props) {
  if (jobs.length === 0) {
    return <p className="text-gray-400 text-sm py-4">No postings yet — trigger a scrape to get started.</p>;
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
  );
}
