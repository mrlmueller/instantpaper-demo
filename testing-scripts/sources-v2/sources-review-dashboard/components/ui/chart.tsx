"use client";

import * as React from "react";
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
    for (const [key, value] of Object.entries(config || {})) {
      if (value?.color) {
        vars[`--color-${key}`] = String(value.color);
      }
    }
    return vars as React.CSSProperties;
  }, [config]);

  return (
    <ChartContext.Provider value={{ config }}>
      <div className={cn("h-full w-full min-h-0 min-w-0", className)} style={style}>
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
}: {
  active?: boolean;
  payload?: Array<{
    value?: number | string;
    color?: string;
    name?: string;
    dataKey?: string | number;
  }>;
  label?: unknown;
  hideLabel?: boolean;
  labelFormatter?: (label: unknown) => React.ReactNode;
}) {
  const { config } = useChart();
  if (!active || !payload?.length) {
    return null;
  }

  const title = hideLabel ? null : labelFormatter ? labelFormatter(label) : (label as React.ReactNode);

  return (
    <div className="chart-tooltip">
      {title ? <div className="chart-tooltip-title">{title}</div> : null}
      <div className="chart-tooltip-list">
        {payload.map((item, index) => {
          const key = String(item.dataKey ?? index);
          const meta = config[key];
          const color = meta?.color || (item.color as string | undefined) || "var(--chart-1)";
          const value = typeof item.value === "number" && Number.isFinite(item.value) ? item.value : null;
          return (
            <div className="chart-tooltip-row" key={`${key}-${index}`}>
              <div className="chart-tooltip-key">
                <span className="chart-tooltip-swatch" style={{ background: color }} />
                <span>{meta?.label ?? item.name ?? key}</span>
              </div>
              <span>{value !== null ? String(value) : "—"}</span>
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
  if (!payload?.length) {
    return null;
  }

  return (
    <div className={cn("chart-legend", className)}>
      {payload.map((item, index) => {
        const key = String(item.dataKey ?? item.value ?? index);
        const meta = config[key];
        const color = meta?.color || item.color || "var(--chart-1)";
        return (
          <div className="chart-legend-item" key={`${key}-${index}`}>
            <span className="chart-tooltip-swatch" style={{ background: color }} />
            <span>{meta?.label ?? item.value ?? key}</span>
          </div>
        );
      })}
    </div>
  );
}
