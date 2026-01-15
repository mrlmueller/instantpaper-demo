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
import { Skeleton } from '@/components/ui/skeleton';
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
  user: AdminUserDetailRow;
  openaiKey: AdminUserOpenAIKey;
};

function keySourceLabel(source: AdminUserOpenAIKey['source']): string {
  if (source === 'user') return 'User Key';
  if (source === 'platform') return 'Platform Key';
  return 'No Key';
}

export function AdminUserDetail({ uid }: { uid: string }) {
  const [detail, setDetail] = useState<AdminUserDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloading, setReloading] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [tab, setTab] = useState<'prompts' | 'stats' | 'projects'>('prompts');

  const title = useMemo(() => {
    const user = detail?.user;
    if (!user) return uid;
    return user.displayName || user.email || user.uid;
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
      {tab === 'stats' ? <AdminUserStatsPanel uid={user.uid} refreshNonce={refreshNonce} /> : null}
      {tab === 'projects' ? <AdminUserProjectsPanel uid={user.uid} refreshNonce={refreshNonce} /> : null}
    </div>
  );
}

