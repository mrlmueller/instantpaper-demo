'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ArrowUpRight, Copy, Pencil, RefreshCw } from 'lucide-react';

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
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';

type CodeDetail = {
  code: string;
  name: string;
  note: string | null;
  maxUses: number;
  uses: number;
  disabled: boolean;
  createdAt: string | null;
  lastUsedAt: string | null;
};

type RedemptionRow = {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoURL: string | null;
  firstRedeemedAt: string | null;
  lastRedeemedAt: string | null;
  firstIp: string | null;
  lastIp: string | null;
  firstUserAgent: string | null;
  lastUserAgent: string | null;
};

type AttemptRow = {
  id: string;
  uid: string | null;
  email: string | null;
  displayName: string | null;
  success: boolean;
  reason: string | null;
  ip: string | null;
  userAgent: string | null;
  createdAt: string | null;
};

type DetailResponse = {
  code: CodeDetail;
  redemptions: RedemptionRow[];
  attempts: AttemptRow[];
  error?: string;
};

function fmtDate(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString('de-DE', { year: 'numeric', month: '2-digit', day: '2-digit' });
  } catch {
    return iso;
  }
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('de-DE', {
      year: '2-digit',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function getErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === 'string' && err.trim()) return err.trim();
  return fallback;
}

export function AdminAccessCodeDetail({ code }: { code: string }) {
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [editOpen, setEditOpen] = useState(false);
  const [editDescription, setEditDescription] = useState('');
  const [editMaxUses, setEditMaxUses] = useState('1');
  const [editNote, setEditNote] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/admin/access-codes/${encodeURIComponent(code)}`, { cache: 'no-store' });
      const data = (await res.json()) as DetailResponse;
      if (!res.ok) throw new Error(data.error || 'Konnte Code nicht laden.');
      setDetail(data);
    } catch (err: unknown) {
      toast.error('Access Code', { description: getErrorMessage(err, 'Konnte Code nicht laden.') });
      setDetail(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const handleCopy = async () => {
    const value = detail?.code?.code;
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Kopiert', { description: value });
    } catch {
      toast.error('Copy', { description: 'Konnte nicht kopieren.' });
    }
  };

  const openEdit = () => {
    if (!detail) return;
    setEditDescription(detail.code.name || '');
    setEditMaxUses(String(detail.code.maxUses || 1));
    setEditNote(detail.code.note || '');
    setEditOpen(true);
  };

  const handleEditSave = async () => {
    if (!detail) return;
    const desc = editDescription.trim();
    if (!desc) {
      toast.error('Access Code', { description: 'Bitte eine Beschreibung angeben.' });
      return;
    }
    const max = Number.parseInt(editMaxUses || '1', 10);
    if (!Number.isFinite(max) || max < 1) {
      toast.error('Access Code', { description: 'Max. Nutzungen muss >= 1 sein.' });
      return;
    }

    setSaving(true);
    try {
      const res = await fetch(`/api/admin/access-codes/${encodeURIComponent(detail.code.code)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: desc, maxUses: max, note: editNote.trim() || null }),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error || 'Konnte Code nicht speichern.');
      toast.success('Code gespeichert');
      setEditOpen(false);
      await load();
    } catch (err: unknown) {
      toast.error('Access Code', { description: getErrorMessage(err, 'Konnte Code nicht speichern.') });
    } finally {
      setSaving(false);
    }
  };

  const redemptions = useMemo(() => detail?.redemptions || [], [detail]);
  const attempts = useMemo(() => detail?.attempts || [], [detail]);

  if (loading) {
    return (
      <div className="rounded-xl border bg-background shadow-sm p-5">
        <p className="text-sm font-medium text-foreground">Laden…</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="rounded-xl border bg-background shadow-sm p-5">
        <p className="text-sm font-semibold text-foreground">Code nicht gefunden</p>
        <p className="mt-1 text-sm text-muted-foreground">
          <Link href="/admin/access-codes" className="text-primary hover:underline">
            Zurück zur Liste
          </Link>
        </p>
      </div>
    );
  }

  const c = detail.code;
  const remaining = Math.max(0, Number(c.maxUses || 0) - Number(c.uses || 0));
  const statusLabel = c.disabled ? 'Inaktiv' : 'Aktiv';
  const statusClass = c.disabled
    ? 'bg-muted/40 text-muted-foreground border-muted-foreground/20'
    : 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Badge className={cn('rounded-md border px-2 py-0.5 text-xs font-semibold', statusClass)}>{statusLabel}</Badge>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={saving}>
          <RefreshCw className={cn('h-4 w-4', saving && 'animate-spin')} />
          Aktualisieren
        </Button>
      </div>

      <div className="rounded-xl border bg-background shadow-sm p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">Code</p>
            <div className="mt-2 flex items-center gap-2">
              <span className="inline-flex items-center rounded-md bg-muted/40 px-3 py-2 text-sm font-mono font-semibold text-foreground">
                {c.code}
              </span>
              <Button variant="ghost" size="icon-sm" className="h-8 w-8" onClick={handleCopy} title="Kopieren">
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={openEdit} disabled={saving}>
            <Pencil className="h-4 w-4" />
            Bearbeiten
          </Button>
        </div>

        <div className="mt-4">
          <p className="text-xs text-muted-foreground">Beschreibung</p>
          <p className="mt-1 text-sm text-foreground">{c.name || '-'}</p>
          {c.note ? <p className="mt-1 text-sm text-muted-foreground">{c.note}</p> : null}
        </div>

        <div className="mt-6 border-t pt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-xs text-muted-foreground">Nutzungen</p>
            <p className="mt-1 text-sm font-semibold text-foreground">
              {c.uses}/{c.maxUses}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Erstellt am</p>
            <p className="mt-1 text-sm font-semibold text-foreground">{fmtDate(c.createdAt)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Ablaufdatum</p>
            <p className="mt-1 text-sm font-semibold text-foreground">Kein Ablauf</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Verbleibend</p>
            <p className="mt-1 text-sm font-semibold text-foreground">{remaining}</p>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-foreground">Aktivierte Accounts ({redemptions.length})</h3>
        </div>

        {redemptions.length === 0 ? (
          <div className="rounded-xl border bg-background shadow-sm p-5 text-sm text-muted-foreground">Keine Aktivierungen.</div>
        ) : (
          <div className="space-y-3">
            {redemptions.map((r) => {
              const label = r.displayName || r.email || r.uid || '-';
              const secondary = r.email || r.uid;
              const activatedAt = r.lastRedeemedAt || r.firstRedeemedAt;
              return (
                <div key={r.uid} className="rounded-xl border bg-background shadow-sm px-5 py-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-foreground truncate">{label}</p>
                      <p className="text-xs text-muted-foreground truncate">{secondary}</p>
                      <p className="text-xs text-muted-foreground truncate">{r.uid}</p>
                    </div>
                    <div className="flex items-center justify-between gap-3 sm:justify-end">
                      <div className="text-right">
                        <p className="text-xs text-muted-foreground">Aktiviert am</p>
                        <p className="text-sm text-foreground">{fmtDateTime(activatedAt)}</p>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="h-8 w-8"
                        asChild
                        title="User Details"
                      >
                        <Link href={`/admin/users/${encodeURIComponent(r.uid)}`}>
                          <ArrowUpRight className="h-4 w-4" />
                        </Link>
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <details className="rounded-xl border bg-background shadow-sm px-5 py-4">
        <summary className="cursor-pointer text-sm font-semibold text-foreground">Redeem Attempts ({attempts.length})</summary>
        <div className="mt-4 space-y-2">
          {attempts.length === 0 ? (
            <p className="text-sm text-muted-foreground">Keine Attempts.</p>
          ) : (
            <div className="space-y-2">
              {attempts.map((a) => (
                <div key={a.id} className="rounded-lg border bg-muted/10 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{a.displayName || a.email || a.uid || '-'}</p>
                      <p className="text-xs text-muted-foreground truncate">{a.reason || (a.success ? 'success' : 'failed')}</p>
                    </div>
                    <div className="text-xs text-muted-foreground">{fmtDateTime(a.createdAt)}</div>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    IP: <span className="font-mono">{a.ip || '-'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </details>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Code bearbeiten</DialogTitle>
            <DialogDescription>{c.code}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="space-y-2">
              <Label htmlFor="ac-edit-desc">Beschreibung</Label>
              <Input
                id="ac-edit-desc"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                disabled={saving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ac-edit-max">Max. Nutzungen</Label>
              <Input
                id="ac-edit-max"
                value={editMaxUses}
                onChange={(e) => setEditMaxUses(e.target.value)}
                inputMode="numeric"
                disabled={saving}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ac-edit-note">Notiz (optional)</Label>
              <Textarea
                id="ac-edit-note"
                value={editNote}
                onChange={(e) => setEditNote(e.target.value)}
                disabled={saving}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)} disabled={saving}>
              Abbrechen
            </Button>
            <Button onClick={handleEditSave} disabled={saving}>
              Speichern
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
