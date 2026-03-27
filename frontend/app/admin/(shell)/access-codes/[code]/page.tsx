import { notFound } from 'next/navigation';

import { AdminAccessCodeDetail } from '../ui/AdminAccessCodeDetail';
import { isAdminUser } from '@/app/lib/api/adminServer';

export const dynamic = 'force-dynamic';

export default async function AdminAccessCodeDetailPage({ params }: { params: Promise<{ code: string }> }) {
  const isAdmin = await isAdminUser();
  if (!isAdmin) notFound();

  const { code } = await params;
  if (!code) notFound();

  return <AdminAccessCodeDetail code={code} />;
}
