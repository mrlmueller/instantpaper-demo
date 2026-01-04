import Link from 'next/link';
import { notFound } from 'next/navigation';

import { ArrowLeft } from 'lucide-react';

import { AdminUserDetail } from '@/app/components/admin/AdminUserDetail';
import { isAdminUser } from '@/app/lib/api/adminServer';
import { Button } from '@/components/ui/button';

export const dynamic = 'force-dynamic';

export default async function AdminUserDetailPage({ params }: { params: Promise<{ uid: string }> }) {
  const isAdmin = await isAdminUser();
  if (!isAdmin) notFound();

  const { uid } = await params;
  if (!uid) notFound();

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto p-4 sm:p-8 space-y-6">
        <div className="flex items-center gap-3">
          <Button asChild variant="ghost" size="icon" className="h-9 w-9">
            <Link href="/admin?section=users" aria-label="Zurück">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <h1 className="text-lg font-semibold text-foreground truncate">User Details</h1>
        </div>

        <AdminUserDetail uid={uid} />
      </div>
    </div>
  );
}

