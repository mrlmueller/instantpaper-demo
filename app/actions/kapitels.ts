'use server';

import { getFirestoreForUser } from '@/app/lib/firebase/serverApp';
import {
  collection,
  addDoc,
  updateDoc,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  query,
  orderBy,
  limit,
  serverTimestamp,
  type Firestore,
  type DocumentReference,
} from 'firebase/firestore';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';

export type KapitelRunResult = {
  quelleId: string;
  resultContent: string;
  hasContent?: boolean;
  modelUsed: string;
  tokensUsed: number;
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  cost: number;
  createdAt: string;
};

export type CombinedResult = {
  id: string;
  combinedContent: string;
  sourceQuelleIds: string[];
  heading: string;
  topic: string;
  modelUsed: string;
  tokensUsed: number;
  inputTokens: number;
  cachedInputTokens: number;
  outputTokens: number;
  reasoningTokens: number;
  cost: number;
  createdAt: string;
};

export type KapitelRun = {
  id: string;
  index: number;
  instruction: string;
  model: string;
  createdAt: string;
  results: KapitelRunResult[];
  combined?: CombinedResult | null;
  promptTemplateId?: string;
  promptPayload?: Record<string, any>;
  autoCombine?: boolean;
};

export type Kapitel = {
  id: string;
  title: string;
  nummer?: string; // e.g., "1", "1.1", "1.1.1" - hierarchical chapter number
  createdAt: string;
  quelleIds: string[];
  runs?: KapitelRun[];
  parentId?: string | null;
  order?: number;
};

// Helper function to check for circular references in parent chain
async function checkCircularReference(
  db: Firestore,
  userId: string,
  kapitelId: string,
  targetParentId: string | null
): Promise<boolean> {
  if (!targetParentId) return false;

  let currentId: string | null = targetParentId;
  const visited = new Set<string>([kapitelId]);

  while (currentId) {
    if (visited.has(currentId)) {
      return true; // Circular reference detected
    }
    visited.add(currentId);

    const parentRef: DocumentReference = doc(db, 'users', userId, 'kapitels', currentId);
    const parentDoc = await getDoc(parentRef);

    if (!parentDoc.exists()) {
      break;
    }

    currentId = parentDoc.data()?.parentId || null;
  }

  return false;
}

// Helper function to calculate depth of a Kapitel in the hierarchy
async function getKapitelDepth(
  db: Firestore,
  userId: string,
  kapitelId: string | null
): Promise<number> {
  if (!kapitelId) return 0;

  let depth = 0;
  let currentId: string | null = kapitelId;

  while (currentId && depth < 10) { // Safety limit
    const kapitelRef: DocumentReference = doc(db, 'users', userId, 'kapitels', currentId);
    const kapitelDoc = await getDoc(kapitelRef);

    if (!kapitelDoc.exists()) {
      break;
    }

    currentId = kapitelDoc.data()?.parentId || null;
    if (currentId) depth++;
  }

  return depth;
}

// Helper function to get next order value for siblings
async function getNextOrderForParent(
  db: Firestore,
  userId: string,
  parentId: string | null
): Promise<number> {
  const kapitelsRef = collection(db, 'users', userId, 'kapitels');
  let q;

  if (parentId === null) {
    // Root level kapitels (no parent)
    q = query(kapitelsRef, orderBy('order', 'desc'), limit(1));
  } else {
    // Child kapitels with specific parent
    q = query(kapitelsRef, orderBy('order', 'desc'), limit(1));
  }

  const snapshot = await getDocs(q);

  if (snapshot.empty) {
    return 0;
  }

  // Filter by parentId in memory (Firestore doesn't support complex queries on optional fields)
  const siblings = snapshot.docs.filter(doc => {
    const data = doc.data();
    return (data.parentId || null) === parentId;
  });

  if (siblings.length === 0) {
    return 0;
  }

  const maxOrder = Math.max(...siblings.map(doc => doc.data().order || 0));
  return maxOrder + 1;
}

export async function createKapitel(
  title: string,
  quelleIds: string[],
  parentId?: string | null,
  nummer?: string
) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    // Validate parentId if provided
    if (parentId) {
      const parentRef = doc(db, 'users', user.uid, 'kapitels', parentId);
      const parentDoc = await getDoc(parentRef);

      if (!parentDoc.exists()) {
        return { success: false, error: 'Parent Kapitel not found' };
      }

      // Check depth - enforce maximum of 5 levels
      const parentDepth = await getKapitelDepth(db, user.uid, parentId);
      if (parentDepth >= 4) {
        return {
          success: false,
          error: 'Maximum nesting depth (5 levels) would be exceeded',
        };
      }
    }

    // Get next order value for siblings
    const order = await getNextOrderForParent(db, user.uid, parentId || null);

    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const docRef = await addDoc(kapitelsRef, {
      title,
      nummer: nummer || '1', // Default to '1' if not provided
      quelleIds,
      parentId: parentId || null,
      order,
      createdAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true, id: docRef.id };
  } catch (error: any) {
    console.error('Error creating Kapitel:', error);
    return { success: false, error: error.message };
  }
}

export async function updateKapitelQuellen(kapitelId: string, quelleIds: string[]) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      throw new Error('Kapitel not found');
    }

    await updateDoc(kapitelRef, {
      quelleIds,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating Kapitel Quellen:', error);
    return { success: false, error: error.message };
  }
}

export async function updateKapitelParent(
  kapitelId: string,
  newParentId: string | null
) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      return { success: false, error: 'Kapitel not found' };
    }

    // Check for circular reference
    if (newParentId) {
      const hasCircular = await checkCircularReference(
        db,
        user.uid,
        kapitelId,
        newParentId
      );

      if (hasCircular) {
        return {
          success: false,
          error: 'Cannot set parent: would create circular reference',
        };
      }

      // Validate new parent exists
      const parentRef = doc(db, 'users', user.uid, 'kapitels', newParentId);
      const parentDoc = await getDoc(parentRef);
      if (!parentDoc.exists()) {
        return { success: false, error: 'Parent Kapitel not found' };
      }

      // Check depth
      const parentDepth = await getKapitelDepth(db, user.uid, newParentId);
      if (parentDepth >= 4) {
        return {
          success: false,
          error: 'Maximum nesting depth (5 levels) would be exceeded',
        };
      }
    }

    // Get next order for new parent's children
    const order = await getNextOrderForParent(db, user.uid, newParentId);

    await updateDoc(kapitelRef, {
      parentId: newParentId,
      order,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating Kapitel parent:', error);
    return { success: false, error: error.message };
  }
}

export async function updateKapitelTitle(
  kapitelId: string,
  title: string,
  nummer: string
) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      throw new Error('Kapitel not found');
    }

    await updateDoc(kapitelRef, {
      title,
      nummer,
      updatedAt: serverTimestamp(),
    });

    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error updating Kapitel title:', error);
    return { success: false, error: error.message };
  }
}

export async function deleteKapitel(
  kapitelId: string,
  deleteStrategy: 'promote' | 'cascade' = 'promote'
) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      throw new Error('Kapitel not found');
    }

    const kapitelData = kapitelDoc.data();
    const parentId = kapitelData.parentId || null;

    // Find all children of this Kapitel
    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const childrenSnapshot = await getDocs(kapitelsRef);
    const children = childrenSnapshot.docs
      .filter((doc) => doc.data().parentId === kapitelId)
      .map((doc) => ({ id: doc.id, ...doc.data() }));

    if (deleteStrategy === 'cascade') {
      // Recursively delete all descendants
      for (const child of children) {
        await deleteKapitel(child.id, 'cascade');
      }
    } else {
      // Promote children to parent's level
      for (const child of children) {
        const childRef = doc(db, 'users', user.uid, 'kapitels', child.id);
        await updateDoc(childRef, {
          parentId: parentId,
          updatedAt: serverTimestamp(),
        });
      }
    }

    // Delete the Kapitel itself
    await deleteDoc(kapitelRef);
    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error deleting Kapitel:', error);
    return { success: false, error: error.message };
  }
}

export async function createKapitelRun(
  kapitelId: string,
  instruction: string,
  model: string,
  options?: {
    promptTemplateId?: string;
    promptPayload?: Record<string, any>;
    autoCombine?: boolean;
    grundlegendeInformationen?: string;
    ueberschrift?: string; // Heading for the chapter
    thema?: string; // Topic/theme (can be same as instruction or separate)
  }
) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const runsRef = collection(db, 'users', user.uid, 'kapitels', kapitelId, 'runs');

    // Determine next run index
    const lastRunSnapshot = await getDocs(query(runsRef, orderBy('index', 'desc'), limit(1)));
    const lastIndex = lastRunSnapshot.empty ? 0 : (lastRunSnapshot.docs[0].data().index || 0);
    const nextIndex = lastIndex + 1;

    const runDoc = await addDoc(runsRef, {
      instruction,
      model,
      index: nextIndex,
      createdAt: serverTimestamp(),
      promptTemplateId: options?.promptTemplateId,
      promptPayload: options?.promptPayload,
      autoCombine: options?.autoCombine ?? false,
      grundlegendeInformationen: options?.grundlegendeInformationen || null,
      ueberschrift: options?.ueberschrift || null,
      thema: options?.thema || null,
    });

    revalidatePath('/dashboard');
    return { success: true, runId: runDoc.id, index: nextIndex };
  } catch (error: any) {
    console.error('Error creating Kapitel run:', error);
    return { success: false, error: error.message };
  }
}

export async function getKapitelRuns(kapitelId: string, runLimit = 10): Promise<KapitelRun[]> {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const runsRef = collection(db, 'users', user.uid, 'kapitels', kapitelId, 'runs');
    const runsSnapshot = await getDocs(query(runsRef, orderBy('index', 'desc'), limit(runLimit)));

    const runs: KapitelRun[] = [];

    for (const runDoc of runsSnapshot.docs) {
      const runData = runDoc.data();
      const resultsRef = collection(
        db,
        'users',
        user.uid,
        'kapitels',
        kapitelId,
        'runs',
        runDoc.id,
        'results'
      );

      const resultsSnapshot = await getDocs(resultsRef);
      const results: KapitelRunResult[] = resultsSnapshot.docs.map((resDoc) => {
        const resData = resDoc.data();
        return {
          quelleId: resDoc.id,
          resultContent: resData.result_content ?? resData.resultContent ?? '',
          hasContent: resData.has_content ?? resData.hasContent ?? true,
          modelUsed: resData.model_used ?? resData.modelUsed ?? '',
          tokensUsed: resData.tokens_used ?? resData.tokensUsed ?? 0,
          inputTokens: resData.input_tokens ?? resData.inputTokens ?? 0,
          cachedInputTokens: resData.cached_input_tokens ?? resData.cachedInputTokens ?? 0,
          outputTokens: resData.output_tokens ?? resData.outputTokens ?? 0,
          reasoningTokens: resData.reasoning_tokens ?? resData.reasoningTokens ?? 0,
          cost: resData.cost ?? 0,
          createdAt: resData.created_at?.toDate?.()?.toISOString()
            || resData.createdAt?.toDate?.()?.toISOString()
            || new Date().toISOString(),
        };
      });

      // fetch combined (single doc named 'combined' if it exists)
      const combinedRef = collection(
        db,
        'users',
        user.uid,
        'kapitels',
        kapitelId,
        'runs',
        runDoc.id,
        'combined'
      );
      const combinedSnapshot = await getDocs(combinedRef);
      let combined: CombinedResult | null = null;
      if (!combinedSnapshot.empty) {
        const doc = combinedSnapshot.docs[0];
        const c = doc.data();
        combined = {
          id: doc.id,
          combinedContent: c.combined_content ?? c.combinedContent ?? '',
          sourceQuelleIds: c.source_quelle_ids ?? c.sourceQuelleIds ?? [],
          heading: c.heading ?? '',
          topic: c.topic ?? '',
          modelUsed: c.model_used ?? c.modelUsed ?? '',
          tokensUsed: c.tokens_used ?? c.tokensUsed ?? 0,
          inputTokens: c.input_tokens ?? c.inputTokens ?? 0,
          cachedInputTokens: c.cached_input_tokens ?? c.cachedInputTokens ?? 0,
          outputTokens: c.output_tokens ?? c.outputTokens ?? 0,
          reasoningTokens: c.reasoning_tokens ?? c.reasoningTokens ?? 0,
          cost: c.cost ?? 0,
          createdAt:
            c.created_at?.toDate?.()?.toISOString() ||
            c.createdAt?.toDate?.()?.toISOString() ||
            new Date().toISOString(),
        };
      }

      runs.push({
        id: runDoc.id,
        index: runData.index || 0,
        instruction: runData.instruction || '',
        model: runData.model || '',
        promptTemplateId: runData.promptTemplateId,
        promptPayload: runData.promptPayload,
        autoCombine: runData.autoCombine ?? false,
        createdAt: runData.createdAt?.toDate?.()?.toISOString()
          || runData.created_at?.toDate?.()?.toISOString()
          || new Date().toISOString(),
        results,
        combined,
      });
    }

    return runs;
  } catch (error: any) {
    console.error('Error fetching Kapitel runs:', error);
    return [];
  }
}

export async function getUserKapitels(withRuns = true, runLimit = 5): Promise<Kapitel[]> {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const snapshot = await getDocs(query(kapitelsRef, orderBy('createdAt', 'desc')));

    const kapitels: Kapitel[] = [];

    for (const kapitelDoc of snapshot.docs) {
      const data = kapitelDoc.data();
      const kapitel: Kapitel = {
        id: kapitelDoc.id,
        title: data.title,
        nummer: data.nummer || '1', // Default to '1' for existing kapitels without nummer
        quelleIds: data.quelleIds || [],
        createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
        parentId: data.parentId || null,
        order: data.order ?? 0,
      };

      if (withRuns) {
        kapitel.runs = await getKapitelRuns(kapitelDoc.id, runLimit);
      }

      kapitels.push(kapitel);
    }

    return kapitels;
  } catch (error: any) {
    console.error('Error getting user Kapitels:', error);
    return [];
  }
}
