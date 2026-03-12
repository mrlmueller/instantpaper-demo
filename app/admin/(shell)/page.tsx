import type { ReactNode } from 'react';
import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ArrowUpRight, Ban, BarChart3, Check, Copy, FileText, Search, UserX } from 'lucide-react';

import {
  adminSetCanUsePdfScan,
  adminSetCanUseQuellenFinder,
  adminSetCanDuplicateSystemPrompts,
  adminSetCanViewUsageInsights,
  adminSetUserBlocked,
  adminSetUserFullAccess,
} from '@/app/actions/admin';
import { ConfirmSubmitDialog } from '@/app/components/admin/ConfirmSubmitDialog';
import { AdminCostsDashboard } from '@/app/components/admin/AdminCostsDashboard';
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

function formatCredits(value: number | null | undefined): string {
  if (value == null) return '-';
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString('de-DE', {
    minimumFractionDigits: 0,
    maximumFractionDigits: n % 1 === 0 ? 0 : 1,
  });
}

function stableRowKey(user: AdminUserRow): string {
  return `${user.uid || user.email || user.displayName || 'user'}-${user.createdAt || ''}-${user.lastSignInAt || ''}`;
}

function safeId(value: string): string {
  return String(value || '')
    .trim()
    .replace(/[^a-zA-Z0-9_-]/g, '_');
}

type ButtonVariant = 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link';
type ButtonSize = 'default' | 'sm' | 'lg' | 'icon' | 'icon-sm' | 'icon-lg';

function ActionForm({
  formId,
  action,
  email,
  hiddenInputs,
  triggerLabel,
  triggerAriaLabel,
  triggerChildren,
  triggerVariant,
  triggerSize,
  triggerClassName,
  title,
  description,
  confirmLabel,
  confirmVariant,
  confirmSize,
  confirmClassName,
  disabled,
}: {
  formId: string;
  action: (formData: FormData) => Promise<void>;
  email: string | null;
  hiddenInputs: Array<{ name: string; value: string }>;
  triggerLabel: string;
  triggerAriaLabel?: string;
  triggerChildren?: ReactNode;
  triggerVariant: ButtonVariant;
  triggerSize: ButtonSize;
  triggerClassName?: string;
  title: string;
  description?: string;
  confirmLabel: string;
  confirmVariant: ButtonVariant;
  confirmSize?: ButtonSize;
  confirmClassName?: string;
  disabled?: boolean;
}) {
  if (!email || disabled) {
    return (
      <Button variant={triggerVariant} size={triggerSize} className={triggerClassName} disabled>
        {triggerChildren ?? triggerLabel}
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
        triggerLabel={triggerLabel}
        triggerAriaLabel={triggerAriaLabel}
        triggerChildren={triggerChildren}
        triggerVariant={triggerVariant}
        triggerSize={triggerSize}
        triggerClassName={triggerClassName}
        title={title}
        description={description}
        confirmLabel={confirmLabel}
        confirmVariant={confirmVariant}
        confirmSize={confirmSize}
        confirmClassName={confirmClassName}
        formId={formId}
        disabled={disabled}
      />
    </form>
  );
}

function PromptCopyButton({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.canDuplicateSystemPrompts === true;
  return (
    <ActionForm
      formId={`allow-syscopy-${formKey}`}
      action={adminSetCanDuplicateSystemPrompts}
      email={user.email}
      hiddenInputs={[{ name: 'canDuplicateSystemPrompts', value: enabled ? 'false' : 'true' }]}
      triggerLabel="Prompt-Kopie"
      triggerAriaLabel={enabled ? 'Prompt-Kopie deaktivieren' : 'Prompt-Kopie aktivieren'}
      triggerChildren={
        <>
          <Copy className="h-4 w-4" />
          <span>Prompt-Kopie</span>
        </>
      }
      triggerVariant={enabled ? 'default' : 'outline'}
      triggerSize="sm"
      triggerClassName="h-8"
      title={enabled ? 'Prompt-Kopie deaktivieren?' : 'Prompt-Kopie aktivieren?'}
      description={
        enabled
          ? `Soll ${user.email} keine System-Prompts mehr duplizieren können?`
          : `Soll ${user.email} System-Prompts in die eigene Prompt-Bibliothek duplizieren dürfen?`
      }
      confirmLabel={enabled ? 'Deaktivieren' : 'Aktivieren'}
      confirmVariant={enabled ? 'outline' : 'default'}
      confirmSize="sm"
    />
  );
}

function UsageInsightsButton({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.canViewUsageInsights === true;
  return (
    <ActionForm
      formId={`usage-insights-${formKey}`}
      action={adminSetCanViewUsageInsights}
      email={user.email}
      hiddenInputs={[{ name: 'canViewUsageInsights', value: enabled ? 'false' : 'true' }]}
      triggerLabel="Usage Insights"
      triggerAriaLabel={enabled ? 'Usage Insights deaktivieren' : 'Usage Insights aktivieren'}
      triggerChildren={<BarChart3 className="h-4 w-4" />}
      triggerVariant="ghost"
      triggerSize="icon-sm"
      triggerClassName={cn(
        'h-8 w-8',
        enabled ? 'text-primary hover:bg-primary/10' : 'text-muted-foreground hover:text-foreground'
      )}
      title={enabled ? 'Usage Insights deaktivieren?' : 'Usage Insights aktivieren?'}
      description={
        enabled
          ? `Soll ${user.email} die Dashboard/Profil Statistiken nicht mehr sehen können?`
          : `Soll ${user.email} die Dashboard/Profil Statistiken sehen können?`
      }
      confirmLabel={enabled ? 'Deaktivieren' : 'Aktivieren'}
      confirmVariant={enabled ? 'outline' : 'default'}
      confirmSize="sm"
    />
  );
}

function QuellenFinderButton({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.canUseQuellenFinder === true;
  return (
    <ActionForm
      formId={`quellen-finder-${formKey}`}
      action={adminSetCanUseQuellenFinder}
      email={user.email}
      hiddenInputs={[{ name: 'canUseQuellenFinder', value: enabled ? 'false' : 'true' }]}
      triggerLabel="Quellen-Finder"
      triggerAriaLabel={enabled ? 'Quellen-Finder deaktivieren' : 'Quellen-Finder aktivieren'}
      triggerChildren={
        <>
          <Search className="h-4 w-4" />
          <span>Quellen-Finder</span>
        </>
      }
      triggerVariant={enabled ? 'default' : 'outline'}
      triggerSize="sm"
      triggerClassName="h-8"
      title={enabled ? 'Quellen-Finder deaktivieren?' : 'Quellen-Finder aktivieren?'}
      description={
        enabled
          ? `Soll ${user.email} Quellen-Finder und die zugehörigen Daten nicht mehr sehen oder benutzen können?`
          : `Soll ${user.email} Zugriff auf Quellen-Finder bekommen?`
      }
      confirmLabel={enabled ? 'Deaktivieren' : 'Aktivieren'}
      confirmVariant={enabled ? 'outline' : 'default'}
      confirmSize="sm"
    />
  );
}

function PdfScanButton({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.canUsePdfScan === true;
  return (
    <ActionForm
      formId={`pdf-scan-${formKey}`}
      action={adminSetCanUsePdfScan}
      email={user.email}
      hiddenInputs={[{ name: 'canUsePdfScan', value: enabled ? 'false' : 'true' }]}
      triggerLabel="PDF-Scan"
      triggerAriaLabel={enabled ? 'PDF-Scan deaktivieren' : 'PDF-Scan aktivieren'}
      triggerChildren={
        <>
          <FileText className="h-4 w-4" />
          <span>PDF-Scan</span>
        </>
      }
      triggerVariant={enabled ? 'default' : 'outline'}
      triggerSize="sm"
      triggerClassName="h-8"
      title={enabled ? 'PDF-Scan deaktivieren?' : 'PDF-Scan aktivieren?'}
      description={
        enabled
          ? `Soll ${user.email} PDF-Scan, Projekt-PDFs und die zugehörigen Daten nicht mehr sehen oder benutzen können?`
          : `Soll ${user.email} Zugriff auf PDF-Scan und die Projekt-PDFs bekommen?`
      }
      confirmLabel={enabled ? 'Deaktivieren' : 'Aktivieren'}
      confirmVariant={enabled ? 'outline' : 'default'}
      confirmSize="sm"
    />
  );
}

function FullAccessButton({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.fullAccess === true;
  const label = enabled ? 'Zugriff entziehen' : 'Freischalten';
  const triggerVariant: ButtonVariant = enabled ? 'ghost' : 'default';
  const triggerSize: ButtonSize = enabled ? 'icon-sm' : 'sm';

  const triggerChildren = enabled ? <UserX className="h-4 w-4" /> : (
    <>
      <Check className="h-4 w-4" />
      <span>Freischalten</span>
    </>
  );

  return (
    <ActionForm
      formId={`full-access-${formKey}`}
      action={adminSetUserFullAccess}
      email={user.email}
      hiddenInputs={[{ name: 'fullAccess', value: enabled ? 'false' : 'true' }]}
      triggerLabel={label}
      triggerAriaLabel={label}
      triggerChildren={triggerChildren}
      triggerVariant={triggerVariant}
      triggerSize={triggerSize}
      triggerClassName={cn(
        enabled ? 'h-8 w-8 text-muted-foreground hover:text-foreground' : 'h-8',
        enabled && user.isAdmin ? 'opacity-50 pointer-events-none' : ''
      )}
      title={enabled ? 'Vollzugriff entziehen?' : 'Vollzugriff geben?'}
      description={
        enabled
          ? `Soll ${user.email} den Vollzugriff verlieren? (Wirksam nach Token-Refresh.)`
          : `Soll ${user.email} Vollzugriff bekommen? (Wirksam nach Token-Refresh.)`
      }
      confirmLabel={enabled ? 'Entziehen' : 'Freischalten'}
      confirmVariant={enabled ? 'destructive' : 'default'}
      confirmSize="sm"
      disabled={user.isAdmin && enabled}
    />
  );
}

function BlockButton({ user, formKey }: { user: AdminUserRow; formKey: string }) {
  const enabled = user.blocked === true;
  const disabled = user.isAdmin === true && !enabled;
  const label = enabled ? 'Entsperren' : 'Blockieren';
  const triggerClassName = cn(
    'h-8 w-8',
    enabled ? 'text-emerald-700 hover:bg-emerald-500/10' : 'text-destructive hover:bg-destructive/10'
  );

  return (
    <ActionForm
      formId={`block-${formKey}`}
      action={adminSetUserBlocked}
      email={user.email}
      hiddenInputs={[{ name: 'blocked', value: enabled ? 'false' : 'true' }]}
      triggerLabel={label}
      triggerAriaLabel={disabled ? 'Admin (nicht blockierbar)' : label}
      triggerChildren={<Ban className="h-4 w-4" />}
      triggerVariant="ghost"
      triggerSize="icon-sm"
      triggerClassName={triggerClassName}
      title={enabled ? 'User entsperren?' : 'User blockieren?'}
      description={
        disabled
          ? 'Admin-Accounts können nicht blockiert werden.'
          : enabled
            ? `Soll ${user.email} wieder Zugriff erhalten (so wie vorher)?`
            : `Soll ${user.email} sofort gesperrt werden? (Wirkt sofort für Firestore/Backend.)`
      }
      confirmLabel={disabled ? 'OK' : enabled ? 'Entsperren' : 'Blockieren'}
      confirmVariant={disabled ? 'outline' : enabled ? 'default' : 'destructive'}
      confirmSize="sm"
      disabled={disabled}
    />
  );
}

function getSubscriptionPill(user: AdminUserRow): { label: string; className: string } {
  const sub = user.billingSubscription;
  const status = String(sub?.status || '').trim().toLowerCase();
  if (!status) {
    return { label: 'Kein Abo', className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20' };
  }

  if (status === 'active' || status === 'trialing') {
    if (sub?.cancelAtPeriodEnd) {
      return { label: 'Gekündigt', className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20' };
    }
    return { label: 'Aktiv', className: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/20' };
  }

  if (status === 'canceled') {
    return { label: 'Gekündigt', className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20' };
  }

  return { label: status, className: 'bg-muted/40 text-muted-foreground border-muted-foreground/20' };
}

function UserCard({ user }: { user: AdminUserRow }) {
  const name = user.displayName || '-';
  const email = user.email || '-';
  const uid = user.uid || null;
  const lastLogin = formatIso(user.lastSignInAt);
  const formKey = safeId(user.uid || user.email || stableRowKey(user));

  const isPending = user.blocked !== true && user.fullAccess !== true;
  const isBlocked = user.blocked === true;

  const availableCredits = user.billingBalance?.availableCredits;
  const creditsLabel = `${formatCredits(availableCredits)} Credits`;
  const subscription = getSubscriptionPill(user);

  return (
    <div
      className={cn(
        'rounded-xl border bg-background shadow-sm px-5 py-4',
        isBlocked && 'border-destructive/30 bg-destructive/5'
      )}
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-foreground truncate">{name}</p>
            {isBlocked ? (
              <Badge className="rounded-md border bg-destructive/10 text-destructive border-destructive/20 px-2 py-0.5 text-xs font-semibold">
                Gesperrt
              </Badge>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground truncate">{email}</p>
        </div>

        {!isPending ? (
          <div className="flex items-center justify-between gap-3 sm:flex-col sm:items-end sm:gap-1">
            <p className="text-sm font-semibold text-foreground">{creditsLabel}</p>
            <span className={cn('inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium', subscription.className)}>
              {subscription.label}
            </span>
          </div>
        ) : null}

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end sm:gap-3">
          <span className="text-xs text-muted-foreground">Login: {lastLogin}</span>
          <div className="flex flex-wrap items-center gap-2 sm:flex-nowrap">
            {isPending ? (
              <>
                <FullAccessButton user={user} formKey={formKey} />
                {uid ? (
                  <Button asChild variant="outline" size="sm" className="h-8">
                    <Link href={`/admin/users/${encodeURIComponent(uid)}`}>Details</Link>
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" className="h-8" disabled>
                    Details
                  </Button>
                )}
              </>
            ) : (
              <>
                <PromptCopyButton user={user} formKey={formKey} />
                <QuellenFinderButton user={user} formKey={formKey} />
                <PdfScanButton user={user} formKey={formKey} />
                <UsageInsightsButton user={user} formKey={formKey} />
                {user.fullAccess ? <FullAccessButton user={user} formKey={formKey} /> : null}
                <BlockButton user={user} formKey={formKey} />
                {uid ? (
                  <Button variant="ghost" size="icon-sm" className="h-8 w-8" asChild title="Details">
                    <Link href={`/admin/users/${encodeURIComponent(uid)}`}>
                      <ArrowUpRight className="h-4 w-4" />
                    </Link>
                  </Button>
                ) : (
                  <Button variant="ghost" size="icon-sm" className="h-8 w-8" disabled title="Details">
                    <ArrowUpRight className="h-4 w-4" />
                  </Button>
                )}
              </>
            )}
          </div>
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
  const section = sectionRaw === 'prompts' ? 'prompts' : sectionRaw === 'costs' ? 'costs' : 'users';

  if (section === 'prompts') {
    return <SystemPromptManager />;
  }

  if (section === 'costs') {
    return <AdminCostsDashboard />;
  }

  const { users } = await listAdminUsers({ maxResults: 1000 });

  const pending = users.filter((u) => u.blocked !== true && u.fullAccess !== true);
  const active = users.filter((u) => u.blocked !== true && u.fullAccess === true);
  const blocked = users.filter((u) => u.blocked === true);

  pending.sort((a, b) => asTime(b.lastSignInAt) - asTime(a.lastSignInAt) || asTime(b.createdAt) - asTime(a.createdAt));
  active.sort((a, b) => asTime(b.lastSignInAt) - asTime(a.lastSignInAt) || String(a.email || '').localeCompare(String(b.email || ''), 'de'));
  blocked.sort((a, b) => asTime(b.lastSignInAt) - asTime(a.lastSignInAt) || String(a.email || '').localeCompare(String(b.email || ''), 'de'));

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Ausstehende Anfragen ({pending.length})</h2>
        {pending.length === 0 ? (
          <div className="rounded-xl border bg-background shadow-sm p-5 text-sm text-muted-foreground">
            Keine ausstehenden Nutzer.
          </div>
        ) : (
          <div className="space-y-3">
            {pending.map((u) => (
              <UserCard key={stableRowKey(u)} user={u} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Freigeschaltete Nutzer ({active.length})</h2>
        {active.length === 0 ? (
          <div className="rounded-xl border bg-background shadow-sm p-5 text-sm text-muted-foreground">
            Noch keine freigeschalteten Nutzer.
          </div>
        ) : (
          <div className="space-y-3">
            {active.map((u) => (
              <UserCard key={stableRowKey(u)} user={u} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Gesperrte Nutzer ({blocked.length})</h2>
        {blocked.length === 0 ? (
          <div className="rounded-xl border bg-background shadow-sm p-5 text-sm text-muted-foreground">
            Keine gesperrten Nutzer.
          </div>
        ) : (
          <div className="space-y-3">
            {blocked.map((u) => (
              <UserCard key={stableRowKey(u)} user={u} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
