import { DashboardClient } from "./dashboard-client";
import { getDashboardPayload } from "@/lib/dashboard-data";
import type { DashboardTab } from "@/lib/dashboard-types";

export const dynamic = "force-dynamic";

function readParam(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}

function readTab(value: string | null): DashboardTab {
  const allowed: DashboardTab[] = ["overview", "plan", "queries", "retrieval", "candidates", "scoring", "coverage", "rerank", "final", "compare"];
  return allowed.includes((value ?? "") as DashboardTab) ? ((value ?? "overview") as DashboardTab) : "overview";
}

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const runId = readParam(params.run);
  const compareId = readParam(params.compare);
  const tab = readTab(readParam(params.tab));
  const data = await getDashboardPayload(runId, compareId);

  return <DashboardClient initialData={data} initialTab={tab} />;
}
