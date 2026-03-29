'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { DollarSign, Key, Menu, MessageSquareText, Users, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogClose, DialogContent, DialogTrigger } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

type NavItem = {
  key: 'users' | 'costs' | 'access-codes' | 'prompts';
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const NAV_ITEMS: NavItem[] = [
  { key: 'users', href: '/admin?section=users', label: 'User Management', icon: Users },
  { key: 'costs', href: '/admin?section=costs', label: 'Costs', icon: DollarSign },
  { key: 'access-codes', href: '/admin/access-codes', label: 'Access Codes', icon: Key },
  { key: 'prompts', href: '/admin?section=prompts', label: 'Default Prompts', icon: MessageSquareText },
];

function getActiveKey(pathname: string, section: string | null): NavItem['key'] {
  const path = String(pathname || '');
  if (path.startsWith('/admin/access-codes')) return 'access-codes';
  if (section === 'costs') return 'costs';
  if (section === 'prompts') return 'prompts';
  return 'users';
}

export function AdminMobileNav() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const section = searchParams.get('section');
  const activeKey = getActiveKey(pathname, section);

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="icon" className="h-9 w-9" aria-label="Admin Navigation">
          <Menu className="h-5 w-5" />
        </Button>
      </DialogTrigger>
      <DialogContent
        showCloseButton={false}
        className="top-0 left-0 h-dvh w-[85vw] max-w-[320px] translate-x-0 translate-y-0 rounded-none border-r p-0 md:hidden"
      >
        <div className="flex items-center justify-between border-b px-4 py-3">
          <span className="text-sm font-semibold text-foreground">Navigation</span>
          <DialogClose asChild>
            <Button variant="ghost" size="icon" className="h-9 w-9" aria-label="Close Navigation">
              <X className="h-5 w-5" />
            </Button>
          </DialogClose>
        </div>

        <nav aria-label="Admin Navigation" className="p-4">
          <ul className="space-y-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = item.key === activeKey;
              return (
                <li key={item.key}>
                  <DialogClose asChild>
                    <Link
                      href={item.href}
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'flex items-center gap-3 rounded-lg px-3.5 py-2.5 text-sm font-medium transition-colors',
                        active
                          ? 'bg-primary text-primary-foreground'
                          : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                      )}
                    >
                      <Icon className="h-4 w-4" />
                      <span>{item.label}</span>
                    </Link>
                  </DialogClose>
                </li>
              );
            })}
          </ul>
        </nav>
      </DialogContent>
    </Dialog>
  );
}
