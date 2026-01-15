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
  Key,
  Eye,
  EyeOff,
  Trash2,
  Settings,
  TrendingUp,
  MessageSquareText,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import Cookies from "js-cookie";

import { useAuth } from "@/app/components/providers/AuthProvider";
import {
  STRIPE_SUBSCRIPTION_PRICE_ID,
  STRIPE_TOPUP_PRICE_ID,
  createCheckoutSessionUrl,
} from "@/app/lib/firebase/stripeCheckout";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import {
  deleteOpenAIKey,
  fetchOpenAIKeyStatus,
  saveOpenAIKey,
  type OpenAIKeyStatus,
} from "@/app/lib/api/openaiKeyClient";
import { PromptManager } from "@/app/components/profile/PromptManager";
import { ExportsTab } from "@/app/components/profile/ExportsTab";
import { getLiveUserStats, type LiveUserStats } from "@/app/actions/stats";

type ProfileTab = "einstellungen" | "billing" | "statistiken" | "exporte";

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
  const { user: authUser, loading: authLoading } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState<ProfileTab>("einstellungen");
  const [stats, setStats] = useState<LiveUserStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [keyStatus, setKeyStatus] = useState<OpenAIKeyStatus | null>(null);
  const [keyLoading, setKeyLoading] = useState(true);
  const [savingKey, setSavingKey] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [statusError, setStatusError] = useState<string | null>(null);
  const [showSavedKey, setShowSavedKey] = useState(false);
  const [backLoading, setBackLoading] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<"subscription" | "topup" | null>(null);

  useEffect(() => {
    const tab = searchParams.get("tab");
    if (tab === "billing") setActiveTab("billing");
  }, [searchParams]);

  const startCheckout = async (kind: "subscription" | "topup") => {
    if (!authUser?.uid) {
      toast.error("Checkout", { description: "Nicht eingeloggt." });
      return;
    }

    setCheckoutLoading(kind);
    try {
      const mode = kind === "subscription" ? "subscription" : "payment";
      const priceId =
        kind === "subscription"
          ? STRIPE_SUBSCRIPTION_PRICE_ID
          : STRIPE_TOPUP_PRICE_ID;
      const returnUrl = `${window.location.origin}/profil?tab=billing`;
      const url = await createCheckoutSessionUrl({
        uid: authUser.uid,
        mode,
        priceId,
        successUrl: returnUrl,
        cancelUrl: returnUrl,
      });
      window.location.assign(url);
    } catch (err: unknown) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Checkout konnte nicht gestartet werden.";
      toast.error("Checkout", { description: message });
    } finally {
      setCheckoutLoading(null);
    }
  };

  useEffect(() => {
    if (authLoading) return;
    const token = Cookies.get("__session");
    if (!token) {
      setStatusError("Keine Sitzung gefunden. Bitte melde dich erneut an.");
      setKeyLoading(false);
      return;
    }

    fetchOpenAIKeyStatus(token)
      .then(setKeyStatus)
      .catch((err: any) => {
        const message = err?.message || "OpenAI-Schlüsselstatus konnte nicht geladen werden.";
        setStatusError(message);
        toast.error("OpenAI Key", { description: message });
      })
      .finally(() => setKeyLoading(false));
  }, [authLoading, authUser?.uid]);

  useEffect(() => {
    if (authLoading) return;
    if (!authUser?.uid) return;

    let cancelled = false;
    setStatsLoading(true);

    getLiveUserStats()
      .then((live) => {
        if (cancelled) return;
        setStats(live);
      })
      .catch((err: unknown) => {
        console.error("Failed to load live stats:", err);
        if (cancelled) return;
        toast.error("Statistiken", {
          description: "Statistiken konnten nicht geladen werden.",
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
  }, [authLoading, authUser?.uid]);

  const handleSaveKey = async () => {
    if (!apiKeyInput.trim()) return;
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Sitzung abgelaufen", {
        description: "Bitte melde dich erneut an.",
      });
      return;
    }
    try {
      setSavingKey(true);
      const status = await saveOpenAIKey(token, apiKeyInput.trim());
      setKeyStatus(status);
      setApiKeyInput("");
      toast.success("API-Schlüssel gespeichert", {
        description: "Dein API-Schlüssel wurde erfolgreich hinzugefügt.",
      });
    } catch (err: any) {
      const message = err?.message || "Key konnte nicht gespeichert werden.";
      toast.error("Fehler", { description: message });
    } finally {
      setSavingKey(false);
    }
  };

  const handleDeleteKey = async () => {
    const token = Cookies.get("__session");
    if (!token) {
      toast.error("Sitzung abgelaufen", {
        description: "Bitte melde dich erneut an.",
      });
      return;
    }
    try {
      setSavingKey(true);
      const status = await deleteOpenAIKey(token);
      setKeyStatus(status);
      toast.success("API-Schlüssel gelöscht");
    } catch (err: any) {
      const message = err?.message || "Key konnte nicht entfernt werden.";
      toast.error("Fehler", { description: message });
    } finally {
      setSavingKey(false);
    }
  };

  const isLoading = authLoading || keyLoading || !authUser;
  const userName = authUser?.displayName || authUser?.email || "Benutzer";
  const userEmail = authUser?.email || "user@example.com";
  const memberSince = useMemo(() => new Date(stats?.memberSince ?? new Date().toISOString()), [stats?.memberSince]);
  const initials = userName
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  const formatCost = (cents: number) => `$${(cents / 100).toFixed(2)}`;
  const formatNumber = (num: number) => num.toLocaleString("de-DE");
  const maskedSavedKey = `sk-**************************************${keyStatus?.last4 || "****"}`;
  const maxMonthlyRuns = Math.max(1, ...(stats?.runsByMonth ?? []).map((m) => m.runs));
  const maxProjektCost = Math.max(1, ...(stats?.costByProjekt ?? []).map((p) => p.cost));

  const handleBack = () => {
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
                disabled={backLoading}
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
              <button
                onClick={() => setActiveTab("einstellungen")}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  activeTab === "einstellungen"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Settings className="h-4 w-4" />
                Einstellungen
              </button>
              <button
                onClick={() => setActiveTab("billing")}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  activeTab === "billing"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Coins className="h-4 w-4" />
                Billing
              </button>
              <button
                onClick={() => setActiveTab("statistiken")}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  activeTab === "statistiken"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <TrendingUp className="h-4 w-4" />
                Statistiken
              </button>
              <button
                onClick={() => setActiveTab("exporte")}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  activeTab === "exporte"
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Download className="h-4 w-4" />
                Meine Exporte
              </button>
            </nav>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-5xl mx-auto py-8 px-8">
            <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as ProfileTab)}>
              <TabsContent value="einstellungen">
                <h2 className="text-lg font-semibold text-foreground mb-4">API-Konfiguration</h2>
                <Card className="p-6 mb-8">
                  <h3 className="text-sm font-medium text-foreground mb-4 flex items-center gap-2">
                    <Key className="h-4 w-4 text-muted-foreground" />
                    API-Schlüssel
                  </h3>

                  {keyStatus?.hasKey ? (
                    <div className="flex items-center gap-3">
                      <div className="flex-1 relative">
                        <Input
                          type={showSavedKey ? "text" : "password"}
                          value={showSavedKey ? maskedSavedKey : maskedSavedKey}
                          readOnly
                          disabled={savingKey}
                          className="pr-10 font-mono text-sm bg-muted/50"
                        />
                        <button
                          type="button"
                          onClick={() => setShowSavedKey(!showSavedKey)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          disabled={savingKey}
                        >
                          {showSavedKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                        </button>
                      </div>
                      <Button variant="destructive" size="icon" onClick={handleDeleteKey} disabled={savingKey}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <Input
                        type="text"
                        placeholder="sk-..."
                        value={apiKeyInput}
                        onChange={(e) => setApiKeyInput(e.target.value)}
                        disabled={savingKey}
                        className="font-mono text-sm"
                      />
                      <Button onClick={handleSaveKey} disabled={!apiKeyInput.trim() || savingKey}>
                        Speichern
                      </Button>
                    </div>
                  )}

                  {statusError && <p className="text-sm text-destructive mt-3">{statusError}</p>}

                  {keyStatus && !keyStatus.hasKey && keyStatus.allowPlatformKey && (
                    <p className="text-xs text-muted-foreground mt-3 p-3 bg-blue-50/50 dark:bg-blue-950/20 rounded border border-blue-200/50 dark:border-blue-800/30">
                      Du bist für den Plattform-Key freigeschaltet und kannst auch ohne eigenen Key verarbeiten.
                    </p>
                  )}

                  <p className="text-xs text-muted-foreground mt-3">
                    {keyStatus?.hasKey
                      ? "Dein API-Schlüssel ist sicher verschlüsselt gespeichert."
                      : "Füge deinen API-Schlüssel hinzu, um die Verarbeitung zu aktivieren."}
                  </p>
                </Card>

                <h2 className="text-lg font-semibold text-foreground mb-4 flex items-center gap-2">
                  <MessageSquareText className="h-5 w-5 text-muted-foreground" />
                  Prompt-Bibliothek
                </h2>
                <Card className="p-4">
                  <PromptManager />
                </Card>
              </TabsContent>

              <TabsContent value="billing">
                <h2 className="text-lg font-semibold text-foreground mb-4">Billing</h2>
                <Card className="p-6 space-y-3">
                  <p className="text-sm text-muted-foreground">
                    Verwalte dein Abo oder lade Credits auf.
                  </p>
                  <div className="grid gap-2">
                    <Button
                      onClick={() => startCheckout("subscription")}
                      disabled={Boolean(checkoutLoading)}
                    >
                      {checkoutLoading === "subscription" ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : null}
                      Abo starten ($25/Monat)
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => startCheckout("topup")}
                      disabled={Boolean(checkoutLoading)}
                    >
                      {checkoutLoading === "topup" ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : null}
                      Credits aufladen
                    </Button>
                  </div>
                </Card>
              </TabsContent>

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
                        label="Gesamtkosten"
                        value={formatCost(stats.totalCost)}
                        subtext={`${stats.totalRuns} Verarbeitungen${
                          stats.exportCount > 0 || stats.exportCost > 0
                            ? ` • Exporte: ${stats.exportCount} (${formatCost(stats.exportCost)})`
                            : ""
                        }`}
                      />
                      <StatCard
                        icon={FileText}
                        label="Projekte"
                        value={String(stats.totalProjekte)}
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
                            <div key={month.month} className="flex items-center gap-3">
                              <span className="text-sm text-muted-foreground w-20 shrink-0">{month.month.slice(0, 3)}</span>
                              <div className="flex-1 h-6 bg-muted/30 rounded overflow-hidden">
                                <div
                                  className="h-full bg-primary/70 rounded transition-all"
                                  style={{ width: `${(month.runs / maxMonthlyRuns) * 100}%` }}
                                />
                              </div>
                              <span className="text-sm text-muted-foreground w-16 text-right">{month.runs} Runs</span>
                            </div>
                          ))}
                        </div>
                      </Card>

                      <Card className="p-6">
                        <h3 className="text-sm font-medium text-foreground mb-6 flex items-center gap-2">
                          <Coins className="h-4 w-4 text-muted-foreground" />
                          Kosten pro Projekt
                        </h3>
                        <div className="space-y-4">
                          {stats.costByProjekt.map((projekt) => (
                            <div key={projekt.projektId}>
                              <div className="flex items-center justify-between mb-1.5">
                                <span className="text-sm text-foreground truncate max-w-[200px]">{projekt.projektName}</span>
                                <span className="text-sm font-medium text-foreground">{formatCost(projekt.cost)}</span>
                              </div>
                              <div className="h-2 bg-muted/30 rounded overflow-hidden">
                                <div
                                  className="h-full bg-primary/70 rounded transition-all"
                                  style={{ width: `${(projekt.cost / maxProjektCost) * 100}%` }}
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
                  </>
                )}
              </TabsContent>

              <TabsContent value="exporte">
                <ExportsTab userId={authUser.uid} />
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </div>
    </div>
  );
}
