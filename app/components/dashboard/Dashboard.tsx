'use client';

import { useState, useCallback, useEffect } from 'react';
import { KapitelNavigator } from './KapitelNavigator';
import { KapitelWorkspace } from './KapitelWorkspace';
import { ProjektHeader } from './ProjektHeader';
import { QuellenPanel } from './QuellenPanel';
import { TextViewerModal } from './TextViewerModal';
import { ProcessingDialog } from './ProcessingDialog';
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { DashboardSkeleton } from './DashboardSkeleton';
import { QuellenPanelSkeleton } from './QuellenPanelSkeleton';
import { toast } from 'sonner';

import type { Quelle, Kapitel, Run, ProcessingSettings, Projekt } from '@/app/types/ui';
import {
  transformQuelleToUI,
  transformKapitelToUI,
  transformRunToUI,
  createQuellenMap,
} from '@/app/lib/transformers/ui-data';

// Import Server Actions
import {
  createQuelle,
  deleteQuelle as deleteQuelleAction,
  type Quelle as FirebaseQuelle,
} from '@/app/actions/quellen';
import {
  createKapitel,
  updateKapitelQuellen,
  deleteKapitel as deleteKapitelAction,
  updateKapitelTitle,
  createKapitelRun,
  type Kapitel as FirebaseKapitel,
} from '@/app/actions/kapitels';

// Firebase real-time
import { useAuth } from '@/app/components/providers/AuthProvider';
import { getAuth } from 'firebase/auth';
import { firebaseApp } from '@/app/lib/firebase/config';
import { getFirestore, collection, onSnapshot, query, orderBy, limit } from 'firebase/firestore';

interface DashboardProps {
  initialKapitels: FirebaseKapitel[];
  initialQuellen: FirebaseQuelle[];
}

export function Dashboard({ initialKapitels, initialQuellen }: DashboardProps) {
  const { user } = useAuth();
  const [isLoading, setIsLoading] = useState(false);
  const [isQuellenLoading, setIsQuellenLoading] = useState(false);

  // Project state (single project for now)
  const [projekt] = useState<Projekt>({
    id: '1',
    name: 'Meine Arbeit',
    createdAt: new Date(),
  });

  // Transform initial data
  const [quellen, setQuellen] = useState<Quelle[]>(
    initialQuellen.map((q) => transformQuelleToUI(q, projekt.id))
  );
  const [kapiteln, setKapiteln] = useState<Kapitel[]>(
    initialKapitels.map((k) => transformKapitelToUI(k, projekt.id))
  );

  // UI state
  const [activeKapitelId, setActiveKapitelId] = useState(kapiteln[0]?.id || '');
  const activeKapitel = kapiteln.find((k) => k.id === activeKapitelId);

  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRun = runs.find((r) => r.id === selectedRunId);

  const [showQuellenPanel, setShowQuellenPanel] = useState(false);
  const [textViewerContent, setTextViewerContent] = useState<{
    title: string;
    text: string;
  } | null>(null);
  const [processingDialogOpen, setProcessingDialogOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: 'quelle' | 'kapitel';
    id: string;
    name: string;
  } | null>(null);

  // Real-time updates for runs
  useEffect(() => {
    if (!user?.uid || !activeKapitelId) {
      setRuns([]);
      setSelectedRunId(null);
      return;
    }

    const auth = getAuth(firebaseApp);
    const db = getFirestore(firebaseApp);
    const runsRef = collection(db, 'users', user.uid, 'kapitels', activeKapitelId, 'runs');
    const q = query(runsRef, orderBy('index', 'desc'), limit(5));

    const unsubscribe = onSnapshot(
      q,
      (snapshot) => {
        const fbRuns: any[] = [];
        snapshot.forEach((doc) => {
          const data = doc.data();
          fbRuns.push({
            id: doc.id,
            index: data.index || 0,
            instruction: data.instruction || '',
            model: data.model || '',
            createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
            ueberschrift: data.ueberschrift || '',
            thema: data.thema || data.instruction || '',
            results: [], // Will be filled below
            combined: null, // Will be filled below
          });
        });

        // Transform to UI runs
        const quellenMap = createQuellenMap(quellen);
        const uiRuns = fbRuns.map((fbRun) => transformRunToUI(fbRun, activeKapitelId, quellenMap));
        setRuns(uiRuns);

        // Auto-select the latest run
        if (uiRuns.length > 0 && !selectedRunId) {
          setSelectedRunId(uiRuns[0].id);
        }
      },
      (error) => {
        console.error('Error listening to runs:', error);
      }
    );

    return () => unsubscribe();
  }, [user?.uid, activeKapitelId, quellen, selectedRunId]);

  // Handlers
  const handleAddQuelle = useCallback(
    async (name: string, text: string) => {
      const result = await createQuelle(name, text);
      if (result.success) {
        toast.success('Quelle hinzugefügt', {
          description: `"${name}" wurde erfolgreich erstellt.`,
        });
        // Optimistically update UI
        const newQuelle: Quelle = {
          id: result.id!,
          name,
          text,
          projektId: projekt.id,
          createdAt: new Date(),
        };
        setQuellen((prev) => [...prev, newQuelle]);
      } else {
        toast.error('Fehler', { description: result.error });
      }
    },
    [projekt.id]
  );

  const handleDeleteQuelle = useCallback(async (id: string) => {
    const result = await deleteQuelleAction(id);
    if (result.success) {
      setQuellen((prev) => prev.filter((q) => q.id !== id));
      // Also remove from all kapitels
      setKapiteln((prev) =>
        prev.map((k) => ({
          ...k,
          assignedQuellenIds: k.assignedQuellenIds.filter((qid) => qid !== id),
        }))
      );
      setDeleteConfirm(null);
      toast.success('Quelle gelöscht');
    } else {
      toast.error('Fehler', { description: result.error });
    }
  }, []);

  const handleAssignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      const newQuelleIds = [...kapitel.assignedQuellenIds, quelleId];
      const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);

      if (result.success) {
        setKapiteln((prev) =>
          prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
        );
      } else {
        toast.error('Fehler', { description: result.error });
      }
    },
    [activeKapitelId, kapiteln]
  );

  const handleUnassignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      const newQuelleIds = kapitel.assignedQuellenIds.filter((id) => id !== quelleId);
      const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);

      if (result.success) {
        setKapiteln((prev) =>
          prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
        );
      } else {
        toast.error('Fehler', { description: result.error });
      }
    },
    [activeKapitelId, kapiteln]
  );

  const handleAddKapitel = useCallback(async (title: string, nummer: string) => {
    const result = await createKapitel(title, [], null, nummer);
    if (result.success) {
      toast.success('Kapitel erstellt', {
        description: `"${nummer} ${title}" wurde hinzugefügt.`,
      });
      // Refresh page to get updated data
      window.location.reload();
    } else {
      toast.error('Fehler', { description: result.error });
    }
  }, []);

  const handleDeleteKapitel = useCallback(
    async (id: string) => {
      const result = await deleteKapitelAction(id);
      if (result.success) {
        setKapiteln((prev) => prev.filter((k) => k.id !== id));
        if (activeKapitelId === id) {
          const remaining = kapiteln.filter((k) => k.id !== id);
          setActiveKapitelId(remaining[0]?.id || '');
        }
        setDeleteConfirm(null);
        toast.success('Kapitel gelöscht');
      } else {
        toast.error('Fehler', { description: result.error });
      }
    },
    [activeKapitelId, kapiteln]
  );

  const handleEditKapitel = useCallback(async (id: string, title: string, nummer: string) => {
    const result = await updateKapitelTitle(id, title, nummer);
    if (result.success) {
      setKapiteln((prev) => prev.map((k) => (k.id === id ? { ...k, title, nummer } : k)));
      toast.success('Kapitel aktualisiert', {
        description: `"${nummer} ${title}" wurde gespeichert.`,
      });
    } else {
      toast.error('Fehler', { description: result.error });
    }
  }, []);

  const handleProcess = useCallback(
    async (settings: ProcessingSettings) => {
      if (!activeKapitel) return;

      const assignedQuellen = quellen.filter((q) => activeKapitel.assignedQuellenIds.includes(q.id));

      toast.loading('Verarbeitung gestartet', {
        description: `"${settings.ueberschrift}" wird mit ${assignedQuellen.length} Quellen verarbeitet...`,
        id: 'processing',
      });

      // Create run via Server Action
      const result = await createKapitelRun(activeKapitelId, settings.thema, settings.model, {
        autoCombine: settings.directCombine,
        grundlegendeInformationen: settings.grundlegendeInfos,
        ueberschrift: settings.ueberschrift,
        thema: settings.thema,
      });

      if (result.success) {
        toast.success('Run erstellt', {
          description: 'Die Verarbeitung wird gestartet...',
          id: 'processing',
        });
        setProcessingDialogOpen(false);

        // Note: Actual processing would be triggered via FastAPI here
        // For now, just show success
      } else {
        toast.error('Fehler beim Erstellen des Runs', {
          description: result.error,
          id: 'processing',
        });
      }
    },
    [activeKapitelId, activeKapitel, quellen]
  );

  const handleCombineTexts = useCallback(async () => {
    toast.info('Combine-Funktion', {
      description: 'Die Texte werden kombiniert (Feature in Entwicklung).',
    });
  }, []);

  const handleToggleQuellenPanel = useCallback(() => {
    if (!showQuellenPanel) {
      setIsQuellenLoading(true);
      setShowQuellenPanel(true);
      setTimeout(() => {
        setIsQuellenLoading(false);
      }, 300);
    } else {
      setShowQuellenPanel(false);
    }
  }, [showQuellenPanel]);

  if (isLoading || !projekt) {
    return <DashboardSkeleton />;
  }

  const assignedQuellen = quellen.filter((q) => activeKapitel?.assignedQuellenIds.includes(q.id));

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Left Navigator */}
      <div className="w-64 border-r border-border bg-sidebar flex flex-col">
        <ProjektHeader projekt={projekt} projekte={[projekt]} />
        <KapitelNavigator
          kapiteln={kapiteln}
          activeKapitelId={activeKapitelId}
          onKapitelSelect={setActiveKapitelId}
          onAddKapitel={handleAddKapitel}
          onDeleteKapitel={(id, name) => setDeleteConfirm({ type: 'kapitel', id, name })}
          onEditKapitel={handleEditKapitel}
        />
      </div>

      {/* Main Workspace */}
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-hidden">
          {activeKapitel ? (
            <KapitelWorkspace
              kapitel={activeKapitel}
              assignedQuellen={assignedQuellen}
              runs={runs}
              selectedRun={selectedRun}
              onSelectRun={setSelectedRunId}
              onOpenTextViewer={setTextViewerContent}
              onOpenProcessing={() => setProcessingDialogOpen(true)}
              onCombineTexts={handleCombineTexts}
              onToggleQuellenPanel={handleToggleQuellenPanel}
            />
          ) : (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                <p className="text-muted-foreground">Wähle ein Kapitel aus oder erstelle ein neues.</p>
              </div>
            </div>
          )}
        </div>

        {showQuellenPanel &&
          activeKapitel &&
          (isQuellenLoading ? (
            <QuellenPanelSkeleton />
          ) : (
            <QuellenPanel
              quellen={quellen}
              assignedQuellenIds={activeKapitel.assignedQuellenIds}
              onClose={() => setShowQuellenPanel(false)}
              onAddQuelle={handleAddQuelle}
              onDeleteQuelle={(id, name) => setDeleteConfirm({ type: 'quelle', id, name })}
              onAssignQuelle={handleAssignQuelle}
              onUnassignQuelle={handleUnassignQuelle}
              onViewQuelle={(quelle) => setTextViewerContent({ title: quelle.name, text: quelle.text })}
            />
          ))}
      </div>

      <TextViewerModal content={textViewerContent} onClose={() => setTextViewerContent(null)} />

      {activeKapitel && (
        <ProcessingDialog
          open={processingDialogOpen}
          onOpenChange={setProcessingDialogOpen}
          kapitelTitle={activeKapitel.title}
          quellenCount={assignedQuellen.length}
          onProcess={handleProcess}
        />
      )}

      <DeleteConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        type={deleteConfirm?.type || 'quelle'}
        name={deleteConfirm?.name || ''}
        onConfirm={() => {
          if (deleteConfirm?.type === 'quelle') {
            handleDeleteQuelle(deleteConfirm.id);
          } else if (deleteConfirm?.type === 'kapitel') {
            handleDeleteKapitel(deleteConfirm.id);
          }
        }}
      />
    </div>
  );
}
