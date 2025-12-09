'use client';

import { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { Kapitel } from '@/app/actions/kapitels';
import { useKapitelTree } from './useKapitelTree';
import { KapitelTreeNode } from './KapitelTreeNode';

interface KapitelTOCProps {
  kapitels: Kapitel[];
  activeKapitelId: string | null;
  onKapitelClick: (kapitelId: string, isExpanded: boolean) => void;
}

export function KapitelTOC({
  kapitels,
  activeKapitelId,
  onKapitelClick,
}: KapitelTOCProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const { rootNodes, expandedIds, toggleExpanded } = useKapitelTree(kapitels);

  if (kapitels.length === 0) {
    return null;
  }

  if (isCollapsed) {
    return (
      <div className="hidden lg:block fixed left-0 top-16 h-[calc(100vh-4rem)] bg-sidebar border-r border-sidebar-border w-12 transition-all duration-300">
        <Button
          variant="ghost"
          size="sm"
          className="w-full h-10"
          onClick={() => setIsCollapsed(false)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    );
  }

  return (
    <div className="hidden lg:block fixed left-0 top-16 h-[calc(100vh-4rem)] bg-sidebar border-r border-sidebar-border w-64 transition-all duration-300">
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-sidebar-border">
          <h2 className="text-lg font-semibold text-sidebar-foreground">Kapiteln</h2>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsCollapsed(true)}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto p-2">
          {rootNodes.map((node) => (
            <KapitelTreeNode
              key={node.id}
              node={node}
              level={0}
              expandedIds={expandedIds}
              activeId={activeKapitelId}
              onToggleExpand={toggleExpanded}
              onKapitelClick={onKapitelClick}
            />
          ))}
        </nav>
      </div>
    </div>
  );
}
