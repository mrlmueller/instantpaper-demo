'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Copy, Plus, RefreshCw, ToggleLeft, ToggleRight } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
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

function fmtIso(iso: string | null): string {
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
  const [createdCode, setCreatedCode] = useState<string | null>(null);

  const [name, setName] = useState('');
  const [maxUses, setMaxUses] = useState('1');
  const [note, setNote] = useState('');

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

  const handleCreate = async () => {
    const nameTrim = name.trim();
    if (!nameTrim) {
      toast.error('Access Code', { description: 'Bitte einen Namen angeben.' });
      return;
    }

    const max = Number.parseInt(maxUses || '1', 10);
    if (!Number.isFinite(max) || max < 1) {
      toast.error('Access Code', { description: 'maxUses muss >= 1 sein.' });
      return;
    }

    setSaving(true);
    try {
      const res = await fetch('/api/admin/access-codes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: nameTrim, maxUses: max, note: note.trim() || null }),
      });
      const data = (await res.json()) as { code?: string; error?: string };
      if (!res.ok) throw new Error(data.error || 'Code konnte nicht erstellt werden.');
      if (data.code) setCreatedCode(String(data.code));
      setName('');
      setMaxUses('1');
      setNote('');
      await load();
      toast.success('Access Code erstellt');
    } catch (err: unknown) {
      toast.error('Access Code', { description: getErrorMessage(err, 'Code konnte nicht erstellt werden.') });
    } finally {
      setSaving(false);
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

  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Kopiert', { description: value });
    } catch {
      toast.error('Copy', { description: 'Konnte nicht kopieren.' });
    }
  };

  const rows = useMemo(() => {
    const out = [...codes];
    out.sort((a, b) => String(b.createdAt || '').localeCompare(String(a.createdAt || '')));
    return out;
  }, [codes]);

  return (
    <div className="space-y-6">
      <Card className="border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">Neuen Access Code erstellen</CardTitle>
          <CardDescription>Default: maxUses = 1, aber konfigurierbar.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="ac-name">Name</Label>
              <Input id="ac-name" value={name} onChange={(e) => setName(e.target.value)} disabled={saving} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ac-max">maxUses</Label>
              <Input
                id="ac-max"
                value={maxUses}
                onChange={(e) => setMaxUses(e.target.value)}
                inputMode="numeric"
                disabled={saving}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="ac-note">Notiz (optional)</Label>
            <Textarea id="ac-note" value={note} onChange={(e) => setNote(e.target.value)} disabled={saving} />
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleCreate} disabled={saving}>
              <Plus className="h-4 w-4" />
              Erstellen
            </Button>
            <Button variant="outline" onClick={load} disabled={saving || loading}>
              <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
              Refresh
            </Button>
          </div>

          {createdCode ? (
            <div className="rounded-lg border p-3 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">Neuer Code</p>
                <p className="text-sm font-mono truncate">{createdCode}</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => handleCopy(createdCode)}>
                <Copy className="h-4 w-4" />
                Copy
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card className="border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">Access Codes</CardTitle>
          <CardDescription>Name, uses/maxUses, lastUsedAt und Status.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Code</TableHead>
                <TableHead>Usage</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Aktionen</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    {loading ? 'Laden…' : 'Keine Codes.'}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((c) => (
                  <TableRow key={c.code}>
                    <TableCell className="min-w-[180px]">
                      <div className="min-w-0">
                        <p className="font-medium truncate">{c.name}</p>
                        {c.note ? <p className="text-xs text-muted-foreground truncate">{c.note}</p> : null}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono">{c.code}</TableCell>
                    <TableCell>
                      {c.uses}/{c.maxUses}
                    </TableCell>
                    <TableCell>{fmtIso(c.createdAt)}</TableCell>
                    <TableCell>{fmtIso(c.lastUsedAt)}</TableCell>
                    <TableCell>
                      <Badge variant={c.disabled ? 'outline' : 'default'}>{c.disabled ? 'Disabled' : 'Active'}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        <Button variant="outline" size="sm" asChild>
                          <Link href={`/admin/access-codes/${encodeURIComponent(c.code)}`}>Details</Link>
                        </Button>
                        <Button
                          variant={c.disabled ? 'default' : 'destructive'}
                          size="sm"
                          disabled={saving}
                          onClick={() => toggleDisabled(c.code, !c.disabled)}
                          title={c.disabled ? 'Aktivieren' : 'Deaktivieren'}
                        >
                          {c.disabled ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
                          {c.disabled ? 'Enable' : 'Disable'}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
