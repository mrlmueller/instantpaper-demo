'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Copy, RefreshCw, ToggleLeft, ToggleRight } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
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

export function AdminAccessCodeDetail({ code }: { code: string }) {
  const [detail, setDetail] = useState<DetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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

  const toggleDisabled = async () => {
    if (!detail) return;
    const nextDisabled = !detail.code.disabled;
    setSaving(true);
    try {
      const res = await fetch(`/api/admin/access-codes/${encodeURIComponent(detail.code.code)}`, {
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

  const redemptions = useMemo(() => detail?.redemptions || [], [detail]);
  const attempts = useMemo(() => detail?.attempts || [], [detail]);

  if (loading) {
    return (
      <Card className="border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">Laden…</CardTitle>
        </CardHeader>
      </Card>
    );
  }

  if (!detail) {
    return (
      <Card className="border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">Code nicht gefunden</CardTitle>
          <CardDescription>
            <Link href="/admin/access-codes" className="text-primary hover:underline">
              Zurück zur Liste
            </Link>
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const c = detail.code;

  return (
    <div className="space-y-6">
      <Card className="border-border shadow-sm">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle className="text-lg truncate">{c.name}</CardTitle>
              <CardDescription className="mt-1">
                <span className="font-mono">{c.code}</span>
                {c.note ? <span className="block mt-1">{c.note}</span> : null}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handleCopy}>
                <Copy className="h-4 w-4" />
                Copy
              </Button>
              <Button
                variant={c.disabled ? 'default' : 'destructive'}
                size="sm"
                onClick={toggleDisabled}
                disabled={saving}
                title={c.disabled ? 'Aktivieren' : 'Deaktivieren'}
              >
                {c.disabled ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
                {c.disabled ? 'Enable' : 'Disable'}
              </Button>
              <Button variant="outline" size="sm" onClick={load} disabled={saving}>
                <RefreshCw className={cn('h-4 w-4', saving && 'animate-spin')} />
                Refresh
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Usage</p>
            <p className="text-sm font-medium">
              {c.uses}/{c.maxUses}
            </p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Status</p>
            <Badge variant={c.disabled ? 'outline' : 'default'}>{c.disabled ? 'Disabled' : 'Active'}</Badge>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Created</p>
            <p className="text-sm font-medium">{fmtIso(c.createdAt)}</p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">Last used</p>
            <p className="text-sm font-medium">{fmtIso(c.lastUsedAt)}</p>
          </div>
        </CardContent>
      </Card>

      <Card className="border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">Aktivierte Accounts</CardTitle>
          <CardDescription>UID, E-Mail, DisplayName, Zeit, IP und User-Agent.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead>First</TableHead>
                <TableHead>Last</TableHead>
                <TableHead>IP</TableHead>
                <TableHead>User-Agent</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {redemptions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Keine Aktivierungen.
                  </TableCell>
                </TableRow>
              ) : (
                redemptions.map((r) => (
                  <TableRow key={r.uid}>
                    <TableCell className="min-w-[260px]">
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{r.displayName || r.email || r.uid}</p>
                        <p className="text-xs text-muted-foreground truncate">{r.email || r.uid}</p>
                      </div>
                    </TableCell>
                    <TableCell>{fmtIso(r.firstRedeemedAt)}</TableCell>
                    <TableCell>{fmtIso(r.lastRedeemedAt)}</TableCell>
                    <TableCell className="font-mono">{r.lastIp || r.firstIp || '-'}</TableCell>
                    <TableCell className="max-w-[380px] truncate">{r.lastUserAgent || r.firstUserAgent || '-'}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg">Redeem Attempts</CardTitle>
          <CardDescription>Erfolgreiche und fehlgeschlagene Versuche (letzte 200).</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Zeit</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead>IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {attempts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    Keine Attempts.
                  </TableCell>
                </TableRow>
              ) : (
                attempts.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>{fmtIso(a.createdAt)}</TableCell>
                    <TableCell className="min-w-[220px]">
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{a.displayName || a.email || a.uid || '-'}</p>
                        <p className="text-xs text-muted-foreground truncate">{a.uid || '-'}</p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={a.success ? 'default' : 'outline'}>{a.success ? 'OK' : 'Fail'}</Badge>
                    </TableCell>
                    <TableCell className="font-mono">{a.reason || '-'}</TableCell>
                    <TableCell className="font-mono">{a.ip || '-'}</TableCell>
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
