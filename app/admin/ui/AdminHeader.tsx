'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowLeft } from 'lucide-react';

import { Button } from '@/components/ui/button';

function getHeaderConfig(pathname: string): { backHref: string; backLabel: string } {
  const path = String(pathname || '');
  if (path.startsWith('/admin/access-codes/') && path !== '/admin/access-codes') {
    return { backHref: '/admin/access-codes', backLabel: 'Zurück zu Access Codes' };
  }
  if (path.startsWith('/admin/users/')) {
    return { backHref: '/admin?section=users', backLabel: 'Zurück zum User Management' };
  }
  return { backHref: '/dashboard', backLabel: 'Zurück zum Dashboard' };
}

export function AdminHeader() {
  const pathname = usePathname();
  const { backHref, backLabel } = getHeaderConfig(pathname);

  return (
    <div className="flex items-center gap-3">
      <Button variant="ghost" size="icon" className="h-9 w-9" asChild>
        <Link href={backHref} aria-label={backLabel}>
          <ArrowLeft className="h-5 w-5" />
        </Link>
      </Button>
      <h1 className="text-lg font-semibold text-foreground">Admin</h1>
    </div>
  );
}
