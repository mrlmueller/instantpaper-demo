"use client";

import * as React from "react";
import type { TooltipProps } from "recharts";
import { Legend, Tooltip } from "recharts";

import { cn } from "@/lib/utils";

export type ChartConfig = Record<
  string,
  {
    label?: React.ReactNode;
    color?: string;
  }
>;

type ChartContextValue = {
  config: ChartConfig;
};

const ChartContext = React.createContext<ChartContextValue>({ config: {} });

function useChart() {
  return React.useContext(ChartContext);
}

export function ChartContainer({
  config,
  className,
  children,
}: {
  config: ChartConfig;
  className?: string;
  children: React.ReactNode;
}) {
  const style = React.useMemo(() => {
    const vars: Record<string, string> = {};
    for (const [key, v] of Object.entries(config || {})) {
      if (v?.color) vars[`--color-${key}`] = String(v.color);
    }
    return vars as React.CSSProperties;
  }, [config]);

  return (
    <ChartContext.Provider value={{ config }}>
      <div className={cn("w-full h-full", className)} style={style}>
        {children}
      </div>
    </ChartContext.Provider>
  );
}

export const ChartTooltip = Tooltip;
export const ChartLegend = Legend;

export function ChartTooltipContent({
  active,
  payload,
  label,
  labelFormatter,
  hideLabel = false,
}: TooltipProps<number, string> & {
  hideLabel?: boolean;
  labelFormatter?: (label: unknown) => React.ReactNode;
}) {
  const { config } = useChart();
  if (!active || !payload?.length) return null;

  const title = hideLabel ? null : labelFormatter ? labelFormatter(label) : (label as React.ReactNode);

  return (
    <div className="rounded-lg border border-border bg-background/95 backdrop-blur px-3 py-2 shadow-sm">
      {title ? <div className="text-xs font-medium mb-2">{title}</div> : null}
      <div className="space-y-1">
        {payload.map((item, idx) => {
          const key = String(item.dataKey ?? idx);
          const meta = config?.[key];
          const color = meta?.color || (item.color as string | undefined) || "var(--color-chart-1)";
          const value = typeof item.value === "number" && Number.isFinite(item.value) ? item.value : null;
          return (
            <div key={`${key}-${idx}`} className="flex items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2 min-w-0">
                <span className="h-2.5 w-2.5 rounded-sm shrink-0" style={{ background: color }} />
                <span className="truncate text-muted-foreground">{meta?.label ?? item.name ?? key}</span>
              </div>
              <span className="tabular-nums">{value !== null ? String(value) : "—"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ChartLegendContent({
  payload,
  className,
}: {
  payload?: Array<{ value?: string; color?: string; dataKey?: string | number }>;
  className?: string;
}) {
  const { config } = useChart();
  if (!payload?.length) return null;

  return (
    <div className={cn("flex flex-wrap items-center gap-3 text-xs", className)}>
      {payload.map((item, idx) => {
        const key = String(item.dataKey ?? item.value ?? idx);
        const meta = config?.[key];
        const color = meta?.color || item.color || "var(--color-chart-1)";
        return (
          <div key={`${key}-${idx}`} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
            <span className="text-muted-foreground">{meta?.label ?? item.value ?? key}</span>
          </div>
        );
      })}
    </div>
  );
}

