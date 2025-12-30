'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/app/components/providers/AuthProvider';
import { DashboardSkeleton } from '@/app/components/dashboard/DashboardSkeleton';

type DashboardAuthWrapperProps = {
  initialShowQuellenPanel?: boolean;
};

export function DashboardAuthWrapper({ initialShowQuellenPanel = false }: DashboardAuthWrapperProps) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;

    if (user) {
      // Auth succeeded - refresh the page to fetch data with valid token
      router.refresh();
    } else {
      // Auth failed - no valid refresh token, redirect to login
      router.replace('/login?reason=session-expired');
    }
  }, [user, loading, router]);

  // Show loading skeleton while waiting for auth to complete
  return <DashboardSkeleton showQuellenPanel={initialShowQuellenPanel} />;
}
