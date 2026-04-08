import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { RoleTrend } from "../api/jobs";

interface Props {
  data: RoleTrend[];
}

const COLORS = ["#10b981", "#34d399", "#6ee7b7"];

export default function RolesChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={360}>
      <BarChart data={data} layout="vertical" margin={{ left: 16, right: 24 }}>
        <XAxis type="number" tick={{ fontSize: 12 }} />
        <YAxis type="category" dataKey="title" width={180} tick={{ fontSize: 12 }} />
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
