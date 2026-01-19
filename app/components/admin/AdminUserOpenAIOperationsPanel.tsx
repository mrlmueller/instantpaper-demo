'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Pencil } from 'lucide-react';

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

type AdminBillingBalance = {
  totalCredits: number;
  subscriptionCredits: number;
  subscriptionExpiresAt: string | null;
  topupCredits: number;
  reservedCredits: number;
  availableCredits: number;
  isNegative: boolean;
};

type OperationEstimate = {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  costUsd?: number;
  spendRate?: number;
  credits?: number;
} & Record<string, unknown>;

type OperationTokens = {
  inputTokens?: number;
  cachedInputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
} & Record<string, unknown>;

type OperationCosts = {
  totalCostUsd?: number;
} & Record<string, unknown>;

type OperationReservation = {
  reservedCredits?: number;
  reservedAt?: string | null;
  releasedAt?: string | null;
  releaseReason?: string | null;
} & Record<string, unknown>;

type OpenAIOperationRow = {
  id: string;
  operationId: string;
  timestamp: string | null;
  runningAt?: string | null;
  status: string;
  errorMessage: string | null;
  operationType: string;
  operationDetails?: unknown;
  userActionId?: string | null;
  model?: string | null;
  keySource?: string | null;
  estimate?: OperationEstimate;
  tokens?: OperationTokens;
  costs?: OperationCosts;
  reservation?: OperationReservation | null;
  actualCredits?: number | null;
};

type OpenAIOperationsResponse = {
  operations?: OpenAIOperationRow[];
  nextCursor?: string | null;
  error?: string;
};

type ReservedCreditsMode = 'delta' | 'set';

function formatCredits(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '-';
  const abs = Math.abs(n);
  const maximumFractionDigits = abs >= 100 ? 0 : abs >= 10 ? 1 : 2;
  return n.toLocaleString('de-DE', { maximumFractionDigits });
}

function formatIso(value: string | null | undefined): string {
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

function statusBadgeClass(status: string): string {
  const s = String(status || '').toLowerCase();
  if (s === 'success') return 'bg-primary text-primary-foreground border-transparent';
  if (s === 'running' || s === 'reserved') return 'bg-amber-500 text-white border-transparent';
  if (s === 'skipped') return 'bg-muted text-foreground border-transparent';
  if (s === 'blocked') return 'bg-destructive text-white border-transparent';
  if (s === 'error') return 'bg-destructive text-white border-transparent';
  return 'bg-muted text-foreground border-transparent';
}

function statusLabel(status: string): string {
  const s = String(status || '').toLowerCase();
  if (s === 'success') return 'Erfolg';
  if (s === 'running' || s === 'reserved') return 'Läuft';
  if (s === 'blocked') return 'Blockiert';
  if (s === 'skipped') return 'Übersprungen';
  if (s === 'error') return 'Fehler';
  return status || 'Unbekannt';
}

function formatTokens(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return '0';
  return Math.max(0, Math.round(n)).toLocaleString('de-DE');
}

function humanizeOperationType(value: string | null | undefined): string {
  const raw = String(value || '').trim();
  if (!raw) return '-';
  return raw.replace(/_/g, ' ');
}

function formatUsd(value: number | null | undefined): string | null {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n) || n <= 0) return null;
  return `$${n.toFixed(6)}`;
}

export function AdminUserOpenAIOperationsPanel({
  uid,
  balance,
  refreshNonce,
  onRefresh,
}: {
  uid: string;
  balance: AdminBillingBalance;
  refreshNonce?: number;
  onRefresh?: () => void;
}) {
  const [operations, setOperations] = useState<OpenAIOperationRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursorStack, setCursorStack] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const [pageNav, setPageNav] = useState<'prev' | 'next' | null>(null);

  const [reservedMode, setReservedMode] = useState<ReservedCreditsMode>('set');
  const [reservedAmount, setReservedAmount] = useState('');
  const [reservedNote, setReservedNote] = useState('');
  const [reservedDialogOpen, setReservedDialogOpen] = useState(false);
  const [reservedStep, setReservedStep] = useState<1 | 2 | 3>(1);
  const [reservedVerify, setReservedVerify] = useState('');
  const [savingReserved, setSavingReserved] = useState(false);

  const headline = useMemo(() => {
    return {
      total: formatCredits(balance?.totalCredits ?? 0),
      available: formatCredits(balance?.availableCredits ?? 0),
      reserved: formatCredits(balance?.reservedCredits ?? 0),
      subscription: formatCredits(balance?.subscriptionCredits ?? 0),
      topup: formatCredits(balance?.topupCredits ?? 0),
      expires: balance?.subscriptionExpiresAt ? formatIso(balance.subscriptionExpiresAt) : null,
    };
  }, [balance]);

  const pageSize = 10;

  const loadOps = async (cursor: string | null) => {
    const qs = new URLSearchParams();
    qs.set('limit', String(pageSize));
    if (cursor) qs.set('cursor', cursor);
    const url = `/api/admin/users/${encodeURIComponent(uid)}/openai/operations?${qs.toString()}`;

    const res = await fetch(url, { method: 'GET', cache: 'no-store' });
    const data = (await res.json().catch(() => ({}))) as OpenAIOperationsResponse;
    if (!res.ok) throw new Error(data?.error || 'OpenAI Operationen konnten nicht geladen werden.');

    const ops = Array.isArray(data.operations) ? data.operations : [];
    const next = typeof data.nextCursor === 'string' ? data.nextCursor : null;
    return { operations: ops, nextCursor: next };
  };

  const reload = async () => {
    setLoading(true);
    setPageIndex(0);
    setCursorStack([null]);
    setPageNav(null);
    try {
      const { operations, nextCursor } = await loadOps(null);
      setOperations(operations);
      setNextCursor(nextCursor);
    } catch (err: any) {
      toast.error('OpenAI', { description: err?.message || 'OpenAI Operationen konnten nicht geladen werden.' });
      setOperations([]);
      setNextCursor(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setOperations([]);
    setNextCursor(null);
    setCursorStack([null]);
    setPageIndex(0);
    setMoreLoading(false);
    setPageNav(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, refreshNonce]);

  const openReservedDialog = () => {
    setReservedMode('set');
    setReservedAmount('');
    setReservedNote('');
    setReservedVerify('');
    setReservedStep(1);
    setReservedDialogOpen(true);
  };

  const handleAdjustReserved = async () => {
    if (savingReserved) return;
    const amountNum = Number(reservedAmount.trim().replace(',', '.'));
    if (!Number.isFinite(amountNum)) {
      toast.error('Reserved Credits', { description: 'Bitte eine gültige Zahl eingeben.' });
      return;
    }
    if (reservedMode === 'set' && amountNum < 0) {
      toast.error('Reserved Credits', { description: 'Set muss >= 0 sein.' });
      return;
    }

    setSavingReserved(true);
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(uid)}/billing/reserved-credits`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: reservedMode, amount: amountNum, note: reservedNote || null }),
      });
      const data = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) throw new Error(data?.error || 'Konnte reservedCredits nicht anpassen.');

      toast.success('Reserved Credits angepasst');
      setReservedAmount('');
      setReservedNote('');
      setReservedVerify('');
      setReservedStep(1);
      setReservedDialogOpen(false);
      onRefresh?.();
      await reload();
    } catch (err: any) {
      toast.error('Reserved Credits', { description: err?.message || 'Konnte reservedCredits nicht anpassen.' });
    } finally {
      setSavingReserved(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Credit-Status</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border bg-background shadow-sm p-5">
            <p className="text-xs text-muted-foreground">Gesamt Credits</p>
            <p className="mt-2 text-2xl font-semibold text-foreground">{headline.total}</p>
            <p className="mt-4 text-xs text-muted-foreground">
              Abo: <span className="text-foreground">{headline.subscription}</span> · Top-Up:{' '}
              <span className="text-foreground">{headline.topup}</span>
            </p>
          </div>

          <div className="rounded-xl border bg-background shadow-sm p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs text-muted-foreground">Verfügbar / Reserviert</p>
                <p className="mt-2 text-2xl font-semibold text-foreground">
                  <span className="text-emerald-700">{headline.available}</span>{' '}
                  <span className="text-muted-foreground">/</span>{' '}
                  <span className="text-amber-600">{headline.reserved}</span>
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="h-8 w-8"
                onClick={openReservedDialog}
                title="Reservierte Credits anpassen"
                aria-label="Reservierte Credits anpassen"
              >
                <Pencil className="h-4 w-4" />
              </Button>
            </div>
            {headline.expires ? <p className="mt-4 text-xs text-muted-foreground">Abo bis: {headline.expires}</p> : null}
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Operations-Verlauf</h2>

        {loading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <Skeleton key={i} className="h-24 w-full" />
            ))}
          </div>
        ) : operations.length === 0 ? (
          <div className="rounded-xl border bg-background shadow-sm p-5 text-sm text-muted-foreground">
            Keine Operationen gefunden.
          </div>
        ) : (
          <div className="space-y-3">
            {operations.map((op) => {
              const status = String(op.status || 'unknown');
              const statusLower = status.toLowerCase();
              const est = op.estimate || {};
              const tok = op.tokens || {};
              const costs = op.costs || {};
              const reservation = op.reservation || {};
              const costUsd = formatUsd(Number(costs.totalCostUsd ?? 0));

              const estCredits = Number(est.credits ?? 0);
              const actCredits = op.actualCredits ?? null;
              const creditsDisplay = formatCredits(actCredits == null ? estCredits : Number(actCredits));

              const cardClass = cn(
                'rounded-xl border bg-background shadow-sm px-5 py-4',
                (statusLower === 'running' || statusLower === 'reserved') && 'border-amber-500/20 bg-amber-500/5',
                (statusLower === 'blocked' || statusLower === 'error') && 'border-destructive/20 bg-destructive/5'
              );

              return (
                <div key={op.operationId || op.id} className={cardClass}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-semibold text-foreground truncate max-w-[360px]">
                          {humanizeOperationType(op.operationType)}
                        </p>
                        {op.model ? (
                          <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-[11px] font-semibold">
                            {op.model}
                          </Badge>
                        ) : null}
                        <Badge className={cn('rounded-md px-2 py-0.5 text-[11px] font-semibold', statusBadgeClass(status))}>
                          {statusLabel(status)}
                        </Badge>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{formatIso(op.timestamp || null)}</p>
                    </div>

                    <div className="shrink-0 text-right">
                      <p className="text-sm font-semibold text-foreground">{creditsDisplay} Credits</p>
                      <p className="text-xs text-muted-foreground">{costUsd ?? '\u00A0'}</p>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div className="text-xs">
                      <p className="text-xs text-muted-foreground">Geschätzte Tokens</p>
                      <p className="mt-1 text-foreground">
                        {formatTokens(Number(est.inputTokens ?? 0))} in / {formatTokens(Number(est.outputTokens ?? 0))} out
                      </p>
                    </div>
                    <div className="text-xs">
                      <p className="text-xs text-muted-foreground">Tatsächliche Tokens</p>
                      <p className="mt-1 text-foreground">
                        {formatTokens(Number(tok.inputTokens ?? 0))} in / {formatTokens(Number(tok.outputTokens ?? 0))} out
                        {tok.cachedInputTokens ? ` / ${formatTokens(Number(tok.cachedInputTokens ?? 0))} cached` : ''}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 border-t pt-4 text-xs text-muted-foreground space-y-1">
                    <p>
                      Reserviert:{' '}
                      <span className="text-foreground">{formatCredits(Number(reservation.reservedCredits ?? 0))}</span>{' '}
                      Credits{reservation.reservedAt ? ` um ${formatIso(reservation.reservedAt)}` : ''}
                    </p>
                    {reservation.releasedAt ? <p>Freigegeben um {formatIso(reservation.releasedAt)}</p> : null}
                  </div>

                  {op.errorMessage ? (
                    <p className="mt-4 text-xs text-destructive">{op.errorMessage}</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">Seite {pageIndex + 1}</p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (moreLoading) return;
                if (pageIndex <= 0) return;
                const prevIndex = pageIndex - 1;
                const cursor = cursorStack[prevIndex] ?? null;
                setMoreLoading(true);
                setPageNav('prev');
                loadOps(cursor)
                  .then(({ operations, nextCursor }) => {
                    setOperations(operations);
                    setNextCursor(nextCursor);
                    setPageIndex(prevIndex);
                  })
                  .catch((err: any) => {
                    toast.error('OpenAI', { description: err?.message || 'OpenAI Operationen konnten nicht geladen werden.' });
                  })
                  .finally(() => {
                    setMoreLoading(false);
                    setPageNav(null);
                  });
              }}
              disabled={moreLoading || pageIndex <= 0}
            >
              {pageNav === 'prev' ? 'Laden…' : 'Neuere'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (moreLoading) return;
                if (!nextCursor) return;
                const cursor = nextCursor;
                const nextIndex = pageIndex + 1;
                setMoreLoading(true);
                setPageNav('next');
                loadOps(cursor)
                  .then(({ operations, nextCursor }) => {
                    setOperations(operations);
                    setNextCursor(nextCursor);
                    setCursorStack((prev) => {
                      const out = prev.slice(0, nextIndex);
                      out[nextIndex] = cursor;
                      return out;
                    });
                    setPageIndex(nextIndex);
                  })
                  .catch((err: any) => {
                    toast.error('OpenAI', { description: err?.message || 'OpenAI Operationen konnten nicht geladen werden.' });
                  })
                  .finally(() => {
                    setMoreLoading(false);
                    setPageNav(null);
                  });
              }}
              disabled={moreLoading || !nextCursor}
            >
              {pageNav === 'next' ? 'Laden…' : 'Ältere'}
            </Button>
          </div>
        </div>
      </section>

      <Dialog
        open={reservedDialogOpen}
        onOpenChange={(open) => {
          setReservedDialogOpen(open);
          if (!open) {
            setReservedStep(1);
            setReservedVerify('');
          }
        }}
      >
        <DialogContent className="sm:max-w-[620px]">
          {(() => {
            const amountTrim = reservedAmount.trim();
            const amountNum = Number(amountTrim.replace(',', '.'));
            const amountOk =
              Number.isFinite(amountNum) && (reservedMode === 'set' ? amountNum >= 0 : amountNum !== 0);

            const verifyTrim = reservedVerify.trim();
            const verifyNum = Number(verifyTrim.replace(',', '.'));
            const verifyMatches = amountOk && Number.isFinite(verifyNum) && Math.abs(amountNum - verifyNum) < 1e-9;

            const noteLabel = reservedNote.trim() ? reservedNote.trim() : 'Keine Notiz angegeben';

            return (
              <>
                <DialogHeader>
                  <DialogTitle>
                    {reservedStep === 1
                      ? 'Reservierte Credits anpassen'
                      : reservedStep === 2
                        ? 'Reservierte Credits bestätigen'
                        : 'Reservierte Credits bestätigen'}
                  </DialogTitle>
                  <DialogDescription>
                    {reservedStep === 1
                      ? 'Ändern Sie die Anzahl der reservierten Credits. Nur verwenden, wenn Credits fälschlicherweise reserviert bleiben.'
                      : reservedStep === 2
                        ? 'Bitte bestätige die Änderung.'
                        : 'Bitte gib den Wert erneut ein, um die Änderung zu bestätigen.'}
                  </DialogDescription>
                </DialogHeader>

                {reservedStep === 1 ? (
                  <div className="grid gap-4 py-2">
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        variant={reservedMode === 'set' ? 'default' : 'outline'}
                        onClick={() => setReservedMode('set')}
                        disabled={savingReserved}
                      >
                        Set
                      </Button>
                      <Button
                        type="button"
                        variant={reservedMode === 'delta' ? 'default' : 'outline'}
                        onClick={() => setReservedMode('delta')}
                        disabled={savingReserved}
                      >
                        Delta
                      </Button>
                    </div>

                    <div className="grid gap-2">
                      <Label htmlFor="reserved-amount">Neue Anzahl reservierter Credits</Label>
                      <Input
                        id="reserved-amount"
                        type="number"
                        step="0.01"
                        value={reservedAmount}
                        onChange={(e) => setReservedAmount(e.target.value)}
                        placeholder={reservedMode === 'delta' ? 'z.B. -10 oder +10' : 'z.B. 0'}
                        disabled={savingReserved}
                      />
                      <div className="rounded-md border bg-amber-500/10 text-amber-900 border-amber-500/20 px-3 py-2 text-sm">
                        Aktuell reserviert: {headline.reserved} Credits
                      </div>
                    </div>

                    <div className="grid gap-2">
                      <Label htmlFor="reserved-note">Notiz / Grund</Label>
                      <Textarea
                        id="reserved-note"
                        value={reservedNote}
                        onChange={(e) => setReservedNote(e.target.value)}
                        placeholder="Grund für die Anpassung…"
                        disabled={savingReserved}
                      />
                    </div>
                  </div>
                ) : null}

                {reservedStep === 2 ? (
                  <div className="py-2 space-y-3">
                    <div className="rounded-md border bg-amber-500/10 text-amber-900 border-amber-500/20 px-3 py-2 text-sm">
                      Modus: {reservedMode.toUpperCase()} · Wert: {formatCredits(amountNum)} · Grund: {noteLabel}
                    </div>
                  </div>
                ) : null}

                {reservedStep === 3 ? (
                  <div className="grid gap-3 py-2">
                    <div className="grid gap-2">
                      <Label htmlFor="reserved-verify">Wert erneut eingeben</Label>
                      <Input
                        id="reserved-verify"
                        type="number"
                        step="0.01"
                        value={reservedVerify}
                        onChange={(e) => setReservedVerify(e.target.value)}
                        placeholder={amountTrim || '0'}
                        disabled={savingReserved}
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
                      if (reservedStep === 1) {
                        setReservedDialogOpen(false);
                        return;
                      }
                      if (reservedStep === 2) setReservedStep(1);
                      if (reservedStep === 3) setReservedStep(2);
                    }}
                    disabled={savingReserved}
                  >
                    {reservedStep === 1 ? 'Abbrechen' : 'Zurück'}
                  </Button>

                  {reservedStep === 1 ? (
                    <Button
                      type="button"
                      onClick={() => {
                        if (!amountOk) {
                          toast.error('Reserved Credits', { description: 'Bitte einen gültigen Wert eingeben.' });
                          return;
                        }
                        setReservedStep(2);
                      }}
                      disabled={savingReserved}
                    >
                      Weiter
                    </Button>
                  ) : null}

                  {reservedStep === 2 ? (
                    <Button
                      type="button"
                      onClick={() => {
                        setReservedVerify('');
                        setReservedStep(3);
                      }}
                      disabled={savingReserved}
                    >
                      Bestätigen
                    </Button>
                  ) : null}

                  {reservedStep === 3 ? (
                    <Button
                      type="button"
                      onClick={handleAdjustReserved}
                      disabled={!verifyMatches || savingReserved}
                    >
                      Anwenden
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

