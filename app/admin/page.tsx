import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ArrowLeft, MessageSquareText, Shield, Users } from 'lucide-react';

import { adminSetAllowPlatformKey, adminSetCanDuplicateSystemPrompts, adminSetUserApproval } from '@/app/actions/admin';
import { ConfirmSubmitDialog } from '@/app/components/admin/ConfirmSubmitDialog';
import { SystemPromptManager } from '@/app/components/admin/SystemPromptManager';
import { isAdminUser, listAdminUsers, type AdminUserRow } from '@/app/lib/api/adminServer';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
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
    return new Date(iso).toLocaleString('de-DE');
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

function stableRowKey(u: AdminUserRow): string {
  return `${u.email || u.displayName || 'user'}-${u.createdAt || ''}-${u.lastSignInAt || ''}`;
}

function PlatformKeyCell({ user, formId }: { user: AdminUserRow; formId: string }) {
  const label = user.allowPlatformKey ? 'allowed' : 'blocked';
  return (
    <div className="flex items-center gap-2">
      {user.allowPlatformKey ? (
        <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">{label}</Badge>
      ) : (
        <Badge variant="outline">{label}</Badge>
      )}
      {user.email ? (
        <form id={formId} action={adminSetAllowPlatformKey} className="inline">
          <input type="hidden" name="email" value={user.email} />
          <input type="hidden" name="allowPlatformKey" value={user.allowPlatformKey ? 'false' : 'true'} />
          <ConfirmSubmitDialog
            triggerLabel={user.allowPlatformKey ? 'Sperren' : 'Erlauben'}
            triggerVariant="outline"
            title={user.allowPlatformKey ? 'Plattform-Key sperren?' : 'Plattform-Key erlauben?'}
            description={
              user.allowPlatformKey
                ? `Plattform OpenAI-Key für ${user.email} deaktivieren?`
                : `Plattform OpenAI-Key für ${user.email} aktivieren? (Kosten laufen dann über deinen Key.)`
            }
            confirmLabel={user.allowPlatformKey ? 'Sperren' : 'Erlauben'}
            confirmVariant={user.allowPlatformKey ? 'outline' : 'default'}
            formId={formId}
          />
        </form>
      ) : null}
    </div>
  );
}

function SystemPromptCopyCell({ user, formId }: { user: AdminUserRow; formId: string }) {
  const label = user.canDuplicateSystemPrompts ? 'allowed' : 'blocked';
  return (
    <div className="flex items-center gap-2">
      {user.canDuplicateSystemPrompts ? (
        <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">{label}</Badge>
      ) : (
        <Badge variant="outline">{label}</Badge>
      )}
      {user.email ? (
        <form id={formId} action={adminSetCanDuplicateSystemPrompts} className="inline">
          <input type="hidden" name="email" value={user.email} />
          <input
            type="hidden"
            name="canDuplicateSystemPrompts"
            value={user.canDuplicateSystemPrompts ? 'false' : 'true'}
          />
          <ConfirmSubmitDialog
            triggerLabel={user.canDuplicateSystemPrompts ? 'Sperren' : 'Erlauben'}
            triggerVariant="outline"
            title={user.canDuplicateSystemPrompts ? 'System-Prompt Kopie sperren?' : 'System-Prompt Kopie erlauben?'}
            description={
              user.canDuplicateSystemPrompts
                ? `Soll ${user.email} keine System-Prompts mehr duplizieren k”nnen? (Wirksam nach neuem Login.)`
                : `Soll ${user.email} System-Prompts in die eigene Prompt-Bibliothek duplizieren drfen? (Wirksam nach neuem Login.)`
            }
            confirmLabel={user.canDuplicateSystemPrompts ? 'Sperren' : 'Erlauben'}
            confirmVariant={user.canDuplicateSystemPrompts ? 'outline' : 'default'}
            formId={formId}
          />
        </form>
      ) : null}
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
      <div className="flex h-screen">
        <div className="w-72 border-r bg-muted/10 flex flex-col shrink-0">
          <div className="p-6 border-b">
            <div className="flex items-center gap-3">
              <Button variant="ghost" size="icon" className="h-9 w-9" asChild>
                <Link href="/dashboard" aria-label="Zurück zum Dashboard">
                  <ArrowLeft className="h-5 w-5" />
                </Link>
              </Button>
              <h1 className="text-lg font-semibold text-foreground">Admin</h1>
            </div>
          </div>

          <div className="p-6 border-b">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                <Shield className="h-5 w-5 text-primary" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground truncate">InstantPaper</p>
                <p className="text-xs text-muted-foreground truncate">Admin Panel</p>
              </div>
            </div>
          </div>

          <div className="p-4 flex-1">
            <nav className="space-y-1">
              <Link
                href="/admin?section=users"
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  section === 'users'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                )}
              >
                <Users className="h-4 w-4" />
                User Management
              </Link>
              <Link
                href="/admin?section=prompts"
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  section === 'prompts'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                )}
              >
                <MessageSquareText className="h-4 w-4" />
                Default Prompts
              </Link>
            </nav>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {section === 'prompts' ? (
            <div className="max-w-5xl mx-auto py-8 px-8 space-y-8">
              <div className="space-y-1">
                <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                  <MessageSquareText className="h-5 w-5 text-muted-foreground" />
                  Default Prompt Manager
                </h2>
                <p className="text-sm text-muted-foreground">
                  System-Prompts sind server-only und werden nicht an Clients ausgeliefert.
                </p>
              </div>
              <SystemPromptManager />
            </div>
          ) : (
            <div className="max-w-5xl mx-auto py-8 px-8 space-y-8">
              <div className="space-y-1">
                <h2 className="text-lg font-semibold text-foreground flex items-center gap-2">
                  <Users className="h-5 w-5 text-muted-foreground" />
                  User Management
                </h2>
              <p className="text-sm text-muted-foreground">
                Pending Users sind noch nicht freigeschaltet. Approved Users können die App verwenden.
              </p>
            </div>

            <Card className="p-6 border-l-4 border-amber-400">
              <div className="flex items-start justify-between gap-4 mb-6">
                <div className="min-w-0">
                  <h3 className="text-sm font-medium text-foreground flex items-center gap-2">
                    <Badge variant="secondary">pending</Badge>
                    Pending Users
                  </h3>
                  <p className="text-xs text-muted-foreground mt-1">
                    Accounts ohne `approved` Claim. Nach dem Approve müssen Nutzer ggf. neu einloggen.
                  </p>
                </div>
                <div className="text-sm text-muted-foreground shrink-0">{pending.length} Nutzer</div>
              </div>

              {pending.length === 0 ? (
                <p className="text-sm text-muted-foreground">Keine offenen Accounts gefunden.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>E-Mail</TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead>Letzter Login</TableHead>
                      <TableHead className="text-right">Aktionen</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pending.map((u, idx) => (
                      <TableRow key={stableRowKey(u)}>
                        <TableCell className="font-medium">{u.email || '-'}</TableCell>
                        <TableCell>{u.displayName || '-'}</TableCell>
                        <TableCell>{formatIso(u.lastSignInAt)}</TableCell>
                        <TableCell className="text-right">
                          {u.email ? (
                            <form id={`pending-approve-${idx}`} action={adminSetUserApproval} className="inline">
                              <input type="hidden" name="email" value={u.email} />
                              <input type="hidden" name="approved" value="true" />
                              <ConfirmSubmitDialog
                                triggerLabel="Approve"
                                triggerVariant="default"
                                title="User freischalten?"
                                description={`Möchtest du ${u.email} freischalten?`}
                                confirmLabel="Approve"
                                confirmVariant="default"
                                formId={`pending-approve-${idx}`}
                              />
                            </form>
                          ) : (
                            <span className="text-sm text-muted-foreground">-</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Card>

            <Card className="p-6 border-l-4 border-emerald-500">
              <div className="flex items-start justify-between gap-4 mb-6">
                <div className="min-w-0">
                  <h3 className="text-sm font-medium text-foreground flex items-center gap-2">
                    <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">approved</Badge>
                    Approved Users
                  </h3>
                  <p className="text-xs text-muted-foreground mt-1">Diese Nutzer können die App verwenden.</p>
                </div>
                <div className="text-sm text-muted-foreground shrink-0">{approved.length} Nutzer</div>
              </div>

              {approved.length === 0 ? (
                <p className="text-sm text-muted-foreground">Noch keine freigeschalteten Accounts.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>E-Mail</TableHead>
                      <TableHead>Name</TableHead>
                      <TableHead>Plattform-Key</TableHead>
                      <TableHead>System-Prompt Copy</TableHead>
                      <TableHead>Letzter Login</TableHead>
                      <TableHead className="text-right">Aktionen</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {approved.map((u, idx) => (
                      <TableRow key={stableRowKey(u)}>
                        <TableCell className="font-medium">{u.email || '-'}</TableCell>
                        <TableCell>{u.displayName || '-'}</TableCell>
                        <TableCell>
                          <PlatformKeyCell user={u} formId={`approved-platform-${idx}`} />
                        </TableCell>
                        <TableCell>
                          <SystemPromptCopyCell user={u} formId={`approved-syscopy-${idx}`} />
                        </TableCell>
                        <TableCell>{formatIso(u.lastSignInAt)}</TableCell>
                        <TableCell className="text-right">
                          {u.email ? (
                            <form id={`approved-revoke-${idx}`} action={adminSetUserApproval} className="inline">
                              <input type="hidden" name="email" value={u.email} />
                              <input type="hidden" name="approved" value="false" />
                              <ConfirmSubmitDialog
                                triggerLabel="Revoke"
                                triggerVariant="outline"
                                title="User sperren?"
                                description={`Möchtest du ${u.email} sperren?`}
                                confirmLabel="Revoke"
                                confirmVariant="destructive"
                                formId={`approved-revoke-${idx}`}
                              />
                            </form>
                          ) : (
                            <span className="text-sm text-muted-foreground">-</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Card>
          </div>
          )}
        </div>
      </div>
    </div>
  );
}
