import { notFound } from 'next/navigation';

import { AdminUserDetail } from '@/app/components/admin/AdminUserDetail';
import { isAdminUser } from '@/app/lib/api/adminServer';

export const dynamic = 'force-dynamic';

export default async function AdminUserDetailPage({ params }: { params: Promise<{ uid: string }> }) {
  const isAdmin = await isAdminUser();
  if (!isAdmin) notFound();

  const { uid } = await params;
  if (!uid) notFound();

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto p-4 sm:p-8">
        <AdminUserDetail uid={uid} />
      </div>
    </div>
  );
}

