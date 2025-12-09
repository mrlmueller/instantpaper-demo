'use client';

import { useState, useRef, useEffect } from 'react';
import type { Kapitel } from '@/app/actions/kapitels';
import type { Quelle } from '@/app/actions/quellen';
import { KapitelTOC } from '@/app/components/kapitels/KapitelTOC';
import { KapitelList } from '@/app/components/kapitels/KapitelList';

interface DashboardWithSidebarProps {
  kapitels: Kapitel[];
  quellen: Quelle[];
}

export function DashboardWithSidebar({
  kapitels,
  quellen,
}: DashboardWithSidebarProps) {
  const [activeKapitelId, setActiveKapitelId] = useState<string | null>(null);
  const kapitelRefs = useRef<Map<string, HTMLElement>>(new Map());

  const setKapitelRef = (kapitelId: string, element: HTMLElement | null) => {
    if (element) {
      kapitelRefs.current.set(kapitelId, element);
    } else {
      kapitelRefs.current.delete(kapitelId);
    }
  };

  const scrollToKapitel = (kapitelId: string) => {
    const element = kapitelRefs.current.get(kapitelId);
    if (element) {
      const offset = 100; // Header offset
      const elementPosition = element.getBoundingClientRect().top;
      const offsetPosition = elementPosition + window.scrollY - offset;

      window.scrollTo({
        top: offsetPosition,
        behavior: 'smooth',
      });
    }
  };

  const handleKapitelClick = (kapitelId: string, isExpanded: boolean) => {
    scrollToKapitel(kapitelId);
    setActiveKapitelId(kapitelId);
  };

  // Intersection Observer for active item detection
  useEffect(() => {
    const observerOptions = {
      rootMargin: '-20% 0px -70% 0px',
      threshold: 0,
    };

    const observerCallback = (entries: IntersectionObserverEntry[]) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const kapitelId = entry.target.getAttribute('data-kapitel-id');
          if (kapitelId) {
            setActiveKapitelId(kapitelId);
          }
        }
      });
    };

    const observer = new IntersectionObserver(observerCallback, observerOptions);

    // Observe all Kapitel elements
    kapitelRefs.current.forEach((element) => {
      observer.observe(element);
    });

    return () => {
      observer.disconnect();
    };
  }, [kapitels]);

  return (
    <>
      <KapitelTOC
        kapitels={kapitels}
        activeKapitelId={activeKapitelId}
        onKapitelClick={handleKapitelClick}
      />
      <div className="lg:ml-64">
        <KapitelList
          kapitels={kapitels}
          quellen={quellen}
          setKapitelRef={setKapitelRef}
        />
      </div>
    </>
  );
}
