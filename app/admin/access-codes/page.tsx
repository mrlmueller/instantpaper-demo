import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ArrowLeft, Key, MessageSquareText, Users } from 'lucide-react';

import { AdminAccessCodes } from './ui/AdminAccessCodes';
import { isAdminUser } from '@/app/lib/api/adminServer';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export const dynamic = 'force-dynamic';

export default async function AdminAccessCodesPage() {
  const isAdmin = await isAdminUser();
  if (!isAdmin) notFound();

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
                'border-transparent text-muted-foreground hover:text-foreground'
              )}
            >
              <Users className="h-4 w-4" />
              <span className="md:hidden">Users</span>
              <span className="hidden md:inline">User Management</span>
            </Link>

            <Link
              href="/admin/access-codes"
              className={cn(
                'flex items-center gap-2 pb-3 text-sm font-medium border-b-2 -mb-px transition-colors',
                'border-primary text-foreground'
              )}
            >
              <Key className="h-4 w-4" />
              <span className="md:hidden">Codes</span>
              <span className="hidden md:inline">Access Codes</span>
            </Link>

            <Link
              href="/admin?section=prompts"
              className={cn(
                'flex items-center gap-2 pb-3 text-sm font-medium border-b-2 -mb-px transition-colors',
                'border-transparent text-muted-foreground hover:text-foreground'
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
        <AdminAccessCodes />
      </div>
    </div>
  );
}

