'use client';

import { ChevronRight, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface KapitelTreeItemProps {
  id: string;
  title: string;
  level: number;
  hasChildren: boolean;
  isExpanded: boolean;
  isActive: boolean;
  onToggleExpand: () => void;
  onClick: () => void;
}

export function KapitelTreeItem({
  id,
  title,
  level,
  hasChildren,
  isExpanded,
  isActive,
  onToggleExpand,
  onClick,
}: KapitelTreeItemProps) {
  const handleClick = () => {
    if (hasChildren) {
      onToggleExpand();
    }
    onClick();
  };

  return (
    <Button
      variant="ghost"
      className={`
        w-full justify-start text-left font-normal
        ${isActive ? 'bg-sidebar-primary text-sidebar-primary-foreground' : 'hover:bg-sidebar-accent'}
        transition-colors
      `}
      style={{ paddingLeft: `${level * 16 + 8}px` }}
      onClick={handleClick}
      title={title}
    >
      {hasChildren ? (
        isExpanded ? (
          <ChevronDown className="h-4 w-4 mr-1 flex-shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 mr-1 flex-shrink-0" />
        )
      ) : (
        <span className="w-4 mr-1" />
      )}
      <span className="flex-1 truncate">{title}</span>
    </Button>
  );
}
