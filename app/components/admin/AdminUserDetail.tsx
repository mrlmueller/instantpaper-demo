'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { ArrowLeft, Calculator, Minus, Pencil, Plus, RefreshCw } from 'lucide-react';

import { AdminUserPromptManager } from '@/app/components/admin/AdminUserPromptManager';
import { AdminUserOpenAIOperationsPanel } from '@/app/components/admin/AdminUserOpenAIOperationsPanel';
import { AdminUserProjectsPanel } from '@/app/components/admin/AdminUserProjectsPanel';
import { AdminUserStatsPanel } from '@/app/components/admin/AdminUserStatsPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
  reservedCredits: number;
  availableCredits: number;
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

type AdminUserDetailResponse = {
  user: AdminUserDetailRow;
  billing: AdminBillingSummary;
};

function ledgerLabel(entry: AdminBillingLedgerEntry): string {
  const source = String(entry.source || '').trim();
  if (source === 'stripe_subscription') return 'Monatliche Credits';
  if (source === 'stripe_topup') return 'Credits gekauft';
  if (source === 'openai') return 'Verbrauch (OpenAI)';
  if (source === 'admin_adjustment') return entry.credits >= 0 ? 'Admin: Credits hinzugefügt' : 'Admin: Credits abgezogen';
  return source || entry.type || 'Ledger';
}

function formatCreditsShort(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '-';
  const abs = Math.abs(n);
  const maximumFractionDigits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return n.toLocaleString('de-DE', { maximumFractionDigits });
}

function formatCreditsExact(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

const PURCHASE_CREDITS_PER_USD = 3;
const DEFAULT_SPEND_RATE = 6;
const STRIPE_FEE_PCT = 0.029;
const STRIPE_FEE_FIXED_USD = 0.3;
const STRIPE_AVG_PURCHASE_USD = 10;

const STRIPE_AVG_FEE_USD = STRIPE_AVG_PURCHASE_USD * STRIPE_FEE_PCT + STRIPE_FEE_FIXED_USD;
const STRIPE_AVG_NET_USD = STRIPE_AVG_PURCHASE_USD - STRIPE_AVG_FEE_USD;
const STRIPE_AVG_CREDITS_ISSUED = STRIPE_AVG_PURCHASE_USD * PURCHASE_CREDITS_PER_USD;

const BREAK_EVEN_CREDITS_PER_USD_OPENAI =
  STRIPE_AVG_NET_USD > 0 ? STRIPE_AVG_CREDITS_ISSUED / STRIPE_AVG_NET_USD : Number.POSITIVE_INFINITY;

function formatUsd2(value: number): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '$0.00';
  return `$${n.toFixed(2)}`;
}

export function AdminUserDetail({ uid }: { uid: string }) {
  const [detail, setDetail] = useState<AdminUserDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [tab, setTab] = useState<'billing' | 'openai' | 'prompts' | 'stats' | 'projects'>('billing');

  const [spendRateDialogOpen, setSpendRateDialogOpen] = useState(false);
  const [spendRateStep, setSpendRateStep] = useState<1 | 2 | 3>(1);
  const [spendRateDraft, setSpendRateDraft] = useState('');
  const [spendRateVerify, setSpendRateVerify] = useState('');
  const [savingSpendRate, setSavingSpendRate] = useState(false);

  type AdjustmentKind = 'add' | 'subtract';
  const [adjustDialogOpen, setAdjustDialogOpen] = useState(false);
  const [adjustKind, setAdjustKind] = useState<AdjustmentKind>('add');
  const [adjustStep, setAdjustStep] = useState<1 | 2 | 3>(1);
  const [adjustAmount, setAdjustAmount] = useState('');
  const [adjustNote, setAdjustNote] = useState('');
  const [adjustVerify, setAdjustVerify] = useState('');
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
    qs.set('includeUsage', 'false');
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
  const effectiveSpendRate = Number.isFinite(user.effectiveSpendRate) ? user.effectiveSpendRate : 6.0;
  const effectiveSpendRateLabel = formatCreditsShort(effectiveSpendRate);
  const handleLine = user.email || user.uid;
  const createdLabel = formatIso(user.createdAt);
  const lastLoginLabel = formatIso(user.lastSignInAt);
  const breakEvenLabel = BREAK_EVEN_CREDITS_PER_USD_OPENAI.toLocaleString('de-DE', { maximumFractionDigits: 2 });
  const marginPct = Number.isFinite(effectiveSpendRate)
    ? (effectiveSpendRate / BREAK_EVEN_CREDITS_PER_USD_OPENAI - 1) * 100
    : Number.NaN;
  const marginLabel = Number.isFinite(marginPct)
    ? `${marginPct.toLocaleString('de-DE', { maximumFractionDigits: 1 })}%`
    : '-';

  const subscription = (() => {
    const sub = billing?.subscription;
    const status = String(sub?.status || '').trim().toLowerCase();
    const cancelAtPeriodEnd = sub?.cancelAtPeriodEnd === true;
    const nextBilling = sub?.currentPeriodEnd ? formatIso(sub.currentPeriodEnd) : null;

    if (status === 'active' || status === 'trialing') {
      if (cancelAtPeriodEnd) {
        return {
          label: 'Gekündigt',
          className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20',
          nextBilling,
        };
      }
      return { label: 'Aktiv', className: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20', nextBilling };
    }

    if (status === 'canceled') {
      return { label: 'Gekündigt', className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20', nextBilling };
    }

    if (status) {
      return { label: status, className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20', nextBilling };
    }

    return { label: 'Kein Abo', className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20', nextBilling: null };
  })();

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3 min-w-0">
          <Button asChild variant="ghost" size="icon" className="h-9 w-9 shrink-0">
            <Link href="/admin?section=users" aria-label="Zurück">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>

          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-foreground truncate">{title}</h1>
              <Badge
                className={cn(
                  'rounded-md border px-2 py-0.5 text-xs font-semibold',
                  user.fullAccess
                    ? 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20'
                    : 'bg-muted/40 text-muted-foreground border-muted-foreground/20'
                )}
              >
                {user.fullAccess ? 'Freigeschaltet' : 'Ausstehend'}
              </Badge>
              {user.blocked ? (
                <Badge className="rounded-md border bg-destructive/10 text-destructive border-destructive/20 px-2 py-0.5 text-xs font-semibold">
                  Gesperrt
                </Badge>
              ) : null}
              {user.isAdmin ? (
                <Badge className="rounded-md border bg-muted/40 text-muted-foreground border-muted-foreground/20 px-2 py-0.5 text-xs font-semibold">
                  Admin
                </Badge>
              ) : null}
            </div>
            <p className="mt-1 text-sm text-muted-foreground break-all">{handleLine}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Erstellt: {createdLabel} · Letzter Login: {lastLoginLabel}
            </p>
          </div>
        </div>

        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={reloading}>
          <RefreshCw className={cn('h-4 w-4', reloading && 'animate-spin')} />
          Aktualisieren
        </Button>
      </div>

      <div className="border-b">
        <nav className="flex items-center gap-6">
          {(
            [
              { id: 'billing', label: 'Billing' },
              { id: 'openai', label: 'OpenAI' },
              { id: 'prompts', label: 'Prompts' },
              { id: 'stats', label: 'Statistiken' },
              { id: 'projects', label: 'Projekte' },
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
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-foreground">Spend Rate</h2>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setSpendRateDraft(user.spendRate != null ? String(user.spendRate) : '');
                  setSpendRateVerify('');
                  setSpendRateStep(1);
                  setSpendRateDialogOpen(true);
                }}
                disabled={savingSpendRate}
              >
                <Pencil className="h-4 w-4" />
                Anpassen
              </Button>
            </div>
            <div className="rounded-xl border bg-background shadow-sm p-5">
              <p className="text-sm font-semibold text-foreground">{effectiveSpendRateLabel} Credits pro $1 OpenAI-Kosten</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Break-Even: ~{breakEvenLabel} Credits/$1 · Override:{' '}
                <span className="text-foreground">
                  {user.spendRate == null ? 'Default' : `${formatCreditsShort(user.spendRate)} Credits/$1`}
                </span>
              </p>
              <div
                className={cn(
                  'mt-4 rounded-md border px-3 py-2 text-sm',
                  marginPct >= 0
                    ? 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20'
                    : 'bg-destructive/5 text-destructive border-destructive/20'
                )}
              >
                Gewinnmarge: ~{marginLabel} pro $1 OpenAI-Kosten
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-foreground">Credit-Guthaben</h2>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-xl border bg-background shadow-sm p-5">
                <p className="text-xs text-muted-foreground">Gesamt</p>
                <p className="mt-2 text-2xl font-semibold text-foreground">
                  {formatCreditsShort(billing?.balance?.totalCredits ?? 0)}
                </p>
              </div>
              <div className="rounded-xl border bg-background shadow-sm p-5">
                <p className="text-xs text-muted-foreground">Abo-Credits</p>
                <p className="mt-2 text-2xl font-semibold text-foreground">
                  {formatCreditsShort(billing?.balance?.subscriptionCredits ?? 0)}
                </p>
                {billing?.balance?.subscriptionExpiresAt ? (
                  <p className="mt-2 text-xs text-muted-foreground">bis {formatIso(billing.balance.subscriptionExpiresAt)}</p>
                ) : (
                  <p className="mt-2 text-xs text-muted-foreground">keine Abo-Credits</p>
                )}
              </div>
              <div className="rounded-xl border bg-background shadow-sm p-5">
                <p className="text-xs text-muted-foreground">Top-Up Credits</p>
                <p className="mt-2 text-2xl font-semibold text-foreground">
                  {formatCreditsShort(billing?.balance?.topupCredits ?? 0)}
                </p>
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-foreground">Abonnement</h2>
            <div className="rounded-xl border bg-background shadow-sm p-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-foreground">Pro Plan</p>
                    <span className={cn('inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium', subscription.className)}>
                      {subscription.label}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {subscription.nextBilling ? `Nächste Abrechnung: ${subscription.nextBilling}` : 'Kein aktives Abonnement.'}
                  </p>
                </div>
              </div>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-sm font-semibold text-foreground">Manuelle Anpassung</h2>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setAdjustKind('add');
                  setAdjustAmount('');
                  setAdjustNote('');
                  setAdjustVerify('');
                  setAdjustStep(1);
                  setAdjustDialogOpen(true);
                }}
                disabled={creatingAdjustment}
              >
                <Plus className="h-4 w-4" />
                Credits hinzufügen
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setAdjustKind('subtract');
                  setAdjustAmount('');
                  setAdjustNote('');
                  setAdjustVerify('');
                  setAdjustStep(1);
                  setAdjustDialogOpen(true);
                }}
                disabled={creatingAdjustment}
              >
                <Minus className="h-4 w-4" />
                Credits abziehen
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Anpassungen erscheinen als Admin Adjustment im Ledger.
            </p>
          </section>

          <section className="rounded-xl border bg-background shadow-sm p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-foreground">Transaktionen</h2>
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
                {ledgerLoading ? 'Laden…' : 'Aktualisieren'}
              </Button>
            </div>

            <div className="mt-4 space-y-2">
              {ledgerLoading ? (
                <p className="text-sm text-muted-foreground">Lade…</p>
              ) : ledger.length === 0 ? (
                <p className="text-sm text-muted-foreground">Noch keine Transaktionen.</p>
              ) : (
                ledger.map((e) => {
                  const sign = e.credits >= 0 ? '+' : '';
                  return (
                    <div key={e.id} className="rounded-xl border bg-background px-5 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground">{ledgerLabel(e)}</p>
                          <p className="text-xs text-muted-foreground">
                            {e.createdAt ? formatIso(e.createdAt) : '-'}
                            {e.expiresAt ? ` · Ablauf: ${formatIso(e.expiresAt)}` : null}
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
                          {formatCreditsShort(e.credits)} Credits
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
          </section>
        </div>
      ) : null}
      {tab === 'openai' ? (
        <AdminUserOpenAIOperationsPanel
          uid={user.uid}
          balance={
            billing?.balance || {
              totalCredits: 0,
              subscriptionCredits: 0,
              subscriptionExpiresAt: null,
              topupCredits: 0,
              reservedCredits: 0,
              availableCredits: 0,
              isNegative: false,
            }
          }
          refreshNonce={refreshNonce}
          onRefresh={handleRefresh}
        />
      ) : null}
      {tab === 'stats' ? <AdminUserStatsPanel uid={user.uid} refreshNonce={refreshNonce} /> : null}
      {tab === 'projects' ? <AdminUserProjectsPanel uid={user.uid} refreshNonce={refreshNonce} /> : null}

      <Dialog
        open={spendRateDialogOpen}
        onOpenChange={(open) => {
          setSpendRateDialogOpen(open);
          if (!open) {
            setSpendRateStep(1);
            setSpendRateVerify('');
          }
        }}
      >
        <DialogContent className="sm:max-w-[560px]">
          {(() => {
            const draftTrim = spendRateDraft.trim();
            const draftNum = draftTrim ? Number(draftTrim.replace(',', '.')) : null;
            const isValid = draftTrim === '' || (Number.isFinite(draftNum) && (draftNum as number) > 0);

            const calcSpendRate =
              draftTrim === ''
                ? DEFAULT_SPEND_RATE
                : Number.isFinite(draftNum) && (draftNum as number) > 0
                  ? (draftNum as number)
                  : effectiveSpendRate;
            const calcSpendRateLabel = formatCreditsShort(calcSpendRate);
            const calcMarginPct = Number.isFinite(calcSpendRate)
              ? (calcSpendRate / BREAK_EVEN_CREDITS_PER_USD_OPENAI - 1) * 100
              : Number.NaN;
            const calcMarginLabel = Number.isFinite(calcMarginPct)
              ? `${calcMarginPct.toLocaleString('de-DE', { maximumFractionDigits: 1 })}%`
              : '-';
            const calcExampleCreditsLabel = formatCreditsShort(calcSpendRate * 10);

            const verifyTrim = spendRateVerify.trim();
            const verifyNum = verifyTrim ? Number(verifyTrim.replace(',', '.')) : null;
            const verifyMatches =
              draftTrim === ''
                ? verifyTrim.toLowerCase() === 'default'
                : Number.isFinite(draftNum) && Number.isFinite(verifyNum) && Math.abs((draftNum as number) - (verifyNum as number)) < 1e-9;

            return (
              <>
                <DialogHeader>
                  <DialogTitle>
                    {spendRateStep === 1 ? 'Spend Rate anpassen' : spendRateStep === 2 ? 'Spend Rate bestätigen' : 'Spend Rate bestätigen'}
                  </DialogTitle>
                  <DialogDescription>
                    {spendRateStep === 1
                      ? 'Credits pro $1 OpenAI-Kosten. Leer lassen = Default.'
                      : spendRateStep === 2
                        ? 'Bitte bestätige die Änderung.'
                        : draftTrim === ''
                          ? 'Tippe DEFAULT, um den Default wiederherzustellen.'
                          : 'Gib den Wert erneut ein, um die Änderung zu bestätigen.'}
                  </DialogDescription>
                </DialogHeader>

                {spendRateStep === 1 ? (
                  <div className="grid gap-4 py-2">
                    <div className="grid gap-2">
                      <Label htmlFor="spend-rate-draft">Credits pro $1 OpenAI-Kosten</Label>
                      <Input
                        id="spend-rate-draft"
                        type="number"
                        step="0.01"
                        min="0"
                        value={spendRateDraft}
                        onChange={(e) => setSpendRateDraft(e.target.value)}
                        placeholder="z.B. 6.0 (leer = Default)"
                        disabled={savingSpendRate}
                      />
                      <p className="text-xs text-muted-foreground">
                        Aktuell effektiv: <span className="text-foreground">{effectiveSpendRateLabel}</span> · Break-Even: ~{breakEvenLabel} Credits/$1
                      </p>
                    </div>

                    <div className="rounded-xl border bg-background shadow-sm p-5">
                      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                        <Calculator className="h-4 w-4 text-muted-foreground" />
                        Wirtschaftlichkeits-Rechner
                      </div>
                      <div className="mt-4 space-y-2 text-sm">
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-muted-foreground">Break-Even Rate:</span>
                          <span className="font-medium text-foreground">~{breakEvenLabel} Credits/$1</span>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-muted-foreground">Aktuelle Rate:</span>
                          <span className="font-medium text-foreground">{calcSpendRateLabel} Credits/$1</span>
                        </div>
                        <div className="h-px bg-border" />
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-muted-foreground">Gewinnmarge:</span>
                          <span className={cn('font-medium', calcMarginPct >= 0 ? 'text-emerald-700' : 'text-destructive')}>
                            {calcMarginLabel}
                          </span>
                        </div>
                        <p className="pt-2 text-xs text-muted-foreground">
                          Bei einem durchschnittlichen ${STRIPE_AVG_PURCHASE_USD} Kauf erhält der User{' '}
                          {Math.round(STRIPE_AVG_CREDITS_ISSUED).toLocaleString('de-DE')} Credits. Nach Stripe-Gebühren (~
                          {formatUsd2(STRIPE_AVG_FEE_USD)}) bleiben {formatUsd2(STRIPE_AVG_NET_USD)} Netto.
                        </p>
                      </div>
                    </div>

                    <div className="rounded-xl border bg-background shadow-sm p-5">
                      <p className="text-sm font-semibold text-foreground">Beispiel-Auswirkung:</p>
                      <p className="mt-2 text-sm text-muted-foreground">
                        Bei <span className="text-foreground font-medium">{calcSpendRateLabel} Credits/$1</span> kostet eine{' '}
                        <span className="text-foreground font-medium">$10</span> OpenAI-Operation{' '}
                        <span className="text-foreground font-medium">{calcExampleCreditsLabel} Credits</span>.
                      </p>
                    </div>
                  </div>
                ) : null}

                {spendRateStep === 2 ? (
                  <div className="py-2">
                      <div className="rounded-md border bg-amber-500/10 text-amber-900 border-amber-500/20 px-3 py-2 text-sm">
                        {draftTrim === '' ? (
                        <span>Reset auf Default ({DEFAULT_SPEND_RATE} Credits pro $1 OpenAI-Kosten)</span>
                        ) : (
                          <span>Neue Spend Rate: {formatCreditsShort(draftNum ?? 0)} Credits pro $1 OpenAI-Kosten</span>
                        )}
                      </div>
                  </div>
                ) : null}

                {spendRateStep === 3 ? (
                  <div className="grid gap-3 py-2">
                    <div className="grid gap-2">
                      <Label htmlFor="spend-rate-verify">
                        {draftTrim === '' ? 'Tippe DEFAULT' : 'Spend Rate erneut eingeben'}
                      </Label>
                      <Input
                        id="spend-rate-verify"
                        type={draftTrim === '' ? 'text' : 'number'}
                        step="0.01"
                        min="0"
                        value={spendRateVerify}
                        onChange={(e) => setSpendRateVerify(e.target.value)}
                        placeholder={draftTrim === '' ? 'DEFAULT' : String(draftNum ?? '')}
                        disabled={savingSpendRate}
                      />
                      {!verifyMatches ? (
                        <p className="text-xs text-destructive">Die Werte stimmen nicht überein</p>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      if (spendRateStep === 1) {
                        setSpendRateDialogOpen(false);
                        return;
                      }
                      if (spendRateStep === 2) setSpendRateStep(1);
                      if (spendRateStep === 3) setSpendRateStep(2);
                    }}
                    disabled={savingSpendRate}
                  >
                    {spendRateStep === 1 ? 'Abbrechen' : 'Zurück'}
                  </Button>

                  {spendRateStep === 1 ? (
                    <Button
                      type="button"
                      onClick={() => {
                        if (!isValid) {
                          toast.error('Spend Rate', { description: 'Bitte eine gültige Spend Rate (> 0) eingeben.' });
                          return;
                        }
                        setSpendRateStep(2);
                      }}
                      disabled={savingSpendRate}
                    >
                      Weiter
                    </Button>
                  ) : null}

                  {spendRateStep === 2 ? (
                    <Button
                      type="button"
                      onClick={() => {
                        setSpendRateVerify('');
                        setSpendRateStep(3);
                      }}
                      disabled={savingSpendRate}
                    >
                      Bestätigen
                    </Button>
                  ) : null}

                  {spendRateStep === 3 ? (
                    <Button
                      type="button"
                      onClick={async () => {
                        if (savingSpendRate) return;
                        if (!verifyMatches) return;
                        if (!isValid) return;

                        setSavingSpendRate(true);
                        try {
                          const spendRate = draftTrim === '' ? null : (draftNum as number);
                          const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/spend-rate`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ spendRate }),
                          });
                          const data = (await res.json().catch(() => ({}))) as { error?: string };
                          if (!res.ok) throw new Error(data?.error || 'Konnte Spend Rate nicht speichern.');

                          toast.success('Spend Rate gespeichert');
                          setSpendRateDialogOpen(false);
                          setSpendRateStep(1);
                          setSpendRateVerify('');
                          handleRefresh();
                        } catch (err: any) {
                          toast.error('Spend Rate', { description: err?.message || 'Konnte Spend Rate nicht speichern.' });
                        } finally {
                          setSavingSpendRate(false);
                        }
                      }}
                      disabled={!verifyMatches || savingSpendRate}
                    >
                      Speichern
                    </Button>
                  ) : null}
                </DialogFooter>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>

      <Dialog
        open={adjustDialogOpen}
        onOpenChange={(open) => {
          setAdjustDialogOpen(open);
          if (!open) {
            setAdjustStep(1);
            setAdjustVerify('');
          }
        }}
      >
        <DialogContent className="sm:max-w-[620px]">
          {(() => {
            const isAdd = adjustKind === 'add';
            const title = isAdd ? 'Credits hinzufügen' : 'Credits abziehen';

            const amountTrim = adjustAmount.trim();
            const amountNum = amountTrim ? Number(amountTrim.replace(',', '.')) : Number.NaN;
            const amountOk = Number.isFinite(amountNum) && amountNum > 0;

            const verifyTrim = adjustVerify.trim();
            const verifyNum = verifyTrim ? Number(verifyTrim.replace(',', '.')) : Number.NaN;
            const verifyMatches = Number.isFinite(verifyNum) && amountOk && Math.abs(amountNum - verifyNum) < 1e-9;

            const noteLabel = adjustNote.trim() ? adjustNote.trim() : 'Keine Notiz angegeben';

            return (
              <>
                <DialogHeader>
                  <DialogTitle>
                    {adjustStep === 1 ? title : adjustStep === 2 ? `${title}?` : 'Credits-Änderung bestätigen'}
                  </DialogTitle>
                  <DialogDescription>
                    {adjustStep === 1
                      ? 'Bitte gib die Anzahl der Credits ein.'
                      : adjustStep === 2
                        ? `Bist du sicher, dass du ${title.toLowerCase()} möchtest?`
                        : 'Bitte gib die Anzahl der Credits erneut ein, um die Änderung zu bestätigen.'}
                  </DialogDescription>
                </DialogHeader>

                {adjustStep === 1 ? (
                  <div className="grid gap-4 py-2">
                    <div className="grid gap-2">
                      <Label htmlFor="adj-amount">Anzahl Credits</Label>
                      <Input
                        id="adj-amount"
                        type="number"
                        step="0.01"
                        min="0"
                        value={adjustAmount}
                        onChange={(e) => setAdjustAmount(e.target.value)}
                        placeholder="0"
                        disabled={creatingAdjustment}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="adj-note">Notiz / Grund</Label>
                      <Textarea
                        id="adj-note"
                        value={adjustNote}
                        onChange={(e) => setAdjustNote(e.target.value)}
                        placeholder="Grund für die Anpassung…"
                        disabled={creatingAdjustment}
                      />
                    </div>
                  </div>
                ) : null}

                {adjustStep === 2 ? (
                  <div className="py-2">
                    <div className="rounded-md border bg-amber-500/10 text-amber-900 border-amber-500/20 px-3 py-2 text-sm">
                      Grund: {noteLabel}
                    </div>
                  </div>
                ) : null}

                {adjustStep === 3 ? (
                  <div className="grid gap-3 py-2">
                    <div className="grid gap-2">
                      <Label htmlFor="adj-verify">Credits erneut eingeben</Label>
                      <Input
                        id="adj-verify"
                        type="number"
                        step="0.01"
                        min="0"
                        value={adjustVerify}
                        onChange={(e) => setAdjustVerify(e.target.value)}
                        placeholder={amountOk ? String(amountNum) : ''}
                        disabled={creatingAdjustment}
                      />
                      {!verifyMatches ? <p className="text-xs text-destructive">Die Werte stimmen nicht überein</p> : null}
                    </div>
                  </div>
                ) : null}

                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      if (adjustStep === 1) {
                        setAdjustDialogOpen(false);
                        return;
                      }
                      if (adjustStep === 2) setAdjustStep(1);
                      if (adjustStep === 3) setAdjustStep(2);
                    }}
                    disabled={creatingAdjustment}
                  >
                    {adjustStep === 1 ? 'Abbrechen' : 'Zurück'}
                  </Button>

                  {adjustStep === 1 ? (
                    <Button
                      type="button"
                      onClick={() => {
                        if (!amountOk) {
                          toast.error('Credits', { description: 'Bitte eine Zahl > 0 eingeben.' });
                          return;
                        }
                        setAdjustStep(2);
                      }}
                      disabled={creatingAdjustment}
                    >
                      Weiter
                    </Button>
                  ) : null}

                  {adjustStep === 2 ? (
                    <Button
                      type="button"
                      onClick={() => {
                        setAdjustVerify('');
                        setAdjustStep(3);
                      }}
                      disabled={creatingAdjustment}
                    >
                      Bestätigen
                    </Button>
                  ) : null}

                  {adjustStep === 3 ? (
                    <Button
                      type="button"
                      onClick={async () => {
                        if (creatingAdjustment) return;
                        if (!verifyMatches) return;
                        if (!amountOk) return;

                        setCreatingAdjustment(true);
                        try {
                          const credits = isAdd ? amountNum : -amountNum;
                          const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/billing/adjustments`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ credits, note: adjustNote.trim() || null }),
                          });
                          const data = (await res.json().catch(() => ({}))) as { error?: string };
                          if (!res.ok) throw new Error(data?.error || 'Konnte Adjustment nicht speichern.');

                          toast.success(isAdd ? 'Credits hinzugefügt' : 'Credits abgezogen');
                          setAdjustDialogOpen(false);
                          setAdjustStep(1);
                          setAdjustAmount('');
                          setAdjustVerify('');
                          setAdjustNote('');

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
                          toast.error('Credits', { description: err?.message || 'Konnte Adjustment nicht speichern.' });
                        } finally {
                          setCreatingAdjustment(false);
                        }
                      }}
                      disabled={!verifyMatches || creatingAdjustment}
                    >
                      {title}
                    </Button>
                  ) : null}
                </DialogFooter>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}

