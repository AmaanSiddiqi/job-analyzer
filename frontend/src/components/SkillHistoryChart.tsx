import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import { SkillHistorySeries } from "../api/jobs";

interface Props {
  series: SkillHistorySeries[];
}

const PALETTE = [
  "#6366f1", "#10b981", "#f59e0b", "#ef4444",
  "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6",
];

type ChartRow = Record<string, string | number>;

// Plots each skill's *share* of that week's postings rather than a raw count.
// Counts jumped and collapsed when the source changed from LinkedIn to company
// boards (different volume, not different demand); a percentage survives that.
function buildChartData(series: SkillHistorySeries[]): ChartRow[] {
  const weekSet = new Set<string>();
  for (const s of series) {
    for (const pt of s.data) weekSet.add(pt.week);
  }
  const weeks = [...weekSet].sort();

  return weeks.map((week) => {
    const row: ChartRow = {
      week: new Date(week).toLocaleDateString("en-CA", {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      }),
    };
    for (const s of series) {
      const pt = s.data.find((d) => d.week === week);
      row[s.skill] = pt ? Math.round(pt.share * 1000) / 10 : 0;
      row[`${s.skill}__n`] = pt?.count ?? 0;
      if (pt) row.__total = pt.total;
    }
    return row;
  });
}

export default function SkillHistoryChart({ series }: Props) {
  if (!series.length) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
        Not enough historical data yet — check back after a few ingest cycles.
      </div>
    );
  }

  const data = buildChartData(series);

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={data} margin={{ left: 0, right: 16, top: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
        <XAxis
          dataKey="week"
          tick={{ fontSize: 11, fill: "#94a3b8" }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: "#94a3b8" }}
          axisLine={false}
          tickLine={false}
          width={36}
          tickFormatter={(v: number) => `${v}%`}
        />
        <Tooltip
          contentStyle={{
            fontSize: 12,
            borderRadius: 8,
            border: "1px solid #e2e8f0",
            boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
          }}
          formatter={(v: number, name: string, item) => {
            const row = item.payload as ChartRow;
            return [`${v}% (${row[`${name}__n`]} of ${row.__total ?? "?"})`, name];
          }}
        />
        <Legend
          wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
          formatter={(value) => <span style={{ color: "#475569" }}>{value}</span>}
        />
        {series.map((s, i) => (
          <Line
            key={s.skill}
            type="monotone"
            dataKey={s.skill}
            stroke={PALETTE[i % PALETTE.length]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
