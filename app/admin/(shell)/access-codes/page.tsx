import { notFound } from 'next/navigation';

import { AdminAccessCodes } from './ui/AdminAccessCodes';
import { isAdminUser } from '@/app/lib/api/adminServer';

export const dynamic = 'force-dynamic';

export default async function AdminAccessCodesPage() {
  const isAdmin = await isAdminUser();
  if (!isAdmin) notFound();

  return <AdminAccessCodes />;
}

