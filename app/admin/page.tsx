import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ArrowLeft, Key, MessageSquareText, Users } from 'lucide-react';

import {
  adminSetCanDuplicateSystemPrompts,
  adminSetUserBlocked,
  adminSetUserFullAccess,
} from '@/app/actions/admin';
import { ConfirmSubmitDialog } from '@/app/components/admin/ConfirmSubmitDialog';
import { SystemPromptManager } from '@/app/components/admin/SystemPromptManager';
import { isAdminUser, listAdminUsers, type AdminUserRow } from '@/app/lib/api/adminServer';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export const dynamic = 'force-dynamic';

type SearchParamsPromise = Promise<Record<string, string | string[] | undefined>>;

function asTime(iso: string | null): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : 0;
}

function formatIso(iso: string | null): string {
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

function splitUsers(users: AdminUserRow[]) {
  const blocked = users.filter((u) => u.blocked === true);
  const pending = users.filter((u) => u.blocked !== true && u.fullAccess !== true);
  const fullAccess = users.filter((u) => u.blocked !== true && u.fullAccess === true);

  blocked.sort((a, b) => asTime(b.lastSignInAt) - asTime(a.lastSignInAt) || asTime(b.createdAt) - asTime(a.createdAt));
  pending.sort((a, b) => asTime(b.lastSignInAt) - asTime(a.lastSignInAt) || asTime(b.createdAt) - asTime(a.createdAt));
  fullAccess.sort((a, b) => String(a.email || '').localeCompare(String(b.email || ''), 'de'));

  return { blocked, pending, fullAccess };
}

function stableRowKey(user: AdminUserRow): string {
  return `${user.uid || user.email || user.displayName || 'user'}-${user.createdAt || ''}-${user.lastSignInAt || ''}`;
}

function safeId(value: string): string {
  return String(value || '')
    .trim()
    .replace(/[^a-zA-Z0-9_-]/g, '_');
}

function CountBadge({ value }: { value: number }) {
  return (
    <Badge className="rounded-md bg-primary text-primary-foreground px-2 py-0.5 text-xs font-semibold">
      {value}
    </Badge>
  );
}

function DetailsLink({ uid }: { uid: string | null }) {
  if (!uid) return null;
  return (
    <Link href={`/admin/users/${encodeURIComponent(uid)}`} className="text-sm font-medium text-foreground hover:underline">
      Details
    </Link>
  );
}

function PillForm({
  formId,
  action,
  email,
  hiddenInputs,
  label,
  enabledVariant,
  title,
  description,
  confirmLabel,
  confirmVariant,
  disabled,
}: {
  formId: string;
  action: (formData: FormData) => Promise<void>;
  email: string | null;
  hiddenInputs: Array<{ name: string; value: string }>;
  label: string;
  enabledVariant: 'default' | 'outline' | 'destructive';
  title: string;
  description: string;
  confirmLabel: string;
  confirmVariant: 'default' | 'outline' | 'destructive';
  disabled?: boolean;
}) {
  if (!email || disabled) {
    return (
      <Button variant={enabledVariant} size="sm" className="h-7 rounded-md px-2 text-xs" disabled>
        {label}
      </Button>
    );
  }

  return (
    <form id={formId} action={action}>
      <input type="hidden" name="email" value={email} />
      {hiddenInputs.map((i) => (
        <input key={i.name} type="hidden" name={i.name} value={i.value} />
      ))}
      <ConfirmSubmitDialog
        triggerLabel={label}
        triggerVariant={enabledVariant}
        triggerSize="sm"
        triggerClassName="h-7 rounded-md px-2 text-xs"
        title={title}
        description={description}
        confirmLabel={confirmLabel}
        confirmVariant={confirmVariant}
        confirmSize="sm"
        formId={formId}
      />
    </form>
  );
}

function PromptCopyPill({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.canDuplicateSystemPrompts === true;
  const label = `Prompt Copy: ${enabled ? 'Ja' : 'Nein'}`;

  return (
    <PillForm
      formId={`allow-syscopy-${formKey}`}
      action={adminSetCanDuplicateSystemPrompts}
      email={user.email}
      label={label}
      enabledVariant={enabled ? 'default' : 'outline'}
      hiddenInputs={[{ name: 'canDuplicateSystemPrompts', value: enabled ? 'false' : 'true' }]}
      title={enabled ? 'System-Prompt Kopie sperren?' : 'System-Prompt Kopie erlauben?'}
      description={
        enabled
          ? `Soll ${user.email} keine System-Prompts mehr duplizieren können?`
          : `Soll ${user.email} System-Prompts in die eigene Prompt-Bibliothek duplizieren dürfen?`
      }
      confirmLabel={enabled ? 'Sperren' : 'Erlauben'}
      confirmVariant={enabled ? 'outline' : 'default'}
    />
  );
}

function FullAccessPill({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.fullAccess === true;
  const label = enabled ? 'Zugriff entziehen' : 'Vollzugriff geben';

  return (
    <PillForm
      formId={`full-access-${formKey}`}
      action={adminSetUserFullAccess}
      email={user.email}
      label={label}
      enabledVariant={enabled ? 'outline' : 'default'}
      hiddenInputs={[{ name: 'fullAccess', value: enabled ? 'false' : 'true' }]}
      title={enabled ? 'Vollzugriff entziehen?' : 'Vollzugriff geben?'}
      description={
        enabled
          ? `Soll ${user.email} den Vollzugriff verlieren? (Wirksam nach Token-Refresh.)`
          : `Soll ${user.email} Vollzugriff bekommen? (Wirksam nach Token-Refresh.)`
      }
      confirmLabel={enabled ? 'Entziehen' : 'Freischalten'}
      confirmVariant={enabled ? 'destructive' : 'default'}
    />
  );
}

function BlockPill({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.blocked === true;
  const label = enabled ? 'Entblocken' : 'Blockieren';
  const disabled = user.isAdmin === true && !enabled;

  return (
    <PillForm
      formId={`block-${formKey}`}
      action={adminSetUserBlocked}
      email={user.email}
      label={disabled ? 'Admin (nicht blockierbar)' : label}
      enabledVariant={enabled ? 'outline' : 'destructive'}
      hiddenInputs={[{ name: 'blocked', value: enabled ? 'false' : 'true' }]}
      title={enabled ? 'User entblocken?' : 'User blockieren?'}
      description={
        disabled
          ? 'Admin-Accounts können nicht blockiert werden.'
          : enabled
            ? `Soll ${user.email} wieder Zugriff erhalten (so wie vorher)?`
            : `Soll ${user.email} sofort gesperrt werden? (Wirkt sofort für Firestore/Backend.)`
      }
      confirmLabel={enabled ? 'Entblocken' : 'Blockieren'}
      confirmVariant={enabled ? 'default' : 'destructive'}
      disabled={disabled}
    />
  );
}

function UserRow({ user, idx }: { user: AdminUserRow; idx: number }) {
  const name = user.displayName || '-';
  const email = user.email || '-';
  const lastLogin = formatIso(user.lastSignInAt);
  const uid = user.uid || null;
  const formKey = safeId(user.uid || user.email || stableRowKey(user));

  return (
    <div className="rounded-lg border bg-background shadow-sm p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 md:flex-1">
          <p className="text-sm font-medium text-foreground truncate">{name}</p>
          <p className="text-xs text-muted-foreground truncate">{email}</p>
          <p className="text-xs text-muted-foreground mt-2 md:hidden">Letzter Login: {lastLogin}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
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
              <Badge variant="outline" className="rounded-md px-2 py-0.5 text-xs font-semibold border-destructive text-destructive">
                Blocked
              </Badge>
            ) : null}
            {user.isAdmin ? (
              <Badge variant="secondary" className="rounded-md px-2 py-0.5 text-xs font-semibold">
                Admin
              </Badge>
            ) : null}
          </div>
        </div>

        <div className="hidden md:flex items-center gap-3 justify-end shrink-0">
          <span className="text-xs text-muted-foreground">{lastLogin}</span>
          <DetailsLink uid={uid} />
          <FullAccessPill user={user} formKey={formKey} />
          <BlockPill user={user} formKey={formKey} />
        </div>

        <div className="grid grid-cols-2 gap-2 md:hidden">
          {uid ? (
            <Button asChild variant="outline" size="default" className="w-full">
              <Link href={`/admin/users/${encodeURIComponent(uid)}`}>Details</Link>
            </Button>
          ) : (
            <Button variant="outline" size="default" className="w-full" disabled>
              Details
            </Button>
          )}

          <div className="flex items-center justify-end gap-2">
            <FullAccessPill user={user} formKey={formKey} />
            <BlockPill user={user} formKey={formKey} />
          </div>
        </div>

        {user.fullAccess ? (
          <div className="flex flex-wrap items-center gap-2 md:flex-1 md:justify-center">
            <PromptCopyPill user={user} formKey={formKey} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default async function AdminPage({ searchParams }: { searchParams: SearchParamsPromise }) {
  const isAdmin = await isAdminUser();
  if (!isAdmin) notFound();

  const sp = (await searchParams) || {};
  const sectionRaw = Array.isArray(sp.section) ? sp.section[0] : sp.section;
  const section = sectionRaw === 'prompts' ? 'prompts' : 'users';

  let blocked: AdminUserRow[] = [];
  let pending: AdminUserRow[] = [];
  let fullAccess: AdminUserRow[] = [];

  if (section === 'users') {
    const { users } = await listAdminUsers({ maxResults: 1000 });
    const split = splitUsers(users);
    blocked = split.blocked;
    pending = split.pending;
    fullAccess = split.fullAccess;
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 md:px-8 py-4">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" className="h-9 w-9" asChild>
              <Link href="/dashboard" aria-label="Zurück zum Dashboard">
                <ArrowLeft className="h-5 w-5" />
              </Link>
            </Button>
            <h1 className="text-lg font-semibold text-foreground">Admin</h1>
          </div>

          <nav className="mt-4 flex items-center gap-6">
            <Link
              href="/admin?section=users"
              className={cn(
                'flex items-center gap-2 pb-3 text-sm font-medium border-b-2 -mb-px transition-colors',
                section === 'users'
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              )}
            >
              <Users className="h-4 w-4" />
              <span className="md:hidden">Users</span>
              <span className="hidden md:inline">User Management</span>
            </Link>

            <Link
              href="/admin/access-codes"
              className="flex items-center gap-2 pb-3 text-sm font-medium border-b-2 -mb-px transition-colors border-transparent text-muted-foreground hover:text-foreground"
            >
              <Key className="h-4 w-4" />
              <span className="md:hidden">Codes</span>
              <span className="hidden md:inline">Access Codes</span>
            </Link>

            <Link
              href="/admin?section=prompts"
              className={cn(
                'flex items-center gap-2 pb-3 text-sm font-medium border-b-2 -mb-px transition-colors',
                section === 'prompts'
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              )}
            >
              <MessageSquareText className="h-4 w-4" />
              <span className="md:hidden">Prompts</span>
              <span className="hidden md:inline">Default Prompts</span>
            </Link>
          </nav>
        </div>
      </div>

      <div className="max-w-5xl mx-auto py-6 px-4 sm:px-6 md:px-8">
        {section === 'prompts' ? (
          <SystemPromptManager />
        ) : (
          <div className="space-y-10">
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold text-foreground">Gesperrte Nutzer</p>
                <CountBadge value={blocked.length} />
              </div>
              {blocked.length === 0 ? (
                <p className="text-sm text-muted-foreground">Keine gesperrten Nutzer.</p>
              ) : (
                <div className="space-y-2">
                  {blocked.map((user, idx) => (
                    <UserRow key={stableRowKey(user)} user={user} idx={idx} />
                  ))}
                </div>
              )}
            </section>

            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold text-foreground">Ausstehende Nutzer</p>
                <CountBadge value={pending.length} />
              </div>
              {pending.length === 0 ? (
                <p className="text-sm text-muted-foreground">Keine ausstehenden Nutzer.</p>
              ) : (
                <div className="space-y-2">
                  {pending.map((user, idx) => (
                    <UserRow key={stableRowKey(user)} user={user} idx={idx} />
                  ))}
                </div>
              )}
            </section>

            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold text-foreground">Freigeschaltete Nutzer</p>
                <CountBadge value={fullAccess.length} />
              </div>
              {fullAccess.length === 0 ? (
                <p className="text-sm text-muted-foreground">Noch keine freigeschalteten Nutzer.</p>
              ) : (
                <div className="space-y-2">
                  {fullAccess.map((user, idx) => (
                    <UserRow key={stableRowKey(user)} user={user} idx={idx} />
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
