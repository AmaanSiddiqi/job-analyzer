import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, LabelList,
} from "recharts";
import { SkillTrend } from "../api/jobs";

interface Props { data: SkillTrend[] }

export default function SkillsChart({ data }: Props) {
  if (!data.length) return (
    <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
      No data yet — trigger a scrape to populate.
    </div>
  );

  return (
    <ResponsiveContainer width="100%" height={440}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 40, top: 4, bottom: 4 }}>
        <XAxis type="number" tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
        <YAxis
          type="category"
          dataKey="skill"
          width={130}
          tick={{ fontSize: 12, fill: "#475569" }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          cursor={{ fill: "#f1f5f9" }}
          formatter={(v: number) => [v, "postings"]}
          contentStyle={{ fontSize: 13, borderRadius: 8, border: "1px solid #e2e8f0", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
        />
        <Bar dataKey="count" fill="#6366f1" radius={[0, 4, 4, 0]} maxBarSize={22}>
          <LabelList dataKey="count" position="right" style={{ fontSize: 11, fill: "#6366f1", fontWeight: 600 }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
