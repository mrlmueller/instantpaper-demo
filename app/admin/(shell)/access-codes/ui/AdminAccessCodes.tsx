'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ArrowUpRight, Check, Copy, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
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

type AccessCodeRow = {
  code: string;
  name: string;
  note: string | null;
  maxUses: number;
  uses: number;
  disabled: boolean;
  createdAt: string | null;
  lastUsedAt: string | null;
};

type ListResponse = { codes?: AccessCodeRow[]; error?: string };

function fmtDate(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('de-DE', { year: '2-digit', month: '2-digit', day: '2-digit' });
  } catch {
    return iso;
  }
}

function getErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === 'string' && err.trim()) return err.trim();
  return fallback;
}

export function AdminAccessCodes() {
  const [codes, setCodes] = useState<AccessCodeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [createdCode, setCreatedCode] = useState<string | null>(null);
  const [createDescription, setCreateDescription] = useState('');
  const [createMaxUses, setCreateMaxUses] = useState('1');
  const [createNote, setCreateNote] = useState('');

  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<AccessCodeRow | null>(null);
  const [editDescription, setEditDescription] = useState('');
  const [editMaxUses, setEditMaxUses] = useState('1');
  const [editNote, setEditNote] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/admin/access-codes', { method: 'GET', cache: 'no-store' });
      const data = (await res.json()) as ListResponse;
      if (!res.ok) throw new Error(data.error || 'Konnte Codes nicht laden.');
      setCodes(Array.isArray(data.codes) ? data.codes : []);
    } catch (err: unknown) {
      toast.error('Access Codes', { description: getErrorMessage(err, 'Konnte Codes nicht laden.') });
      setCodes([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const rows = useMemo(() => {
    const out = [...codes];
    out.sort((a, b) => String(b.createdAt || '').localeCompare(String(a.createdAt || '')));
    return out;
  }, [codes]);

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Kopiert', { description: value });
    } catch {
      toast.error('Copy', { description: 'Konnte nicht kopieren.' });
    }
  };

  const toggleDisabled = async (code: string, nextDisabled: boolean) => {
    setSaving(true);
    try {
      const res = await fetch(`/api/admin/access-codes/${encodeURIComponent(code)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ disabled: nextDisabled }),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error || 'Konnte Code-Status nicht ändern.');
      await load();
    } catch (err: unknown) {
      toast.error('Access Code', { description: getErrorMessage(err, 'Konnte Code-Status nicht ändern.') });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (code: string) => {
    setSaving(true);
    try {
      const res = await fetch(`/api/admin/access-codes/${encodeURIComponent(code)}`, { method: 'DELETE' });
      const data = (await res.json().catch(() => ({}))) as { error?: string };
      if (!res.ok) throw new Error(data.error || 'Konnte Code nicht löschen.');
      toast.success('Code gelöscht');
      await load();
    } catch (err: unknown) {
      toast.error('Access Code', { description: getErrorMessage(err, 'Konnte Code nicht löschen.') });
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (row: AccessCodeRow) => {
    setEditTarget(row);
    setEditDescription(row.name || '');
    setEditMaxUses(String(row.maxUses || 1));
    setEditNote(row.note || '');
    setEditOpen(true);
  };

  const handleEditSave = async () => {
    if (!editTarget) return;
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
      const res = await fetch(`/api/admin/access-codes/${encodeURIComponent(editTarget.code)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: desc, maxUses: max, note: editNote.trim() || null }),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error || 'Konnte Code nicht speichern.');
      toast.success('Code gespeichert');
      setEditOpen(false);
      setEditTarget(null);
      await load();
    } catch (err: unknown) {
      toast.error('Access Code', { description: getErrorMessage(err, 'Konnte Code nicht speichern.') });
    } finally {
      setSaving(false);
    }
  };

  const handleCreate = async () => {
    const desc = createDescription.trim();
    if (!desc) {
      toast.error('Access Code', { description: 'Bitte eine Beschreibung angeben.' });
      return;
    }

    const max = Number.parseInt(createMaxUses || '1', 10);
    if (!Number.isFinite(max) || max < 1) {
      toast.error('Access Code', { description: 'Max. Nutzungen muss >= 1 sein.' });
      return;
    }

    setSaving(true);
    try {
      const res = await fetch('/api/admin/access-codes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: desc, maxUses: max, note: createNote.trim() || null }),
      });
      const data = (await res.json()) as { code?: string; error?: string };
      if (!res.ok) throw new Error(data.error || 'Code konnte nicht erstellt werden.');
      if (data.code) setCreatedCode(String(data.code));
      setCreateDescription('');
      setCreateMaxUses('1');
      setCreateNote('');
      setCreateOpen(false);
      await load();
      toast.success('Access Code erstellt');
    } catch (err: unknown) {
      toast.error('Access Code', { description: getErrorMessage(err, 'Code konnte nicht erstellt werden.') });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold text-foreground">Access Codes</h2>
          <p className="text-sm text-muted-foreground">Einladungs- und Promo-Codes verwalten</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="icon"
            className="h-9 w-9"
            onClick={load}
            disabled={loading || saving}
            aria-label="Aktualisieren"
            title="Aktualisieren"
          >
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </Button>
          <Button onClick={() => setCreateOpen(true)} disabled={saving}>
            <Plus className="h-4 w-4" />
            Neuer Code
          </Button>
        </div>
      </div>

      {createdCode ? (
        <div className="rounded-xl border bg-background shadow-sm p-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">Neuer Code</p>
            <p className="mt-1 font-mono text-sm truncate">{createdCode}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => handleCopy(createdCode)}>
              <Copy className="h-4 w-4" />
              Kopieren
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setCreatedCode(null)}>
              OK
            </Button>
          </div>
        </div>
      ) : null}

      <div className="space-y-3">
        {rows.length === 0 ? (
          <div className="rounded-xl border bg-background shadow-sm p-5 text-sm text-muted-foreground">
            {loading ? 'Laden…' : 'Keine Codes.'}
          </div>
        ) : (
          rows.map((c) => {
            const statusLabel = c.disabled ? 'Inaktiv' : 'Aktiv';
            return (
              <div key={c.code} className="rounded-xl border bg-background shadow-sm px-5 py-4">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleCopy(c.code)}
                        className="inline-flex items-center rounded-md bg-muted/40 px-2.5 py-1 text-xs font-mono font-semibold text-foreground hover:bg-muted/60"
                        title="Code kopieren"
                      >
                        {c.code}
                      </button>
                      <Badge
                        className={cn(
                          'rounded-md border px-2 py-0.5 text-xs font-semibold',
                          c.disabled
                            ? 'bg-muted/40 text-muted-foreground border-muted-foreground/20'
                            : 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20'
                        )}
                      >
                        {statusLabel}
                      </Badge>
                    </div>
                    <p className="mt-2 text-sm font-medium text-foreground truncate">{c.name}</p>
                    {c.note ? <p className="mt-1 text-xs text-muted-foreground truncate">{c.note}</p> : null}
                  </div>

                  <div className="flex flex-col gap-2 sm:items-end">
                    <div className="text-sm font-semibold text-foreground sm:text-right">
                      {c.uses}/{c.maxUses} genutzt
                    </div>
                    <div className="text-xs text-muted-foreground sm:text-right">Erstellt: {fmtDate(c.createdAt)}</div>
                  </div>

                  <div className="flex items-center gap-2 sm:justify-end">
                    <Button variant="ghost" size="icon-sm" className="h-8 w-8" asChild title="Details öffnen">
                      <Link href={`/admin/access-codes/${encodeURIComponent(c.code)}`}>
                        <ArrowUpRight className="h-4 w-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-8 w-8"
                      onClick={() => openEdit(c)}
                      title="Bearbeiten"
                      disabled={saving}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className={cn('h-8 w-8', c.disabled ? 'text-emerald-700' : 'text-amber-600')}
                      onClick={() => toggleDisabled(c.code, !c.disabled)}
                      title={c.disabled ? 'Aktivieren' : 'Deaktivieren'}
                      disabled={saving}
                    >
                      {c.disabled ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
                    </Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          className="h-8 w-8 text-destructive"
                          title="Löschen"
                          disabled={saving}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Code löschen?</AlertDialogTitle>
                          <AlertDialogDescription>
                            Soll der Code <span className="font-mono">{c.code}</span> wirklich gelöscht werden?
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel disabled={saving}>Abbrechen</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={() => handleDelete(c.code)}
                            className="bg-destructive text-white hover:bg-destructive/90"
                            disabled={saving}
                          >
                            Löschen
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Neuen Code erstellen</DialogTitle>
            <DialogDescription>Lege einen neuen Access Code an (Default: maxUses = 1).</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="space-y-2">
              <Label htmlFor="ac-desc">Beschreibung</Label>
              <Input
                id="ac-desc"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                disabled={saving}
                placeholder="z.B. Beta Tester Einladung"
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="ac-max">Max. Nutzungen</Label>
                <Input
                  id="ac-max"
                  value={createMaxUses}
                  onChange={(e) => setCreateMaxUses(e.target.value)}
                  inputMode="numeric"
                  disabled={saving}
                />
              </div>
              <div className="space-y-2">
                <Label>Code</Label>
                <Input value="wird automatisch generiert" disabled />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ac-note">Notiz (optional)</Label>
              <Textarea
                id="ac-note"
                value={createNote}
                onChange={(e) => setCreateNote(e.target.value)}
                disabled={saving}
                placeholder="Kurze Notiz"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Abbrechen
            </Button>
            <Button onClick={handleCreate} disabled={saving}>
              Speichern
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Code bearbeiten</DialogTitle>
            <DialogDescription>{editTarget ? editTarget.code : ''}</DialogDescription>
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
            <Button onClick={handleEditSave} disabled={saving || !editTarget}>
              Speichern
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
