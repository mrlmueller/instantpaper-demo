'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, LogOut, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';

import { hasFullAccess, refreshIdTokenAndCookie, signOut } from '@/app/lib/firebase/auth';
import {
  STRIPE_SUBSCRIPTION_PRICE_ID,
  STRIPE_TOPUP_PRICE_ID,
  createCheckoutSessionUrl,
} from '@/app/lib/firebase/stripeCheckout';
import { useAuth } from '@/app/components/providers/AuthProvider';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type MeResponse = {
  uid: string;
  email: string | null;
  accountStatus: 'active' | 'blocked' | 'pending';
  blocked: boolean;
  fullAccess: boolean;
  legacyApproved: boolean;
};

function normalizeCode(value: string): string {
  return String(value || '')
    .trim()
    .toUpperCase()
    .replace(/\s+/g, '')
    .replace(/_/g, '-');
}

export function ActivatePage() {
  const { user, access, loading } = useAuth();
  const router = useRouter();

  const [code, setCode] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<'subscription' | 'topup' | null>(null);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meLoading, setMeLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const effectiveBlocked = Boolean(me?.blocked || access.blocked);
  const effectiveHasAccess = hasFullAccess(access) && !effectiveBlocked;

  const subtitle = useMemo(() => {
    if (effectiveBlocked) return 'Dein Account ist gesperrt. Bitte kontaktiere den Admin.';
    return "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>";
  }, [effectiveBlocked]);

  const getErrorMessage = (err: unknown, fallback: string) => {
    if (err instanceof Error && err.message) return err.message;
    if (typeof err === 'string' && err.trim()) return err.trim();
    return fallback;
  };

  const loadMe = async () => {
    setMeLoading(true);
    try {
      const res = await fetch('/api/me', { method: 'GET', cache: 'no-store' });
      const data = (await res.json()) as Partial<MeResponse> & { error?: string };
      if (!res.ok) throw new Error(data.error || 'Konnte Account-Status nicht laden.');
      setMe(data as MeResponse);
    } catch {
      // Non-fatal: gate can still work purely via token claims.
      setMe(null);
    } finally {
      setMeLoading(false);
    }
  };

  useEffect(() => {
    if (loading) return;
    if (!user) return;
    loadMe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, user?.uid]);

  useEffect(() => {
    if (loading) return;
    if (!user) return;
    if (effectiveHasAccess) {
      router.replace('/dashboard');
    }
  }, [loading, user, effectiveHasAccess, router]);

  const handleRedeem = async () => {
    setError(null);

    const codeNorm = normalizeCode(code);
    if (!codeNorm) {
      setError('Bitte einen Access‑Code eingeben.');
      return;
    }

    if (effectiveBlocked) {
      setError('Dein Account ist gesperrt. Bitte kontaktiere den Admin.');
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch('/api/access-codes/redeem', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: codeNorm }),
      });

      const data = (await res.json()) as { status?: string; error?: string; message?: string };
      if (!res.ok) {
        throw new Error(data.error || data.message || 'Code konnte nicht eingelöst werden.');
      }

      // Claim propagation requires a token refresh.
      await refreshIdTokenAndCookie();
      await loadMe();
      router.replace('/dashboard');
    } catch (err: unknown) {
      const msg = getErrorMessage(err, 'Code konnte nicht eingelöst werden.');
      setError(msg);
      toast.error('Aktivierung', { description: msg });
    } finally {
      setSubmitting(false);
    }
  };

  const handleRefresh = async () => {
    setError(null);
    setRefreshing(true);
    try {
      await refreshIdTokenAndCookie();
      await loadMe();
      router.refresh();
    } catch (err: unknown) {
      const msg = getErrorMessage(err, 'Konnte Token nicht aktualisieren.');
      toast.error('Aktualisieren', { description: msg });
    } finally {
      setRefreshing(false);
    }
  };

  const handleLogout = async () => {
    setError(null);
    try {
      await signOut();
    } catch {
      // ignore
    } finally {
      router.replace('/login');
    }
  };

  const startCheckout = async (kind: 'subscription' | 'topup') => {
    setError(null);

    if (!user) return;
    if (effectiveBlocked) {
      setError('Dein Account ist gesperrt. Bitte kontaktiere den Admin.');
      return;
    }

    setCheckoutLoading(kind);
    try {
      const mode = kind === 'subscription' ? 'subscription' : 'payment';
      const priceId = kind === 'subscription' ? STRIPE_SUBSCRIPTION_PRICE_ID : STRIPE_TOPUP_PRICE_ID;
      const returnBase = `${window.location.origin}/activate`;
      const url = await createCheckoutSessionUrl({
        uid: user.uid,
        mode,
        priceId,
        successUrl: `${returnBase}?checkout=success`,
        cancelUrl: `${returnBase}?checkout=cancel`,
      });
      window.location.assign(url);
    } catch (err: unknown) {
      const msg = getErrorMessage(err, 'Checkout konnte nicht gestartet werden.');
      setError(msg);
      toast.error('Checkout', { description: msg });
    } finally {
      setCheckoutLoading(null);
    }
  };

  const email = user?.email || me?.email || null;

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <Card className="border-border shadow-sm">
          <CardHeader className="space-y-1">
            <CardTitle className="text-xl">Zugriff aktivieren</CardTitle>
            <CardDescription>
              {email ? (
                <span className="block">
                  Eingeloggt als <span className="font-medium text-foreground">{email}</span>
                </span>
              ) : null}
              <span className="block mt-2">{subtitle}</span>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="access-code">Access‑Code</Label>
              <Input
                id="access-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="IP-XXXX-XXXX-XXXX"
                autoComplete="off"
                disabled={submitting || refreshing || effectiveBlocked}
              />
            </div>

            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            <div className="grid grid-cols-1 gap-2">
              <Button onClick={handleRedeem} disabled={submitting || refreshing || effectiveBlocked || meLoading}>
                {submitting ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                Einlösen
              </Button>

              <Button
                variant="outline"
                onClick={handleRefresh}
                disabled={submitting || refreshing || meLoading}
                title="Token Refresh, damit Admin-Freischaltung ohne Re-Login greift"
              >
                {refreshing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-2" />}
                Neu prüfen
              </Button>

              <Button variant="outline" onClick={handleLogout} disabled={submitting || refreshing}>
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </Button>
            </div>

            <div className="border-t pt-4 space-y-2">
              <p className="text-sm text-muted-foreground">Kein Code? Du kannst auch Credits kaufen.</p>
              <Button
                onClick={() => startCheckout('subscription')}
                disabled={Boolean(checkoutLoading) || submitting || refreshing || effectiveBlocked || meLoading}
              >
                {checkoutLoading === 'subscription' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                Abo starten ($25/Monat)
              </Button>
              <Button
                variant="outline"
                onClick={() => startCheckout('topup')}
                disabled={Boolean(checkoutLoading) || submitting || refreshing || effectiveBlocked || meLoading}
              >
                {checkoutLoading === 'topup' ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                Credits aufladen
              </Button>
            </div>

            {me && (me.accountStatus === 'blocked' || me.accountStatus === 'pending') ? (
              <p className="text-xs text-muted-foreground">
                Status: <span className="font-medium">{me.accountStatus}</span>
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
