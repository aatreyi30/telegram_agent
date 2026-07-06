import { useCallback, useRef, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, 
  LabelList, Legend, Line, LineChart, Pie, PieChart, Radar, RadarChart,
  PolarGrid, PolarAngleAxis, PolarRadiusAxis, RadialBar, RadialBarChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
  ReferenceLine, Brush,
} from "recharts";
import { cn } from "@/lib/utils";

const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";
const CHART_COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
  "#60a5fa", "#f472b6", "#34d399", "#fbbf24", "#a78bfa",
  "#fb923c", "#22d3ee", "#e879f9", "#4ade80", "#facc15",
];

function fmt(v: number) { return v?.toLocaleString() ?? "—"; }

function Tip({ active, payload, label, unit = "", formatter }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border bg-popover px-4 py-3 text-xs shadow-xl backdrop-blur-sm">
      {label && <div className="mb-1.5 font-medium text-foreground">{label}</div>}
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2 text-muted-foreground">
          {p.color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: p.color }} />}
          <span>{p.name || formatter?.(p) || ""}:</span>
          <span className="font-semibold text-foreground">{fmt(Number(p.value))}{unit}</span>
        </div>
      ))}
    </div>
  );
}

export function TimelineChart({ data, dataKey = "value", unit = "", color, height = 260 }: 
  { data: any[]; dataKey?: string; unit?: string; color?: string; height?: number }) {
  const c = color || CHART_COLORS[0];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <defs>
          <linearGradient id={`fill-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={c} stopOpacity={0.35} />
            <stop offset="100%" stopColor={c} stopOpacity={0.04} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          minTickGap={40} interval="preserveStartEnd" />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40}
          tickFormatter={(v) => v >= 1000 ? `${(v/1000).toFixed(0)}k` : fmt(v)} />
        <Tooltip content={<Tip unit={unit} />} />
        <Area type="monotone" dataKey={dataKey} stroke={c} strokeWidth={2} fill={`url(#fill-${dataKey})`}
          dot={false} activeDot={{ r: 4, strokeWidth: 0 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function MultiTimelineChart({ data, keys, unit = "", height = 280 }:
  { data: any[]; keys: string[]; unit?: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <defs>
          {keys.map((k, i) => (
            <linearGradient key={k} id={`fill-m-${k}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART_COLORS[i % CHART_COLORS.length]} stopOpacity={0.25} />
              <stop offset="100%" stopColor={CHART_COLORS[i % CHART_COLORS.length]} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          minTickGap={40} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} />
        <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
        {keys.map((k, i) => (
          <Area key={k} type="monotone" dataKey={k} stroke={CHART_COLORS[i % CHART_COLORS.length]}
            strokeWidth={2} fill={`url(#fill-m-${k})`} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function BarsChart({ data, dataKey = "value", unit = "", height = 260, color, radius = true }:
  { data: any[]; dataKey?: string; unit?: string; height?: number; color?: string; radius?: boolean }) {
  const c = color || CHART_COLORS[0];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          interval={0} angle={data.length > 8 ? -35 : 0} textAnchor={data.length > 8 ? "end" : "middle"}
          height={data.length > 8 ? 50 : 30} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} cursor={{ fill: "hsl(var(--secondary))", opacity: 0.4 }} />
        <Bar dataKey={dataKey} fill={c} radius={radius ? [4, 4, 0, 0] : 0} maxBarSize={48} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function GroupedBarChart({ data, keys, unit = "", height = 280 }:
  { data: any[]; keys: string[]; unit?: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          interval={0} angle={data.length > 6 ? -25 : 0} textAnchor={data.length > 6 ? "end" : "middle"}
          height={data.length > 6 ? 50 : 30} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} cursor={{ fill: "hsl(var(--secondary))", opacity: 0.4 }} />
        <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
        {keys.map((k, i) => (
          <Bar key={k} dataKey={k} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[3, 3, 0, 0]}
            maxBarSize={24} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function StackedBarChart({ data, keys, unit = "", height = 280 }:
  { data: any[]; keys: string[]; unit?: string; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
          minTickGap={40} />
        <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<Tip unit={unit} />} cursor={{ fill: "hsl(var(--secondary))", opacity: 0.4 }} />
        <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
        {keys.map((k, i) => (
          <Bar key={k} dataKey={k} stackId="a" fill={CHART_COLORS[i % CHART_COLORS.length]} radius={i === keys.length - 1 ? [3, 3, 0, 0] : 0} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function SparklineChart({ data, dataKey = "value", color, height = 48, width = 120 }:
  { data: any[]; dataKey?: string; color?: string; height?: number; width?: number }) {
  const c = color || CHART_COLORS[0];
  if (!data?.length) return null;
  return (
    <ResponsiveContainer width={width} height={height}>
      <AreaChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`spark-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={c} stopOpacity={0.4} />
            <stop offset="100%" stopColor={c} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey={dataKey} stroke={c} strokeWidth={1.5} fill={`url(#spark-${dataKey})`}
          dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function RadarChartComponent({ data, keys, height = 300 }:
  { data: any[]; keys: string[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
        <PolarGrid stroke={GRID} />
        <PolarAngleAxis dataKey="label" tick={{ fill: AXIS, fontSize: 10 }} />
        <PolarRadiusAxis tick={{ fill: AXIS, fontSize: 9 }} axisLine={false} tickCount={4} />
        <Tooltip content={<Tip />} />
        {keys.map((k, i) => (
          <Radar key={k} name={k} dataKey={k} stroke={CHART_COLORS[i % CHART_COLORS.length]}
            fill={CHART_COLORS[i % CHART_COLORS.length]} fillOpacity={0.15} strokeWidth={2} />
        ))}
      </RadarChart>
    </ResponsiveContainer>
  );
}

export function PieChartComponent({ data, dataKey = "value", nameKey = "label", height = 260, innerRadius = 0 }:
  { data: any[]; dataKey?: string; nameKey?: string; height?: number; innerRadius?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie data={data} dataKey={dataKey} nameKey={nameKey} cx="50%" cy="50%"
          innerRadius={innerRadius} outerRadius={Math.min(height * 0.35, 100)}
          paddingAngle={2} strokeWidth={0}>
          {data.map((_, i) => (
            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip content={<Tip />} />
        <Legend wrapperStyle={{ fontSize: 10, paddingTop: 8 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function FunnelChart({ data, height = 280 }:
  { data: { label: string; value: number; rate?: string }[]; height?: number }) {
  const maxV = Math.max(...data.map(d => d.value));
  return (
    <div className="flex flex-col gap-1.5 px-2" style={{ height }}>
      {data.map((d, i) => {
        const pct = (d.value / maxV) * 100;
        return (
          <div key={i} className="flex items-center gap-3">
            <div className="w-24 shrink-0 text-right text-xs text-muted-foreground truncate" title={d.label}>{d.label}</div>
            <div className="flex-1">
              <div className="relative h-10 w-full">
                <div className="absolute inset-0 flex items-center">
                  <div className="h-full rounded-lg bg-primary/20" style={{ width: `${pct}%`, margin: "0 auto" }} />
                </div>
                <div className="absolute inset-0 flex items-center justify-between px-3 text-xs">
                  <span className="font-semibold text-foreground">{d.value.toLocaleString()}</span>
                  {d.rate && <span className="text-muted-foreground">{d.rate}</span>}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function HeatmapChart({ data, xKey = "hour", yKey = "day", valueKey = "value", height = 260 }:
  { data: any[]; xKey?: string; yKey?: string; valueKey?: string; height?: number }) {
  if (!data?.length) return null;
  const values = data.map(d => d[valueKey] ?? 0);
  const maxVal = Math.max(...values, 1);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <div className="grid gap-0.5" style={{ height, gridTemplateColumns: `repeat(${Math.ceil(Math.sqrt(data.length))}, 1fr)` }}>
        {data.map((d, i) => {
          const intensity = (d[valueKey] ?? 0) / maxVal;
          const r = Math.round(20 + intensity * 30);
          const g = Math.round(30 + (1 - intensity) * 40);
          const b = Math.round(50 + intensity * 60);
          return (
            <div key={i}
              className="rounded transition-all hover:scale-110 cursor-help"
              style={{ background: `rgb(${r}, ${g}, ${b})` }}
              title={`${d[yKey] || ""} ${d[xKey] || ""}: ${d[valueKey]?.toLocaleString() || 0}`}
            />
          );
        })}
      </div>
    </ResponsiveContainer>
  );
}

export function DistributionChart({ data, dataKey = "value", bins = 20, height = 200 }:
  { data: { value: number }[]; dataKey?: string; bins?: number; height?: number }) {
  if (!data?.length) return null;
  const values = data.map(d => d[dataKey] ?? 0).filter(v => v > 0);
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const binSize = (max - min) / bins || 1;
  const dist = Array.from({ length: bins }, (_, i) => {
    const lo = min + i * binSize;
    const hi = lo + binSize;
    const count = values.filter(v => v >= lo && (i === bins - 1 ? v <= hi : v < hi)).length;
    return { label: `${Math.round(lo).toLocaleString()}`, count, range: `${Math.round(lo)}-${Math.round(hi)}` };
  });
  return (
    <BarsChart data={dist} dataKey="count" unit="" height={height} color={CHART_COLORS[1]} />
  );
}
