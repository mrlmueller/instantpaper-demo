'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { KapitelNavigator } from './KapitelNavigator';
import { KapitelWorkspace } from './KapitelWorkspace';
import { ProjektHeader } from './ProjektHeader';
import { QuellenPanel } from './QuellenPanel';
import { TextViewerModal } from './TextViewerModal';
import { QuelleViewerModal } from './QuelleViewerModal';
import { ProcessingDialog } from './ProcessingDialog';
import { ShortenDialog } from './ShortenDialog';
import { LeseflussDialog } from './LeseflussDialog';
import { ExportDialog } from './ExportDialog';
import { CombinedRefinementDialog } from './CombinedRefinementDialog';
import { ShortenedRefinementDialog } from './ShortenedRefinementDialog';
import { LeseflussRefinementDialog } from './LeseflussRefinementDialog';
import { ResultRefinementDialog } from './ResultRefinementDialog';
import { DeleteConfirmDialog } from './DeleteConfirmDialog';
import { DashboardSkeleton } from './DashboardSkeleton';
import { QuellenPanelSkeleton } from './QuellenPanelSkeleton';
import { ViewportWarning } from '@/app/components/viewport-warning';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import type {
  PromptStage,
  PromptTemplate,
  ActivePromptSelections,
  SystemPromptTemplateMeta,
} from '@/app/types/prompts';
import { STAGE_CONFIG } from '@/app/lib/prompts/promptConfig';

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
  getQuelleContent,
  getUserQuellen,
  type Quelle as FirebaseQuelle,
  type ImageMetadata,
} from '@/app/actions/quellen';
import {
  createKapitel,
  updateKapitelQuellen,
  deleteKapitel as deleteKapitelAction,
  updateKapitelTitle,
  createKapitelRun,
  createShortenRun,
  createLeseflussRun,
  createDocxExport,
  getUserKapitels,
  type KapitelRun as FirebaseKapitelRun,
  type Kapitel as FirebaseKapitel,
} from '@/app/actions/kapitels';
import { archiveProject, createProject, unarchiveProject, type Project as FirebaseProject } from '@/app/actions/projects';

// Firebase real-time
import { useAuth } from '@/app/components/providers/AuthProvider';
import { firestoreClient } from '@/app/lib/firebase/firestoreClient';
import {
  collection,
  onSnapshot,
  query,
  orderBy,
  limit,
  where,
  doc,
  getDoc,
  getDocs,
  updateDoc,
  serverTimestamp,
  addDoc,
} from 'firebase/firestore';
import Cookies from 'js-cookie';
import { getQuellenPanelState, setQuellenPanelState, STORAGE_KEYS } from '@/app/lib/storage/preferences';
import { getActiveKapitelCookieName } from '@/app/lib/ui/kapitelSelection';
import { getActiveProjektCookieName } from '@/app/lib/ui/projektSelection';
import { getDownloadUrlFromStorage } from '@/app/lib/firebase/storage';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';
const RUN_HISTORY_LIMIT = 10;
const MAX_RUN_HISTORY_LIMIT = 200;

type PromptChoiceDialogProps = {
  open: boolean;
  stages: PromptStage[];
  templates: PromptTemplate[];
  systemTemplates: SystemPromptTemplateMeta[];
  active: ActivePromptSelections;
  onConfirm: (choices: Record<PromptStage, string | 'default'>) => void;
  onCancel: () => void;
};

function PromptSelectDialog({
  open,
  stages,
  templates,
  systemTemplates,
  active,
  onConfirm,
  onCancel,
}: PromptChoiceDialogProps) {
  const [choices, setChoices] = useState<Record<PromptStage, string | 'default'>>(() => {
    const initial = {} as Record<PromptStage, string | 'default'>;
    stages.forEach((s) => {
      initial[s] = (active[s] as string | 'default') || 'default';
    });
    return initial;
  });

  useEffect(() => {
    const init = {} as Record<PromptStage, string | 'default'>;
    stages.forEach((s) => {
      init[s] = (active[s] as string | 'default') || 'default';
    });
    setChoices(init);
  }, [stages, active, open]);

  return (
    <Dialog open={open} onOpenChange={(val) => !val && onCancel()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Prompt auswählen</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {stages.map((stage) => {
            const stageTemplates = templates.filter((t) => t.stage === stage);
            const stageSystemTemplates = systemTemplates
              .filter((t) => t.stage === stage)
              .slice()
              .sort((a, b) => {
                const rank = (key: string) => (key === 'default' ? 0 : key === 'default_v2' ? 1 : 2);
                const ra = rank(a.templateKey);
                const rb = rank(b.templateKey);
                if (ra !== rb) return ra - rb;
                return a.name.localeCompare(b.name, 'de');
              });
            const config = STAGE_CONFIG[stage];
            return (
              <Card key={stage} className="p-3">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <p className="text-sm font-medium">{config.label}</p>
                    <p className="text-xs text-muted-foreground">
                      Pflicht: {config.requiredPlaceholders.length ? config.requiredPlaceholders.join(", ") : "Keine"}
                    </p>
                  </div>
                  <Select
                    value={choices[stage] || 'default'}
                    onValueChange={(val) => setChoices((prev) => ({ ...prev, [stage]: val as string | 'default' }))}
                  >
                     <SelectTrigger className="w-64">
                       <SelectValue />
                     </SelectTrigger>
                    <SelectContent>
                      {stageSystemTemplates.map((tpl) => (
                        <SelectItem key={`sys-${tpl.templateKey}`} value={tpl.templateKey}>
                          <span className="text-muted-foreground">{tpl.name}</span>
                        </SelectItem>
                      ))}
                      {stageTemplates.map((tpl) => (
                        <SelectItem key={tpl.id} value={tpl.id}>
                          {tpl.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <p className="text-xs text-muted-foreground line-clamp-2 font-mono">
                  {(() => {
                    const choice = choices[stage];
                    const sys = stageSystemTemplates.find((t) => t.templateKey === choice);
                    if (sys) return sys.name;
                    if (choice === 'default') return 'System-Standard';
                    if (choice === 'default_v2') return 'System-Standard (v2)';
                    return stageTemplates.find((t) => t.id === choice)?.instructions?.slice(0, 160) || 'System-Standard';
                  })()}
                </p>
              </Card>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Abbrechen
          </Button>
          <Button onClick={() => onConfirm(choices)}>Weiter</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface DashboardProps {
  initialKapitels: FirebaseKapitel[];
  initialQuellen: FirebaseQuelle[];
  initialProjekt: FirebaseProject;
  initialProjekte: FirebaseProject[];
  initialRuns?: FirebaseKapitelRun[];
  initialActiveKapitelId?: string;
  initialShowQuellenPanel?: boolean;
}

export function Dashboard({
  initialKapitels,
  initialQuellen,
  initialProjekt,
  initialProjekte,
  initialRuns = [],
  initialActiveKapitelId: initialActiveKapitelIdProp,
  initialShowQuellenPanel: initialShowQuellenPanelProp,
}: DashboardProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuth();
  // Start with skeleton to avoid empty flash before data appears
  const [isLoading, setIsLoading] = useState(true);
  const [isQuellenLoading, setIsQuellenLoading] = useState(false);

  const initialProjektList = initialProjekte.length ? initialProjekte : [initialProjekt];
  const [projekt, setProjekt] = useState<Projekt>({
    id: initialProjekt.id,
    name: initialProjekt.name,
    createdAt: new Date(initialProjekt.createdAt),
    archived: Boolean(initialProjekt.archived),
  });
  const [projekte, setProjekte] = useState<Projekt[]>(
    initialProjektList.map((p) => ({
      id: p.id,
      name: p.name,
      createdAt: new Date(p.createdAt),
      archived: Boolean(p.archived),
    }))
  );

  // Transform initial data
  const [quellen, setQuellen] = useState<Quelle[]>(
    initialQuellen.map((q) => transformQuelleToUI(q, projekt.id))
  );
  const [kapiteln, setKapiteln] = useState<Kapitel[]>(
    initialKapitels.map((k) => transformKapitelToUI(k, projekt.id))
  );
  const [kapitelIndicatorById, setKapitelIndicatorById] = useState<
    Record<string, { stage: 0 | 1 | 2 | 3 | 4; isProcessing: boolean }>
  >({});
  const kapitelIndicatorUnsubsRef = useRef<Map<string, { runId: string; unsubscribe: () => void }>>(new Map());
  const [kapitelArtifactStageById, setKapitelArtifactStageById] = useState<Record<string, 0 | 1 | 2 | 3 | 4>>({});
  const kapitelArtifactUnsubsRef = useRef<Map<string, { runId: string; unsubscribe: () => void }>>(new Map());
  const [kapitelOverallStageById, setKapitelOverallStageById] = useState<Record<string, 0 | 1 | 2 | 3 | 4>>({});
  const kapitelOverallStageInFlightRef = useRef<Set<string>>(new Set());
  const kapitelOverallStageComputedRef = useRef<Set<string>>(new Set());

  // UI state
  const initialActiveKapitelId =
    initialActiveKapitelIdProp && kapiteln.some((k) => k.id === initialActiveKapitelIdProp)
      ? initialActiveKapitelIdProp
      : kapiteln[0]?.id || '';
  const [activeKapitelId, setActiveKapitelId] = useState(initialActiveKapitelId);
  const activeKapitel = kapiteln.find((k) => k.id === activeKapitelId);

  const [loadedProjektId, setLoadedProjektId] = useState<string>(initialProjekt.id);
  const loadedProjektIdRef = useRef<string>(initialProjekt.id);
  const activeKapitelIdRef = useRef<string>(initialActiveKapitelId);
  const kapitelnRef = useRef<Kapitel[]>(kapiteln);

  const [fbRuns, setFbRuns] = useState<FirebaseKapitelRun[]>(initialRuns);
  const keepInitialRunsRef = useRef(initialRuns.length > 0);
  const [runListLimit, setRunListLimit] = useState<number>(RUN_HISTORY_LIMIT);
  const [allRunsLoaded, setAllRunsLoaded] = useState(false);
  const [isKapitelLoading, setIsKapitelLoading] = useState(initialRuns.length === 0);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);
  const userSelectedRunRef = useRef(false);
  const selectedRun = runs.find((r) => r.id === selectedRunId);
  const hasShownNoticeRef = useRef(false);
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [systemPromptTemplates, setSystemPromptTemplates] = useState<SystemPromptTemplateMeta[]>([]);
  const [promptActive, setPromptActive] = useState<ActivePromptSelections>({});
  const [askOnEachProcess, setAskOnEachProcess] = useState(false);
  const [promptChooser, setPromptChooser] = useState<{
    stages: PromptStage[];
    resolve: (choices: Record<PromptStage, string | 'default'> | null) => void;
  } | null>(null);

  const computeKapitelIndicatorFromRunDoc = useCallback((runData: any) => {
    const artifactsStatus = (runData?.artifactsStatus ?? {}) as Record<string, unknown>;
    const combinedStatus = typeof artifactsStatus.combined === 'string' ? artifactsStatus.combined : 'empty';
    const shortenedStatus = typeof artifactsStatus.shortened === 'string' ? artifactsStatus.shortened : 'empty';
    const leseflussStatus = typeof artifactsStatus.lesefluss === 'string' ? artifactsStatus.lesefluss : 'empty';

    const resultsExpected = Number(runData?.resultsExpectedCount ?? 0);
    const resultsCompleted = Number(runData?.resultsCompletedCount ?? 0);
    const resultsWithContent = Number(runData?.resultsWithContentCount ?? 0);
    const hasAnySourceResult =
      resultsCompleted > 0 ||
      resultsWithContent > 0 ||
      (resultsExpected > 0 && resultsCompleted >= resultsExpected);

    const resultsRunningCount = Math.max(0, Number(runData?.resultsRunningCount ?? 0));
    const summariesRunningCount = Math.max(0, Number(runData?.summariesRunningCount ?? 0));
    const artifactsRunningCount = Math.max(0, Number(runData?.artifactsRunningCount ?? 0));
    const refinementRunningCount = Math.max(0, Number(runData?.refinementRunningCount ?? 0));

    const isProcessing =
      resultsRunningCount > 0 ||
      summariesRunningCount > 0 ||
      artifactsRunningCount > 0 ||
      refinementRunningCount > 0;

    let stage: 0 | 1 | 2 | 3 | 4 = 0;
    if (leseflussStatus === 'success') stage = 4;
    else if (shortenedStatus === 'success') stage = 3;
    else if (combinedStatus === 'success') stage = 2;
    else if (hasAnySourceResult) stage = 1;

    return { stage, isProcessing };
  }, []);

  const handleAuthFailure = useCallback(() => {
    toast.error('Sitzung erforderlich', {
      description: 'Bitte melde dich erneut an.',
      id: 'auth-required',
    });
    router.replace('/login?reason=unauthenticated');
  }, [router]);

  const ensureOpenAIAccess = useCallback(async (): Promise<boolean> => {
    const token = Cookies.get('__session');
    if (!token) {
      handleAuthFailure();
      return false;
    }

    return true;
  }, [handleAuthFailure]);

  const notifyServerDown = useCallback(
    (toastId: string | number = 'fastapi-down') => {
      toast.error('Server nicht erreichbar', {
        description:
          'Der FastAPI-Server antwortet aktuell nicht. Das ist ein Server-Problem - du kannst nichts tun außer es später erneut zu versuchen.',
        id: toastId,
      });
    },
    []
  );

  useEffect(() => {
    if (hasShownNoticeRef.current) return;
    const notice = searchParams.get('notice');
    if (!notice) return;
    hasShownNoticeRef.current = true;

    if (notice === 'already-authenticated') {
      toast.info('Bereits angemeldet', {
        description: 'Du bist bereits eingeloggt.',
      });
      router.replace('/dashboard');
    }
  }, [router, searchParams]);

  const handleSelectRun = useCallback((id: string) => {
    selectedRunIdRef.current = id;
    setSelectedRunId((prev) => (prev === id ? prev : id));
  }, []);

  const handleUserSelectRun = useCallback(
    (id: string) => {
      userSelectedRunRef.current = true;
      handleSelectRun(id);
    },
    [handleSelectRun]
  );

  useEffect(() => {
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  const [showQuellenPanel, setShowQuellenPanel] = useState(() => initialShowQuellenPanelProp ?? getQuellenPanelState());
  const [textViewerContent, setTextViewerContent] = useState<{
    title: string;
    text: string;
  } | null>(null);
  const [quelleViewer, setQuelleViewer] = useState<Quelle | null>(null);
  const [quelleViewerLoading, setQuelleViewerLoading] = useState(false);
  const [processingDialogOpen, setProcessingDialogOpen] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);

  const exportToastIdRef = useRef<string | number | null>(null);
  const exportUnsubRef = useRef<null | (() => void)>(null);
  const exportIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Persist Quellen panel state (for SSR skeleton + client preference)
  useEffect(() => {
    setQuellenPanelState(showQuellenPanel);

    const cookieName = STORAGE_KEYS.QUELLEN_PANEL_OPEN;
    if (showQuellenPanel) {
      Cookies.set(cookieName, 'true', {
        expires: 365,
        sameSite: 'lax',
        secure: process.env.NODE_ENV === 'production',
        path: '/',
      });
    } else {
      Cookies.remove(cookieName, { path: '/' });
    }
  }, [showQuellenPanel]);

  // One-time migration: if older sessions only persisted to localStorage, upgrade to cookie-backed state.
  useEffect(() => {
    const cookieValue = Cookies.get(STORAGE_KEYS.QUELLEN_PANEL_OPEN);
    if (cookieValue != null) return;

    const stored = getQuellenPanelState();
    if (stored !== showQuellenPanel) {
      setShowQuellenPanel(stored);
    }
  }, [showQuellenPanel]);

  const [shortenDialogOpen, setShortenDialogOpen] = useState(false);
  const [leseflussDialogOpen, setLeseflussDialogOpen] = useState(false);
  const [combinedRefinementDialogOpen, setCombinedRefinementDialogOpen] = useState(false);
  const [shortenedRefinementDialogOpen, setShortenedRefinementDialogOpen] = useState(false);
  const [leseflussRefinementDialogOpen, setLeseflussRefinementDialogOpen] = useState(false);
  const [resultRefinementDialogOpen, setResultRefinementDialogOpen] = useState(false);
  const [resultRefinementTarget, setResultRefinementTarget] = useState<{ quelleId: string; quelleName: string } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: 'quelle' | 'kapitel' | 'projekt';
    id: string;
    name: string;
  } | null>(null);
  const [isAddingQuelle, setIsAddingQuelle] = useState(false);
  const [assigningQuelleIds, setAssigningQuelleIds] = useState<string[]>([]);
  const [unassigningQuelleIds, setUnassigningQuelleIds] = useState<string[]>([]);
  const [deletingQuelleIds, setDeletingQuelleIds] = useState<string[]>([]);
  const [isProcessingRun, setIsProcessingRun] = useState(false);
  const [isCombining, setIsCombining] = useState(false);
  const [isShortening, setIsShortening] = useState(false);
  const [isImprovingLesefluss, setIsImprovingLesefluss] = useState(false);
  const [isExportingDocx, setIsExportingDocx] = useState(false);
  const [isCreatingKapitel, setIsCreatingKapitel] = useState(false);
  const [isEditingKapitel, setIsEditingKapitel] = useState(false);
  const [isCreatingProjekt, setIsCreatingProjekt] = useState(false);

  const cleanupExportWatcher = useCallback(() => {
    if (exportIntervalRef.current) {
      clearInterval(exportIntervalRef.current);
      exportIntervalRef.current = null;
    }
    if (exportUnsubRef.current) {
      exportUnsubRef.current();
      exportUnsubRef.current = null;
    }
    exportToastIdRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      cleanupExportWatcher();
    };
  }, [cleanupExportWatcher]);

  const loadProjektData = useCallback(async (projektId: string) => {
    setIsKapitelLoading(true);
    setRunListLimit(RUN_HISTORY_LIMIT);
    setAllRunsLoaded(false);
    const [fbQuellen, fbKapitels] = await Promise.all([
      getUserQuellen(projektId),
      getUserKapitels(projektId, false, RUN_HISTORY_LIMIT),
    ]);
    setLoadedProjektId(projektId);
    loadedProjektIdRef.current = projektId;
    setQuellen(fbQuellen.map((q) => transformQuelleToUI(q, projektId)));
    setKapiteln(fbKapitels.map((k) => transformKapitelToUI(k, projektId)));
    const persistedKapitelId = Cookies.get(getActiveKapitelCookieName(projektId));
    const nextKapitelId =
      persistedKapitelId && fbKapitels.some((k) => k.id === persistedKapitelId) ? persistedKapitelId : fbKapitels[0]?.id || '';
    setActiveKapitelId(nextKapitelId);
    setSelectedRunId(null);
    selectedRunIdRef.current = null;
    setFbRuns([]);
    keepInitialRunsRef.current = false;

    if (!nextKapitelId) {
      setIsKapitelLoading(false);
    }
  }, []);

  useEffect(() => {
    loadedProjektIdRef.current = loadedProjektId;
  }, [loadedProjektId]);

  useEffect(() => {
    activeKapitelIdRef.current = activeKapitelId;
  }, [activeKapitelId]);

  useEffect(() => {
    kapitelnRef.current = kapiteln;
  }, [kapiteln]);

  const persistActiveKapitelCookie = useCallback((projektId: string, kapitelId: string | null) => {
    const cookieName = getActiveKapitelCookieName(projektId);
    if (!kapitelId) {
      Cookies.remove(cookieName, { path: '/' });
      return;
    }

    Cookies.set(cookieName, kapitelId, {
      expires: 365,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
    });
  }, []);

  const persistActiveProjektCookie = useCallback((projektId: string | null) => {
    const cookieName = getActiveProjektCookieName();
    if (!projektId) {
      Cookies.remove(cookieName, { path: '/' });
      return;
    }

    Cookies.set(cookieName, projektId, {
      expires: 365,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
    });
  }, []);

  const syncActiveKapitelFromCookie = useCallback(() => {
    const projektId = loadedProjektIdRef.current;
    const currentActive = activeKapitelIdRef.current;
    const currentKapiteln = kapitelnRef.current;
    const persistedKapitelId = Cookies.get(getActiveKapitelCookieName(projektId));
    if (!persistedKapitelId || persistedKapitelId === currentActive) return;
    if (!currentKapiteln.some((k) => k.id === persistedKapitelId)) return;
    setActiveKapitelId(persistedKapitelId);
  }, []);

  useEffect(() => {
    // When navigating back/forward, Next can restore a cached dashboard tree (including stale Kapitel state).
    // Sync to the persisted cookie to keep browser back in sync with the last selection.
    const onShow = () => syncActiveKapitelFromCookie();
    const onPop = () => syncActiveKapitelFromCookie();
    const onVisibility = () => {
      if (document.visibilityState === 'visible') syncActiveKapitelFromCookie();
    };

    syncActiveKapitelFromCookie();
    window.addEventListener('pageshow', onShow);
    window.addEventListener('popstate', onPop);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('pageshow', onShow);
      window.removeEventListener('popstate', onPop);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [syncActiveKapitelFromCookie]);

  useEffect(() => {
    persistActiveKapitelCookie(loadedProjektId, activeKapitelId || null);
  }, [loadedProjektId, activeKapitelId, persistActiveKapitelCookie]);

  useEffect(() => {
    persistActiveProjektCookie(projekt.id);
  }, [projekt.id, persistActiveProjektCookie]);

  const handleKapitelSelect = useCallback(
    (kapitelId: string) => {
      setActiveKapitelId(kapitelId);
      // Persist immediately so fast navigation away (e.g. Quellen Manager) still keeps the latest selection.
      persistActiveKapitelCookie(loadedProjektIdRef.current, kapitelId);
    },
    [persistActiveKapitelCookie]
  );

  const persistKapitelQuellenClient = useCallback(async (kapitelId: string, quelleIds: string[]) => {
    if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
    const db = firestoreClient;
    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    await updateDoc(kapitelRef, {
      quelleIds,
      updatedAt: serverTimestamp(),
    });
  }, [user?.uid]);

  const createKapitelClient = useCallback(
    async (title: string, nummer: string, parentId: string | null = null, thema?: string) => {
    if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
    const db = firestoreClient;
    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const docRef = await addDoc(kapitelsRef, {
      title,
      projektId: projekt.id,
      nummer,
      thema: thema?.trim() || null,
      quelleIds: [],
      parentId,
      order: Date.now(),
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp(),
      archived: false,
    });
    return docRef.id;
    },
    [user?.uid, projekt.id]
  );

  const updateKapitelTitleClient = useCallback(async (kapitelId: string, title: string, nummer: string, thema?: string) => {
    if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
    const db = firestoreClient;
    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const patch: Record<string, unknown> = {
      title,
      nummer,
      updatedAt: serverTimestamp(),
    };
    if (thema !== undefined) {
      patch.thema = thema.trim() || null;
    }
    await updateDoc(kapitelRef, patch);
  }, [user?.uid]);

  const deleteKapitelClient = useCallback(
    async (kapitelId: string, deleteStrategy: 'promote' | 'cascade' = 'promote') => {
      if (!user?.uid) throw new Error('Kein Nutzer angemeldet');
      const db = firestoreClient;

      const archiveRec = async (id: string, strategy: 'promote' | 'cascade') => {
        const kapitelRef = doc(db, 'users', user.uid, 'kapitels', id);
        const kapitelSnap = await getDoc(kapitelRef);
        if (!kapitelSnap.exists()) return;
        const parentId = (kapitelSnap.data() as any).parentId ?? null;

        const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
        const childrenQ = query(kapitelsRef, where('parentId', '==', id), where('archived', '==', false));
        const childrenSnap = await getDocs(childrenQ);

        if (strategy === 'cascade') {
          for (const child of childrenSnap.docs) {
            await archiveRec(child.id, 'cascade');
          }
        } else {
          for (const child of childrenSnap.docs) {
            await updateDoc(doc(db, 'users', user.uid, 'kapitels', child.id), {
              parentId,
              updatedAt: serverTimestamp(),
            });
          }
        }

        await updateDoc(kapitelRef, {
          archived: true,
          archivedAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        });
      };

      await archiveRec(kapitelId, deleteStrategy);
    },
    [user?.uid]
  );

  // When the active Kapitel changes, seed runs from initial data while real-time listeners attach
  useEffect(() => {
    if (!activeKapitelId) {
      setFbRuns([]);
      setRuns([]);
      setSelectedRunId(null);
      selectedRunIdRef.current = null;
      userSelectedRunRef.current = false;
      setIsKapitelLoading(false);
      return;
    }

    setIsKapitelLoading(true);
    setSelectedRunId(null);
    // Prevent a race where the runs listener fires before `selectedRunId` state clears,
    // which can block auto-selecting the first run and leave the Kapitel stuck loading.
    selectedRunIdRef.current = null;
    userSelectedRunRef.current = false;
    setRunListLimit(RUN_HISTORY_LIMIT);
    setAllRunsLoaded(false);

    if (keepInitialRunsRef.current) {
      // Preserve the initially provided runs once; subsequent Kapitel switches clear state
      setIsKapitelLoading(false);
      keepInitialRunsRef.current = false;
      return;
    }

    setFbRuns([]);
    setRuns([]);
  }, [activeKapitelId]);

  // Real-time updates for runs, results, and combined content of the active Kapitel
  useEffect(() => {
    if (!user?.uid || !activeKapitelId) {
      setFbRuns([]);
      setRuns([]);
      setSelectedRunId(null);
      selectedRunIdRef.current = null;
      return;
    }

    const db = firestoreClient;
    const runsRef = collection(db, 'users', user.uid, 'kapitels', activeKapitelId, 'runs');
    const q = query(runsRef, where('archived', '==', false), orderBy('index', 'desc'), limit(runListLimit));

    const unsubscribeRuns = onSnapshot(
      q,
      (snapshot) => {
        setFbRuns((prev) => {
          const prevMap = new Map(prev.map((run) => [run.id, run]));
          const baseRuns: FirebaseKapitelRun[] = snapshot.docs.map((doc) => {
            const data: any = doc.data();
            const existing = prevMap.get(doc.id);
            return {
              id: doc.id,
              index: data.index || 0,
              instruction: data.instruction || '',
              name: typeof data.name === 'string' ? data.name : existing?.name,
              model: data.model || '',
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
              promptTemplateId: data.promptTemplateId,
              promptPayload: data.promptPayload,
              autoCombine: data.autoCombine ?? false,
              results: existing?.results || [],
              artifacts: existing?.artifacts,
              artifactsStatus: data.artifactsStatus,
              resultsExpectedCount: data.resultsExpectedCount,
              resultsCompletedCount: data.resultsCompletedCount,
              resultsWithContentCount: data.resultsWithContentCount,
              lastResultAt: data.lastResultAt?.toDate?.()?.toISOString() ?? null,
              lastActivityAt: data.lastActivityAt?.toDate?.()?.toISOString() ?? null,
              ueberschrift: data.ueberschrift || existing?.ueberschrift || '',
              thema: data.thema || existing?.thema || '',
              grundlegendeInformationen: data.grundlegendeInformationen ?? existing?.grundlegendeInformationen ?? null,
            } as FirebaseKapitelRun;
          });
          return baseRuns;
        });

        if (!snapshot.empty) {
          const firstRunId = snapshot.docs[0].id;
          const activeRunId = activeKapitel?.activeRunId;
          const preferredRunId =
            activeRunId && snapshot.docs.some((d) => d.id === activeRunId) ? activeRunId : firstRunId;
          const currentSelected = selectedRunIdRef.current;
          const currentIsInSnapshot =
            currentSelected != null && snapshot.docs.some((d) => d.id === currentSelected);

          if (!currentSelected || !currentIsInSnapshot) {
            handleSelectRun(preferredRunId);
          }
        }

        if (snapshot.empty) {
          setIsKapitelLoading(false);
        }

        // Once we have the runs snapshot for this Kapitel (empty or not), stop the workspace skeleton.
        // Artifact/result docs can stream in asynchronously via the selected-run listeners.
        setIsKapitelLoading(false);
      },
      (error) => {
        console.error('Error listening to runs:', error);
        setIsKapitelLoading(false);
      }
    );

    return () => {
      unsubscribeRuns();
    };
  }, [user?.uid, activeKapitelId, runListLimit, handleSelectRun, activeKapitel?.activeRunId]);

  useEffect(() => {
    if (!user?.uid || !activeKapitelId) return;
    const activeRunId = activeKapitel?.activeRunId;
    if (!activeRunId) return;

    const db = firestoreClient;
    const activeRunRef = doc(db, 'users', user.uid, 'kapitels', activeKapitelId, 'runs', activeRunId);

    const unsub = onSnapshot(
      activeRunRef,
      (snap) => {
        if (!snap.exists()) return;
        const data: any = snap.data();
        setFbRuns((prev) => {
          const prevMap = new Map(prev.map((run) => [run.id, run]));
          const existing = prevMap.get(snap.id);
          const next: FirebaseKapitelRun = {
            id: snap.id,
            index: data.index || 0,
            instruction: data.instruction || '',
            name: typeof data.name === 'string' ? data.name : existing?.name,
            model: data.model || '',
            createdAt: data.createdAt?.toDate?.()?.toISOString() || existing?.createdAt || new Date().toISOString(),
            updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            promptTemplateId: data.promptTemplateId,
            promptPayload: data.promptPayload,
            autoCombine: data.autoCombine ?? false,
            results: existing?.results || [],
            artifacts: existing?.artifacts,
            artifactsStatus: data.artifactsStatus,
            resultsExpectedCount: data.resultsExpectedCount,
            resultsCompletedCount: data.resultsCompletedCount,
            resultsWithContentCount: data.resultsWithContentCount,
            lastResultAt: data.lastResultAt?.toDate?.()?.toISOString() ?? null,
            lastActivityAt: data.lastActivityAt?.toDate?.()?.toISOString() ?? null,
            ueberschrift: data.ueberschrift || existing?.ueberschrift || '',
            thema: data.thema || existing?.thema || '',
            grundlegendeInformationen: data.grundlegendeInformationen ?? existing?.grundlegendeInformationen ?? null,
          } as FirebaseKapitelRun;

          const merged = existing ? prev.map((r) => (r.id === snap.id ? next : r)) : [...prev, next];
          return merged.sort((a, b) => Number(b.index ?? 0) - Number(a.index ?? 0));
        });
      },
      (err) => {
        console.error('Error listening to active run:', err);
      }
    );

    return () => unsub();
  }, [user?.uid, activeKapitelId, activeKapitel?.activeRunId]);

  // Load data (artifacts/results) only for the selected run
  useEffect(() => {
    if (!user?.uid || !activeKapitelId || !selectedRunId) {
      return;
    }

    const db = firestoreClient;

    const artifactsRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      activeKapitelId,
      'runs',
      selectedRunId,
      'artifacts'
    );

    const resultsRef = collection(
      db,
      'users',
      user.uid,
      'kapitels',
      activeKapitelId,
      'runs',
      selectedRunId,
      'results'
    );

    let hasData = false;
    let settledOnce = false;

    // Batch multiple listener updates to reduce re-renders
    let pendingUpdate: Partial<FirebaseKapitelRun> = {};
    let updateTimeout: NodeJS.Timeout | null = null;

    // Track when both listeners have fired at least once
    let listenersSettled = 0;
    const totalListeners = 4;

    const flushBatchedUpdate = () => {
      if (Object.keys(pendingUpdate).length > 0) {
        setFbRuns((prev) => prev.map((run) => (run.id === selectedRunId ? { ...run, ...pendingUpdate } : run)));
        pendingUpdate = {};
      }
    };

    const updateRunBatched = (partial: Partial<FirebaseKapitelRun>) => {
      pendingUpdate = { ...pendingUpdate, ...partial };

      if (updateTimeout) {
        clearTimeout(updateTimeout);
      }

      updateTimeout = setTimeout(flushBatchedUpdate, 50);
    };

    const finishIfNeeded = () => {
      if (!settledOnce) {
        settledOnce = true;
        setIsKapitelLoading(false);
      }
    };

    const checkListenerSettled = () => {
      listenersSettled++;
      if (listenersSettled >= totalListeners) {
        finishIfNeeded();
      }
    };

    const normalizeRefinement = (refinement: any) =>
      refinement
        ? {
            rootVersionId: 'root' as const,
            activeVersionId: refinement.activeVersionId ?? 'root',
            maxDepth: refinement.maxDepth ?? 4,
            costTotalUsd: refinement.costTotalUsd ?? 0,
            initializedAt: refinement.initializedAt?.toDate?.()?.toISOString() || new Date().toISOString(),
            selectedAt: refinement.selectedAt?.toDate?.()?.toISOString() ?? null,
          }
        : {
            rootVersionId: 'root' as const,
            activeVersionId: 'root',
            maxDepth: 4,
            costTotalUsd: 0,
            initializedAt: new Date().toISOString(),
            selectedAt: null,
          };

    const normalizeUsage = (usage: any) =>
      usage
        ? {
            inputTokens: usage.inputTokens ?? 0,
            cachedInputTokens: usage.cachedInputTokens ?? 0,
            outputTokens: usage.outputTokens ?? 0,
            reasoningTokens: usage.reasoningTokens ?? 0,
            totalTokens: usage.totalTokens ?? 0,
          }
        : { inputTokens: 0, cachedInputTokens: 0, outputTokens: 0, reasoningTokens: 0, totalTokens: 0 };

    // Listen to fixed artifact docs individually so we don't fail if legacy/unknown docs exist in the collection.
    const artifacts: any = { combined: null, shortened: null, lesefluss: null };

    const listenArtifact = (artifactId: 'combined' | 'shortened' | 'lesefluss') =>
      onSnapshot(
        doc(artifactsRef, artifactId),
        (snap) => {
          if (!snap.exists()) {
            artifacts[artifactId] = null;
            updateRunBatched({ artifacts: { ...artifacts } });
            checkListenerSettled();
            return;
          }

          const data: any = snap.data();
          const refinement = normalizeRefinement(data.refinement);
          const usage = normalizeUsage(data.usage);

          if (artifactId === 'combined') {
            artifacts.combined = {
              id: 'combined',
              content: data.content ?? '',
              status: data.status,
              sourceQuelleIds: data.sourceQuelleIds ?? [],
              heading: data.heading ?? '',
              topic: data.topic ?? '',
              model: data.model ?? '',
              usage,
              costUsd: data.costUsd ?? 0,
              refinement,
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            };
          } else if (artifactId === 'shortened') {
            artifacts.shortened = {
              id: 'shortened',
              content: data.content ?? '',
              status: data.status,
              originalLength: data.originalLength ?? 0,
              shortenedLength: data.shortenedLength ?? 0,
              usedKapitelIds: data.usedKapitelIds ?? [],
              model: data.model ?? '',
              usage,
              costUsd: data.costUsd ?? 0,
              refinement,
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            };
          } else if (artifactId === 'lesefluss') {
            artifacts.lesefluss = {
              id: 'lesefluss',
              content: data.content ?? '',
              status: data.status,
              aufgabenstellung: data.aufgabenstellung ?? '',
              originalLength: data.originalLength,
              leseflussLength: data.leseflussLength ?? 0,
              usedKapitelIds: data.usedKapitelIds ?? [],
              model: data.model ?? '',
              usage,
              costUsd: data.costUsd ?? 0,
              refinement,
              createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
              updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            };
          }

          updateRunBatched({ artifacts: { ...artifacts } });
          hasData = hasData || Boolean(artifacts.combined || artifacts.shortened || artifacts.lesefluss);
          if (hasData) finishIfNeeded();
          checkListenerSettled();
        },
        (err) => {
          console.error(`Artifact listen failed (${artifactId}):`, err);
          checkListenerSettled();
        }
      );

    const artifactsUnsubs = [listenArtifact('combined'), listenArtifact('shortened'), listenArtifact('lesefluss')];

    const resultsUnsub = onSnapshot(
      resultsRef,
      (resSnapshot) => {
        const results = resSnapshot.docs.map((resDoc) => {
          const resData: any = resDoc.data();
          return {
            quelleId: resDoc.id,
            userInput: resData.userInput ?? '',
            content: resData.content ?? '',
            hasContent: typeof resData.hasContent === 'boolean' ? resData.hasContent : true,
            status: resData.status,
            model: resData.model ?? '',
            usage: normalizeUsage(resData.usage),
            costUsd: resData.costUsd ?? 0,
            refinement: normalizeRefinement(resData.refinement),
            createdAt: resData.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
            updatedAt: resData.updatedAt?.toDate?.()?.toISOString(),
          };
        });

        updateRunBatched({ results });
        hasData = hasData || results.length > 0;
        if (hasData) finishIfNeeded();
        if (!hasData && resSnapshot.empty) {
          finishIfNeeded();
        }
        checkListenerSettled();
      },
      (err) => {
        console.error('Results listen failed:', err);
        checkListenerSettled();
      }
    );

    return () => {
      if (updateTimeout) {
        clearTimeout(updateTimeout);
        flushBatchedUpdate();
      }
      artifactsUnsubs.forEach((fn) => fn());
      resultsUnsub();
    };
  }, [user?.uid, activeKapitelId, selectedRunId]);

  // Realtime Kapitels list for the active project (status comes from denormalized `latestRun`)
  useEffect(() => {
    if (!user?.uid || !projekt?.id) return;

    const db = firestoreClient;
    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const q = query(
      kapitelsRef,
      where('projektId', '==', projekt.id),
      where('archived', '==', false),
      orderBy('order', 'asc')
    );

    const unsub = onSnapshot(
      q,
      (snap) => {
        const fb = snap.docs.map((d) => {
          const data: any = d.data();
          return {
            id: d.id,
            title: data.title || '',
            thema: typeof data.thema === 'string' ? data.thema : null,
            projektId: data.projektId || projekt.id,
            nummer: data.nummer || '1',
            createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
            updatedAt: data.updatedAt?.toDate?.()?.toISOString(),
            archived: Boolean(data.archived),
            archivedAt: data.archivedAt?.toDate?.()?.toISOString(),
            quelleIds: data.quelleIds || [],
            parentId: data.parentId ?? null,
            order: data.order ?? 0,
            latestRun: data.latestRun
              ? {
                  runId: data.latestRun.runId,
                  index: data.latestRun.index,
                  status: data.latestRun.status,
                  updatedAt: data.latestRun.updatedAt?.toDate?.()?.toISOString() || new Date().toISOString(),
                }
              : undefined,
            activeRunId: typeof data.activeRunId === 'string' ? data.activeRunId : undefined,
          };
        });

        const ui = fb.map((k) => transformKapitelToUI(k as any, projekt.id));
        setKapiteln(ui);

        setActiveKapitelId((prev) => {
          if (!ui.length) return '';
          if (prev && ui.some((k) => k.id === prev)) return prev;
          const persistedKapitelId = Cookies.get(getActiveKapitelCookieName(projekt.id));
          if (persistedKapitelId && ui.some((k) => k.id === persistedKapitelId)) return persistedKapitelId;
          return ui[0].id;
        });
      },
      (err) => {
        console.error('Error listening to kapitels:', err);
      }
    );

    return () => unsub();
  }, [user?.uid, projekt.id]);

  useEffect(() => {
    return () => {
      for (const entry of kapitelIndicatorUnsubsRef.current.values()) {
        entry.unsubscribe();
      }
      kapitelIndicatorUnsubsRef.current.clear();
    };
  }, []);

  useEffect(() => {
    return () => {
      for (const entry of kapitelArtifactUnsubsRef.current.values()) {
        entry.unsubscribe();
      }
      kapitelArtifactUnsubsRef.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!user?.uid) {
      for (const entry of kapitelIndicatorUnsubsRef.current.values()) {
        entry.unsubscribe();
      }
      kapitelIndicatorUnsubsRef.current.clear();
      setKapitelIndicatorById({});
      return;
    }

    const db = firestoreClient;
    const desiredByKapitel = new Map<string, string>();
    for (const kapitel of kapiteln) {
      const runId = (kapitel.activeRunId || kapitel.latestRunId || '').trim();
      if (runId) desiredByKapitel.set(kapitel.id, runId);
    }

    for (const [kapitelId, entry] of kapitelIndicatorUnsubsRef.current.entries()) {
      const desiredRunId = desiredByKapitel.get(kapitelId);
      if (!desiredRunId || desiredRunId !== entry.runId) {
        entry.unsubscribe();
        kapitelIndicatorUnsubsRef.current.delete(kapitelId);
        setKapitelIndicatorById((prev) => {
          if (!prev[kapitelId]) return prev;
          const next = { ...prev };
          delete next[kapitelId];
          return next;
        });
      }
    }

    for (const [kapitelId, runId] of desiredByKapitel.entries()) {
      if (kapitelIndicatorUnsubsRef.current.has(kapitelId)) continue;

      const runRef = doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId);
      const unsubscribe = onSnapshot(
        runRef,
        (snap) => {
          if (!snap.exists()) {
            setKapitelIndicatorById((prev) => ({ ...prev, [kapitelId]: { stage: 0, isProcessing: false } }));
            return;
          }
          const indicator = computeKapitelIndicatorFromRunDoc(snap.data());
          setKapitelIndicatorById((prev) => ({ ...prev, [kapitelId]: indicator }));
        },
        (err) => {
          console.error('Error listening to run indicator:', err);
          setKapitelIndicatorById((prev) => ({ ...prev, [kapitelId]: { stage: 0, isProcessing: false } }));
        }
      );

      kapitelIndicatorUnsubsRef.current.set(kapitelId, { runId, unsubscribe });
    }
  }, [user?.uid, kapiteln, computeKapitelIndicatorFromRunDoc]);

  useEffect(() => {
    if (!user?.uid) {
      for (const entry of kapitelArtifactUnsubsRef.current.values()) {
        entry.unsubscribe();
      }
      kapitelArtifactUnsubsRef.current.clear();
      setKapitelArtifactStageById({});
      return;
    }

    const db = firestoreClient;

    const desiredByKapitel = new Map<string, string>();
    for (const kapitel of kapiteln) {
      const runId = (kapitel.activeRunId || kapitel.latestRunId || '').trim();
      if (runId) desiredByKapitel.set(kapitel.id, runId);
    }

    for (const [kapitelId, entry] of kapitelArtifactUnsubsRef.current.entries()) {
      const desiredRunId = desiredByKapitel.get(kapitelId);
      if (!desiredRunId || desiredRunId !== entry.runId) {
        entry.unsubscribe();
        kapitelArtifactUnsubsRef.current.delete(kapitelId);
        setKapitelArtifactStageById((prev) => {
          if (!prev[kapitelId]) return prev;
          const next = { ...prev };
          delete next[kapitelId];
          return next;
        });
      }
    }

    const isArtifactSuccess = (data: any) => {
      const status = typeof data?.status === 'string' ? data.status : '';
      const content = typeof data?.content === 'string' ? data.content : '';
      return status === 'success' || content.trim().length > 0;
    };

    for (const [kapitelId, runId] of desiredByKapitel.entries()) {
      if (kapitelArtifactUnsubsRef.current.has(kapitelId)) continue;

      let combinedOk = false;
      let shortenedOk = false;
      let leseflussOk = false;

      const recompute = () => {
        const stage: 0 | 1 | 2 | 3 | 4 = leseflussOk ? 4 : shortenedOk ? 3 : combinedOk ? 2 : 0;
        setKapitelArtifactStageById((prev) => ({ ...prev, [kapitelId]: stage }));
      };

      const onError = (err: unknown) => {
        console.error('Error listening to artifact indicator:', kapitelId, runId, err);
        setKapitelArtifactStageById((prev) => ({ ...prev, [kapitelId]: 0 }));
      };

      const combinedRef = doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', 'combined');
      const shortenedRef = doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', 'shortened');
      const leseflussRef = doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', 'lesefluss');

      const unsubCombined = onSnapshot(
        combinedRef,
        (snap) => {
          combinedOk = snap.exists() && isArtifactSuccess(snap.data());
          recompute();
        },
        onError
      );
      const unsubShortened = onSnapshot(
        shortenedRef,
        (snap) => {
          shortenedOk = snap.exists() && isArtifactSuccess(snap.data());
          recompute();
        },
        onError
      );
      const unsubLesefluss = onSnapshot(
        leseflussRef,
        (snap) => {
          leseflussOk = snap.exists() && isArtifactSuccess(snap.data());
          recompute();
        },
        onError
      );

      const unsubscribe = () => {
        unsubCombined();
        unsubShortened();
        unsubLesefluss();
      };

      kapitelArtifactUnsubsRef.current.set(kapitelId, { runId, unsubscribe });
    }
  }, [user?.uid, kapiteln]);

  // Compute "overall" stage across ALL runs of a Kapitel (slow path for legacy data where artifactsStatus is missing).
  // This makes the left-panel indicator match what you see in the Kapitel workspace, even if the best text lives in an older run.
  useEffect(() => {
    if (!user?.uid) {
      kapitelOverallStageInFlightRef.current.clear();
      kapitelOverallStageComputedRef.current.clear();
      setKapitelOverallStageById({});
      return;
    }

    const db = firestoreClient;
    let cancelled = false;

    const isArtifactSuccess = (data: any) => {
      const status = typeof data?.status === 'string' ? data.status : '';
      const content = typeof data?.content === 'string' ? data.content : '';
      return status === 'success' || content.trim().length > 0;
    };

    const computeOverallStageForKapitel = async (kapitelId: string) => {
      try {
        const runsRef = collection(db, 'users', user.uid, 'kapitels', kapitelId, 'runs');
        const runsSnap = await getDocs(
          query(runsRef, where('archived', '==', false), orderBy('index', 'desc'), limit(MAX_RUN_HISTORY_LIMIT))
        );

        const runs = runsSnap.docs.map((d) => ({ id: d.id, data: d.data() as any }));

        const hasStatus = (artifactId: 'combined' | 'shortened' | 'lesefluss') =>
          runs.some((r) => (r.data?.artifactsStatus ?? {})[artifactId] === 'success');

        if (hasStatus('lesefluss')) return 4 as const;
        if (hasStatus('shortened')) return 3 as const;
        if (hasStatus('combined')) return 2 as const;

        const runIds = runs.map((r) => r.id);

        for (const runId of runIds) {
          const snap = await getDoc(
            doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', 'lesefluss')
          );
          if (snap.exists() && isArtifactSuccess(snap.data())) return 4 as const;
        }

        for (const runId of runIds) {
          const snap = await getDoc(
            doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', 'shortened')
          );
          if (snap.exists() && isArtifactSuccess(snap.data())) return 3 as const;
        }

        for (const runId of runIds) {
          const snap = await getDoc(
            doc(db, 'users', user.uid, 'kapitels', kapitelId, 'runs', runId, 'artifacts', 'combined')
          );
          if (snap.exists() && isArtifactSuccess(snap.data())) return 2 as const;
        }

        return 0 as const;
      } catch (err) {
        console.error('Failed to compute overall Kapitel stage:', kapitelId, err);
        return 0 as const;
      }
    };

    const kapitelIds = kapiteln.map((k) => k.id).filter((id) => !kapitelOverallStageComputedRef.current.has(id));
    if (!kapitelIds.length) return;

    let cursor = 0;
    const concurrency = 4;

    const worker = async () => {
      while (true) {
        const kapitelId = kapitelIds[cursor++];
        if (!kapitelId) return;

        if (kapitelOverallStageInFlightRef.current.has(kapitelId)) continue;
        kapitelOverallStageInFlightRef.current.add(kapitelId);

        const stage = await computeOverallStageForKapitel(kapitelId);

        kapitelOverallStageInFlightRef.current.delete(kapitelId);
        kapitelOverallStageComputedRef.current.add(kapitelId);

        if (!cancelled) {
          setKapitelOverallStageById((prev) => ({
            ...prev,
            [kapitelId]: Math.max(prev[kapitelId] ?? 0, stage) as 0 | 1 | 2 | 3 | 4,
          }));
        }
      }
    };

    Promise.all(Array.from({ length: concurrency }, worker));

    return () => {
      cancelled = true;
    };
  }, [user?.uid, kapiteln]);

  // hide initial skeleton once first client render completes
  useEffect(() => {
    setIsLoading(false);
  }, []);

  // Transform Firestore run data to UI runs, keep selection and Kapitel status in sync
  useEffect(() => {
    if (!activeKapitelId) {
      setRuns([]);
      setSelectedRunId(null);
      return;
    }

    const quellenMap = createQuellenMap(quellen);
    const assignedQuelleIds = activeKapitel?.assignedQuellenIds || [];

    // Deduplicate runs by id to avoid duplicate keys in run select
    const uniqueFbRuns = Array.from(
      fbRuns.reduce((map, run) => (map.has(run.id) ? map : map.set(run.id, run)), new Map<string, FirebaseKapitelRun>())
        .values()
    );
    uniqueFbRuns.sort((a, b) => Number(b.index ?? 0) - Number(a.index ?? 0));

    const uiRuns = uniqueFbRuns.map((fbRun) => {
      const uiRun = transformRunToUI(fbRun, activeKapitelId, quellenMap);
      const existingIds = new Set(uiRun.quellenErgebnisse.map((r) => r.quelleId));

      const resultsExpectedCount =
        typeof fbRun.resultsExpectedCount === 'number' ? fbRun.resultsExpectedCount : undefined;
      const resultsCompletedCount =
        typeof fbRun.resultsCompletedCount === 'number' ? fbRun.resultsCompletedCount : undefined;
      const hasRunningArtifacts = Boolean(
        fbRun.artifactsStatus && Object.values(fbRun.artifactsStatus).includes('running')
      );
      const hasRunningResult = fbRun.results.some((r) => r.status === 'running');
      const isProcessing =
        hasRunningArtifacts ||
        hasRunningResult ||
        (resultsExpectedCount != null &&
          resultsCompletedCount != null &&
          resultsCompletedCount < resultsExpectedCount);

      const expectedReached =
        resultsExpectedCount != null &&
        (resultsCompletedCount != null
          ? resultsCompletedCount >= resultsExpectedCount
          : fbRun.results.length >= resultsExpectedCount);

      const placeholderStatus =
        expectedReached || (!isProcessing && resultsExpectedCount == null)
          ? ('not-in-run' as const)
          : ('pending' as const);

      const placeholderResults = assignedQuelleIds
        .filter((id) => !existingIds.has(id))
        .map((id) => ({
          id,
          quelleId: id,
          quelleName: quellenMap.get(id) || '',
          text: '',
          status: placeholderStatus,
          cost: 0,
        }));

      return {
        ...uiRun,
        quellenErgebnisse: [...uiRun.quellenErgebnisse, ...placeholderResults],
      };
    });

    setRuns(uiRuns);

    if (uiRuns.length === 0) {
      setSelectedRunId(null);
      userSelectedRunRef.current = false;
    } else {
      const activeRunId = activeKapitel?.activeRunId;
      const preferredRunId =
        activeRunId && uiRuns.some((run) => run.id === activeRunId) ? activeRunId : uiRuns[0].id;
      const currentSelectedExists = selectedRunId != null && uiRuns.some((run) => run.id === selectedRunId);

      if (!currentSelectedExists) {
        handleSelectRun(preferredRunId);
      } else if (!userSelectedRunRef.current && selectedRunId !== preferredRunId) {
        handleSelectRun(preferredRunId);
      }
    }

  }, [fbRuns, quellen, activeKapitelId, activeKapitel?.assignedQuellenIds, activeKapitel?.activeRunId, selectedRunId, handleSelectRun]);

  // Handlers
  const handleSwitchProjekt = useCallback(
    async (projektId: string, fallbackProjekt?: Projekt) => {
      if (projektId === projekt.id) return;
      try {
        persistActiveProjektCookie(projektId);
        setIsLoading(true);
        await loadProjektData(projektId);
        const next = projekte.find((p) => p.id === projektId) || fallbackProjekt;
        if (next) {
          setProjekt(next);
        } else {
          // minimal fallback if not found
          setProjekt({ id: projektId, name: 'Projekt', createdAt: new Date(), archived: false });
        }
      } catch (error: any) {
        console.error('Projekt wechseln fehlgeschlagen:', error);
        toast.error('Projekt konnte nicht geladen werden', { description: error.message });
      } finally {
        setIsLoading(false);
      }
    },
    [loadProjektData, persistActiveProjektCookie, projekt.id, projekte]
  );

  const handleCreateProjekt = useCallback(
    async (name: string) => {
      if (isCreatingProjekt) return;
      setIsCreatingProjekt(true);
      const toastId = toast.loading('Projekt wird erstellt...');

      try {
        const result = await createProject(name);
        if (!result.success || !result.id) {
          throw new Error(result.error || 'Projekt konnte nicht erstellt werden.');
        }
        const newProjekt: Projekt = {
          id: result.id,
          name,
          createdAt: new Date(),
          archived: false,
        };
        setProjekte((prev) => [newProjekt, ...prev]);
        // Switch immediately using the newly created project
        persistActiveProjektCookie(result.id);
        setProjekt(newProjekt);
        await loadProjektData(result.id);
        toast.success('Projekt erstellt', { description: `"${name}" wurde erstellt.`, id: toastId });
      } catch (error: any) {
        console.error('Projekt erstellen fehlgeschlagen:', error);
        toast.error('Projekt konnte nicht erstellt werden', { description: error.message, id: toastId });
      } finally {
        setIsCreatingProjekt(false);
      }
    },
    [loadProjektData, isCreatingProjekt, persistActiveProjektCookie]
  );

  const handleArchiveProjekt = useCallback(
    async (projektId: string) => {
      if (projektId === 'default') {
        toast.error('Standardprojekt kann nicht archiviert werden');
        return;
      }

      const activeCount = projekte.filter((p) => p.archived !== true).length;
      if (activeCount <= 1) {
        toast.error('Projekt archivieren nicht möglich', { description: 'Mindestens ein aktives Projekt muss bestehen.' });
        return;
      }
      try {
        const result = await archiveProject(projektId);
        if (!result.success) {
          throw new Error(result.error || 'Projekt konnte nicht archiviert werden.');
        }
        setProjekte((prev) => prev.map((p) => (p.id === projektId ? { ...p, archived: true } : p)));
        const remainingActive = projekte.filter((p) => p.id !== projektId && p.archived !== true);
        if (projekt.id === projektId && remainingActive.length > 0) {
          persistActiveProjektCookie(remainingActive[0].id);
          setProjekt(remainingActive[0]);
          await loadProjektData(remainingActive[0].id);
        }
        toast.success('Projekt archiviert');
      } catch (error: any) {
        console.error('Projekt archivieren fehlgeschlagen:', error);
        toast.error('Projekt konnte nicht archiviert werden', { description: error.message });
      }
    },
    [loadProjektData, persistActiveProjektCookie, projekt.id, projekte]
  );

  const handleUnarchiveProjekt = useCallback(async (projektId: string) => {
    try {
      const result = await unarchiveProject(projektId);
      if (!result.success) {
        throw new Error(result.error || 'Projekt konnte nicht wiederhergestellt werden.');
      }

      setProjekte((prev) => prev.map((p) => (p.id === projektId ? { ...p, archived: false } : p)));
      toast.success('Projekt wiederhergestellt');
    } catch (error: any) {
      console.error('Projekt wiederherstellen fehlgeschlagen:', error);
      toast.error('Projekt konnte nicht wiederhergestellt werden', { description: error.message });
    }
  }, []);

  const handleAddQuelle = useCallback(
    async (name: string, text: string, imageFiles: File[] = [], advancedFields?: Record<string, any>): Promise<boolean> => {
      if (isAddingQuelle) return false;
      setIsAddingQuelle(true);

      const loadingToast = toast.loading('Quelle wird hinzugefügt...');
      const uploadingToast =
        imageFiles.length > 0
          ? toast.loading(`Lade ${imageFiles.length} Bild(er) hoch...`)
          : undefined;

      let imageMetadata: ImageMetadata[] = [];
      let success = false;

      try {
        // Upload images to Storage first (client-side)
        if (imageFiles.length > 0) {
          const { uploadImagesToStorage } = await import('@/app/lib/firebase/storage');
          imageMetadata = await uploadImagesToStorage(user!.uid, imageFiles);
        }

        // Create Quelle with image metadata (not files) and advanced fields
        const result = await createQuelle(name, text, projekt.id, imageMetadata, advancedFields);

        if (uploadingToast) toast.dismiss(uploadingToast);

        if (result.success) {
          success = true;
          toast.success('Quelle hinzugefügt', {
            description: `"${name}" wurde erfolgreich erstellt${imageFiles.length > 0 ? ` mit ${imageFiles.length} Bild(ern)` : ''}.`,
            id: loadingToast,
          });
          // Optimistically update UI
          const newQuelle: Quelle = {
            id: result.id!,
            name,
            text,
            projektId: projekt.id,
            createdAt: new Date(),
            images: result.imageUrls || [],
            // Include advanced fields in optimistic update
            ...advancedFields,
          };
          setQuellen((prev) => [...prev, newQuelle]);
        } else {
          toast.error('Fehler', { description: result.error, id: loadingToast });

          // Cleanup uploaded images if Firestore creation failed
          if (imageMetadata.length > 0) {
            const { deleteImagesFromStorage } = await import('@/app/lib/firebase/storage');
            await deleteImagesFromStorage(imageMetadata.map((img) => img.path));
          }
        }
      } catch (error) {
        if (uploadingToast) toast.dismiss(uploadingToast);
        toast.error('Upload fehlgeschlagen', {
          description: error instanceof Error ? error.message : 'Unbekannter Fehler',
          id: loadingToast,
        });

        // Cleanup uploaded images on error
        if (imageMetadata.length > 0) {
          const { deleteImagesFromStorage } = await import('@/app/lib/firebase/storage');
          await deleteImagesFromStorage(imageMetadata.map((img) => img.path));
        }
      } finally {
        setIsAddingQuelle(false);
      }

      return success;
    },
    [isAddingQuelle, projekt.id, user]
  );

  const handleDeleteQuelle = useCallback(async (id: string) => {
    if (deletingQuelleIds.includes(id)) return;
    setDeletingQuelleIds((prev) => [...prev, id]);
    const toastId = toast.loading('Quelle wird gelöscht...');

    try {
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
        toast.success('Quelle gelöscht', { id: toastId });
      } else {
        toast.error('Fehler', { description: result.error, id: toastId });
      }
    } catch (error: any) {
      toast.error('Fehler', { description: error?.message || 'Quelle konnte nicht gelöscht werden.', id: toastId });
    } finally {
      setDeletingQuelleIds((prev) => prev.filter((qid) => qid !== id));
    }
  }, [deletingQuelleIds]);

  const handleViewQuelle = useCallback(async (quelle: Quelle) => {
    setQuelleViewerLoading(true);
    setQuelleViewer({ ...quelle, text: '' });
    try {
      const content = await getQuelleContent(quelle.id);
      if (content?.text != null) {
        setQuelleViewer((prev) => (prev?.id === quelle.id ? { ...prev, text: content.text } : prev));
      }
    } finally {
      setQuelleViewerLoading(false);
    }
  }, []);

  const handleAssignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      if (assigningQuelleIds.includes(quelleId) || unassigningQuelleIds.includes(quelleId)) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      setAssigningQuelleIds((prev) => [...prev, quelleId]);

      const prevQuelleIds = kapitel.assignedQuellenIds;
      const newQuelleIds = [...prevQuelleIds, quelleId];

      // Optimistic update for snappier UI
      setKapiteln((prev) =>
        prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
      );

      const quelle = quellen.find((q) => q.id === quelleId);

      const toastId = toast.loading('Quelle wird zugewiesen...');

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
        toast.success('Quelle zugewiesen', {
          id: toastId,
          description: quelle ? `"${quelle.name}" wurde dem Kapitel hinzugefügt.` : undefined,
        });
      } catch (clientErr) {
        // Fallback to server action
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error, id: toastId });
        } else {
          toast.success('Quelle zugewiesen', {
            id: toastId,
            description: quelle ? `"${quelle.name}" wurde dem Kapitel hinzugefügt.` : undefined,
          });
        }
      } finally {
        setAssigningQuelleIds((prev) => prev.filter((id) => id !== quelleId));
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient, quellen, assigningQuelleIds, unassigningQuelleIds]
  );

  const handleUnassignQuelle = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId) return;
      if (unassigningQuelleIds.includes(quelleId) || assigningQuelleIds.includes(quelleId)) return;
      const kapitel = kapiteln.find((k) => k.id === activeKapitelId);
      if (!kapitel) return;

      setUnassigningQuelleIds((prev) => [...prev, quelleId]);

      const prevQuelleIds = kapitel.assignedQuellenIds;
      const newQuelleIds = prevQuelleIds.filter((id) => id !== quelleId);

      // Optimistic update for snappier UI
      setKapiteln((prev) =>
        prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: newQuelleIds } : k))
      );

      const quelle = quellen.find((q) => q.id === quelleId);

      const toastId = toast.loading('Quelle wird entfernt...');

      try {
        await persistKapitelQuellenClient(activeKapitelId, newQuelleIds);
        toast.success('Quelle entfernt', {
          id: toastId,
          description: quelle ? `"${quelle.name}" wurde vom Kapitel entfernt.` : undefined,
        });
      } catch (clientErr) {
        const result = await updateKapitelQuellen(activeKapitelId, newQuelleIds);
        if (!result.success) {
          setKapiteln((prev) =>
            prev.map((k) => (k.id === activeKapitelId ? { ...k, assignedQuellenIds: prevQuelleIds } : k))
          );
          toast.error('Fehler', { description: result.error, id: toastId });
        } else {
          toast.success('Quelle entfernt', {
            id: toastId,
            description: quelle ? `"${quelle.name}" wurde vom Kapitel entfernt.` : undefined,
          });
        }
      } finally {
        setUnassigningQuelleIds((prev) => prev.filter((id) => id !== quelleId));
      }
    },
    [activeKapitelId, kapiteln, persistKapitelQuellenClient, quellen, unassigningQuelleIds, assigningQuelleIds]
  );

  const handleAddKapitel = useCallback(async (title: string, nummer: string, thema: string) => {
    if (isCreatingKapitel) return;
    setIsCreatingKapitel(true);
    const toastId = toast.loading('Kapitel wird erstellt...');

    const tempId = `temp-${Date.now()}`;
    const newKapitel: Kapitel = {
      id: tempId,
      title,
      thema,
      nummer,
      status: 'nicht-verarbeitet',
      order: Date.now(),
      projektId: projekt.id,
      assignedQuellenIds: [],
    };

    // Optimistic UI update
    setKapiteln((prev) => [newKapitel, ...prev]);
    setActiveKapitelId(tempId);

    try {
      const newId = await createKapitelClient(title, nummer, null, thema);
      setKapiteln((prev) =>
        prev.map((k) => (k.id === tempId ? { ...k, id: newId } : k))
      );
      setActiveKapitelId(newId);
      toast.success('Kapitel erstellt', {
        description: `"${nummer} ${title}" wurde hinzugefügt.`,
        id: toastId,
      });
    } catch (clientErr) {
      // Fallback to server action
      const result = await createKapitel(title, [], null, nummer, projekt.id, thema);
      if (result.success && result.id) {
        setKapiteln((prev) =>
          prev.map((k) => (k.id === tempId ? { ...k, id: result.id! } : k))
        );
        setActiveKapitelId(result.id);
        toast.success('Kapitel erstellt', {
          description: `"${nummer} ${title}" wurde hinzugefügt.`,
          id: toastId,
        });
      } else {
        // Revert on failure
        setKapiteln((prev) => prev.filter((k) => k.id !== tempId));
        setActiveKapitelId((prev) => (prev === tempId ? kapiteln[0]?.id || '' : prev));
        toast.error('Fehler', { description: result.error || (clientErr as Error).message, id: toastId });
      }
    } finally {
      setIsCreatingKapitel(false);
    }
  }, [createKapitelClient, kapiteln, projekt.id, isCreatingKapitel]);

  const handleDeleteKapitel = useCallback(
    async (id: string) => {
      const prevKapiteln = kapiteln;
      const remaining = kapiteln.filter((k) => k.id !== id);
      setKapiteln(remaining);
      if (activeKapitelId === id) {
        setActiveKapitelId(remaining[0]?.id || '');
      }
      setDeleteConfirm(null);

      try {
        await deleteKapitelClient(id);
        toast.success('Kapitel gelöscht');
      } catch (clientErr) {
        const result = await deleteKapitelAction(id);
        if (result.success) {
          toast.success('Kapitel gelöscht');
        } else {
          // Revert on failure
          setKapiteln(prevKapiteln);
          setActiveKapitelId(activeKapitelId);
          toast.error('Fehler', { description: result.error || (clientErr as Error).message });
        }
      }
    },
    [activeKapitelId, kapiteln, deleteKapitelClient]
  );

  const handleEditKapitel = useCallback(async (id: string, title: string, nummer: string, thema: string) => {
    if (isEditingKapitel) return;
    setIsEditingKapitel(true);
    const toastId = toast.loading('Kapitel wird aktualisiert...');

    const prevKapiteln = kapiteln;
    setKapiteln((prev) => prev.map((k) => (k.id === id ? { ...k, title, nummer, thema } : k)));

    try {
      await updateKapitelTitleClient(id, title, nummer, thema);
      toast.success('Kapitel aktualisiert', {
        description: `"${nummer} ${title}" wurde gespeichert.`,
        id: toastId,
      });
    } catch (clientErr) {
      const result = await updateKapitelTitle(id, title, nummer, thema);
      if (!result.success) {
        setKapiteln(prevKapiteln);
        toast.error('Fehler', { description: result.error || (clientErr as Error).message, id: toastId });
      } else {
        toast.success('Kapitel aktualisiert', {
          description: `"${nummer} ${title}" wurde gespeichert.`,
          id: toastId,
        });
      }
    } finally {
      setIsEditingKapitel(false);
    }
  }, [kapiteln, updateKapitelTitleClient, isEditingKapitel]);

  useEffect(() => {
    const loadPrompts = async () => {
      try {
        const res = await fetch('/api/prompt-templates', { cache: 'no-store' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Prompts konnten nicht geladen werden.');
        setPromptTemplates(data.templates || []);
        setSystemPromptTemplates(Array.isArray(data.systemTemplates) ? data.systemTemplates : []);
        setPromptActive(data.active || {});
        setAskOnEachProcess(Boolean(data.askOnEachProcess));
      } catch (err: any) {
        console.error('Prompt templates load failed', err);
        toast.error('Prompts', { description: err?.message || 'Prompts konnten nicht geladen werden.' });
      }
    };
    loadPrompts();
  }, []);

  const applyActivePrompt = useCallback(async (stage: PromptStage, templateId: string | 'default') => {
    setPromptActive((prev) => ({ ...prev, [stage]: templateId }));
    try {
      await fetch('/api/prompt-templates/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage, templateId }),
      });
    } catch (err) {
      console.error('Aktives Prompt setzen fehlgeschlagen', err);
    }
  }, []);

  const requestPromptChoice = useCallback(
    async (stages: PromptStage[]): Promise<Record<PromptStage, string | 'default'> | null> => {
      // Ensure we have the freshest askOnEachProcess flag in case the user just toggled it elsewhere.
      let shouldAsk = askOnEachProcess;
      if (!askOnEachProcess) {
        try {
          const res = await fetch('/api/prompt-templates/settings');
          if (res.ok) {
            const data = await res.json();
            if (typeof data.askOnEachProcess === 'boolean') {
              shouldAsk = data.askOnEachProcess;
              setAskOnEachProcess(data.askOnEachProcess);
            }
          }
        } catch (err) {
          console.error('askOnEachProcess fetch failed', err);
        }
      }

      if (!shouldAsk) {
        return null;
      }

      return new Promise((resolve) => {
        setPromptChooser({ stages, resolve });
      });
    },
    [askOnEachProcess]
  );

  const handleProcess = useCallback(
    async (settings: ProcessingSettings) => {
      if (!activeKapitel) return;

      if (!(await ensureOpenAIAccess())) return;

      const assignedQuellen = quellen.filter((q) => activeKapitel.assignedQuellenIds.includes(q.id));
      if (assignedQuellen.length === 0) {
        toast.error('Keine Quellen', {
          description: 'Füge zuerst Quellen zu diesem Kapitel hinzu.',
        });
        return;
      }

      if (!settings.ueberschrift.trim() || !settings.thema.trim()) {
        toast.error('Bitte Überschrift und Thema angeben.');
        return;
      }

      const token = Cookies.get('__session');
      if (!token) {
        handleAuthFailure();
        return;
      }

      const requestedStages: PromptStage[] = settings.directCombine
        ? ['process_quelle', 'combine']
        : ['process_quelle'];
      const providedChoices = settings.promptChoice;
      const choices = providedChoices ?? (await requestPromptChoice(requestedStages));
      if (askOnEachProcess && !providedChoices && choices === null) {
        toast.info('Aktion abgebrochen');
        return;
      }

      // If the user changed their standard prompt in another tab (Profil), refresh selections once.
      let activeSnapshot = promptActive;
      if (!providedChoices && !choices) {
        try {
          const res = await fetch('/api/prompt-templates', { cache: 'no-store' });
          const data = await res.json();
          if (res.ok) {
            if (Array.isArray(data.templates)) setPromptTemplates(data.templates);
            if (Array.isArray(data.systemTemplates)) setSystemPromptTemplates(data.systemTemplates);
            if (data.active) {
              setPromptActive(data.active);
              activeSnapshot = data.active;
            }
            if (typeof data.askOnEachProcess === 'boolean') setAskOnEachProcess(Boolean(data.askOnEachProcess));
          }
        } catch (err) {
          console.error('Prompt templates refresh failed', err);
        }
      }

      const processChoice =
        providedChoices?.process_quelle ??
        choices?.process_quelle ??
        (activeSnapshot.process_quelle as string | 'default') ??
        'default';
      const combineChoice = settings.directCombine
        ? providedChoices?.combine ??
          choices?.combine ??
          (activeSnapshot.combine as string | 'default') ??
          'default'
        : undefined;

      const shouldApplyChoice = Boolean(providedChoices || choices);
      if (shouldApplyChoice) {
        await applyActivePrompt('process_quelle', processChoice);
        if (settings.directCombine && combineChoice) {
          await applyActivePrompt('combine', combineChoice);
        }
      }

      const runInstruction = settings.thema.trim();

      setIsProcessingRun(true);
      setProcessingDialogOpen(false);
      const processingToastId = toast.loading('Verarbeitung gestartet', {
        description: `"${settings.ueberschrift}" wird mit ${assignedQuellen.length} Quellen verarbeitet...`,
      });

      try {
        const result = await createKapitelRun(activeKapitelId, runInstruction, settings.model, {
          autoCombine: settings.directCombine,
          promptTemplateId: processChoice,
          promptPayload: {
            heading: settings.ueberschrift.trim(),
            topic: settings.thema.trim(),
          },
          grundlegendeInformationen: settings.grundlegendeInfos?.trim() || undefined,
          ueberschrift: settings.ueberschrift.trim(),
          thema: settings.thema.trim(),
        });

        if (!result.success || !result.runId) {
          throw new Error(result.error || 'Run konnte nicht erstellt werden.');
        }

        // Optimistically show the new run while Firestore listeners update
        setFbRuns((prev) => {
          if (prev.some((r) => r.id === result.runId)) return prev;
          const combinedStatus = settings.directCombine ? 'running' : 'empty';
          return [
            {
              id: result.runId!,
              index: result.index ?? (prev[0]?.index || 0) + 1,
              instruction: runInstruction,
              model: settings.model,
              createdAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
              promptTemplateId: processChoice,
              promptPayload: {
                heading: settings.ueberschrift.trim(),
                topic: settings.thema.trim(),
              },
              autoCombine: settings.directCombine,
              results: [],
              artifacts: { combined: null, shortened: null, lesefluss: null },
              artifactsStatus: { combined: combinedStatus, shortened: 'empty', lesefluss: 'empty' },
              resultsExpectedCount: assignedQuellen.length,
              resultsCompletedCount: 0,
              resultsWithContentCount: 0,
              lastResultAt: null,
              lastActivityAt: new Date().toISOString(),
              ueberschrift: settings.ueberschrift.trim(),
              thema: settings.thema.trim(),
              grundlegendeInformationen: settings.grundlegendeInfos?.trim() || null,
            },
            ...prev,
          ];
        });
        handleSelectRun(result.runId);
        toast.success('Run erstellt', {
          description: 'Die Verarbeitung wurde gestartet...',
          id: processingToastId,
        });

        // Queue processing for all assigned Quellen (mirrors previous implementation)
        const queue = [...assignedQuellen];
        const concurrency = Math.min(3, queue.length || 1);

        let authFailed = false;
        let serverUnavailable = false;

        const worker = async () => {
          while (queue.length > 0 && !authFailed && !serverUnavailable) {
            const nextQuelle = queue.shift();
            if (!nextQuelle) return;
            try {
              const response = await fetch(`${API_BASE_URL}/api/process`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({
                  quelle_id: nextQuelle.id,
                  kapitel_id: activeKapitelId,
                  run_id: result.runId,
                  model: settings.model,
                }),
              });

              if (!response.ok) {
                if (response.status === 401) {
                  authFailed = true;
                  queue.length = 0;
                  toast.error('Verarbeitung abgebrochen', {
                    description: 'Bitte melde dich erneut an.',
                    id: processingToastId,
                  });
                  handleAuthFailure();
                  return;
                }

                const errorBody = await response.json().catch(() => ({}));
                const error: any = new Error(errorBody.detail || 'Fehler beim Verarbeiten');
                error.status = response.status;
                throw error;
              }
            } catch (err: any) {
              if (authFailed || serverUnavailable) return;

              const status = err?.status;
              if (status === 401) {
                authFailed = true;
                queue.length = 0;
                toast.error('Verarbeitung abgebrochen', {
                  description: 'Bitte melde dich erneut an.',
                  id: processingToastId,
                });
                handleAuthFailure();
                return;
              }

              if (err instanceof TypeError || (typeof status === 'number' && status >= 500)) {
                serverUnavailable = true;
                queue.length = 0;
                notifyServerDown(processingToastId);
                return;
              }

              console.error(`Error processing Quelle ${nextQuelle?.id}:`, err);
              toast.error('Fehler bei einer Quelle', {
                description: err.message || 'Unbekannter Fehler beim Verarbeiten der Quelle',
                id: processingToastId,
              });
            }
          }
        };

        await Promise.all(Array.from({ length: concurrency }, () => worker()));

        if (authFailed || serverUnavailable) {
          return;
        }

        toast.success('Verarbeitung läuft', {
          description: 'Die Quellen werden nacheinander verarbeitet.',
          id: processingToastId,
        });
      } catch (error: any) {
        console.error('Fehler beim Starten der Verarbeitung:', error);
        toast.error('Fehler beim Erstellen des Runs', {
          description: error.message || 'Ein Fehler ist aufgetreten.',
          id: processingToastId,
        });
      } finally {
        setIsProcessingRun(false);
      }
    },
    [
      activeKapitelId,
      activeKapitel,
      ensureOpenAIAccess,
      handleAuthFailure,
      handleSelectRun,
      notifyServerDown,
      quellen,
      requestPromptChoice,
      askOnEachProcess,
      promptActive,
      applyActivePrompt,
      isProcessingRun,
    ]
  );

  const handleCombineTexts = useCallback(async () => {
    if (!activeKapitelId || !selectedRun) {
      toast.error('Kein Run ausgewählt');
      return;
    }

    if (selectedRun.combinedStatus === 'running') {
      toast.info('Kombination laeuft bereits', {
        description: 'Bitte warte, bis die Kombination abgeschlossen ist.',
      });
      return;
    }

    if (!(await ensureOpenAIAccess())) return;

    const readyResults = selectedRun.quellenErgebnisse?.filter((r) => r.status === 'success' && r.text?.trim()) || [];
    if (readyResults.length < 2) {
      toast.error('Zu wenige Texte zum Kombinieren', {
        description: 'Mindestens zwei Quellen müssen ein Ergebnis haben.',
      });
      return;
    }

    const token = Cookies.get('__session');
    if (!token) {
      handleAuthFailure();
      return;
    }

    if (isCombining) return;
    setIsCombining(true);

    if (askOnEachProcess) {
      const choice = await requestPromptChoice(['combine']);
      if (!choice) {
        toast.info('Aktion abgebrochen');
        setIsCombining(false);
        return;
      }
      await applyActivePrompt('combine', choice.combine ?? 'default');
    }

    const combineToastId = toast.loading('Texte kombinieren', {
      description: 'Die Texte werden kombiniert...',
    });

    try {
      const response = await fetch(`${API_BASE_URL}/api/combine-run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          kapitel_id: activeKapitelId,
          run_id: selectedRun.id,
        }),
      });

      if (!response.ok) {
        if (response.status === 401) {
          toast.error('Kombination abgebrochen', {
            description: 'Bitte melde dich erneut an.',
            id: 'combine',
          });
          handleAuthFailure();
          return;
        }

        if (response.status >= 500) {
          notifyServerDown(combineToastId);
          return;
        }

        const error = await response.json().catch(() => ({}));
        const err: any = new Error(error.detail || 'Fehler beim Kombinieren');
        err.status = response.status;
        throw err;
      }

      toast.success('Kombination gestartet', {
        description: 'Die Texte werden nun zusammengeführt.',
        id: combineToastId,
      });
      } catch (err: any) {
        if (err instanceof TypeError) {
          notifyServerDown(combineToastId);
          setIsCombining(false);
          return;
        }

        if (err?.status === 401) {
          handleAuthFailure();
          setIsCombining(false);
        return;
      }

      console.error('Fehler beim Kombinieren:', err);
        toast.error('Combine fehlgeschlagen', {
          description: err.message || 'Unbekannter Fehler beim Kombinieren',
          id: combineToastId,
        });
      } finally {
      setIsCombining(false);
    }
  }, [
    activeKapitelId,
    ensureOpenAIAccess,
    handleAuthFailure,
    notifyServerDown,
    selectedRun,
    askOnEachProcess,
    requestPromptChoice,
    applyActivePrompt,
    isCombining,
  ]);

  const handleAdoptSingleTextAsCombined = useCallback(
    async (quelleId: string) => {
      if (!activeKapitelId || !selectedRun) {
        toast.error('Kein Run ausgew„hlt');
        return;
      }

      if (selectedRun.combinedStatus === 'running') {
        toast.info('Kombination laeuft bereits', {
          description: 'Bitte warte, bis die Kombination abgeschlossen ist.',
        });
        return;
      }

      const eligible =
        selectedRun.quellenErgebnisse?.filter((r) => r.status === 'success' && r.text?.trim()) || [];
      if (eligible.length !== 1) {
        toast.error('Uebernehmen nicht moeglich', {
          description: 'Es muss genau ein verwertbarer Quellentext vorhanden sein.',
        });
        return;
      }

      if (eligible[0].quelleId !== quelleId) {
        toast.error('Uebernehmen nicht moeglich', {
          description: 'Die ausgewaehlte Quelle ist nicht der einzige verwertbare Text in diesem Run.',
        });
        return;
      }

      const token = Cookies.get('__session');
      if (!token) {
        handleAuthFailure();
        return;
      }

      if (isCombining) return;
      setIsCombining(true);

      const adoptToastId = toast.loading('Text uebernehmen', {
        description: 'Der Quellentext wird als kombinierter Text uebernommen...',
      });

      try {
        const response = await fetch(`${API_BASE_URL}/api/adopt-combined`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            kapitel_id: activeKapitelId,
            run_id: selectedRun.id,
            quelle_id: quelleId,
          }),
        });

        if (!response.ok) {
          if (response.status === 401) {
            toast.error('Uebernehmen abgebrochen', {
              description: 'Bitte melde dich erneut an.',
              id: adoptToastId,
            });
            handleAuthFailure();
            return;
          }

          if (response.status >= 500) {
            notifyServerDown(adoptToastId);
            return;
          }

          const error = await response.json().catch(() => ({}));
          const err: any = new Error(error.detail || 'Fehler beim Uebernehmen');
          err.status = response.status;
          throw err;
        }

        toast.success('Text uebernommen', {
          description: 'Der Quellentext ist jetzt der kombinierte Text.',
          id: adoptToastId,
        });
      } catch (err: any) {
        if (err instanceof TypeError) {
          notifyServerDown(adoptToastId);
          return;
        }

        if (err?.status === 401) {
          handleAuthFailure();
          return;
        }

        console.error('Fehler beim Uebernehmen:', err);
        toast.error('Uebernehmen fehlgeschlagen', {
          description: err.message || 'Unbekannter Fehler beim Uebernehmen',
          id: adoptToastId,
        });
      } finally {
        setIsCombining(false);
      }
    },
    [activeKapitelId, handleAuthFailure, isCombining, notifyServerDown, selectedRun]
  );

  const handleShorten = useCallback(
    async (contextKapitelIds: string[], promptChoice?: Partial<Record<PromptStage, string | 'default'>>) => {
      if (!activeKapitel || !selectedRun) return;

      if (selectedRun.shortenedStatus === 'running') {
        toast.info('Kuerzung laeuft bereits', {
          description: 'Bitte warte, bis die Kuerzung abgeschlossen ist.',
        });
        return;
      }

      if (!(await ensureOpenAIAccess())) return;

      if (contextKapitelIds.length === 0) {
        toast.error('Keine Kontextkapitel ausgewählt', {
          description: 'Wähle mindestens ein Kapitel als Kontext aus.',
        });
        return;
      }

      if (isShortening) return;
      setIsShortening(true);

      const providedChoices = promptChoice;
      if (askOnEachProcess && !providedChoices) {
        const choice = await requestPromptChoice(['shorten', 'summary']);
        if (!choice) {
          toast.info('Aktion abgebrochen');
          setIsShortening(false);
          return;
        }
        await applyActivePrompt('shorten', choice.shorten ?? 'default');
        await applyActivePrompt('summary', choice.summary ?? 'default');
      }
      if (providedChoices) {
        await applyActivePrompt('shorten', providedChoices.shorten ?? 'default');
        await applyActivePrompt('summary', providedChoices.summary ?? 'default');
      }

      const shortenToastId = toast.loading('Text wird gekürzt', {
        description: 'Der Text wird mit Hilfe der ausgewählten Kapitel gekürzt...',
      });

      try {
        const result = await createShortenRun(activeKapitelId, selectedRun.id, contextKapitelIds);

        if (!result?.success) {
          const message = result?.error || 'Kürzung konnte nicht gestartet werden.';
          const lower = message.toLowerCase();

          if (lower.includes('sitzung')) {
            toast.error('Kürzung abgebrochen', {
              description: message,
              id: shortenToastId,
            });
            handleAuthFailure();
            return;
          }

          if (lower.includes('fastapi-server')) {
            notifyServerDown(shortenToastId);
            return;
          }

          toast.error('Kürzung fehlgeschlagen', {
            description: message,
            id: shortenToastId,
          });
          return;
        }

        toast.success('Kürzung gestartet', {
          description: 'Der Text wird nun gekürzt und entdupliziert.',
          id: shortenToastId,
        });
      } catch (err: any) {
        console.error('Fehler beim Kürzen:', err);
        const message = err?.message || 'Unbekannter Fehler beim Kürzen';

        if (message.toLowerCase().includes('sitzung')) {
          toast.error('Kürzung abgebrochen', {
            description: message,
            id: shortenToastId,
          });
          handleAuthFailure();
          return;
        }

        if (message.toLowerCase().includes('fastapi-server')) {
          notifyServerDown(shortenToastId);
          return;
        }

        toast.error('Kürzung fehlgeschlagen', {
          description: message,
          id: shortenToastId,
        });
      } finally {
        setIsShortening(false);
      }
    },
    [
      activeKapitelId,
      activeKapitel,
      ensureOpenAIAccess,
      handleAuthFailure,
      notifyServerDown,
      selectedRun,
      askOnEachProcess,
      requestPromptChoice,
      applyActivePrompt,
      isShortening,
    ]
  );

  const handleLesefluss = useCallback(
    async (
      contextKapitelIds: string[],
      aufgabenstellung: string,
      promptChoice?: Partial<Record<PromptStage, string | 'default'>>
    ) => {
      if (!activeKapitel || !selectedRun) return;

      if (selectedRun.leseflussStatus === 'running') {
        toast.info('Lesefluss laeuft bereits', {
          description: 'Bitte warte, bis der Lesefluss abgeschlossen ist.',
        });
        return;
      }

      if (!(await ensureOpenAIAccess())) return;

      if (contextKapitelIds.length === 0) {
        toast.error('Keine Kontextkapitel ausgewählt', {
          description: 'Wähle mindestens ein Kapitel als Kontext aus.',
        });
        return;
      }

      if (isImprovingLesefluss) return;
      setIsImprovingLesefluss(true);

      const providedChoices = promptChoice;
      if (askOnEachProcess && !providedChoices) {
        const choice = await requestPromptChoice(['lesefluss', 'summary']);
        if (!choice) {
          toast.info('Aktion abgebrochen');
          setIsImprovingLesefluss(false);
          return;
        }
        await applyActivePrompt('lesefluss', choice.lesefluss ?? 'default');
        await applyActivePrompt('summary', choice.summary ?? 'default');
      }
      if (providedChoices) {
        await applyActivePrompt('lesefluss', providedChoices.lesefluss ?? 'default');
        await applyActivePrompt('summary', providedChoices.summary ?? 'default');
      }

      const leseflussToastId = toast.loading('Lese Fluss wird verbessert', {
        description: 'Der Text wird nun mit verbessertem Lesefluss erstellt...',
      });

      try {
        const result = await createLeseflussRun(activeKapitelId, selectedRun.id, contextKapitelIds, aufgabenstellung);

        if (!result?.success) {
          const message = result?.error || 'Lese Fluss verbessern konnte nicht gestartet werden.';
          const lower = message.toLowerCase();

          if (lower.includes('sitzung')) {
            toast.error('Lese Fluss abgebrochen', {
              description: message,
              id: leseflussToastId,
            });
            handleAuthFailure();
            return;
          }

          if (lower.includes('fastapi-server')) {
            notifyServerDown(leseflussToastId);
            return;
          }

          toast.error('Lese Fluss fehlgeschlagen', {
            description: message,
            id: leseflussToastId,
          });
          return;
        }

        toast.success('Lese Fluss gestartet', {
          description: 'Der Text wird nun mit verbessertem Lesefluss erstellt.',
          id: leseflussToastId,
        });
      } catch (err: any) {
        console.error('Fehler beim Lese Fluss:', err);
        const message = err?.message || 'Unbekannter Fehler beim Lese Fluss';

        if (message.toLowerCase().includes('sitzung')) {
          toast.error('Lese Fluss abgebrochen', {
            description: message,
            id: leseflussToastId,
          });
          handleAuthFailure();
          return;
        }

        if (message.toLowerCase().includes('fastapi-server')) {
          notifyServerDown(leseflussToastId);
          return;
        }

        toast.error('Lese Fluss fehlgeschlagen', {
          description: message,
          id: leseflussToastId,
        });
      } finally {
        setIsImprovingLesefluss(false);
      }
    },
    [
      activeKapitelId,
      activeKapitel,
      ensureOpenAIAccess,
      handleAuthFailure,
      notifyServerDown,
      selectedRun,
      askOnEachProcess,
      requestPromptChoice,
      applyActivePrompt,
      isImprovingLesefluss,
    ]
  );

  const handleExportDocx = useCallback(
    async (selection: 'all' | 'selected', kapitelIds: string[]) => {
      if (!projekt?.id) return;
      if (!user?.uid) return;

      if (!(await ensureOpenAIAccess())) return;
      if (isExportingDocx) return;

      if (kapitelIds.length === 0) {
        toast.error('Keine Kapitel ausgewählt', {
          description: 'Wähle mindestens ein Kapitel für den Export aus.',
        });
        return;
      }

      cleanupExportWatcher();
      setIsExportingDocx(true);

      let progress = 8;
      const renderProgress = () => (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">
            Du kannst die Seite schließen. Den Download findest du später unter Profil → Meine Exporte.
          </div>
          <Progress value={progress} />
        </div>
      );

      const exportToastId = toast.loading('Export wird erstellt', {
        description: renderProgress(),
      });
      exportToastIdRef.current = exportToastId;

      try {
        const result = await createDocxExport(projekt.id, selection, kapitelIds);

        if (!result?.success) {
          const message = result?.error || 'Export konnte nicht gestartet werden.';
          const lower = message.toLowerCase();

          if (lower.includes('sitzung')) {
            toast.error('Export abgebrochen', { description: message, id: exportToastId });
            handleAuthFailure();
            setIsExportingDocx(false);
            return;
          }

          if (lower.includes('fastapi-server')) {
            notifyServerDown(exportToastId);
            setIsExportingDocx(false);
            return;
          }

          toast.error('Export fehlgeschlagen', { description: message, id: exportToastId });
          setIsExportingDocx(false);
          return;
        }

        const exportId = (result.data as any)?.export_id as string | undefined;
        if (!exportId) {
          toast.error('Export fehlgeschlagen', { description: 'Export-ID fehlt.', id: exportToastId });
          setIsExportingDocx(false);
          return;
        }

        exportIntervalRef.current = setInterval(() => {
          progress = Math.min(90, progress + Math.max(1, Math.round(Math.random() * 6)));
          toast.loading('Export wird erstellt', { id: exportToastId, description: renderProgress() });
        }, 650);

        const exportDocRef = doc(firestoreClient, 'users', user.uid, 'exports', exportId);
        exportUnsubRef.current = onSnapshot(
          exportDocRef,
          (snap) => {
            if (!snap.exists()) return;
            const data = snap.data() as any;
            const status = String(data.status || '');

            if (status === 'running') return;

            cleanupExportWatcher();

            if (status === 'success') {
              progress = 100;
              const file = data.file || {};
              const storagePath = String(file.storagePath || '');
              const fileName = String(file.fileName || 'export.docx');

              toast.success('Export fertig', {
                id: exportToastId,
                description: (
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs text-muted-foreground">Download wird vorbereitet...</span>
                    <Button size="sm" variant="outline" disabled>
                      Download
                    </Button>
                  </div>
                ),
              });

              void (async () => {
                try {
                  if (!storagePath) throw new Error('Kein Dateipfad gefunden.');
                  const downloadUrl = await getDownloadUrlFromStorage(storagePath);
                  toast.success('Export fertig', {
                    id: exportToastId,
                    description: (
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-xs text-muted-foreground">Download bereit.</span>
                        <Button asChild size="sm">
                          <a href={downloadUrl} rel="noreferrer" download={fileName}>
                            Download
                          </a>
                        </Button>
                      </div>
                    ),
                  });
                } catch (err: unknown) {
                  const message = err instanceof Error ? err.message : 'Unbekannter Fehler';
                  toast.error('Download fehlgeschlagen', {
                    description: message,
                  });
                }
              })();
            } else {
              toast.error('Export fehlgeschlagen', {
                id: exportToastId,
                description: 'Bitte versuche es später erneut.',
              });
            }

            setIsExportingDocx(false);
          },
          (err) => {
            console.error('Export listen failed:', err);
            cleanupExportWatcher();
            toast.error('Export fehlgeschlagen', { id: exportToastId });
            setIsExportingDocx(false);
          }
        );
      } catch (err: any) {
        console.error('Export error:', err);
        cleanupExportWatcher();
        toast.error('Export fehlgeschlagen', {
          id: exportToastId,
          description: err?.message || 'Unbekannter Fehler',
        });
        setIsExportingDocx(false);
      }
    },
    [
      cleanupExportWatcher,
      ensureOpenAIAccess,
      handleAuthFailure,
      isExportingDocx,
      notifyServerDown,
      projekt?.id,
      user?.uid,
    ]
  );

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
    return <DashboardSkeleton showQuellenPanel={showQuellenPanel} />;
  }

  const assignedQuellen = quellen.filter((q) => activeKapitel?.assignedQuellenIds.includes(q.id));
  // Keep the workspace skeleton visible until we have a selected run *and* the UI-transformed run list is ready.
  // This avoids a brief blank state between "runs snapshot arrived" and "runs + selection resolved".
  const kapitelWorkspaceLoading =
    isKapitelLoading || (fbRuns.length > 0 && runs.length === 0) || (runs.length > 0 && !selectedRun);

  const kapitelNavigatorIndicators = kapiteln.reduce<Record<string, { stage: 0 | 1 | 2 | 3 | 4; isProcessing: boolean }>>(
    (acc, kapitel) => {
      const base = kapitelIndicatorById[kapitel.id];
      const artifactStage = kapitelArtifactStageById[kapitel.id] ?? 0;
      const overallStage = kapitelOverallStageById[kapitel.id] ?? 0;
      const stage = (Math.max(base?.stage ?? 0, artifactStage, overallStage) as 0 | 1 | 2 | 3 | 4);
      const isProcessing = base?.isProcessing ?? false;
      acc[kapitel.id] = { stage, isProcessing };
      return acc;
    },
    {}
  );

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Left Navigator */}
      <div className="w-64 border-r border-border bg-sidebar flex flex-col">
        <ProjektHeader
          projekt={projekt}
          projekte={projekte}
          onSwitchProjekt={handleSwitchProjekt}
          onCreateProjekt={handleCreateProjekt}
          onArchiveProjekt={(id, name) => setDeleteConfirm({ type: 'projekt', id, name })}
          onUnarchiveProjekt={handleUnarchiveProjekt}
          isCreatingProjekt={isCreatingProjekt}
          onOpenExport={() => setExportDialogOpen(true)}
          isExporting={isExportingDocx}
        />
        <KapitelNavigator
          kapiteln={kapiteln}
          kapitelIndicators={kapitelNavigatorIndicators}
          activeKapitelId={activeKapitelId}
          onKapitelSelect={handleKapitelSelect}
          onAddKapitel={handleAddKapitel}
          onDeleteKapitel={(id, name) => setDeleteConfirm({ type: 'kapitel', id, name })}
          onEditKapitel={handleEditKapitel}
          addKapitelLoading={isCreatingKapitel}
          editKapitelLoading={isEditingKapitel}
        />
      </div>

      {/* Main Workspace */}
      <div className="flex-1 overflow-hidden flex">
        <div className="flex-1 overflow-hidden">
          {activeKapitel ? (
            <KapitelWorkspace
              loading={kapitelWorkspaceLoading}
              kapitel={activeKapitel}
              assignedQuellen={assignedQuellen}
              runs={runs}
              selectedRun={selectedRun}
              allKapitels={kapiteln}
              onLoadAllRuns={() => {
                setRunListLimit(MAX_RUN_HISTORY_LIMIT);
                setAllRunsLoaded(true);
              }}
              allRunsLoaded={allRunsLoaded}
              onSelectRun={handleUserSelectRun}
              onOpenTextViewer={setTextViewerContent}
              onOpenProcessing={() => setProcessingDialogOpen(true)}
              onCombineTexts={handleCombineTexts}
              onAdoptSingleTextAsCombined={handleAdoptSingleTextAsCombined}
              isCombining={isCombining}
              onToggleQuellenPanel={handleToggleQuellenPanel}
              onOpenShorten={() => setShortenDialogOpen(true)}
              onOpenLesefluss={() => setLeseflussDialogOpen(true)}
              onOpenLeseflussRefinement={() => setLeseflussRefinementDialogOpen(true)}
              onOpenCombinedRefinement={() => setCombinedRefinementDialogOpen(true)}
              onOpenShortenedRefinement={() => setShortenedRefinementDialogOpen(true)}
              onOpenResultRefinement={(quelleId, quelleName) => {
                setResultRefinementTarget({ quelleId, quelleName });
                setResultRefinementDialogOpen(true);
              }}
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
              onViewQuelle={handleViewQuelle}
              isAddingQuelle={isAddingQuelle}
              assigningQuelleIds={assigningQuelleIds}
              unassigningQuelleIds={unassigningQuelleIds}
              deletingQuelleIds={deletingQuelleIds}
            />
          ))}
      </div>

      <TextViewerModal content={textViewerContent} onClose={() => setTextViewerContent(null)} />
      <QuelleViewerModal
        quelle={quelleViewer}
        loading={quelleViewerLoading}
        open={!!quelleViewer}
        onOpenChange={(open) => {
          if (!open) setQuelleViewer(null);
        }}
      />

      <ExportDialog
        open={exportDialogOpen}
        onOpenChange={setExportDialogOpen}
        allKapitels={kapiteln}
        projektId={projekt.id}
        onExport={handleExportDocx}
        isExporting={isExportingDocx}
      />

      {activeKapitel && (
        <ProcessingDialog
          open={processingDialogOpen}
          onOpenChange={setProcessingDialogOpen}
          kapitelTitle={activeKapitel.title}
          kapitelThema={activeKapitel.thema || ''}
          quellenCount={assignedQuellen.length}
          askOnEachProcess={askOnEachProcess}
          promptTemplates={promptTemplates}
          systemPromptTemplates={systemPromptTemplates}
          promptActive={promptActive}
          onProcess={handleProcess}
          isProcessing={isProcessingRun}
        />
      )}

      {activeKapitel && selectedRun && (
        <ShortenDialog
          open={shortenDialogOpen}
          onOpenChange={setShortenDialogOpen}
          allKapitels={kapiteln}
          currentKapitelId={activeKapitel.id}
          runModel={selectedRun.model}
          onShorten={handleShorten}
          askOnEachProcess={askOnEachProcess}
          promptTemplates={promptTemplates}
          systemPromptTemplates={systemPromptTemplates}
          promptActive={promptActive}
          isShortening={isShortening}
        />
      )}

      {activeKapitel && selectedRun && (
        <LeseflussDialog
          open={leseflussDialogOpen}
          onOpenChange={setLeseflussDialogOpen}
          projektId={projekt.id}
          allKapitels={kapiteln}
          currentKapitelId={activeKapitel.id}
          runModel={selectedRun.model}
          onLesefluss={handleLesefluss}
          askOnEachProcess={askOnEachProcess}
          promptTemplates={promptTemplates}
          systemPromptTemplates={systemPromptTemplates}
          promptActive={promptActive}
          isLeseflussLoading={isImprovingLesefluss}
        />
      )}

      {activeKapitel && selectedRun && (
        <CombinedRefinementDialog
          open={combinedRefinementDialogOpen}
          onOpenChange={setCombinedRefinementDialogOpen}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          runModel={selectedRun.model}
          kapitelLabel={`${activeKapitel.nummer} ${activeKapitel.title}`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {activeKapitel && selectedRun && (
        <ShortenedRefinementDialog
          open={shortenedRefinementDialogOpen}
          onOpenChange={setShortenedRefinementDialogOpen}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          kapitelLabel={`${activeKapitel.nummer} ${activeKapitel.title}`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {activeKapitel && selectedRun && (
        <LeseflussRefinementDialog
          open={leseflussRefinementDialogOpen}
          onOpenChange={setLeseflussRefinementDialogOpen}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          kapitelLabel={`${activeKapitel.nummer} ${activeKapitel.title}`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {activeKapitel && selectedRun && resultRefinementTarget && (
        <ResultRefinementDialog
          open={resultRefinementDialogOpen}
          onOpenChange={(open) => {
            setResultRefinementDialogOpen(open);
            if (!open) setResultRefinementTarget(null);
          }}
          kapitelId={activeKapitel.id}
          runId={selectedRun.id}
          quelleId={resultRefinementTarget.quelleId}
          quelleName={resultRefinementTarget.quelleName}
          kapitelLabel={`${activeKapitel.nummer} ${activeKapitel.title}`}
          ensureOpenAIAccess={ensureOpenAIAccess}
          onAuthFailure={handleAuthFailure}
          onServerDown={notifyServerDown}
          onOpenTextViewer={setTextViewerContent}
        />
      )}

      {promptChooser && (
        <PromptSelectDialog
          open={!!promptChooser}
          stages={promptChooser.stages}
          templates={promptTemplates}
          systemTemplates={systemPromptTemplates}
          active={promptActive}
          onConfirm={(choices) => {
            promptChooser.resolve(choices);
            setPromptChooser(null);
          }}
          onCancel={() => {
            promptChooser.resolve(null);
            setPromptChooser(null);
          }}
        />
      )}

      <DeleteConfirmDialog
        open={deleteConfirm !== null}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
        type={deleteConfirm?.type || 'quelle'}
        name={deleteConfirm?.name || ''}
        onConfirm={() => {
          const current = deleteConfirm;
          setDeleteConfirm(null);
          if (!current) return;

          if (current.type === 'quelle') {
            handleDeleteQuelle(current.id);
          } else if (current.type === 'kapitel') {
            handleDeleteKapitel(current.id);
          } else if (current.type === 'projekt') {
            handleArchiveProjekt(current.id);
          }
        }}
      />

      {/* Viewport Warning */}
      <ViewportWarning />
    </div>
  );
}

// Status is now maintained via lightweight live listeners per Kapitel
