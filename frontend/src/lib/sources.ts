/** Display metadata for ingestion sources — kept out of component files so
 *  React fast refresh isn't broken by non-component exports. */

const SOURCE_LABELS: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  adzuna: "Adzuna",
  jooble: "Jooble",
  linkedin: "LinkedIn (archive)",
};

/** Tailwind classes for a filled bar per source. */
export const SOURCE_BAR: Record<string, string> = {
  greenhouse: "bg-emerald-500",
  lever: "bg-sky-500",
  ashby: "bg-violet-500",
  adzuna: "bg-amber-500",
  jooble: "bg-rose-500",
  linkedin: "bg-gray-400",
};

/** Tailwind classes for a small badge per source. */
export const SOURCE_BADGE: Record<string, string> = {
  greenhouse: "bg-emerald-50 text-emerald-700",
  lever: "bg-sky-50 text-sky-700",
  ashby: "bg-violet-50 text-violet-700",
  adzuna: "bg-amber-50 text-amber-700",
  jooble: "bg-rose-50 text-rose-700",
  linkedin: "bg-gray-100 text-gray-600",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}
