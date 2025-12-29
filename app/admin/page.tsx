import { notFound } from 'next/navigation';

import { adminSetUserApproval } from '@/app/actions/admin';
import { isAdminUser, listAdminUsers, type AdminUserRow } from '@/app/lib/api/adminServer';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';

export const dynamic = 'force-dynamic';

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

export default async function AdminPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>> | Record<string, string | string[] | undefined>;
}) {
  const isAdmin = await isAdminUser();
  if (!isAdmin) notFound();

  const sp = await Promise.resolve(searchParams ?? {});
  const qRaw = sp.q;
  const q = typeof qRaw === 'string' ? qRaw.trim() : '';

  const { users } = await listAdminUsers({ query: q || undefined, maxResults: 1000 });
  const { pending, approved } = splitUsers(users);

  return (
    <div className="min-h-screen bg-background p-6">
      <div className="mx-auto w-full max-w-5xl space-y-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Admin</h1>
          <p className="text-sm text-muted-foreground">Nur für Administratoren.</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>User freischalten</CardTitle>
            <CardDescription>E-Mail eingeben und Account freischalten oder sperren.</CardDescription>
          </CardHeader>
          <CardContent>
            <form action={adminSetUserApproval} className="grid gap-3 sm:grid-cols-[1fr_200px_auto] sm:items-end">
              <div className="space-y-1">
                <Label htmlFor="email">E-Mail</Label>
                <Input id="email" name="email" type="email" placeholder="user@gmail.com" required />
              </div>
              <div className="space-y-1">
                <Label htmlFor="approved">Status</Label>
                <select
                  id="approved"
                  name="approved"
                  defaultValue="true"
                  className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  <option value="true">approved</option>
                  <option value="false">revoked</option>
                </select>
              </div>
              <Button type="submit">Speichern</Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Suche</CardTitle>
            <CardDescription>Filtert nach E-Mail oder Anzeigename (Firebase Auth).</CardDescription>
          </CardHeader>
          <CardContent>
            <form method="get" className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <div className="space-y-1">
                <Label htmlFor="q">Query</Label>
                <Input id="q" name="q" defaultValue={q} placeholder="z.B. gmail" />
              </div>
              <Button type="submit" variant="outline">
                Anwenden
              </Button>
            </form>
          </CardContent>
        </Card>

        <Separator />

        <Card>
          <CardHeader>
            <CardTitle>
              Pending ({pending.length})
            </CardTitle>
            <CardDescription>Accounts ohne `approved` Claim (oder `approved=false`).</CardDescription>
          </CardHeader>
          <CardContent>
            {pending.length === 0 ? (
              <p className="text-sm text-muted-foreground">Keine offenen Accounts gefunden.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>E-Mail</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Letzter Login</TableHead>
                    <TableHead>Erstellt</TableHead>
                    <TableHead className="text-right">Aktion</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pending.map((u) => (
                    <TableRow key={`${u.email || u.displayName || 'user'}-${u.createdAt || ''}-${u.lastSignInAt || ''}`}>
                      <TableCell className="font-medium">{u.email || '-'}</TableCell>
                      <TableCell>{u.displayName || '-'}</TableCell>
                      <TableCell>
                        <Badge variant="secondary">pending</Badge>
                      </TableCell>
                      <TableCell>{formatIso(u.lastSignInAt)}</TableCell>
                      <TableCell>{formatIso(u.createdAt)}</TableCell>
                      <TableCell className="text-right">
                        {u.email ? (
                          <form action={adminSetUserApproval} className="inline">
                            <input type="hidden" name="email" value={u.email} />
                            <input type="hidden" name="approved" value="true" />
                            <Button type="submit" size="sm">
                              Approve
                            </Button>
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
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              Approved ({approved.length})
            </CardTitle>
            <CardDescription>Freigeschaltete Accounts.</CardDescription>
          </CardHeader>
          <CardContent>
            {approved.length === 0 ? (
              <p className="text-sm text-muted-foreground">Noch keine freigeschalteten Accounts.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>E-Mail</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Letzter Login</TableHead>
                    <TableHead>Erstellt</TableHead>
                    <TableHead className="text-right">Aktion</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {approved.map((u) => (
                    <TableRow key={`${u.email || u.displayName || 'user'}-${u.createdAt || ''}-${u.lastSignInAt || ''}`}>
                      <TableCell className="font-medium">{u.email || '-'}</TableCell>
                      <TableCell>{u.displayName || '-'}</TableCell>
                      <TableCell>
                        <Badge>approved</Badge>
                      </TableCell>
                      <TableCell>{formatIso(u.lastSignInAt)}</TableCell>
                      <TableCell>{formatIso(u.createdAt)}</TableCell>
                      <TableCell className="text-right">
                        {u.email ? (
                          <form action={adminSetUserApproval} className="inline">
                            <input type="hidden" name="email" value={u.email} />
                            <input type="hidden" name="approved" value="false" />
                            <Button type="submit" size="sm" variant="outline">
                              Revoke
                            </Button>
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
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
