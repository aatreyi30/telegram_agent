/** Shared types for reusable UI components — component-specific prop types
 * (e.g. ButtonProps' cva variants) stay colocated with their component, per
 * shadcn convention; this file is for types genuinely shared across more than
 * one file (a component's public data shape + whoever consumes it). */

export type DateRange = { from?: Date; to?: Date };

export type DatePreset = { label: string; days: number | "all" };

export type CalloutSeverity = "info" | "success" | "warning" | "danger";
