'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import { requireAuth } from '@/app/lib/auth/server-auth';
import {
  collection,
  doc,
  getDoc,
  getDocs,
  getCountFromServer,
  limit,
  orderBy,
  query,
  startAfter,
  type DocumentData,
  type CollectionReference,
  type Firestore,
  type Query,
  type QueryDocumentSnapshot,
} from 'firebase/firestore';

export type LiveUserStats = {
  totalCost: number; // cents
  totalRuns: number; // OpenAI operations
  totalProjekte: number;
  totalKapitel: number;
  totalQuellen: number;
  totalWords: number; // estimated from output tokens
  runsByMonth: { month: string; runs: number; cost: number }[];
  costByProjekt: { projektName: string; cost: number }[];
  modelUsage: { model: string; count: number }[];
  memberSince: string; // ISO
};

function toIso(candidate: unknown): string | null {
  if (!candidate) return null;
  if (typeof candidate === 'string') return candidate;
  if (candidate instanceof Date) return candidate.toISOString();
  const toDate = (candidate as { toDate?: unknown })?.toDate;
  if (typeof toDate === 'function') {
    try {
      return (toDate as () => Date)().toISOString();
    } catch {
      return null;
    }
  }
  return null;
}

function monthKey(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function addMonths(d: Date, delta: number): Date {
  const copy = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
  copy.setUTCMonth(copy.getUTCMonth() + delta);
  return copy;
}

function monthLabelDe(d: Date): string {
  return d.toLocaleDateString('de-DE', { month: 'long' });
}

function centsFromUsd(value: unknown): number {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return 0;
  return Math.round(num * 100);
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object') return {};
  return value as Record<string, unknown>;
}

async function safeCount(ref: CollectionReference<DocumentData>): Promise<number> {
  try {
    const snap = await getCountFromServer(ref);
    return Number(snap.data().count || 0);
  } catch {
    const snap = await getDocs(ref);
    return snap.size;
  }
}

function displayModelKey(key: string): string {
  // cost_service sanitizes '.' -> '_' for map keys (e.g., gpt-5.2 -> gpt-5_2)
  if (!key) return key;
  if (key.includes('_')) return key.replaceAll('_', '.');
  return key;
}

async function getMemberSinceIso(db: Firestore, uid: string): Promise<string> {
  const candidates: Array<string> = [];

  try {
    const userSnap = await getDoc(doc(db, 'users', uid));
    if (userSnap.exists()) {
      const iso = toIso(userSnap.data()?.createdAt);
      if (iso) candidates.push(iso);
    }
  } catch {
    // ignore
  }

  const firstCreatedAt = async (colPath: string): Promise<string | null> => {
    try {
      const q = query(
        collection(db, 'users', uid, colPath),
        orderBy('createdAt', 'asc'),
        limit(1)
      );
      const snap = await getDocs(q);
      const first = snap.docs[0];
      if (!first) return null;
      return toIso(first.data()?.createdAt);
    } catch {
      return null;
    }
  };

  const projectIso = await firstCreatedAt('projects');
  if (projectIso) candidates.push(projectIso);
  const kapitelIso = await firstCreatedAt('kapitels');
  if (kapitelIso) candidates.push(kapitelIso);
  const quelleIso = await firstCreatedAt('quellen');
  if (quelleIso) candidates.push(quelleIso);

  const sorted = candidates
    .map((x) => new Date(x))
    .filter((d) => !Number.isNaN(d.getTime()))
    .sort((a, b) => a.getTime() - b.getTime());

  return (sorted[0] || new Date()).toISOString();
}

type OperationScanResult = {
  outputTokens: number;
  modelCounts: Map<string, number>;
};

async function scanOperationsForBackfill(
  db: Firestore,
  uid: string,
  maxDocs = 5000
): Promise<OperationScanResult> {
  let outputTokens = 0;
  const modelCounts = new Map<string, number>();

  let fetched = 0;
  let cursor: QueryDocumentSnapshot<DocumentData> | null = null;

  while (fetched < maxDocs) {
    const base = collection(db, 'users', uid, 'costMetrics', 'v1', 'operations');
    let qRef: Query<DocumentData>;
    if (cursor) {
      qRef = query(base, orderBy('timestamp', 'desc'), startAfter(cursor), limit(500));
    } else {
      qRef = query(base, orderBy('timestamp', 'desc'), limit(500));
    }

    const snap = await getDocs(qRef);
    if (snap.empty) break;

    for (const docSnap of snap.docs) {
      const data = asRecord(docSnap.data());
      const tokens = asRecord(data.tokens);
      const out = Number(tokens.outputTokens || 0);
      if (Number.isFinite(out)) outputTokens += out;

      const modelRaw = data.modelNormalized ?? data.model ?? data.modelKey ?? 'unknown';
      const modelStr = String(modelRaw || 'unknown');
      const model = modelStr.includes('_') ? displayModelKey(modelStr) : modelStr;
      modelCounts.set(model, (modelCounts.get(model) ?? 0) + 1);
    }

    fetched += snap.docs.length;
    cursor = snap.docs[snap.docs.length - 1];
    if (snap.docs.length < 500) break;
  }

  return { outputTokens, modelCounts };
}

export async function getLiveUserStats(): Promise<LiveUserStats> {
  const user = await requireAuth();
  if (!user) throw new Error('Not authenticated');

  const db = await getFirestoreForUser();
  const uid = user.uid;

  const [totalProjekte, totalKapitel, totalQuellen] = await Promise.all([
    safeCount(collection(db, 'users', uid, 'projects')),
    safeCount(collection(db, 'users', uid, 'kapitels')),
    safeCount(collection(db, 'users', uid, 'quellen')),
  ]);

  const aggregateRef = doc(db, 'users', uid, 'costMetrics', 'v1', 'aggregatesByUser', 'lifetime');
  const aggSnap = await getDoc(aggregateRef);
  const agg = asRecord(aggSnap.exists() ? aggSnap.data() : {});

  const totalCost = centsFromUsd(agg.totalCostUsd);
  const totalRuns = Number(agg.operationCount || 0);

  // Runs by month: show last 6 months (including current)
  const byTime = asRecord(agg.byTimePeriod);
  const now = new Date();
  const runsByMonth = Array.from({ length: 6 }).map((_, idx) => {
    const d = addMonths(now, -(5 - idx));
    const key = monthKey(d);
    const entry = asRecord(byTime[key]);
    return {
      month: monthLabelDe(d),
      runs: Number(entry.count || 0),
      cost: centsFromUsd(entry.totalCostUsd),
    };
  });

  // Cost per project: join project names with cost aggregates.
  let projectsSnap;
  try {
    projectsSnap = await getDocs(query(collection(db, 'users', uid, 'projects'), orderBy('createdAt', 'desc')));
  } catch {
    projectsSnap = await getDocs(collection(db, 'users', uid, 'projects'));
  }
  const projects = projectsSnap.docs.map((d) => ({ id: d.id, data: asRecord(d.data()) }));
  const projectNameById = new Map<string, string>();
  for (const p of projects) {
    projectNameById.set(p.id, String(p.data.name || p.id));
  }

  const projectAggSnap = await getDocs(collection(db, 'users', uid, 'costMetrics', 'v1', 'aggregatesByProject'));
  const costByProjectId = new Map<string, number>();
  for (const d of projectAggSnap.docs) {
    const data = asRecord(d.data());
    costByProjectId.set(d.id, centsFromUsd(data.totalCostUsd));
    if (!projectNameById.has(d.id)) {
      const projektSnapshot = asRecord(data.projektSnapshot);
      const snapName = projektSnapshot.name;
      if (snapName) projectNameById.set(d.id, String(snapName));
    }
  }

  const costByProjekt = Array.from(projectNameById.entries()).map(([id, name]) => ({
    projektName: name,
    cost: costByProjectId.get(id) ?? 0,
  }));
  costByProjekt.sort((a, b) => b.cost - a.cost);
  if (costByProjekt.length === 0) {
    costByProjekt.push({ projektName: 'Standard', cost: 0 });
  }

  // Model usage from aggregates (fallback to empty)
  const byModel = asRecord(agg.byModel);
  let modelUsage = Object.entries(byModel)
    .map(([key, val]) => {
      const count = typeof val === 'number' ? Number(val || 0) : Number(asRecord(val).count || 0);
      return { model: displayModelKey(key), count };
    })
    .filter((m) => Number.isFinite(m.count) && m.count > 0)
    .sort((a, b) => b.count - a.count);

  // Estimated generated words from output tokens.
  let totalOutputTokens = Number(agg.totalOutputTokens || 0);
  const needsBackfillFromOps =
    !Number.isFinite(totalOutputTokens) || totalOutputTokens <= 0 || modelUsage.length === 0;

  if (needsBackfillFromOps) {
    // Backfill estimate from operations (read-only).
    const scan = await scanOperationsForBackfill(db, uid);
    if (!Number.isFinite(totalOutputTokens) || totalOutputTokens <= 0) {
      totalOutputTokens = scan.outputTokens;
    }
    if (modelUsage.length === 0) {
      modelUsage = Array.from(scan.modelCounts.entries())
        .map(([model, count]) => ({ model, count }))
        .sort((a, b) => b.count - a.count);
    }
  }

  if (modelUsage.length === 0) modelUsage.push({ model: '-', count: 0 });
  const totalWords = Math.max(0, Math.round(totalOutputTokens * 0.75));

  const memberSince = await getMemberSinceIso(db, uid);

  return {
    totalCost,
    totalRuns,
    totalProjekte,
    totalKapitel,
    totalQuellen,
    totalWords,
    runsByMonth,
    costByProjekt,
    modelUsage,
    memberSince,
  };
}
