'use server';

import { revalidatePath } from 'next/cache';
import {
  setUserBlockedByEmail,
  setUserCanDuplicateSystemPromptsByEmail,
  setUserCanUsePdfScanByEmail,
  setUserCanUseQuellenFinderByEmail,
  setUserCanViewUsageInsightsByEmail,
  setUserFullAccessByEmail,
} from '@/app/lib/api/adminServer';

function normalizeEmail(value: unknown): string {
  const email = String(value || '').trim();
  return email;
}

export async function adminSetUserFullAccess(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const raw = String(formData.get('fullAccess') ?? 'true').trim().toLowerCase();
  const fullAccess = raw === 'true' || raw === '1' || raw === 'yes' || raw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine g〕tige E-Mail angeben.');
  }

  await setUserFullAccessByEmail(email, fullAccess);
  revalidatePath('/admin');
}

export async function adminSetUserBlocked(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const raw = String(formData.get('blocked') ?? 'true').trim().toLowerCase();
  const blocked = raw === 'true' || raw === '1' || raw === 'yes' || raw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine g〕tige E-Mail angeben.');
  }

  await setUserBlockedByEmail(email, blocked);
  revalidatePath('/admin');
}

export async function adminSetCanDuplicateSystemPrompts(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const allowRaw = String(formData.get('canDuplicateSystemPrompts') ?? 'false').trim().toLowerCase();
  const allow = allowRaw === 'true' || allowRaw === '1' || allowRaw === 'yes' || allowRaw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine g?tige E-Mail angeben.');
  }

  await setUserCanDuplicateSystemPromptsByEmail(email, allow);
  revalidatePath('/admin');
}

export async function adminSetCanViewUsageInsights(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const allowRaw = String(formData.get('canViewUsageInsights') ?? 'false').trim().toLowerCase();
  const allow = allowRaw === 'true' || allowRaw === '1' || allowRaw === 'yes' || allowRaw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine gültige E-Mail angeben.');
  }

  await setUserCanViewUsageInsightsByEmail(email, allow);
  revalidatePath('/admin');
}

export async function adminSetCanUseQuellenFinder(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const allowRaw = String(formData.get('canUseQuellenFinder') ?? 'false').trim().toLowerCase();
  const allow = allowRaw === 'true' || allowRaw === '1' || allowRaw === 'yes' || allowRaw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine gültige E-Mail angeben.');
  }

  await setUserCanUseQuellenFinderByEmail(email, allow);
  revalidatePath('/admin');
}

export async function adminSetCanUsePdfScan(formData: FormData) {
  const email = normalizeEmail(formData.get('email'));
  const allowRaw = String(formData.get('canUsePdfScan') ?? 'false').trim().toLowerCase();
  const allow = allowRaw === 'true' || allowRaw === '1' || allowRaw === 'yes' || allowRaw === 'on';

  if (!email || !email.includes('@')) {
    throw new Error('Bitte eine gültige E-Mail angeben.');
  }

  await setUserCanUsePdfScanByEmail(email, allow);
  revalidatePath('/admin');
}

