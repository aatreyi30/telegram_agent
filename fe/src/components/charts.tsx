import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  CHART_AXIS_COLOR as AXIS, CHART_GRID_COLOR as GRID, CHART_PRIMARY_COLOR as C1,
  CHART_SECONDARY_COLOR as C2, CHART_SERIES_COLORS as SERIES_COLORS,
} from "@/constants/charts";

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

function formatCategoryTick(value: string | number) {
  const text = String(value);
  if (/^\d{2}:\d{2}$/.test(text)) return text.slice(0, 2);
  return text;
}

// Area/line over time (timeline: [{label, avg_views, posts}])
export function TimelineChart({ data, dataKey = "avg_views", unit = "", secondaryKey, secondaryUnit }: {
  data: any[]; dataKey?: string; unit?: string; secondaryKey?: string; secondaryUnit?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="fillC1" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C1} stopOpacity={0.5} />
            <stop offset="100%" stopColor={C1} stopOpacity={0.04} />
          </linearGradient>
          <linearGradient id="fillC2" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C2} stopOpacity={0.3} />
            <stop offset="100%" stopColor={C2} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          minTickGap={40} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40}
          yAxisId="left" />
        {secondaryKey && (
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40}
            yAxisId="right" orientation="right" />
        )}
        <Tooltip content={<Tip unit={unit} />} />
        <Area yAxisId="left" type="monotone" dataKey={dataKey} stroke={C1} strokeWidth={2}
          fill="url(#fillC1)" name={dataKey} />
        {secondaryKey && (
          <Area yAxisId="right" type="monotone" dataKey={secondaryKey} stroke={C2}
            strokeWidth={1.5} strokeDasharray="4 3" fill="url(#fillC2)" name={secondaryKey} />
        )}
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
      <BarChart data={data} margin={{ top: 8, right: 24, left: 0, bottom: 46 }} barCategoryGap="10%">
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: data.length > 12 ? 10 : 11 }} tickLine={false} axisLine={false}
          interval={0} angle={data.length > 12 ? -30 : 0} textAnchor={data.length > 12 ? "end" : "middle"}
          height={data.length > 12 ? 70 : 30} tickMargin={10} tickFormatter={formatCategoryTick}
          padding={{ left: 12, right: 12 }} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} cursor={{ fill: "hsl(var(--secondary))", opacity: 0.4 }} />
        <Bar dataKey={dataKey} fill={C1} radius={[4, 4, 0, 0]} minPointSize={2} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// Multiple named lines over the same x-axis — e.g. owned channel vs 2-3
// competitors' views/day over time. data: [{label, ownedKey: n, competitorKey: n}]
export function MultiLineChart({ data, series, unit = "", height = 280 }: {
  data: any[]; series: { key: string; name: string; color?: string }[]; unit?: string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          minTickGap={40} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} />
        <Legend wrapperStyle={{ fontSize: 11, color: AXIS }} />
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.name}
            stroke={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]} strokeWidth={2} dot={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

// Stacked bars across named keys — e.g. deal-mix comparison across competitors.
// data: [{label, keyA: n, keyB: n, ...}]
export function StackedBarsChart({ data, keys, unit = "", height = 280 }: {
  data: any[]; keys: { key: string; name: string; color?: string }[]; unit?: string; height?: number;
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
        <Legend wrapperStyle={{ fontSize: 11, color: AXIS }} />
        {keys.map((k, i) => (
          <Bar key={k.key} dataKey={k.key} name={k.name} stackId="stack"
            fill={k.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
            radius={i === keys.length - 1 ? [4, 4, 0, 0] : undefined} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
