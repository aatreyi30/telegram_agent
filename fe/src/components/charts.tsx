import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";
const C1 = "hsl(var(--chart-1))";

function Tip({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-foreground">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="text-muted-foreground">
          {p.name}: <span className="font-semibold text-foreground">{Number(p.value).toLocaleString()}{unit}</span>
        </div>
      ))}
    </div>
  );
}

// Area/line over time (timeline: [{label, avg_views, posts}])
export function TimelineChart({ data, dataKey = "avg_views", unit = "" }: {
  data: any[]; dataKey?: string; unit?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="fillC1" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C1} stopOpacity={0.5} />
            <stop offset="100%" stopColor={C1} stopOpacity={0.04} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          minTickGap={40} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} />
        <Area type="monotone" dataKey={dataKey} stroke={C1} strokeWidth={2} fill="url(#fillC1)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Vertical bars (category on X). data: [{label, avg_views}]
export function BarsChart({ data, dataKey = "avg_views", unit = "", height = 260 }: {
  data: any[]; dataKey?: string; unit?: string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          interval={0} angle={data.length > 8 ? -35 : 0} textAnchor={data.length > 8 ? "end" : "middle"}
          height={data.length > 8 ? 60 : 30} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} cursor={{ fill: "hsl(var(--secondary))", opacity: 0.4 }} />
        <Bar dataKey={dataKey} fill={C1} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
