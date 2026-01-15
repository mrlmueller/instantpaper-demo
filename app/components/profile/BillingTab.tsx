"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Cookies from "js-cookie";
import { Loader2, RefreshCw } from "lucide-react";
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
import { Card } from "@/components/ui/card";

function getSessionTokenOrNull(): string | null {
  const raw = Cookies.get("__session");
  if (typeof raw !== "string") return null;
  const token = raw.trim();
  return token ? token : null;
}

function formatCredits(value: number): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "0.00";
  return n.toFixed(2);
}

function formatIsoDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ledgerLabel(entry: BillingLedgerEntry): string {
  const source = (entry.source || "").trim();
  if (source === "stripe_subscription") return "Abo (Stripe)";
  if (source === "stripe_topup") return "Top-up (Stripe)";
  if (source === "openai") return "Verbrauch (OpenAI)";
  if (source === "admin_adjustment") return "Admin Adjustment";
  return source || entry.type || "Ledger";
}

export function BillingTab({ active }: { active: boolean }) {
  const { user, access, loading: authLoading } = useAuth();

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

  const isBlocked = access.blocked;

  const refreshAll = useCallback(async () => {
    const token = getSessionTokenOrNull();
    if (!token) {
      toast.error("Billing", {
        description: "Keine Sitzung gefunden. Bitte melde dich erneut an.",
      });
      return;
    }

    setLoading(true);
    try {
      const [b, s, first] = await Promise.all([
        fetchBillingBalance(token),
        fetchBillingSubscriptionStatus(token),
        fetchBillingLedger(token, { limit: 30, cursor: null }),
      ]);
      setBalance(b);
      setSubscription(s);
      setLedger(first.entries || []);
      setNextCursor(first.nextCursor);
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
    const token = getSessionTokenOrNull();
    if (!token) return;
    if (!nextCursor) return;

    setLedgerLoading(true);
    try {
      const res = await fetchBillingLedger(token, { limit: 30, cursor: nextCursor });
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
    void refreshAll();
  }, [active, authLoading, refreshAll]);

  const expiresAtLabel = useMemo(
    () => formatIsoDate(balance?.subscriptionExpiresAt),
    [balance?.subscriptionExpiresAt]
  );
  const periodEndLabel = useMemo(
    () => formatIsoDate(subscription?.currentPeriodEnd),
    [subscription?.currentPeriodEnd]
  );

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end gap-2">
        <Button
          variant="outline"
          onClick={refreshAll}
          disabled={
            loading ||
            ledgerLoading ||
            Boolean(checkoutLoading) ||
            portalLoading ||
            authLoading
          }
        >
          {loading ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4 mr-2" />
          )}
          Aktualisieren
        </Button>
      </div>

      {isBlocked ? (
        <Card className="p-6">
          <p className="text-sm font-medium text-foreground">Account gesperrt</p>
          <p className="text-sm text-muted-foreground mt-1">
            Du kannst dein Abo weiterhin kuendigen oder deine Zahlungsmethode
            verwalten.
          </p>
          <div className="mt-4">
            <Button
              variant="outline"
              onClick={openPortal}
              disabled={portalLoading}
            >
              {portalLoading ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : null}
              Abo verwalten (Stripe)
            </Button>
          </div>
        </Card>
      ) : null}

      <Card className="p-6">
        <div className="flex items-start justify-between gap-6">
          <div>
            <p className="text-sm text-muted-foreground">Guthaben</p>
            <p className="text-3xl font-semibold text-foreground mt-1">
              {formatCredits(balance?.totalCredits || 0)} Credits
            </p>
            {balance?.isNegative ? (
              <p className="text-sm text-destructive mt-2">
                Negatives Guthaben: bitte im Billing Credits aufladen.
              </p>
            ) : null}
          </div>
          <div className="grid gap-1 text-sm text-muted-foreground">
            <div>
              Abo:{" "}
              <span className="text-foreground">
                {formatCredits(balance?.subscriptionCredits || 0)}
              </span>
            </div>
            <div>
              Top-up:{" "}
              <span className="text-foreground">
                {formatCredits(balance?.topupCredits || 0)}
              </span>
            </div>
            {expiresAtLabel ? <div>Abo bis: {expiresAtLabel}</div> : null}
          </div>
        </div>

        <div className="grid gap-2 mt-4">
          <Button
            onClick={() => startCheckout("subscription")}
            disabled={Boolean(checkoutLoading) || portalLoading || isBlocked}
          >
            {checkoutLoading === "subscription" ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            Abo starten ($25/Monat)
          </Button>
          <Button
            variant="outline"
            onClick={() => startCheckout("topup")}
            disabled={Boolean(checkoutLoading) || portalLoading || isBlocked}
          >
            {checkoutLoading === "topup" ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            Credits aufladen
          </Button>
          <Button
            variant="outline"
            onClick={openPortal}
            disabled={portalLoading || Boolean(checkoutLoading)}
          >
            {portalLoading ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : null}
            Abo verwalten (Stripe)
          </Button>
        </div>
      </Card>

      <Card className="p-6">
        <p className="text-sm text-muted-foreground">Subscription Status</p>
        <p className="text-lg font-medium text-foreground mt-1">
          {subscription?.status || "Keine Subscription"}
        </p>
        {periodEndLabel ? (
          <p className="text-sm text-muted-foreground mt-1">
            Period end: {periodEndLabel}
          </p>
        ) : null}
        {subscription?.cancelAtPeriodEnd ? (
          <p className="text-sm text-muted-foreground mt-1">
            Kuendigt am Period-Ende: ja
          </p>
        ) : null}
      </Card>

      <Card className="p-6">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">Ledger</h3>
        </div>

        <div className="mt-4 space-y-2">
          {ledger.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Noch keine Eintraege.
            </p>
          ) : (
            ledger.map((e) => {
              const sign = e.credits >= 0 ? "+" : "";
              const created = formatIsoDate(e.createdAt);
              const expires = formatIsoDate(e.expiresAt);
              return (
                <div key={e.id} className="border rounded-lg p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground">
                        {ledgerLabel(e)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {created ? `Created: ${created}` : null}
                        {created && expires ? " · " : null}
                        {expires ? `Expires: ${expires}` : null}
                      </p>
                    </div>
                    <div
                      className={
                        e.credits >= 0
                          ? "text-emerald-600 font-medium"
                          : "text-red-600 font-medium"
                      }
                    >
                      {sign}
                      {formatCredits(e.credits)} Credits
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {nextCursor ? (
          <div className="mt-4">
            <Button variant="outline" onClick={loadMore} disabled={ledgerLoading}>
              {ledgerLoading ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : null}
              Mehr laden
            </Button>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

