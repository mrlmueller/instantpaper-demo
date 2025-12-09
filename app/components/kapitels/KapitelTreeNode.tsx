'use client';

import type { TreeNode } from './useKapitelTree';
import { KapitelTreeItem } from './KapitelTreeItem';

interface KapitelTreeNodeProps {
  node: TreeNode;
  level: number;
  expandedIds: Set<string>;
  activeId: string | null;
  onToggleExpand: (id: string) => void;
  onKapitelClick: (id: string, isExpanded: boolean) => void;
}

export function KapitelTreeNode({
  node,
  level,
  expandedIds,
  activeId,
  onToggleExpand,
  onKapitelClick,
}: KapitelTreeNodeProps) {
  const isExpanded = expandedIds.has(node.id);
  const hasChildren = node.children.length > 0;
  const isActive = activeId === node.id;

  const handleToggleExpand = () => {
    onToggleExpand(node.id);
  };

  const handleClick = () => {
    onKapitelClick(node.id, isExpanded);
  };

  return (
    <div>
      <KapitelTreeItem
        id={node.id}
        title={node.title}
        level={level}
        hasChildren={hasChildren}
        isExpanded={isExpanded}
        isActive={isActive}
        onToggleExpand={handleToggleExpand}
        onClick={handleClick}
      />
      {isExpanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <KapitelTreeNode
              key={child.id}
              node={child}
              level={level + 1}
              expandedIds={expandedIds}
              activeId={activeId}
              onToggleExpand={onToggleExpand}
              onKapitelClick={onKapitelClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}
