"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeft,
  Mail,
  Calendar,
  FileText,
  Download,
  Coins,
  BarChart3,
  Zap,
  PenTool,
  TrendingUp,
  MessageSquareText,
  Loader2,
  LogOut,
  User,
} from "lucide-react";
import { toast } from "sonner";
import Cookies from "js-cookie";

import { useAuth } from "@/app/components/providers/AuthProvider";
import { signOut } from "@/app/lib/firebase/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
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
        <div className="w-72 border-r border-sidebar-border bg-sidebar flex flex-col shrink-0">
          <div className="p-6 border-b border-sidebar-border">
            <div className="flex items-center justify-between gap-3">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-9 w-9 rounded-md" />
            </div>
          </div>
          <div className="p-6 border-b border-sidebar-border">
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
              <Skeleton className="h-10 w-full rounded-lg" />
            </div>
          </div>
          <div className="p-4 border-t border-sidebar-border">
            <Skeleton className="h-10 w-full rounded-lg" />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-6xl mx-auto py-10 px-6 sm:px-10">
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
  const [logoutLoading, setLogoutLoading] = useState(false);
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
  const formatEur = (value: number) =>
    `${Number(value || 0).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
  const formatCompactNumber = (value: number) => {
    const abs = Math.abs(value);
    if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("de-DE", { maximumFractionDigits: 1 })}M`;
    if (abs >= 1_000) return `${(value / 1_000).toLocaleString("de-DE", { maximumFractionDigits: 1 })}k`;
    return formatNumber(value);
  };
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

  const handleLogout = async () => {
    if (logoutLoading) return;
    setLogoutLoading(true);
    try {
      const sessionCookie = Cookies.get("__session");
      if (sessionCookie) {
        try {
          await fetch(`${API_BASE_URL}/api/auth/revoke`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sessionCookie }),
          });
        } catch (error) {
          console.error("Failed to revoke session:", error);
        }
      }

      await signOut();
      window.location.href = "/login";
    } catch (error) {
      console.error("Logout failed:", error);
      toast.error("Abmelden fehlgeschlagen", {
        description: error instanceof Error ? error.message : "Bitte versuche es erneut.",
      });
      setLogoutLoading(false);
    }
  };

  if (isLoading) {
    return <ProfilePageSkeleton />;
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="flex h-screen">
        <div className="w-72 border-r border-sidebar-border bg-sidebar text-sidebar-foreground flex flex-col shrink-0">
          <div className="p-6 border-b border-sidebar-border">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-semibold text-foreground">InstantPaper</div>
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9"
                onClick={handleBack}
                disabled={backLoading || effectiveBlocked}
                aria-label="Zurück"
              >
                {backLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : <ArrowLeft className="h-5 w-5" />}
              </Button>
            </div>
          </div>

          <div className="p-6 border-b border-sidebar-border">
            <div className="flex flex-col items-center text-center">
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center text-xl font-semibold text-primary mb-3">
                {initials}
              </div>
              <h2 className="font-semibold text-foreground">{userName}</h2>
              <div className="flex items-center gap-1.5 mt-1 text-muted-foreground text-sm">
                <Mail className="h-3.5 w-3.5" />
                <span className="truncate max-w-[220px]">{userEmail}</span>
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
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground"
                  )}
                >
                  <User className="h-4 w-4" />
                  Profil
                </button>
              ) : null}

              <button
                onClick={() => setActiveTab("statistiken")}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  displayedTab === "statistiken"
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
                  effectiveBlocked || !canViewUsageInsights ? "hidden" : ""
                )}
              >
                <TrendingUp className="h-4 w-4" />
                Statistiken
              </button>

              <button
                onClick={() => setActiveTab("billing")}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  displayedTab === "billing"
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground"
                )}
              >
                <Coins className="h-4 w-4" />
                Billing
              </button>

              {!effectiveBlocked ? (
                <button
                  onClick={() => setActiveTab("exporte")}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                    displayedTab === "exporte"
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground"
                  )}
                >
                  <Download className="h-4 w-4" />
                  Exporte
                </button>
              ) : null}
            </nav>
          </div>

          <div className="p-4 border-t border-sidebar-border">
            <button
              onClick={handleLogout}
              disabled={logoutLoading}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                "text-destructive hover:bg-destructive/10 disabled:opacity-60 disabled:cursor-not-allowed"
              )}
            >
              {logoutLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogOut className="h-4 w-4" />}
              Abmelden
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-6xl mx-auto py-10 px-6 sm:px-10">
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
                <div className="mb-6">
                  <h2 className="text-xl font-semibold text-foreground">Deine Nutzungsstatistiken</h2>
                </div>
 
                {statsLoading ? (
                  <div className="space-y-6">
                    <div className="grid gap-6 lg:grid-cols-3">
                      <Card className="lg:col-span-2">
                        <CardContent className="space-y-4">
                          <div className="flex items-start justify-between gap-6">
                            <div className="space-y-2">
                              <Skeleton className="h-3 w-28" />
                              <Skeleton className="h-10 w-56" />
                            </div>
                            <div className="space-y-2 text-right">
                              <Skeleton className="h-3 w-16 ml-auto" />
                              <Skeleton className="h-6 w-24 ml-auto" />
                            </div>
                          </div>
                          <Skeleton className="h-2 w-full max-w-xl" />
                          <Skeleton className="h-3 w-28" />
                        </CardContent>
                      </Card>
                      <Card>
                        <CardContent className="space-y-4">
                          <Skeleton className="h-4 w-24" />
                          <Skeleton className="h-4 w-full" />
                          <Skeleton className="h-4 w-full" />
                          <Skeleton className="h-4 w-full" />
                        </CardContent>
                      </Card>
                    </div>

                    <Card>
                      <CardHeader className="border-b">
                        <Skeleton className="h-4 w-44" />
                      </CardHeader>
                      <CardContent>
                        <Skeleton className="h-24 w-full" />
                      </CardContent>
                    </Card>

                    <div className="grid gap-6 lg:grid-cols-2">
                      <Card>
                        <CardHeader className="border-b">
                          <Skeleton className="h-4 w-44" />
                        </CardHeader>
                        <CardContent>
                          <Skeleton className="h-48 w-full" />
                        </CardContent>
                      </Card>
                      <Card>
                        <CardHeader className="border-b">
                          <Skeleton className="h-4 w-44" />
                        </CardHeader>
                        <CardContent>
                          <Skeleton className="h-48 w-full" />
                        </CardContent>
                      </Card>
                    </div>

                    <div className="grid gap-6 lg:grid-cols-2">
                      <Card>
                        <CardHeader className="border-b">
                          <Skeleton className="h-4 w-44" />
                        </CardHeader>
                        <CardContent>
                          <Skeleton className="h-56 w-full" />
                        </CardContent>
                      </Card>
                      <Card>
                        <CardHeader className="border-b">
                          <Skeleton className="h-4 w-44" />
                        </CardHeader>
                        <CardContent>
                          <Skeleton className="h-56 w-full" />
                        </CardContent>
                      </Card>
                    </div>
                  </div>
                ) : !stats ? (
                  <Card className="p-6">
                    <p className="text-sm text-muted-foreground">Noch keine Statistiken verfügbar.</p>
                  </Card>
                ) : (
                  <>
                    <div className="grid gap-6 lg:grid-cols-3 mb-6">
                      <Card className="lg:col-span-2">
                        <CardContent>
                          <div className="flex items-start justify-between gap-6">
                            <div>
                              <p className="text-xs text-muted-foreground">Gesamtverbrauch</p>
                              <div className="mt-1 flex items-baseline gap-2">
                                <span className="text-4xl font-semibold text-foreground tabular-nums">
                                  {formatCreditsValue(stats.creditsTotal)}
                                </span>
                                <span className="text-sm text-muted-foreground">Credits</span>
                              </div>
                            </div>
                            <div className="text-right">
                              <p className="text-xs text-muted-foreground">Entspricht</p>
                              <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                                {formatEur(stats.estimatedCostUsd)}
                              </p>
                            </div>
                          </div>

                          <Progress value={100} className="mt-6 max-w-xl" />

                          <p className="mt-3 text-xs text-muted-foreground">
                            Seit{" "}
                            {memberSince.toLocaleDateString("de-DE", {
                              month: "long",
                              year: "numeric",
                            })}
                          </p>
                        </CardContent>
                      </Card>

                      <Card>
                        <CardHeader>
                          <CardTitle className="text-sm font-medium text-muted-foreground">Aktivität</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-3">
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-sm text-foreground">Verarbeitungen</span>
                            <span className="text-sm font-medium text-foreground tabular-nums">
                              {formatNumber(stats.runsTotal)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-sm text-foreground">Exporte</span>
                            <span className="text-sm font-medium text-foreground tabular-nums">
                              {formatNumber(stats.exportCount)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-sm text-foreground">Quellen</span>
                            <span className="text-sm font-medium text-foreground tabular-nums">
                              {formatNumber(stats.totalQuellen)}
                            </span>
                          </div>
                        </CardContent>
                      </Card>
                    </div>

                    <Card className="mb-6">
                      <CardHeader className="border-b">
                        <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
                          <PenTool className="h-4 w-4 text-muted-foreground" />
                          Generierte Inhalte
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-6">
                          <div className="text-center">
                            <div className="text-3xl font-semibold text-primary tabular-nums">
                              {formatNumber(stats.totalProjects)}
                            </div>
                            <div className="text-xs text-muted-foreground">Projekte</div>
                          </div>
                          <div className="text-center">
                            <div className="text-3xl font-semibold text-primary tabular-nums">
                              {formatNumber(stats.totalKapitel)}
                            </div>
                            <div className="text-xs text-muted-foreground">Kapitel</div>
                          </div>
                          <div className="text-center">
                            <div className="text-3xl font-semibold text-primary tabular-nums">
                              {formatCompactNumber(stats.totalWords > 0 ? Math.round(stats.totalWords / 0.75) : 0)}
                            </div>
                            <div className="text-xs text-muted-foreground">Tokens generiert</div>
                          </div>
                          <div className="text-center">
                            <div className="text-3xl font-semibold text-primary tabular-nums">
                              {formatNumber(stats.totalQuellen)}
                            </div>
                            <div className="text-xs text-muted-foreground">Quellen verarbeitet</div>
                          </div>
                          <div className="text-center">
                            <div className="text-3xl font-semibold text-primary tabular-nums">
                              {Number(stats.runsTotal > 0 ? stats.creditsTotal / stats.runsTotal : 0).toLocaleString("de-DE", {
                                maximumFractionDigits: 1,
                              })}
                            </div>
                            <div className="text-xs text-muted-foreground">Ø Credits/Run</div>
                          </div>
                        </div>
                    </CardContent>
                    </Card>

                    <div className="grid gap-6 lg:grid-cols-2 mb-6">
                      <Card>
                        <CardHeader className="border-b">
                          <div className="flex items-center justify-between gap-3">
                            <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
                              <BarChart3 className="h-4 w-4 text-muted-foreground" />
                              Credit-Verbrauch
                            </CardTitle>
                            <span className="text-xs text-muted-foreground">Letzte 6 Monate</span>
                          </div>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          {stats.runsByMonth.map((month) => (
                            <div key={month.key} className="flex items-center gap-3">
                              <span className="text-sm text-muted-foreground w-20 shrink-0">
                                {new Date(`${month.key}-01`)
                                  .toLocaleDateString("de-DE", { month: "short", year: "numeric" })
                                  .replace(".", "")}
                              </span>
                              <Progress value={(month.credits / maxMonthlyCredits) * 100} className="h-2 flex-1" />
                              <div className="w-24 text-right">
                                <div className="text-sm font-medium text-foreground tabular-nums">{formatCreditsValue(month.credits)}</div>
                                <div className="text-xs text-muted-foreground tabular-nums">
                                  {formatEur(stats.spendRate > 0 ? month.credits / stats.spendRate : 0)}
                                </div>
                              </div>
                            </div>
                          ))}
                        </CardContent>
                      </Card>

                      <Card>
                        <CardHeader className="border-b">
                          <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
                            <FileText className="h-4 w-4 text-muted-foreground" />
                            Projekt-Statistiken
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          {stats.creditsByProject.length > 0 ? (
                            <div className="space-y-4">
                              {stats.creditsByProject.map((projekt) => (
                                <div key={projekt.projektId}>
                                  <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-sm text-foreground truncate max-w-[220px]">{projekt.projektName}</span>
                                    <div className="text-right">
                                      <div className="text-sm font-medium text-foreground tabular-nums">
                                        {formatCreditsValue(projekt.credits)}
                                      </div>
                                      <div className="text-xs text-muted-foreground tabular-nums">
                                        {formatEur(stats.spendRate > 0 ? projekt.credits / stats.spendRate : 0)}
                                      </div>
                                    </div>
                                  </div>
                                  <Progress value={(projekt.credits / maxProjektCredits) * 100} className="h-2" />
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">Noch keine Credits erfasst.</p>
                          )}
                        </CardContent>
                      </Card>
                    </div>

                    <div className="grid gap-6 lg:grid-cols-2">
                      <Card>
                        <CardHeader className="border-b">
                          <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
                            <Coins className="h-4 w-4 text-muted-foreground" />
                            Verbrauch pro Operation
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          {operationRows.length > 0 ? (
                            <div className="space-y-4">
                              {operationRows
                                .filter((row) => row.key !== "other" && row.credits > 0)
                                .map((row) => (
                                  <div key={`${row.key}-${row.indent}`} className="space-y-2">
                                    <div className="flex items-start justify-between gap-4">
                                      <div className="min-w-0">
                                        <div
                                          className={cn(
                                            "truncate",
                                            row.indent ? "text-sm text-muted-foreground" : "text-sm font-medium text-foreground"
                                          )}
                                        >
                                          {row.label}
                                        </div>
                                      </div>
                                      <div className="text-right shrink-0">
                                        <div className="text-sm font-medium text-foreground tabular-nums">
                                          {formatCreditsValue(row.credits)}
                                        </div>
                                        <div className="text-xs text-muted-foreground tabular-nums">
                                          {formatEur(stats.spendRate > 0 ? row.credits / stats.spendRate : 0)}
                                        </div>
                                      </div>
                                    </div>
                                    <Progress
                                      value={(row.credits / maxOperationCredits) * 100}
                                      className={cn("h-2", row.indent ? "opacity-60" : "")}
                                    />
                                  </div>
                                ))}
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground">Noch keine Daten.</p>
                          )}
                        </CardContent>
                      </Card>

                      <Card>
                        <CardHeader className="border-b">
                          <CardTitle className="text-sm font-semibold text-foreground flex items-center gap-2">
                            <Zap className="h-4 w-4 text-muted-foreground" />
                            Modellnutzung
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-4">
                          {(() => {
                            const total = Math.max(1, stats.modelUsage.reduce((acc, m) => acc + (m.count || 0), 0));
                            return (
                              <>
                                {stats.modelUsage.map((model) => {
                                  const percent = Math.round(((model.count || 0) / total) * 100);
                                  return (
                                    <div key={model.model} className="space-y-2">
                                      <div className="flex items-center justify-between gap-4">
                                        <div className="flex items-center gap-2 min-w-0">
                                          <span className="h-2 w-2 rounded-full bg-primary shrink-0" />
                                          <span className="text-sm font-medium text-foreground truncate">{model.model}</span>
                                        </div>
                                        <div className="flex items-center gap-3 text-xs text-muted-foreground tabular-nums shrink-0">
                                          <span>{formatNumber(model.count)}</span>
                                          <span>{percent}%</span>
                                        </div>
                                      </div>
                                      <Progress value={percent} className="h-2" />
                                    </div>
                                  );
                                })}

                                <div className="pt-4 border-t border-border">
                                  <div className="flex items-center justify-between gap-4">
                                    <span className="text-sm text-muted-foreground">Credits / 1k Wörter</span>
                                    <span className="text-sm font-medium text-foreground tabular-nums">
                                      {formatCreditsValue(stats.totalWords > 0 ? stats.creditsTotal / (stats.totalWords / 1000) : 0)}
                                    </span>
                                  </div>
                                </div>
                              </>
                            );
                          })()}
                        </CardContent>
                      </Card>
                    </div>
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
