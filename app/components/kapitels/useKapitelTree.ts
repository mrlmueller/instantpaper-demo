'use client';

import { useMemo, useState } from 'react';
import type { Kapitel } from '@/app/actions/kapitels';

export type TreeNode = {
  id: string;
  title: string;
  parentId: string | null;
  order: number;
  children: TreeNode[];
  kapitel: Kapitel;
};

export function useKapitelTree(kapitels: Kapitel[]) {
  // Build tree structure from flat list
  const rootNodes = useMemo(() => {
    // Create a map of all nodes
    const nodeMap = new Map<string, TreeNode>();

    // First pass: create all nodes
    kapitels.forEach((kapitel) => {
      nodeMap.set(kapitel.id, {
        id: kapitel.id,
        title: kapitel.title,
        parentId: kapitel.parentId || null,
        order: kapitel.order ?? 0,
        children: [],
        kapitel,
      });
    });

    // Second pass: link children to parents
    const roots: TreeNode[] = [];
    nodeMap.forEach((node) => {
      if (node.parentId === null) {
        roots.push(node);
      } else {
        const parent = nodeMap.get(node.parentId);
        if (parent) {
          parent.children.push(node);
        } else {
          // Orphaned node - treat as root
          roots.push(node);
        }
      }
    });

    // Sort children by order
    const sortByOrder = (nodes: TreeNode[]) => {
      nodes.sort((a, b) => a.order - b.order);
      nodes.forEach((node) => sortByOrder(node.children));
    };

    sortByOrder(roots);

    return roots;
  }, [kapitels]);

  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const expandAll = () => {
    const allIds = new Set<string>();
    const collectIds = (nodes: TreeNode[]) => {
      nodes.forEach((node) => {
        if (node.children.length > 0) {
          allIds.add(node.id);
          collectIds(node.children);
        }
      });
    };
    collectIds(rootNodes);
    setExpandedIds(allIds);
  };

  const collapseAll = () => {
    setExpandedIds(new Set());
  };

  return {
    rootNodes,
    expandedIds,
    toggleExpanded,
    expandAll,
    collapseAll,
  };
}
