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
} from 'firebase/firestore';
import { requireAuth } from '@/app/lib/auth/server-auth';
import { revalidatePath } from 'next/cache';

export type KapitelRunResult = {
  quelleId: string;
  resultContent: string;
  modelUsed: string;
  tokensUsed: number;
  inputTokens: number;
  outputTokens: number;
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
};

export type Kapitel = {
  id: string;
  title: string;
  createdAt: string;
  quelleIds: string[];
  runs?: KapitelRun[];
};

export async function createKapitel(title: string, quelleIds: string[]) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const kapitelsRef = collection(db, 'users', user.uid, 'kapitels');
    const docRef = await addDoc(kapitelsRef, {
      title,
      quelleIds,
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

export async function deleteKapitel(kapitelId: string) {
  try {
    const user = await requireAuth();
    const db = await getFirestoreForUser();

    const kapitelRef = doc(db, 'users', user.uid, 'kapitels', kapitelId);
    const kapitelDoc = await getDoc(kapitelRef);
    if (!kapitelDoc.exists()) {
      throw new Error('Kapitel not found');
    }

    await deleteDoc(kapitelRef);
    revalidatePath('/dashboard');
    return { success: true };
  } catch (error: any) {
    console.error('Error deleting Kapitel:', error);
    return { success: false, error: error.message };
  }
}

export async function createKapitelRun(kapitelId: string, instruction: string, model: string) {
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
          modelUsed: resData.model_used ?? resData.modelUsed ?? '',
          tokensUsed: resData.tokens_used ?? resData.tokensUsed ?? 0,
          inputTokens: resData.input_tokens ?? resData.inputTokens ?? 0,
          outputTokens: resData.output_tokens ?? resData.outputTokens ?? 0,
          cost: resData.cost ?? 0,
          createdAt: resData.created_at?.toDate?.()?.toISOString()
            || resData.createdAt?.toDate?.()?.toISOString()
            || new Date().toISOString(),
        };
      });

      runs.push({
        id: runDoc.id,
        index: runData.index || 0,
        instruction: runData.instruction || '',
        model: runData.model || '',
        createdAt: runData.createdAt?.toDate?.()?.toISOString()
          || runData.created_at?.toDate?.()?.toISOString()
          || new Date().toISOString(),
        results,
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
        quelleIds: data.quelleIds || [],
        createdAt: data.createdAt?.toDate?.()?.toISOString() || new Date().toISOString(),
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
