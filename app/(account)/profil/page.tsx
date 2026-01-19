"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Mail,
  Calendar,
  FileText,
  Download,
  BookOpen,
  Coins,
  BarChart3,
  Zap,
  PenTool,
  Settings,
  TrendingUp,
  MessageSquareText,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import Cookies from "js-cookie";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { BillingTab } from "@/app/components/profile/BillingTab";
import { PromptManager } from "@/app/components/profile/PromptManager";
import { ExportsTab } from "@/app/components/profile/ExportsTab";

type ProfileTab = "einstellungen" | "billing" | "statistiken" | "exporte";

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

type UsageInsightsStats = {
  creditsTotal: number;
  spendRate: number;
  estimatedCostUsd: number;
  runsTotal: number;
  exportCount: number;
  totalProjects: number;
  totalKapitel: number;
  totalQuellen: number;
  totalWords: number;
  runsByMonth: Array<{ key: string; count: number; credits: number }>;
  creditsByProject: Array<{ projektId: string; projektName: string; credits: number }>;
  byOperationType: Array<{ operationType: string; count: number; credits: number }>;
  modelUsage: Array<{ model: string; count: number; credits: number }>;
  memberSince?: string;
  usd?: { totalCostUsd: number; exportCostUsd: number };
  limits?: { operationsScanned: number; maxOperationsScanned: number };
};

function ProfilePageSkeleton() {
  return (
    <div className="min-h-screen bg-background">
      <div className="flex h-screen">
        {/* Left Sidebar skeleton */}
        <div className="w-72 border-r bg-muted/10 flex flex-col shrink-0">
          <div className="p-6 border-b">
            <div className="flex items-center gap-3">
              <Skeleton className="h-9 w-9 rounded-md" />
              <Skeleton className="h-6 w-16" />
            </div>
          </div>
          <div className="p-6 border-b">
            <div className="flex flex-col items-center text-center">
              <Skeleton className="w-16 h-16 rounded-full mb-3" />
              <Skeleton className="h-5 w-28 mb-2" />
              <Skeleton className="h-4 w-36 mb-2" />
              <Skeleton className="h-3 w-24" />
            </div>
          </div>
          <div className="p-4 flex-1">
            <div className="space-y-1">
              <Skeleton className="h-10 w-full rounded-lg" />
              <Skeleton className="h-10 w-full rounded-lg" />
              <Skeleton className="h-10 w-full rounded-lg" />
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-5xl mx-auto py-8 px-8">
            <Skeleton className="h-6 w-40 mb-4" />
            <Card className="p-6 mb-8">
              <div className="flex items-center gap-2 mb-4">
                <Skeleton className="h-4 w-4" />
                <Skeleton className="h-4 w-28" />
              </div>
              <div className="flex gap-3">
                <Skeleton className="h-10 flex-1" />
                <Skeleton className="h-10 w-24" />
              </div>
              <Skeleton className="h-3 w-64 mt-3" />
            </Card>

            <div className="flex items-center gap-2 mb-4">
              <Skeleton className="h-5 w-5" />
              <Skeleton className="h-6 w-36" />
            </div>
            <Card className="p-6">
              <div className="flex items-center justify-between mb-6 pb-4 border-b">
                <div>
                  <Skeleton className="h-4 w-52 mb-2" />
                  <Skeleton className="h-3 w-72" />
                </div>
                <Skeleton className="h-6 w-11 rounded-full" />
              </div>
              <div className="flex gap-2 mb-6">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-9 w-28 rounded-md" />
                ))}
              </div>
              <div className="grid gap-3">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="border rounded-lg p-4">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Skeleton className="h-5 w-32" />
                        <Skeleton className="h-5 w-16 rounded-full" />
                      </div>
                      <div className="flex gap-1">
                        <Skeleton className="h-8 w-8 rounded-md" />
                        <Skeleton className="h-8 w-8 rounded-md" />
                        <Skeleton className="h-8 w-8 rounded-md" />
                      </div>
                    </div>
                    <Skeleton className="h-4 w-full mb-1" />
                    <Skeleton className="h-4 w-3/4" />
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ProfilPage() {
  const { user: authUser, effectiveBlocked, loading: authLoading, canViewUsageInsights } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState<ProfileTab>("einstellungen");
  const [stats, setStats] = useState<UsageInsightsStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [backLoading, setBackLoading] = useState(false);
  const displayedTab: ProfileTab = effectiveBlocked ? "billing" : !canViewUsageInsights && activeTab === "statistiken" ? "billing" : activeTab;

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab === "billing") setActiveTab("billing");
  }, [searchParams]);

  useEffect(() => {
    if (effectiveBlocked) setActiveTab("billing");
  }, [effectiveBlocked]);

  useEffect(() => {
    if (authLoading) return;
    if (!authUser?.uid) return;
    if (effectiveBlocked || !canViewUsageInsights) {
      setStats(null);
      setStatsLoading(false);
      return;
    }

    let cancelled = false;
    setStatsLoading(true);

    const token = Cookies.get("__session");
    if (!token) {
      setStats(null);
      setStatsLoading(false);
      return;
    }

    fetch(`${API_BASE_URL}/api/usage-insights/stats`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (res) => {
        if (res.status === 401) throw new Error("Sitzung abgelaufen. Bitte melde dich erneut an.");
        if (res.status === 403) return null;
        if (!res.ok) {
          const detail = (await res.json().catch(() => ({})))?.detail;
          throw new Error(typeof detail === "string" ? detail : "Statistiken konnten nicht geladen werden.");
        }
        return (await res.json()) as UsageInsightsStats;
      })
      .then((payload) => {
        if (cancelled) return;
        setStats(payload);
      })
      .catch((err: unknown) => {
        console.error("Failed to load usage insights stats:", err);
        if (cancelled) return;
        toast.error("Statistiken", {
          description: err instanceof Error ? err.message : "Statistiken konnten nicht geladen werden.",
        });
        setStats(null);
      })
      .finally(() => {
        if (cancelled) return;
        setStatsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authLoading, authUser?.uid, effectiveBlocked, canViewUsageInsights]);

  const isLoading = authLoading || !authUser;
  const userName = authUser?.displayName || authUser?.email || "Benutzer";
  const userEmail = authUser?.email || "user@example.com";
  const memberSince = useMemo(() => new Date(stats?.memberSince ?? new Date().toISOString()), [stats?.memberSince]);
  const initials = userName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  const formatNumber = (num: number) => num.toLocaleString("de-DE");
  const formatCreditsValue = (value: number) =>
    Number(value || 0).toLocaleString("de-DE", { maximumFractionDigits: 2 });
  const formatCredits = (value: number) => `${formatCreditsValue(value)} Credits`;
  const formatUsd = (value: number) => `$${Number(value || 0).toFixed(2)}`;
  const maxMonthlyCredits = Math.max(1, ...(stats?.runsByMonth ?? []).map((m) => m.credits));
  const maxProjektCredits = Math.max(1, ...(stats?.creditsByProject ?? []).map((p) => p.credits));

  type OpAggRow = { key: string; label: string; credits: number; count: number; indent: number; hint?: string };
  const operationRows: OpAggRow[] = useMemo(() => {
    if (!stats?.byOperationType?.length) return [];

    type Agg = { count: number; credits: number };
    const byType = new Map<string, Agg>();
    for (const item of stats.byOperationType) {
      const key = String(item.operationType || "").trim() || "unknown";
      byType.set(key, {
        count: Number(item.count ?? 0),
        credits: Number(item.credits ?? 0),
      });
    }

    const sum = (keys: string[]) =>
      keys.reduce(
        (acc, k) => {
          const v = byType.get(k);
          if (!v) return acc;
          return { count: acc.count + v.count, credits: acc.credits + v.credits };
        },
        { count: 0, credits: 0 } as Agg
      );

    const formatHint = (count: number, singular: string, plural: string) => {
      if (!count) return undefined;
      return `${count} ${count === 1 ? singular : plural}`;
    };

    const rows: OpAggRow[] = [];
    const push = (key: string, label: string, agg: Agg, indent: number, hint?: string) => {
      rows.push({ key, label, credits: agg.credits, count: agg.count, indent, hint });
    };

    const groups = [
      {
        key: "process_quelle",
        label: "Quellen verarbeiten",
        agg: sum(["process_quelle"]),
        hint: formatHint(sum(["process_quelle"]).count, "Quelle", "Quellen"),
        children: [{ key: "refine_result", label: "Quellen-Text verfeinern", unit: ["Version", "Versionen"] as const }],
      },
      {
        key: "combine",
        label: "Text kombinieren",
        agg: sum(["combine", "combine_intermediate"]),
        hint: formatHint(sum(["combine", "combine_intermediate"]).count, "Operation", "Operationen"),
        children: [{ key: "refine_combined", label: "Verfeinerung (Kombiniert)", unit: ["Version", "Versionen"] as const }],
      },
      {
        key: "summary",
        label: "Kontext-Summaries",
        agg: sum(["summary"]),
        hint: formatHint(sum(["summary"]).count, "Kapitel", "Kapitel"),
        children: [],
      },
      {
        key: "shorten",
        label: "Text kürzen",
        agg: sum(["shorten"]),
        hint: formatHint(sum(["shorten"]).count, "Run", "Runs"),
        children: [{ key: "refine_shortened", label: "Verfeinerung (Gekürzt)", unit: ["Version", "Versionen"] as const }],
      },
      {
        key: "lesefluss",
        label: "Lesefluss verbessern",
        agg: sum(["lesefluss"]),
        hint: formatHint(sum(["lesefluss"]).count, "Run", "Runs"),
        children: [{ key: "refine_lesefluss", label: "Verfeinerung (Lesefluss)", unit: ["Version", "Versionen"] as const }],
      },
      {
        key: "export_docx",
        label: "Export (DOCX)",
        agg: sum(["export_docx"]),
        hint: formatHint(sum(["export_docx"]).count, "Export", "Exporte"),
        children: [],
      },
    ];

    const known = new Set<string>([
      "process_quelle",
      "refine_result",
      "combine",
      "combine_intermediate",
      "refine_combined",
      "summary",
      "shorten",
      "refine_shortened",
      "lesefluss",
      "refine_lesefluss",
      "export_docx",
    ]);

    for (const g of groups) {
      const hasAny =
        g.agg.credits > 0 ||
        g.agg.count > 0 ||
        g.children.some((c) => (byType.get(c.key)?.credits ?? 0) > 0 || (byType.get(c.key)?.count ?? 0) > 0);
      if (!hasAny) continue;

      push(g.key, g.label, g.agg, 0, g.hint);
      for (const child of g.children) {
        const agg = byType.get(child.key);
        if (!agg || (agg.credits <= 0 && agg.count <= 0)) continue;
        push(child.key, child.label, agg, 1, formatHint(agg.count, child.unit[0], child.unit[1]));
      }
    }

    const extras: Array<{ key: string; agg: Agg }> = [];
    for (const [key, agg] of byType.entries()) {
      if (known.has(key)) continue;
      if (agg.credits <= 0 && agg.count <= 0) continue;
      extras.push({ key, agg });
    }
    if (extras.length) {
      extras.sort((a, b) => b.agg.credits - a.agg.credits);
      push("other", "Sonstiges", sum([]), 0);
      for (const extra of extras.slice(0, 8)) {
        push(extra.key, extra.key, extra.agg, 1, formatHint(extra.agg.count, "Op", "Ops"));
      }
    }

    return rows;
  }, [stats?.byOperationType]);

  const maxOperationCredits = useMemo(
    () => Math.max(1, ...operationRows.filter((r) => r.key !== "other").map((r) => r.credits)),
    [operationRows]
  );

  const handleBack = () => {
    if (effectiveBlocked) return;
    if (backLoading) return;
    setBackLoading(true);
    try {
      router.push("/dashboard");
    } catch (error: any) {
      setBackLoading(false);
    }
  };

  if (isLoading) {
    return <ProfilePageSkeleton />;
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="flex h-screen">
        <div className="w-72 border-r bg-muted/10 flex flex-col shrink-0">
          <div className="p-6 border-b">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9"
                onClick={handleBack}
                disabled={backLoading || effectiveBlocked}
              >
                {backLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin" />
                ) : (
                  <ArrowLeft className="h-5 w-5" />
                )}
              </Button>
              <h1 className="text-lg font-semibold text-foreground">Profil</h1>
            </div>
          </div>

          <div className="p-6 border-b">
            <div className="flex flex-col items-center text-center">
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center text-xl font-semibold text-primary mb-3">
                {initials}
              </div>
              <h2 className="font-semibold text-foreground">{userName}</h2>
              <div className="flex items-center gap-1.5 mt-1 text-muted-foreground text-sm">
                <Mail className="h-3.5 w-3.5" />
                <span>{userEmail}</span>
              </div>
              <div className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground">
                <Calendar className="h-3.5 w-3.5" />
                <span>
                  Seit{" "}
                  {memberSince.toLocaleDateString("de-DE", {
                    month: "short",
                    year: "numeric",
                  })}
                </span>
              </div>
            </div>
          </div>

          <div className="p-4 flex-1">
            <nav className="space-y-1">
              {!effectiveBlocked ? (
                <button
                  onClick={() => setActiveTab("einstellungen")}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                    displayedTab === "einstellungen"
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <Settings className="h-4 w-4" />
                  Einstellungen
                </button>
              ) : null}
              <button
                onClick={() => setActiveTab("billing")}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  displayedTab === "billing"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Coins className="h-4 w-4" />
                Billing
              </button>
              {!effectiveBlocked && canViewUsageInsights ? (
                <button
                  onClick={() => setActiveTab("statistiken")}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                    displayedTab === "statistiken"
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <TrendingUp className="h-4 w-4" />
                  Statistiken
                </button>
              ) : null}
              {!effectiveBlocked ? (
                <button
                  onClick={() => setActiveTab("exporte")}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                    displayedTab === "exporte"
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <Download className="h-4 w-4" />
                  Meine Exporte
                </button>
              ) : null}
            </nav>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-5xl mx-auto py-8 px-8">
              <Tabs value={displayedTab} onValueChange={(v) => setActiveTab(v as ProfileTab)}>
                {!effectiveBlocked ? (
                  <TabsContent value="einstellungen">
                    <h2 className="text-lg font-semibold text-foreground mb-4 flex items-center gap-2">
                      <MessageSquareText className="h-5 w-5 text-muted-foreground" />
                      Prompt-Bibliothek
                    </h2>
                    <Card className="p-4">
                      <PromptManager />
                    </Card>
                  </TabsContent>
                ) : null}

              <TabsContent value="billing">
                <h2 className="text-lg font-semibold text-foreground mb-4">Billing</h2>
                <BillingTab active={displayedTab === "billing"} />
              </TabsContent>

              {!effectiveBlocked && canViewUsageInsights ? (
                <TabsContent value="statistiken">
                <div className="mb-4">
                  <h2 className="text-lg font-semibold text-foreground">Statistiken</h2>
                  <p className="text-sm text-muted-foreground">
                    Credits-first Übersicht. USD-Werte sind nur eine interne Referenz.
                  </p>
                </div>
 
                {statsLoading ? (
                  <div className="space-y-6">
                    <Card className="p-6">
                      <Skeleton className="h-4 w-28 mb-3" />
                      <Skeleton className="h-10 w-56 mb-4" />
                      <div className="grid grid-cols-2 gap-3 max-w-sm">
                        <div className="rounded-lg border bg-muted/10 p-4">
                          <Skeleton className="h-3 w-24 mb-2" />
                          <Skeleton className="h-6 w-20" />
                        </div>
                        <div className="rounded-lg border bg-muted/10 p-4">
                          <Skeleton className="h-3 w-20 mb-2" />
                          <Skeleton className="h-6 w-24" />
                        </div>
                        <div className="rounded-lg border bg-muted/10 p-4">
                          <Skeleton className="h-3 w-16 mb-2" />
                          <Skeleton className="h-6 w-12" />
                        </div>
                        <div className="rounded-lg border bg-muted/10 p-4">
                          <Skeleton className="h-3 w-24 mb-2" />
                          <Skeleton className="h-6 w-28" />
                        </div>
                      </div>
                    </Card>
                    <div className="grid md:grid-cols-2 gap-6">
                      <Card className="p-6">
                        <Skeleton className="h-4 w-40 mb-6" />
                        <div className="space-y-4">
                          <Skeleton className="h-6 w-full" />
                          <Skeleton className="h-6 w-full" />
                          <Skeleton className="h-6 w-full" />
                        </div>
                      </Card>
                      <Card className="p-6">
                        <Skeleton className="h-4 w-40 mb-6" />
                        <div className="space-y-4">
                          <Skeleton className="h-10 w-full" />
                          <Skeleton className="h-10 w-full" />
                          <Skeleton className="h-10 w-full" />
                        </div>
                      </Card>
                    </div>
                  </div>
                ) : !stats ? (
                  <Card className="p-6">
                    <p className="text-sm text-muted-foreground">Noch keine Statistiken verfügbar.</p>
                  </Card>
                ) : (
                  <>
                    <Card className="p-6 mb-8">
                      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-6">
                        <div className="min-w-0">
                          <p className="text-xs text-muted-foreground">Gesamtverbrauch</p>
                          <p className="mt-1 text-3xl font-semibold text-foreground tabular-nums">
                            {formatCredits(stats.creditsTotal)}
                          </p>
                          <p className="mt-2 text-sm text-muted-foreground">
                            {formatNumber(stats.runsTotal)} Runs · {formatNumber(stats.totalProjects)} Projekte ·{" "}
                            {formatNumber(stats.totalKapitel)} Kapitel · {formatNumber(stats.totalQuellen)} Quellen
                          </p>
                          <p className="mt-2 text-xs text-muted-foreground">
                            Interne Kosten (≈ OpenAI):{" "}
                            <span className="font-medium text-foreground tabular-nums">
                              {formatUsd(stats.estimatedCostUsd)}
                            </span>
                            {stats.runsTotal > 0 ? (
                              <>
                                {" "}
                                · Ø{" "}
                                <span className="font-medium text-foreground tabular-nums">
                                  {formatUsd(stats.estimatedCostUsd / stats.runsTotal)}
                                </span>{" "}
                                pro Run
                              </>
                            ) : null}
                            {" "}
                            <span className="text-muted-foreground/70">
                              (Spend Rate: {formatCreditsValue(stats.spendRate)} Credits/$1)
                            </span>
                            {stats.usd ? (
                              <span className="text-muted-foreground/70">
                                {" "}
                                · Log: {formatUsd(stats.usd.totalCostUsd)}
                              </span>
                            ) : null}
                          </p>
                        </div>

                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full">
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">Ø Credits/Run</p>
                            <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                              {formatCreditsValue(stats.runsTotal > 0 ? stats.creditsTotal / stats.runsTotal : 0)}
                            </p>
                          </div>
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">$ pro Credit</p>
                            <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                              {formatUsd(stats.spendRate > 0 ? 1 / stats.spendRate : 0)}
                            </p>
                          </div>
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">Spend Rate</p>
                            <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                              {formatCreditsValue(stats.spendRate)}
                            </p>
                          </div>
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">Wörter (≈)</p>
                            <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                              {formatNumber(stats.totalWords)}
                            </p>
                          </div>
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">Credits / 1k Wörter</p>
                            <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                              {formatCreditsValue(stats.totalWords > 0 ? stats.creditsTotal / (stats.totalWords / 1000) : 0)}
                            </p>
                          </div>
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">Mitglied seit</p>
                            <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                              {memberSince.toLocaleDateString("de-DE")}
                            </p>
                          </div>
                        </div>
                      </div>
                    </Card>

                    <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
                      <Card className="p-6">
                        <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                          <BarChart3 className="h-4 w-4 text-muted-foreground" />
                          Letzte 6 Monate
                        </h3>
                        <div className="space-y-4">
                          {stats.runsByMonth.map((month) => (
                            <div key={month.key} className="flex items-center gap-3">
                              <span className="text-sm text-muted-foreground w-16 shrink-0">
                                {new Date(`${month.key}-01`)
                                  .toLocaleDateString("de-DE", { month: "short" })
                                  .replace(".", "")}
                              </span>
                              <div className="flex-1 h-6 bg-muted/30 rounded overflow-hidden">
                                <div
                                  className="h-full bg-primary/70 rounded transition-all"
                                  style={{ width: `${(month.credits / maxMonthlyCredits) * 100}%` }}
                                />
                              </div>
                              <div className="w-28 text-right">
                                <div className="text-sm text-muted-foreground tabular-nums">
                                  {formatCreditsValue(month.credits)}
                                </div>
                                <div className="text-xs text-muted-foreground">{month.count} Runs</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </Card>

                      <Card className="p-6">
                        <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                          <Coins className="h-4 w-4 text-muted-foreground" />
                          Top Projekte (Credits)
                        </h3>
                        {stats.creditsByProject.length > 0 ? (
                          <div className="space-y-4">
                            {stats.creditsByProject.map((projekt) => (
                              <div key={projekt.projektId}>
                                <div className="flex items-center justify-between mb-1.5">
                                  <span className="text-sm text-foreground truncate max-w-[220px]">{projekt.projektName}</span>
                                  <span className="text-sm font-medium text-foreground tabular-nums">
                                    {formatCreditsValue(projekt.credits)}
                                  </span>
                                </div>
                                <div className="h-2 bg-muted/30 rounded overflow-hidden">
                                  <div
                                    className="h-full bg-primary/70 rounded transition-all"
                                    style={{ width: `${(projekt.credits / maxProjektCredits) * 100}%` }}
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">Noch keine Credits erfasst.</p>
                        )}
                      </Card>

                      <Card className="p-6 md:col-span-2 lg:col-span-1">
                        <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                          <TrendingUp className="h-4 w-4 text-muted-foreground" />
                          Verbrauch nach Operation
                        </h3>
                        {operationRows.length > 0 ? (
                          <div className="space-y-3">
                            {operationRows.map((row) => (
                              <div
                                key={`${row.key}-${row.indent}`}
                                className={cn(
                                  "space-y-1",
                                  row.indent ? "pl-3 border-l border-border/60" : ""
                                )}
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div className="min-w-0">
                                    <div
                                      className={cn(
                                        "truncate",
                                        row.indent ? "text-muted-foreground text-sm" : "text-foreground text-sm font-medium"
                                      )}
                                    >
                                      {row.label}
                                    </div>
                                    {row.hint ? (
                                      <div className="text-xs text-muted-foreground">{row.hint}</div>
                                    ) : null}
                                  </div>
                                  <div className="text-sm font-medium text-foreground tabular-nums">
                                    {formatCreditsValue(row.credits)}
                                  </div>
                                </div>
                                {row.key !== "other" ? (
                                  <div className="h-1.5 bg-muted/30 rounded overflow-hidden">
                                    <div
                                      className={cn("h-full rounded", row.indent ? "bg-primary/30" : "bg-primary/70")}
                                      style={{ width: `${(row.credits / maxOperationCredits) * 100}%` }}
                                    />
                                  </div>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-sm text-muted-foreground">Noch keine Daten.</p>
                        )}
                        <p className="mt-4 text-xs text-muted-foreground">
                          Basis: {formatNumber(stats.limits?.operationsScanned ?? 0)}
                          {stats.limits?.maxOperationsScanned ? `/${formatNumber(stats.limits.maxOperationsScanned)}` : ""}{" "}
                          Operationen (neueste zuerst).
                        </p>
                      </Card>
                    </div>

                    <Card className="p-6">
                      <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                        <Zap className="h-4 w-4 text-muted-foreground" />
                        Modellnutzung
                      </h3>
                      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {stats.modelUsage.map((model) => (
                          <div key={model.model} className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-sm font-medium text-foreground truncate">{model.model}</p>
                            <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                              <span>{formatNumber(model.count)} Ops</span>
                              <span className="font-medium text-foreground tabular-nums">
                                {formatCreditsValue(model.credits)} Credits
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </Card>

                    <p className="text-xs text-muted-foreground mt-6">
                      Hinweis: Credits sind die Nutzer-Einheit. USD-Werte sind interne OpenAI-Kosten (kein Abrechnungsbetrag) und werden aus Credits / Spend Rate abgeleitet.
                    </p>
                  </>
                )}
                </TabsContent>
              ) : null}

              {!effectiveBlocked ? (
                <TabsContent value="exporte">
                  <ExportsTab userId={authUser.uid} />
                </TabsContent>
              ) : null}
            </Tabs>
          </div>
        </div>
      </div>
    </div>
  );
}
