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
  runsTotal: number;
  exportCount: number;
  totalProjects: number;
  totalKapitel: number;
  totalQuellen: number;
  totalWords: number;
  runsByMonth: Array<{ key: string; count: number; credits: number }>;
  creditsByProject: Array<{ projektId: string; projektName: string; credits: number }>;
  modelUsage: Array<{ model: string; count: number }>;
  memberSince?: string;
  usd?: { totalCostUsd: number; exportCostUsd: number };
};

function StatCard({
  icon: Icon,
  label,
  value,
  subtext,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  subtext?: string;
}) {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-4">
        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <Icon className="h-5 w-5 text-primary" />
        </div>
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold text-foreground mt-1">{value}</p>
          {subtext && <p className="text-xs text-muted-foreground mt-1">{subtext}</p>}
        </div>
      </div>
    </Card>
  );
}

function StatCardSkeleton() {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-4">
        <Skeleton className="w-10 h-10 rounded-lg" />
        <div className="flex-1">
          <Skeleton className="h-4 w-20 mb-2" />
          <Skeleton className="h-8 w-24" />
        </div>
      </div>
    </Card>
  );
}

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
  const formatCredits = (value: number) =>
    `${Number(value || 0).toLocaleString("de-DE", { maximumFractionDigits: 2 })} Credits`;
  const formatUsd = (value: number) => `$${Number(value || 0).toFixed(2)}`;
  const maxMonthlyRuns = Math.max(1, ...(stats?.runsByMonth ?? []).map((m) => m.count));
  const maxProjektCredits = Math.max(1, ...(stats?.creditsByProject ?? []).map((p) => p.credits));

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
                <h2 className="text-lg font-semibold text-foreground mb-4">Übersicht</h2>

                {statsLoading ? (
                  <div className="space-y-6">
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                      <StatCardSkeleton />
                      <StatCardSkeleton />
                      <StatCardSkeleton />
                      <StatCardSkeleton />
                    </div>
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
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                      <StatCard
                        icon={Coins}
                        label="Credits verbraucht"
                        value={formatCredits(stats.creditsTotal)}
                        subtext={`${stats.runsTotal} Verarbeitungen${stats.exportCount > 0 ? ` • Exporte: ${stats.exportCount}` : ""}`}
                      />
                      <StatCard
                        icon={FileText}
                        label="Projekte"
                        value={String(stats.totalProjects)}
                        subtext={`${stats.totalKapitel} Kapitel`}
                      />
                      <StatCard icon={BookOpen} label="Quellen" value={String(stats.totalQuellen)} subtext="Hochgeladen" />
                      <StatCard
                        icon={PenTool}
                        label="Generierte Wörter (≈)"
                        value={formatNumber(stats.totalWords)}
                        subtext="Aus Output Tokens"
                      />
                    </div>

                    <div className="grid md:grid-cols-2 gap-6 mb-8">
                      <Card className="p-6">
                        <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                          <BarChart3 className="h-4 w-4 text-muted-foreground" />
                          Aktivität pro Monat
                        </h3>
                        <div className="space-y-4">
                          {stats.runsByMonth.map((month) => (
                            <div key={month.key} className="flex items-center gap-3">
                              <span className="text-sm text-muted-foreground w-20 shrink-0">
                                {new Date(`${month.key}-01`).toLocaleDateString("de-DE", { month: "long" }).slice(0, 3)}
                              </span>
                              <div className="flex-1 h-6 bg-muted/30 rounded overflow-hidden">
                                <div
                                  className="h-full bg-primary/70 rounded transition-all"
                                  style={{ width: `${(month.count / maxMonthlyRuns) * 100}%` }}
                                />
                              </div>
                              <span className="text-sm text-muted-foreground w-16 text-right">{month.count} Runs</span>
                            </div>
                          ))}
                        </div>
                      </Card>

                      <Card className="p-6">
                        <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                          <Coins className="h-4 w-4 text-muted-foreground" />
                          Credits pro Projekt
                        </h3>
                        <div className="space-y-4">
                          {stats.creditsByProject.map((projekt) => (
                            <div key={projekt.projektId}>
                              <div className="flex items-center justify-between mb-1.5">
                                <span className="text-sm text-foreground truncate max-w-[200px]">{projekt.projektName}</span>
                                <span className="text-sm font-medium text-foreground">{formatCredits(projekt.credits)}</span>
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
                      </Card>
                    </div>

                    <Card className="p-6">
                      <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                        <Zap className="h-4 w-4 text-muted-foreground" />
                        Modellnutzung
                      </h3>
                      <div className="flex gap-6 flex-wrap">
                        {stats.modelUsage.map((model) => (
                          <div key={model.model} className="flex items-center gap-3 px-4 py-3 bg-muted/30 rounded-lg">
                            <div className="w-3 h-3 rounded-full bg-primary" />
                            <div>
                              <p className="text-sm font-medium text-foreground">{model.model}</p>
                              <p className="text-xs text-muted-foreground">{model.count} Verarbeitungen</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </Card>

                    {stats.usd ? (
                      <Card className="p-6 mt-6">
                        <h3 className="text-sm font-medium text-foreground mb-2 flex items-center gap-2">
                          <Coins className="h-4 w-4 text-muted-foreground" />
                          Interne Kosten (USD)
                        </h3>
                        <p className="text-xs text-muted-foreground">
                          Nur sichtbar für ausgewählte Accounts.
                        </p>
                        <div className="mt-4 grid grid-cols-2 gap-4">
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">Gesamt</p>
                            <p className="mt-2 text-lg font-semibold text-foreground tabular-nums">
                              {formatUsd(stats.usd.totalCostUsd)}
                            </p>
                          </div>
                          <div className="rounded-lg border bg-muted/10 p-4">
                            <p className="text-xs text-muted-foreground">Exporte</p>
                            <p className="mt-2 text-lg font-semibold text-foreground tabular-nums">
                              {formatUsd(stats.usd.exportCostUsd)}
                            </p>
                          </div>
                        </div>
                      </Card>
                    ) : null}
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
