'use client';

import { useState } from 'react';
import type { Kapitel } from '@/app/actions/kapitels';
import type { Quelle } from '@/app/actions/quellen';
import { KapitelList } from '@/app/components/kapitels/KapitelList';
import { QuellenList } from '@/app/components/quellen/QuellenList';
import { CreateKapitelDialog } from '@/app/components/kapitels/CreateKapitelDialog';
import { CreateQuelleDialog } from '@/app/components/quellen/CreateQuelleDialog';

interface DashboardPanelsProps {
  kapitels: Kapitel[];
  quellen: Quelle[];
}

const tabs = [
  { id: 'kapitel', label: 'Kapiteln' },
  { id: 'quellen', label: 'Quellen' },
];

export function DashboardPanels({ kapitels, quellen }: DashboardPanelsProps) {
  const [activeTab, setActiveTab] = useState<'kapitel' | 'quellen'>('kapitel');

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-2 rounded-full bg-gray-100 p-1 w-fit">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as 'kapitel' | 'quellen')}
              className={`px-4 py-2 text-sm font-medium rounded-full transition ${
                activeTab === tab.id
                  ? 'bg-white shadow text-gray-900'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {activeTab === 'kapitel' ? (
          <CreateKapitelDialog quellen={quellen} />
        ) : (
          <CreateQuelleDialog />
        )}
      </div>

      {activeTab === 'kapitel' ? (
        <KapitelList kapitels={kapitels} quellen={quellen} />
      ) : (
        <div className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold">Quellen verwalten</h2>
            <p className="text-sm text-muted-foreground">
              Lege Quellen an und ordne sie Kapiteln zu.
            </p>
          </div>
          <QuellenList initialQuellen={quellen} />
        </div>
      )}
    </div>
  );
}
