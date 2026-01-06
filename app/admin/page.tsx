import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ArrowLeft, Check, MessageSquareText, Users, X } from 'lucide-react';

import { adminSetAllowPlatformKey, adminSetCanDuplicateSystemPrompts, adminSetUserApproval } from '@/app/actions/admin';
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
  const pending = users.filter((u) => !u.approved);
  const approved = users.filter((u) => u.approved);

  pending.sort((a, b) => asTime(b.lastSignInAt) - asTime(a.lastSignInAt) || asTime(b.createdAt) - asTime(a.createdAt));
  approved.sort((a, b) => String(a.email || '').localeCompare(String(b.email || ''), 'de'));

  return { pending, approved };
}

function stableRowKey(user: AdminUserRow): string {
  return `${user.uid || user.email || user.displayName || 'user'}-${user.createdAt || ''}-${user.lastSignInAt || ''}`;
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
}: {
  formId: string;
  action: (formData: FormData) => Promise<void>;
  email: string | null;
  hiddenInputs: Array<{ name: string; value: string }>;
  label: string;
  enabledVariant: 'default' | 'outline';
  title: string;
  description: string;
  confirmLabel: string;
  confirmVariant: 'default' | 'outline' | 'destructive';
}) {
  if (!email) {
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

function PlatformKeyPill({ user, idx }: { user: AdminUserRow; idx: number }) {
  const enabled = user.allowPlatformKey === true;
  const label = `Platform Key: ${enabled ? 'Ja' : 'Nein'}`;

  return (
    <PillForm
      formId={`allow-platform-${idx}`}
      action={adminSetAllowPlatformKey}
      email={user.email}
      label={label}
      enabledVariant={enabled ? 'default' : 'outline'}
      hiddenInputs={[{ name: 'allowPlatformKey', value: enabled ? 'false' : 'true' }]}
      title={enabled ? 'Platform Key sperren?' : 'Platform Key erlauben?'}
      description={
        enabled
          ? `Plattform OpenAI-Key für ${user.email} deaktivieren?`
          : `Plattform OpenAI-Key für ${user.email} aktivieren? (Kosten laufen dann über deinen Key.)`
      }
      confirmLabel={enabled ? 'Sperren' : 'Erlauben'}
      confirmVariant={enabled ? 'outline' : 'default'}
    />
  );
}

function PromptCopyPill({ user, idx }: { user: AdminUserRow; idx: number }) {
  const enabled = user.canDuplicateSystemPrompts === true;
  const label = `Prompt Copy: ${enabled ? 'Ja' : 'Nein'}`;

  return (
    <PillForm
      formId={`allow-syscopy-${idx}`}
      action={adminSetCanDuplicateSystemPrompts}
      email={user.email}
      label={label}
      enabledVariant={enabled ? 'default' : 'outline'}
      hiddenInputs={[{ name: 'canDuplicateSystemPrompts', value: enabled ? 'false' : 'true' }]}
      title={enabled ? 'System-Prompt Kopie sperren?' : 'System-Prompt Kopie erlauben?'}
      description={
        enabled
          ? `Soll ${user.email} keine System-Prompts mehr duplizieren können? (Wirksam nach neuem Login.)`
          : `Soll ${user.email} System-Prompts in die eigene Prompt-Bibliothek duplizieren dürfen? (Wirksam nach neuem Login.)`
      }
      confirmLabel={enabled ? 'Sperren' : 'Erlauben'}
      confirmVariant={enabled ? 'outline' : 'default'}
    />
  );
}

function UserRow({
  user,
  idx,
  kind,
}: {
  user: AdminUserRow;
  idx: number;
  kind: 'pending' | 'approved';
}) {
  const name = user.displayName || '-';
  const email = user.email || '-';
  const lastLogin = formatIso(user.lastSignInAt);
  const uid = user.uid || null;

  const actionLabel = kind === 'pending' ? 'Freischalten' : 'Sperren';
  const actionIcon = kind === 'pending' ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />;
  const triggerVariant = kind === 'pending' ? 'default' : 'outline';
  const confirmVariant = kind === 'pending' ? 'default' : 'destructive';
  const approvalFormIdDesktop = `${kind}-approval-desktop-${idx}`;
  const approvalFormIdMobile = `${kind}-approval-mobile-${idx}`;

  return (
    <div className="rounded-lg border bg-background shadow-sm p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 md:flex-1">
          <p className="text-sm font-medium text-foreground truncate">{name}</p>
          <p className="text-xs text-muted-foreground truncate">{email}</p>
          <p className="text-xs text-muted-foreground mt-2 md:hidden">Letzter Login: {lastLogin}</p>
        </div>

        {kind === 'approved' ? (
          <div className="flex flex-wrap items-center gap-2 md:flex-1 md:justify-center">
            <PlatformKeyPill user={user} idx={idx} />
            <PromptCopyPill user={user} idx={idx} />
          </div>
        ) : null}

        <div className="hidden md:flex items-center gap-3 justify-end shrink-0">
          <span className="text-xs text-muted-foreground">{lastLogin}</span>
          <DetailsLink uid={uid} />

          {user.email ? (
            <form id={approvalFormIdDesktop} action={adminSetUserApproval} className="inline">
              <input type="hidden" name="email" value={user.email} />
              <input type="hidden" name="approved" value={kind === 'pending' ? 'true' : 'false'} />
              <ConfirmSubmitDialog
                triggerLabel={actionLabel}
                triggerVariant={triggerVariant}
                triggerSize="default"
                triggerChildren={
                  <>
                    {actionIcon}
                    <span>{actionLabel}</span>
                  </>
                }
                title={kind === 'pending' ? 'User freischalten?' : 'User sperren?'}
                description={
                  kind === 'pending'
                    ? `Möchtest du ${user.email} freischalten?`
                    : `Möchtest du ${user.email} sperren?`
                }
                confirmLabel={actionLabel}
                confirmVariant={confirmVariant}
                formId={approvalFormIdDesktop}
              />
            </form>
          ) : (
            <Button variant={triggerVariant} size="default" disabled className="opacity-50">
              {actionIcon}
              <span>{actionLabel}</span>
            </Button>
          )}
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

          {user.email ? (
            <form id={approvalFormIdMobile} action={adminSetUserApproval} className="w-full">
              <input type="hidden" name="email" value={user.email} />
              <input type="hidden" name="approved" value={kind === 'pending' ? 'true' : 'false'} />
              <ConfirmSubmitDialog
                triggerLabel={actionLabel}
                triggerVariant={triggerVariant}
                triggerSize="default"
                triggerClassName="w-full"
                triggerChildren={
                  <>
                    {actionIcon}
                    <span>{actionLabel}</span>
                  </>
                }
                title={kind === 'pending' ? 'User freischalten?' : 'User sperren?'}
                description={
                  kind === 'pending'
                    ? `Möchtest du ${user.email} freischalten?`
                    : `Möchtest du ${user.email} sperren?`
                }
                confirmLabel={actionLabel}
                confirmVariant={confirmVariant}
                formId={approvalFormIdMobile}
              />
            </form>
          ) : (
            <Button variant={triggerVariant} size="default" className="w-full opacity-50" disabled>
              {actionIcon}
              <span>{actionLabel}</span>
            </Button>
          )}
        </div>
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

  let pending: AdminUserRow[] = [];
  let approved: AdminUserRow[] = [];

  if (section === 'users') {
    const { users } = await listAdminUsers({ maxResults: 1000 });
    const split = splitUsers(users);
    pending = split.pending;
    approved = split.approved;
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
                <p className="text-sm font-semibold text-foreground">Ausstehende Nutzer</p>
                <CountBadge value={pending.length} />
              </div>

              {pending.length === 0 ? (
                <p className="text-sm text-muted-foreground">Keine ausstehenden Nutzer.</p>
              ) : (
                <div className="space-y-2">
                  {pending.map((user, idx) => (
                    <UserRow key={stableRowKey(user)} user={user} idx={idx} kind="pending" />
                  ))}
                </div>
              )}
            </section>

            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <p className="text-sm font-semibold text-foreground">Freigeschaltete Nutzer</p>
                <CountBadge value={approved.length} />
              </div>

              {approved.length === 0 ? (
                <p className="text-sm text-muted-foreground">Noch keine freigeschalteten Nutzer.</p>
              ) : (
                <div className="space-y-2">
                  {approved.map((user, idx) => (
                    <UserRow key={stableRowKey(user)} user={user} idx={idx} kind="approved" />
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

