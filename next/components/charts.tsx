"use client";

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  CHART_AXIS_COLOR as AXIS, CHART_GRID_COLOR as GRID, CHART_PRIMARY_COLOR as C1,
  CHART_SECONDARY_COLOR as C2, CHART_SERIES_COLORS as SERIES_COLORS,
} from "@/constants/charts";

// Humanize a raw dataKey ("avg_views" -> "Avg views") for legible tooltips/legends.
function humanize(key?: string): string {
  if (!key) return "";
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Tip({ active, payload, label, unit, countKey, countLabel = "Posts" }: any) {
  if (!active || !payload?.length) return null;
  // The full data row is on payload[0].payload — use it to surface an extra
  // context value (e.g. post count) without plotting a mismatched-scale series.
  const row = payload[0]?.payload;
  const count = countKey && row ? row[countKey] : undefined;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="font-medium text-foreground">{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="text-muted-foreground">
          {/* per-series unit (p.unit) wins over the chart-wide fallback, so a % series
              is never labelled with the primary series' unit (e.g. " views"). */}
          {p.name}: <span className="font-semibold text-foreground">{Number(p.value).toLocaleString()}{p.unit ?? unit}</span>
        </div>
      ))}
      {count != null && (
        <div className="text-muted-foreground">
          {countLabel}: <span className="font-semibold text-foreground">{Number(count).toLocaleString()}</span>
        </div>
      )}
    </div>
  );
}

export function TimelineChart({ data, dataKey = "avg_views", unit = "", secondaryKey, secondaryUnit, countKey, countLabel }: {
  data: any[]; dataKey?: string; unit?: string; secondaryKey?: string; secondaryUnit?: string; countKey?: string; countLabel?: string;
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
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={40} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} yAxisId="left" />
        {secondaryKey && (
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} yAxisId="right" orientation="right" />
        )}
        <Tooltip content={<Tip unit={unit} countKey={countKey} countLabel={countLabel} />} />
        <Area yAxisId="left" type="monotone" dataKey={dataKey} stroke={C1} strokeWidth={2} fill="url(#fillC1)" name={humanize(dataKey)} unit={unit} />
        {secondaryKey && (
          <Area yAxisId="right" type="monotone" dataKey={secondaryKey} stroke={C2} strokeWidth={1.5} strokeDasharray="4 3" fill="url(#fillC2)" name={humanize(secondaryKey)} unit={secondaryUnit} />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
}

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
        <Bar dataKey={dataKey} fill={C1} radius={[4, 4, 0, 0]} name={humanize(dataKey)} unit={unit} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function MultiLineChart({ data, series, unit = "", height = 280 }: {
  data: any[]; series: { key: string; name: string; color?: string }[]; unit?: string; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={40} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} />
        <Legend wrapperStyle={{ fontSize: 11, color: AXIS }} />
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} unit={unit}
            stroke={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]} strokeWidth={2} dot={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

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
          <Bar key={k.key} dataKey={k.key} name={k.name} stackId="stack" unit={unit}
            fill={k.color ?? SERIES_COLORS[i % SERIES_COLORS.length]}
            radius={i === keys.length - 1 ? [4, 4, 0, 0] : undefined} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
