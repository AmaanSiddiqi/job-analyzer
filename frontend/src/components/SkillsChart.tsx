import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { SkillTrend } from "../api/jobs";

interface Props {
  data: SkillTrend[];
}

const COLORS = ["#6366f1", "#8b5cf6", "#a78bfa"];

export default function SkillsChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={420}>
      <BarChart data={data} layout="vertical" margin={{ left: 16, right: 24 }}>
        <XAxis type="number" tick={{ fontSize: 12 }} />
        <YAxis type="category" dataKey="skill" width={140} tick={{ fontSize: 12 }} />
        <Tooltip
          formatter={(value: number) => [value, "postings"]}
          contentStyle={{ fontSize: 13 }}
        />
        <Bar dataKey="count" radius={[0, 4, 4, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
