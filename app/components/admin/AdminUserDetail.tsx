'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { ArrowLeft, RefreshCw } from 'lucide-react';

import { AdminUserPromptManager } from '@/app/components/admin/AdminUserPromptManager';
import { AdminUserProjectsPanel } from '@/app/components/admin/AdminUserProjectsPanel';
import { AdminUserStatsPanel } from '@/app/components/admin/AdminUserStatsPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

type AdminUserDetailRow = {
  uid: string;
  email: string | null;
  displayName: string | null;
  fullAccess: boolean;
  legacyApproved: boolean;
  blocked: boolean;
  isAdmin: boolean;
  accountStatus: string | null;
  activatedByCode: string | null;
  activatedAt: string | null;
  disabled: boolean;
  allowPlatformKey: boolean;
  canDuplicateSystemPrompts: boolean;
  spendRate: number | null;
  effectiveSpendRate: number;
  createdAt: string | null;
  lastSignInAt: string | null;
};

type AdminBillingBalance = {
  totalCredits: number;
  subscriptionCredits: number;
  subscriptionExpiresAt: string | null;
  topupCredits: number;
  isNegative: boolean;
};

type AdminBillingSubscriptionStatus = {
  id: string;
  status: string | null;
  cancelAtPeriodEnd: boolean;
  currentPeriodEnd: string | null;
} | null;

type AdminBillingSummary = {
  balance: AdminBillingBalance;
  subscription: AdminBillingSubscriptionStatus;
};

type AdminBillingLedgerEntry = {
  id: string;
  type: string;
  source: string;
  credits: number;
  createdAt: string | null;
  expiresAt: string | null;
  note: string | null;
};

type AdminUserOpenAIKey = {
  hasKey: boolean;
  last4: string | null;
  allowPlatformKey: boolean;
  source: 'user' | 'platform' | 'none';
};

type AdminUserDetailResponse = {
  user: AdminUserDetailRow;
  openaiKey: AdminUserOpenAIKey;
  billing: AdminBillingSummary;
};

function keySourceLabel(source: AdminUserOpenAIKey['source']): string {
  if (source === 'user') return 'User Key';
  if (source === 'platform') return 'Platform Key';
  return 'No Key';
}

function ledgerLabel(entry: AdminBillingLedgerEntry): string {
  const source = String(entry.source || '').trim();
  if (source === 'stripe_subscription') return 'Abo (Stripe)';
  if (source === 'stripe_topup') return 'Top-up (Stripe)';
  if (source === 'openai') return 'Verbrauch (OpenAI)';
  if (source === 'admin_adjustment') return 'Admin Adjustment';
  return source || entry.type || 'Ledger';
}

function formatCredits(value: number): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '0.00';
  return n.toFixed(2);
}

function formatIso(value: string | null): string {
  if (!value) return '-';
  try {
    return new Date(value).toLocaleString('de-DE', {
      year: '2-digit',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return value;
  }
}

export function AdminUserDetail({ uid }: { uid: string }) {
  const [detail, setDetail] = useState<AdminUserDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [tab, setTab] = useState<'prompts' | 'billing' | 'stats' | 'projects'>('prompts');

  const [spendRateInput, setSpendRateInput] = useState('');
  const [savingSpendRate, setSavingSpendRate] = useState(false);

  const [adjustmentCreditsInput, setAdjustmentCreditsInput] = useState('');
  const [adjustmentNote, setAdjustmentNote] = useState('');
  const [creatingAdjustment, setCreatingAdjustment] = useState(false);

  const [ledger, setLedger] = useState<AdminBillingLedgerEntry[]>([]);
  const [ledgerNextCursor, setLedgerNextCursor] = useState<string | null>(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [ledgerMoreLoading, setLedgerMoreLoading] = useState(false);

  const title = useMemo(() => {
    const user = detail?.user;
    if (!user) return uid;
    return user.displayName || user.email || user.uid;
  }, [detail, uid]);

  const billing = detail?.billing;

  const load = async () => {
    setReloading(true);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}`, { cache: 'no-store' });
      const data = (await res.json()) as AdminUserDetailResponse & { error?: string };
      if (!res.ok) throw new Error(data.error || 'Konnte User nicht laden.');
      setDetail(data);
    } catch (err: any) {
      toast.error('Admin', { description: err?.message || 'Konnte User nicht laden.' });
      setDetail(null);
    } finally {
      setLoading(false);
      setReloading(false);
    }
  };

  const loadLedger = async (cursor: string | null) => {
    const qs = new URLSearchParams();
    qs.set('limit', '30');
    if (cursor) qs.set('cursor', cursor);
    const url = `/api/admin/users/${encodeURIComponent(uid)}/billing/ledger?${qs.toString()}`;

    const res = await fetch(url, { method: 'GET', cache: 'no-store' });
    const data = (await res.json().catch(() => ({}))) as
      | { entries?: AdminBillingLedgerEntry[]; nextCursor?: string | null; error?: string }
      | Record<string, unknown>;
    if (!res.ok) throw new Error((data as any)?.error || 'Ledger konnte nicht geladen werden.');

    const entries = Array.isArray((data as any).entries) ? ((data as any).entries as AdminBillingLedgerEntry[]) : [];
    const nextCursor = typeof (data as any).nextCursor === 'string' ? ((data as any).nextCursor as string) : null;
    return { entries, nextCursor };
  };

  useEffect(() => {
    setLoading(true);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  useEffect(() => {
    if (!detail) return;
    setSpendRateInput(detail.user.spendRate != null ? String(detail.user.spendRate) : '');
  }, [detail?.user.spendRate]);

  useEffect(() => {
    setLedger([]);
    setLedgerNextCursor(null);
    setLedgerLoading(false);
    setLedgerMoreLoading(false);
  }, [uid]);

  useEffect(() => {
    if (tab !== 'billing') return;
    if (!detail) return;
    setLedgerLoading(true);
    loadLedger(null)
      .then(({ entries, nextCursor }) => {
        setLedger(entries);
        setLedgerNextCursor(nextCursor);
      })
      .catch((err: any) => {
        toast.error('Billing', { description: err?.message || 'Ledger konnte nicht geladen werden.' });
        setLedger([]);
        setLedgerNextCursor(null);
      })
      .finally(() => setLedgerLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, detail?.user.uid]);

  const handleRefresh = () => {
    load();
    setRefreshNonce((n) => n + 1);
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <Skeleton className="h-9 w-9 rounded-md" />
            <div className="space-y-2">
              <Skeleton className="h-6 w-64" />
              <Skeleton className="h-4 w-40" />
            </div>
          </div>
          <Skeleton className="h-9 w-9 rounded-md" />
        </div>
        <div className="border-b">
          <Skeleton className="h-8 w-64" />
        </div>
        <div className="rounded-lg border p-6">
          <Skeleton className="h-10 w-full" />
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="rounded-lg border p-6">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{uid}</p>
            <p className="text-xs text-muted-foreground">Keine Daten verfügbar.</p>
          </div>
          <Button variant="outline" onClick={load} disabled={reloading}>
            Reload
          </Button>
        </div>
      </div>
    );
  }

  const user = detail.user;
  const key = detail.openaiKey;
  const keyLabel = `${keySourceLabel(key.source)}${key.last4 ? ` (.${key.last4})` : ''}`;
  const effectiveSpendRateLabel = Number.isFinite(user.effectiveSpendRate)
    ? formatCredits(user.effectiveSpendRate)
    : formatCredits(6.0);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <Button asChild variant="ghost" size="icon" className="h-9 w-9 shrink-0">
            <Link href="/admin?section=users" aria-label="Zurück">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>

          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground truncate">{title}</h1>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground break-all">{user.uid}</span>

              <Badge
                className={cn(
                  'rounded-md px-2 py-0.5 text-xs font-semibold',
                  user.fullAccess
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-transparent text-foreground border border-muted-foreground/30'
                )}
              >
                {user.fullAccess ? 'Full Access' : 'Pending'}
              </Badge>

              {user.blocked ? (
                <Badge
                  variant="outline"
                  className="rounded-md px-2 py-0.5 text-xs font-semibold border-destructive text-destructive"
                >
                  Blocked
                </Badge>
              ) : null}

              {user.isAdmin ? (
                <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-semibold">
                  Admin
                </Badge>
              ) : null}

              {user.disabled ? (
                <Badge
                  variant="outline"
                  className="rounded-md px-2 py-0.5 text-xs font-semibold border-destructive text-destructive"
                >
                  Disabled
                </Badge>
              ) : null}

              <Badge
                variant={user.allowPlatformKey ? 'default' : 'outline'}
                className={cn(
                  'rounded-md px-2 py-0.5 text-xs font-semibold',
                  user.allowPlatformKey ? 'bg-primary text-primary-foreground' : 'bg-transparent'
                )}
              >
                Platform Key: {user.allowPlatformKey ? 'Ja' : 'Nein'}
              </Badge>

              <Badge
                variant={user.canDuplicateSystemPrompts ? 'default' : 'outline'}
                className={cn(
                  'rounded-md px-2 py-0.5 text-xs font-semibold',
                  user.canDuplicateSystemPrompts ? 'bg-primary text-primary-foreground' : 'bg-transparent'
                )}
              >
                Prompt Copy: {user.canDuplicateSystemPrompts ? 'Ja' : 'Nein'}
              </Badge>

              <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-semibold">
                OpenAI: {keyLabel}
              </Badge>
            </div>

            {user.activatedByCode || user.activatedAt ? (
              <p className="mt-3 text-xs text-muted-foreground">
                Aktiviert: {user.activatedByCode ? <span className="font-mono">{user.activatedByCode}</span> : '-'} ·{' '}
                {user.activatedAt || '-'}
              </p>
            ) : null}
          </div>
        </div>

        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={handleRefresh}
          disabled={reloading}
          aria-label="Aktualisieren"
        >
          <RefreshCw className={cn('h-5 w-5', reloading && 'animate-spin')} />
        </Button>
      </div>

      <div className="border-b">
        <nav className="flex items-center gap-6">
          {(
            [
              { id: 'prompts', label: 'Prompts' },
              { id: 'billing', label: 'Billing' },
              { id: 'stats', label: 'Stats' },
              { id: 'projects', label: 'Projects' },
            ] as const
          ).map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                'pb-3 text-sm font-medium border-b-2 -mb-px transition-colors',
                tab === t.id
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              )}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {tab === 'prompts' ? <AdminUserPromptManager uid={user.uid} refreshNonce={refreshNonce} /> : null}
      {tab === 'billing' ? (
        <div className="space-y-6">
          <div className="rounded-lg border p-6">
            <h2 className="text-sm font-semibold text-foreground">Spend Rate</h2>
            <p className="text-xs text-muted-foreground mt-1">
              Default: 6.00 · Effektiv: <span className="font-medium text-foreground">{effectiveSpendRateLabel}</span>
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="spend-rate">
                  Override (Credits pro $1 OpenAI Kosten)
                </label>
                <Input
                  id="spend-rate"
                  type="number"
                  step="0.01"
                  min="0"
                  value={spendRateInput}
                  onChange={(e) => setSpendRateInput(e.target.value)}
                  placeholder="(leer = Default)"
                  disabled={savingSpendRate}
                />
              </div>
              <Button
                onClick={async () => {
                  if (savingSpendRate) return;
                  setSavingSpendRate(true);
                  try {
                    const raw = spendRateInput.trim();
                    let spendRate: number | null = null;
                    if (raw) {
                      const n = Number(raw);
                      if (!Number.isFinite(n) || n <= 0) {
                        throw new Error('Spend Rate muss > 0 sein (oder leer lassen, um Default zu nutzen).');
                      }
                      spendRate = n;
                    }

                    if (raw && spendRate === null) {
                      throw new Error('Spend Rate muss > 0 sein (oder leer lassen, um Default zu nutzen).');
                    }

                    const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/spend-rate`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ spendRate }),
                    });
                    const data = (await res.json().catch(() => ({}))) as { error?: string };
                    if (!res.ok) throw new Error(data?.error || 'Konnte Spend Rate nicht speichern.');

                    toast.success('Spend Rate gespeichert');
                    handleRefresh();
                  } catch (err: any) {
                    toast.error('Spend Rate', { description: err?.message || 'Konnte Spend Rate nicht speichern.' });
                  } finally {
                    setSavingSpendRate(false);
                  }
                }}
                disabled={savingSpendRate}
              >
                {savingSpendRate ? 'Speichern…' : 'Speichern'}
              </Button>
              <Button
                variant="outline"
                onClick={async () => {
                  if (savingSpendRate) return;
                  setSavingSpendRate(true);
                  try {
                    const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/spend-rate`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ spendRate: null }),
                    });
                    const data = (await res.json().catch(() => ({}))) as { error?: string };
                    if (!res.ok) throw new Error(data?.error || 'Konnte Spend Rate nicht zuruecksetzen.');

                    toast.success('Spend Rate zurueckgesetzt');
                    handleRefresh();
                  } catch (err: any) {
                    toast.error('Spend Rate', { description: err?.message || 'Konnte Spend Rate nicht zuruecksetzen.' });
                  } finally {
                    setSavingSpendRate(false);
                  }
                }}
                disabled={savingSpendRate}
              >
                Reset
              </Button>
            </div>
          </div>

          <div className="rounded-lg border p-6">
            <h2 className="text-sm font-semibold text-foreground">Billing Status</h2>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded-lg border p-4">
                <p className="text-xs text-muted-foreground">Credits</p>
                <p className="text-2xl font-semibold text-foreground mt-1">
                  {formatCredits(billing?.balance?.totalCredits || 0)} Credits
                </p>
                <div className="mt-2 text-sm text-muted-foreground grid gap-1">
                  <div>
                    Abo:{' '}
                    <span className="text-foreground">
                      {formatCredits(billing?.balance?.subscriptionCredits || 0)}
                    </span>
                  </div>
                  <div>
                    Top-up:{' '}
                    <span className="text-foreground">{formatCredits(billing?.balance?.topupCredits || 0)}</span>
                  </div>
                  {billing?.balance?.subscriptionExpiresAt ? (
                    <div>Abo bis: {formatIso(billing.balance.subscriptionExpiresAt)}</div>
                  ) : null}
                </div>
              </div>

              <div className="rounded-lg border p-4">
                <p className="text-xs text-muted-foreground">Subscription</p>
                <p className="text-lg font-medium text-foreground mt-1">
                  {billing?.subscription?.status || 'Keine Subscription'}
                </p>
                {billing?.subscription?.currentPeriodEnd ? (
                  <p className="text-sm text-muted-foreground mt-1">
                    Period end: {formatIso(billing.subscription.currentPeriodEnd)}
                  </p>
                ) : null}
                {billing?.subscription?.cancelAtPeriodEnd ? (
                  <p className="text-sm text-muted-foreground mt-1">Cancel at period end: ja</p>
                ) : null}
              </div>
            </div>
          </div>

          <div className="rounded-lg border p-6">
            <h2 className="text-sm font-semibold text-foreground">Manual Adjustment</h2>
            <p className="text-xs text-muted-foreground mt-1">Betrag in Credits (positiv oder negativ) + Notiz.</p>
            <div className="mt-4 grid gap-3">
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="adj-credits">
                  Credits
                </label>
                <Input
                  id="adj-credits"
                  type="number"
                  step="0.01"
                  value={adjustmentCreditsInput}
                  onChange={(e) => setAdjustmentCreditsInput(e.target.value)}
                  placeholder="+10 oder -10"
                  disabled={creatingAdjustment}
                />
              </div>
              <div className="grid gap-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="adj-note">
                  Notiz (optional)
                </label>
                <Textarea
                  id="adj-note"
                  value={adjustmentNote}
                  onChange={(e) => setAdjustmentNote(e.target.value)}
                  placeholder="z.B. Promo / Refund / Support"
                  disabled={creatingAdjustment}
                />
              </div>
              <div className="flex items-center gap-2">
                <Button
                  onClick={async () => {
                    if (creatingAdjustment) return;
                    setCreatingAdjustment(true);
                    try {
                      const credits = Number(adjustmentCreditsInput.trim());
                      if (!Number.isFinite(credits) || credits === 0) {
                        throw new Error('Bitte einen Betrag != 0 angeben.');
                      }

                      const res = await fetch(
                        `/api/admin/users/${encodeURIComponent(uid)}/billing/adjustments`,
                        {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({
                            credits,
                            note: adjustmentNote.trim() || null,
                          }),
                        }
                      );
                      const data = (await res.json().catch(() => ({}))) as
                        | { error?: string; balance?: AdminBillingBalance }
                        | Record<string, unknown>;
                      if (!res.ok) throw new Error((data as any)?.error || 'Konnte Adjustment nicht speichern.');

                      toast.success('Adjustment gespeichert');
                      setAdjustmentCreditsInput('');
                      setAdjustmentNote('');

                      handleRefresh();
                      setLedgerLoading(true);
                      loadLedger(null)
                        .then(({ entries, nextCursor }) => {
                          setLedger(entries);
                          setLedgerNextCursor(nextCursor);
                        })
                        .catch(() => {
                          // ignore
                        })
                        .finally(() => setLedgerLoading(false));
                    } catch (err: any) {
                      toast.error('Adjustment', { description: err?.message || 'Konnte Adjustment nicht speichern.' });
                    } finally {
                      setCreatingAdjustment(false);
                    }
                  }}
                  disabled={creatingAdjustment}
                >
                  {creatingAdjustment ? 'Speichern…' : 'Speichern'}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setAdjustmentCreditsInput('');
                    setAdjustmentNote('');
                  }}
                  disabled={creatingAdjustment}
                >
                  Zuruecksetzen
                </Button>
              </div>
            </div>
          </div>

          <div className="rounded-lg border p-6">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-foreground">Ledger</h2>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  if (ledgerLoading) return;
                  setLedgerLoading(true);
                  loadLedger(null)
                    .then(({ entries, nextCursor }) => {
                      setLedger(entries);
                      setLedgerNextCursor(nextCursor);
                    })
                    .catch((err: any) => {
                      toast.error('Ledger', { description: err?.message || 'Ledger konnte nicht geladen werden.' });
                      setLedger([]);
                      setLedgerNextCursor(null);
                    })
                    .finally(() => setLedgerLoading(false));
                }}
                disabled={ledgerLoading}
              >
                {ledgerLoading ? 'Laden…' : 'Refresh'}
              </Button>
            </div>

            <div className="mt-4 space-y-2">
              {ledgerLoading ? (
                <p className="text-sm text-muted-foreground">Lade…</p>
              ) : ledger.length === 0 ? (
                <p className="text-sm text-muted-foreground">Noch keine Eintraege.</p>
              ) : (
                ledger.map((e) => {
                  const sign = e.credits >= 0 ? '+' : '';
                  return (
                    <div key={e.id} className="border rounded-lg p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">{ledgerLabel(e)}</p>
                          <p className="text-xs text-muted-foreground">
                            {e.createdAt ? `Created: ${formatIso(e.createdAt)}` : null}
                            {e.expiresAt ? ` · Expires: ${formatIso(e.expiresAt)}` : null}
                          </p>
                          {e.note ? <p className="text-xs text-muted-foreground mt-1">{e.note}</p> : null}
                        </div>
                        <div
                          className={cn(
                            'font-medium',
                            e.credits >= 0 ? 'text-emerald-600' : 'text-destructive'
                          )}
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

            {ledgerNextCursor ? (
              <div className="mt-4">
                <Button
                  variant="outline"
                  onClick={() => {
                    if (!ledgerNextCursor) return;
                    if (ledgerMoreLoading) return;
                    setLedgerMoreLoading(true);
                    loadLedger(ledgerNextCursor)
                      .then(({ entries, nextCursor }) => {
                        setLedger((prev) => [...prev, ...entries]);
                        setLedgerNextCursor(nextCursor);
                      })
                      .catch((err: any) => {
                        toast.error('Ledger', { description: err?.message || 'Ledger konnte nicht geladen werden.' });
                      })
                      .finally(() => setLedgerMoreLoading(false));
                  }}
                  disabled={ledgerMoreLoading}
                >
                  {ledgerMoreLoading ? 'Laden…' : 'Mehr laden'}
                </Button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
      {tab === 'stats' ? <AdminUserStatsPanel uid={user.uid} refreshNonce={refreshNonce} /> : null}
      {tab === 'projects' ? <AdminUserProjectsPanel uid={user.uid} refreshNonce={refreshNonce} /> : null}
    </div>
  );
}

