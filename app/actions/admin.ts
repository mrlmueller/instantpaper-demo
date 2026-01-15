'use server';

import { revalidatePath } from 'next/cache';
import {
  setUserBlockedByEmail,
  setUserCanDuplicateSystemPromptsByEmail,
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

