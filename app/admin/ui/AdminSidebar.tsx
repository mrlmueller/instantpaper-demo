'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { Key, MessageSquareText, Users } from 'lucide-react';

import { cn } from '@/lib/utils';

type NavItem = {
  key: 'users' | 'access-codes' | 'prompts';
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const NAV_ITEMS: NavItem[] = [
  { key: 'users', href: '/admin?section=users', label: 'User Management', icon: Users },
  { key: 'access-codes', href: '/admin/access-codes', label: 'Access Codes', icon: Key },
  { key: 'prompts', href: '/admin?section=prompts', label: 'Default Prompts', icon: MessageSquareText },
];

function getActiveKey(pathname: string, section: string | null): NavItem['key'] {
  const path = String(pathname || '');
  if (path.startsWith('/admin/access-codes')) return 'access-codes';
  if (section === 'prompts') return 'prompts';
  return 'users';
}

export function AdminSidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const section = searchParams.get('section');
  const activeKey = getActiveKey(pathname, section);

  return (
    <nav aria-label="Admin Navigation">
      <ul className="space-y-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = item.key === activeKey;
          return (
            <li key={item.key}>
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-3 rounded-lg px-3.5 py-2.5 text-sm font-medium transition-colors',
                  active
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'
                )}
              >
                <Icon className="h-4 w-4" />
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
