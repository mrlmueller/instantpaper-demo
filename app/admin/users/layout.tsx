import type { ReactNode } from 'react';

export const dynamic = 'force-dynamic';

export default function AdminUsersLayout({ children }: { children: ReactNode }) {
  return <div className="mx-auto w-full max-w-5xl px-6 py-8">{children}</div>;
}

