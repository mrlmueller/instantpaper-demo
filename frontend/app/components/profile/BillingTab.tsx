"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  BarChart3,
  CreditCard,
  Loader2,
  Minus,
  Plus,
  RotateCcw,
  Settings,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/app/components/providers/AuthProvider";
import {
  createCheckoutSessionUrl,
  createCustomerPortalUrl,
  STRIPE_SUBSCRIPTION_PRICE_ID,
  STRIPE_TOPUP_PRICE_ID,
} from "@/app/lib/firebase/stripeCheckout";
import {
  fetchBillingBalance,
  fetchBillingLedger,
  fetchBillingSubscriptionStatus,
  type BillingBalance,
  type BillingLedgerEntry,
  type BillingSubscriptionStatus,
} from "@/app/lib/api/billingClient";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function formatCredits(value: number): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "0.00";
  return n.toLocaleString("de-DE", { maximumFractionDigits: 2 });
}

function formatDateTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateOnly(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("de-DE", {
    day: "numeric",
    month: "numeric",
    year: "numeric",
  });
}

function ledgerTitle(entry: BillingLedgerEntry): string {
  const source = (entry.source || "").trim();
  if (source === "stripe_subscription") return "Monatliche Abrechnung";
  if (source === "stripe_topup") return "Credits gekauft";
  if (source === "admin_adjustment") return "Credits angepasst";
  return source || entry.type || "Credit-Event";
}

function ledgerTag(entry: BillingLedgerEntry): string | null {
  const source = (entry.source || "").trim();
  if (source === "stripe_subscription") return "Abo";
  if (source === "stripe_topup") return "Aufladung";
  if (source === "admin_adjustment") return "Manuell";
  return null;
}

export function BillingTab({ active }: { active: boolean }) {
  const { user, effectiveBlocked, loading: authLoading } = useAuth();

  const [balance, setBalance] = useState<BillingBalance | null>(null);
  const [subscription, setSubscription] =
    useState<BillingSubscriptionStatus>(null);
  const [ledger, setLedger] = useState<BillingLedgerEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<
    "subscription" | "topup" | null
  >(null);
  const [portalLoading, setPortalLoading] = useState(false);

  const isBlocked = effectiveBlocked;

  const LEDGER_PAGE_LIMIT = 50;
  const LEDGER_VISIBLE_TARGET = 8;
  const LEDGER_MAX_PAGES = 6;

  const fetchLedgerUntilVisibleTarget = useCallback(
    async (cursor: string | null) => {
      let pageCursor: string | null = cursor;
      let next: string | null = null;
      const all: BillingLedgerEntry[] = [];

      for (let i = 0; i < LEDGER_MAX_PAGES; i++) {
        const res = await fetchBillingLedger({
          limit: LEDGER_PAGE_LIMIT,
          cursor: pageCursor,
        });
        all.push(...(res.entries || []));
        next = res.nextCursor;

        const visibleCount = all.filter((e) => (e.source || "").trim() !== "openai").length;
        if (!next || visibleCount >= LEDGER_VISIBLE_TARGET) break;

        pageCursor = next;
      }

      return { entries: all, nextCursor: next };
    },
    [LEDGER_MAX_PAGES]
  );

  const refreshAll = useCallback(async () => {
    setLoading(true);
    try {
      const [b, s, firstLedger] = await Promise.all([
        fetchBillingBalance(),
        fetchBillingSubscriptionStatus(),
        fetchLedgerUntilVisibleTarget(null),
      ]);
      setBalance(b);
      setSubscription(s);
      setLedger(firstLedger.entries || []);
      setNextCursor(firstLedger.nextCursor);
    } catch (err: unknown) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Billing konnte nicht geladen werden.";
      toast.error("Billing", { description: message });
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (!nextCursor) return;

    setLedgerLoading(true);
    try {
      const res = await fetchLedgerUntilVisibleTarget(nextCursor);
      setLedger((prev) => [...prev, ...(res.entries || [])]);
      setNextCursor(res.nextCursor);
    } catch (err: unknown) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Ledger konnte nicht geladen werden.";
      toast.error("Ledger", { description: message });
    } finally {
      setLedgerLoading(false);
    }
  }, [nextCursor]);

  useEffect(() => {
    if (!active) return;
    if (authLoading) return;
    if (!user?.uid) return;
    if (isBlocked) return;
    void refreshAll();
  }, [active, authLoading, isBlocked, user?.uid, refreshAll]);

  const periodEndLabel = useMemo(() => formatDateOnly(subscription?.currentPeriodEnd), [subscription?.currentPeriodEnd]);

  const startCheckout = useCallback(
    async (kind: "subscription" | "topup") => {
      if (!user?.uid) {
        toast.error("Checkout", { description: "Nicht eingeloggt." });
        return;
      }
      if (isBlocked) {
        toast.error("Checkout", { description: "Dein Account ist gesperrt." });
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
          uid: user.uid,
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
    },
    [isBlocked, user?.uid]
  );

  const openPortal = useCallback(async () => {
    if (!user?.uid) {
      toast.error("Portal", { description: "Nicht eingeloggt." });
      return;
    }

    setPortalLoading(true);
    try {
      const returnUrl = `${window.location.origin}/profil?tab=billing`;
      const url = await createCustomerPortalUrl({ returnUrl });
      window.location.assign(url);
    } catch (err: unknown) {
      const message =
        err instanceof Error && err.message
          ? err.message
          : "Portal konnte nicht geoeffnet werden.";
      toast.error("Portal", { description: message });
    } finally {
      setPortalLoading(false);
    }
  }, [user?.uid]);

  const planState = useMemo(() => {
    const status = String(subscription?.status || "").trim().toLowerCase();
    if (!subscription || !status) return "none" as const;
    if (status === "past_due") return "past_due" as const;
    if (subscription.cancelAtPeriodEnd) return "canceled" as const;
    if (status === "active" || status === "trialing") return "active" as const;
    return "none" as const;
  }, [subscription]);

  const subscriptionCreditsPerPeriod = useMemo(() => {
    const grant = ledger.find((e) => (e.source || "").trim() === "stripe_subscription" && Number(e.credits || 0) > 0);
    if (!grant) return null;
    const n = Number(grant.credits || 0);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [ledger]);

  const showHintBanner = planState === "active";
  const isCheckoutDisabled = Boolean(checkoutLoading) || portalLoading || loading || authLoading || isBlocked;

  const ledgerWithSaldo = useMemo(() => {
    const total = Number(balance?.totalCredits ?? 0);
    if (!Number.isFinite(total)) return [] as Array<{ entry: BillingLedgerEntry; saldoAfter: number }>;

    let saldo = total;
    return (ledger || []).map((entry) => {
      const saldoAfter = saldo;
      saldo = saldo - Number(entry.credits || 0);
      return { entry, saldoAfter };
    });
  }, [balance?.totalCredits, ledger]);

  const visibleLedger = useMemo(
    () => ledgerWithSaldo.filter(({ entry }) => (entry.source || "").trim() !== "openai").slice(0, 12),
    [ledgerWithSaldo]
  );

  if (isBlocked) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-semibold text-foreground">Credits &amp; Abonnement</h2>
        </div>

        <Card>
          <CardContent>
            <p className="text-sm font-medium text-foreground">Account gesperrt</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Du kannst dein Abo weiterhin verwalten (z. B. kündigen oder Zahlungsmethode ändern).
            </p>
            <div className="mt-4">
              <Button variant="outline" onClick={openPortal} disabled={portalLoading}>
                {portalLoading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Settings className="h-4 w-4" />}
                Abo verwalten
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-foreground">Credits &amp; Abonnement</h2>
      </div>

      {showHintBanner ? (
        <div className="flex items-center gap-3 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
          <RotateCcw className="h-4 w-4 text-blue-600" />
          <span className="font-medium">
            Hinweis: Deine Abo-Credits
            {subscriptionCreditsPerPeriod ? ` (${formatCredits(subscriptionCreditsPerPeriod)} Credits)` : ""} werden jeden
            Monat zurückgesetzt. Ungenutzte Credits verfallen.
          </span>
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardContent>
            <div className="flex items-start justify-between gap-6">
              <div>
                <p className="text-sm text-muted-foreground">Gesamt Credits</p>
                <p className="mt-2 text-4xl font-semibold text-foreground tabular-nums">
                  {formatCredits(balance?.totalCredits || 0)}
                </p>
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <Zap className="h-5 w-5 text-primary" />
              </div>
            </div>

            <div className="mt-6 space-y-2">
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm text-muted-foreground">Abo-Credits</span>
                <span className="text-sm font-medium text-foreground tabular-nums">
                  {formatCredits(balance?.subscriptionCredits || 0)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm text-muted-foreground">Auflade-Credits</span>
                <span className="text-sm font-medium text-foreground tabular-nums">
                  {formatCredits(balance?.topupCredits || 0)}
                </span>
              </div>
            </div>

            {balance?.isNegative ? (
              <p className="mt-4 text-sm text-destructive">
                Negatives Guthaben: bitte Credits aufladen.
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                <CreditCard className="h-5 w-5 text-muted-foreground" />
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium text-foreground">
                    {planState === "none" ? "Kein Abo" : "Pro Plan"}
                  </p>

                  {planState === "active" ? (
                    <span className="inline-flex items-center rounded-md bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
                      Aktiv
                    </span>
                  ) : null}
                  {planState === "canceled" ? (
                    <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                      Gekündigt
                    </span>
                  ) : null}
                  {planState === "past_due" ? (
                    <span className="inline-flex items-center rounded-md bg-red-600 px-2 py-0.5 text-xs font-semibold text-white">
                      Zahlung fällig
                    </span>
                  ) : null}
                </div>

                {planState === "active" && periodEndLabel ? (
                  <p className="mt-1 text-xs text-muted-foreground">Nächste Abrechnung: {periodEndLabel}</p>
                ) : null}

                {planState === "canceled" && periodEndLabel ? (
                  <p className="mt-1 flex items-center gap-1 text-xs text-orange-600">
                    <AlertCircle className="h-3.5 w-3.5" />
                    Läuft am {periodEndLabel} aus
                  </p>
                ) : null}
              </div>
            </div>

            <div className="mt-6">
              {planState === "active" ? (
                <Button variant="outline" className="w-full" onClick={openPortal} disabled={portalLoading || loading}>
                  {portalLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Settings className="h-4 w-4" />}
                  Abo verwalten
                </Button>
              ) : (
                <Button onClick={() => startCheckout("subscription")} className="w-full" disabled={isCheckoutDisabled}>
                  {checkoutLoading === "subscription" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                  Abo starten – 20€/Monat
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="py-0 gap-0">
        <CardContent className="flex items-center justify-between gap-6 py-6">
          <div>
              <p className="text-sm font-medium text-foreground">Credits aufladen</p>
            <p className="mt-1 text-sm text-muted-foreground">Kaufe zusätzliche Credits, die nicht ablaufen</p>
          </div>
          <Button
            onClick={() => startCheckout("topup")}
            disabled={isCheckoutDisabled}
            className="shrink-0"
          >
            {checkoutLoading === "topup" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Credits kaufen
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <BarChart3 className="h-4 w-4 text-muted-foreground" />
          Credit-Verlauf
        </div>

        <Card className="py-0 gap-0">
          <div className="divide-y">
            {loading && visibleLedger.length === 0 ? (
              <div className="px-6 py-4 text-sm text-muted-foreground">Lade Verlauf…</div>
            ) : visibleLedger.length === 0 ? (
              <div className="px-6 py-4 text-sm text-muted-foreground">Noch keine Einträge.</div>
            ) : (
              visibleLedger.map(({ entry, saldoAfter }) => {
                const delta = Number(entry.credits || 0);
                const isPositive = delta >= 0;
                const sign = isPositive ? "+" : "";
                const created = formatDateTime(entry.createdAt);
                const tag = ledgerTag(entry);
                return (
                  <div key={entry.id} className="flex items-start justify-between gap-6 px-6 py-4">
                    <div className="flex min-w-0 items-start gap-3">
                      <div
                        className={cn(
                          "mt-0.5 flex h-9 w-9 items-center justify-center rounded-md",
                          isPositive ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-600"
                        )}
                      >
                        {isPositive ? <Plus className="h-4 w-4" /> : <Minus className="h-4 w-4" />}
                      </div>

                      <div className="min-w-0">
                        <p className="text-sm font-medium text-foreground">{ledgerTitle(entry)}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          {created ? <span className="text-xs text-muted-foreground">{created}</span> : null}
                          {tag ? (
                            <span className="rounded-md border bg-background px-2 py-0.5 text-xs text-muted-foreground">
                              {tag}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className={cn("text-sm font-semibold tabular-nums", isPositive ? "text-emerald-600" : "text-red-600")}>
                        {sign}
                        {formatCredits(delta)}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground tabular-nums">
                        Saldo: {formatCredits(saldoAfter)}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {nextCursor ? (
            <div className="px-6 py-4">
              <Button variant="outline" onClick={loadMore} disabled={ledgerLoading}>
                {ledgerLoading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                Mehr anzeigen
              </Button>
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
