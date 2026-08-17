import type { SourceCount } from "../api/jobs";
import { SOURCE_BAR, sourceLabel } from "../lib/sources";

interface Props {
  sources: SourceCount[];
  recentSources: SourceCount[];
  activeSource?: string;
  onSelect: (source: string | undefined) => void;
}

export default function SourceBreakdown({
  sources,
  recentSources,
  activeSource,
  onSelect,
}: Props) {
  const total = sources.reduce((sum, s) => sum + s.count, 0);
  const recentBySource = new Map(recentSources.map((s) => [s.source_type, s.count]));

  return (
    <div className="space-y-3">
      {sources.map((s) => {
        const share = total ? (s.count / total) * 100 : 0;
        const recent = recentBySource.get(s.source_type) ?? 0;
        const isActive = activeSource === s.source_type;
        return (
          <button
            key={s.source_type}
            onClick={() => onSelect(isActive ? undefined : s.source_type)}
            aria-pressed={isActive}
            className={`w-full text-left group ${isActive ? "opacity-100" : "opacity-90 hover:opacity-100"}`}
          >
            <div className="flex items-baseline justify-between text-sm mb-1">
              <span className={`${isActive ? "font-semibold text-gray-900" : "text-gray-700"}`}>
                {sourceLabel(s.source_type)}
              </span>
              <span className="text-gray-500 tabular-nums">
                {s.count.toLocaleString()}
                <span className="text-gray-300 mx-1.5">·</span>
                <span className={recent > 0 ? "text-emerald-600" : "text-gray-400"}>
                  {recent > 0 ? `+${recent.toLocaleString()} this week` : "none this week"}
                </span>
              </span>
            </div>
            <div className="h-2 w-full bg-gray-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${SOURCE_BAR[s.source_type] ?? "bg-gray-400"}`}
                style={{ width: `${Math.max(share, 1)}%` }}
              />
            </div>
          </button>
        );
      })}
      {sources.length === 0 && <p className="text-sm text-gray-400">No postings yet.</p>}
    </div>
  );
}
