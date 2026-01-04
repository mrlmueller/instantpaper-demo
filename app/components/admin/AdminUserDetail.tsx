'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { AdminUserPromptManager } from '@/app/components/admin/AdminUserPromptManager';
import { AdminUserProjectsPanel } from '@/app/components/admin/AdminUserProjectsPanel';
import { AdminUserStatsPanel } from '@/app/components/admin/AdminUserStatsPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

type AdminUserDetail = {
  uid: string;
  email: string | null;
  displayName: string | null;
  approved: boolean;
  disabled: boolean;
  allowPlatformKey: boolean;
  canDuplicateSystemPrompts: boolean;
  createdAt: string | null;
  lastSignInAt: string | null;
};

type AdminUserOpenAIKey = {
  hasKey: boolean;
  last4: string | null;
  allowPlatformKey: boolean;
  source: 'user' | 'platform' | 'none';
};

type AdminUserDetailResponse = {
  user: AdminUserDetail;
  openaiKey: AdminUserOpenAIKey;
};

function formatIso(iso: string | null): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('de-DE');
  } catch {
    return iso;
  }
}

function keySourceLabel(source: AdminUserOpenAIKey['source']): string {
  if (source === 'user') return 'User Key';
  if (source === 'platform') return 'Platform Key';
  return 'No Key';
}

export function AdminUserDetail({ uid }: { uid: string }) {
  const [detail, setDetail] = useState<AdminUserDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);

  const title = useMemo(() => {
    const u = detail?.user;
    if (!u) return uid;
    return u.email || u.displayName || u.uid;
  }, [detail, uid]);

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

  useEffect(() => {
    setLoading(true);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Card className="p-6 space-y-3">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-80" />
        </Card>
        <Card className="p-6">
          <Skeleton className="h-10 w-full" />
        </Card>
      </div>
    );
  }

  if (!detail) {
    return (
      <Card className="p-6">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{uid}</p>
            <p className="text-xs text-muted-foreground">Keine Daten verfügbar.</p>
          </div>
          <Button variant="outline" onClick={load} disabled={reloading}>
            Reload
          </Button>
        </div>
      </Card>
    );
  }

  const u = detail.user;
  const key = detail.openaiKey;

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-foreground truncate">{title}</h2>
            <p className="text-xs text-muted-foreground mt-1 break-all">UID: {u.uid}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge variant={u.approved ? 'default' : 'outline'}>{u.approved ? 'approved' : 'pending'}</Badge>
              {u.disabled ? (
                <Badge variant="outline" className="border-destructive text-destructive">
                  disabled
                </Badge>
              ) : null}
              <Badge variant="secondary">platform-key: {u.allowPlatformKey ? 'allowed' : 'blocked'}</Badge>
              <Badge variant="secondary">syscopy: {u.canDuplicateSystemPrompts ? 'allowed' : 'blocked'}</Badge>
            </div>
          </div>

          <div className="flex flex-col items-start gap-2 sm:items-end">
            <Button variant="outline" onClick={load} disabled={reloading}>
              Reload
            </Button>
            <div className="text-xs text-muted-foreground space-y-1">
              <div>Created: {formatIso(u.createdAt)}</div>
              <div>Last login: {formatIso(u.lastSignInAt)}</div>
              <div>
                OpenAI: <span className="text-foreground">{keySourceLabel(key.source)}</span>
                {key.last4 ? <span className="text-muted-foreground"> (…{key.last4})</span> : null}
              </div>
            </div>
          </div>
        </div>
      </Card>

      <Tabs defaultValue="prompts">
        <TabsList className="w-full flex-wrap h-auto gap-1 p-1">
          <TabsTrigger value="prompts" className="text-xs px-3 py-1.5">
            Prompts
          </TabsTrigger>
          <TabsTrigger value="stats" className="text-xs px-3 py-1.5">
            Stats
          </TabsTrigger>
          <TabsTrigger value="projects" className="text-xs px-3 py-1.5">
            Projects & Quellen
          </TabsTrigger>
        </TabsList>

        <TabsContent value="prompts">
          <AdminUserPromptManager uid={u.uid} />
        </TabsContent>
        <TabsContent value="stats">
          <AdminUserStatsPanel uid={u.uid} />
        </TabsContent>
        <TabsContent value="projects">
          <AdminUserProjectsPanel uid={u.uid} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
