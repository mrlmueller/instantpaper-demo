import 'server-only';

import { cookies } from 'next/headers';

const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

type FastApiErrorPayload = { detail?: unknown };

async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const data = (await res.json()) as FastApiErrorPayload;
    if (typeof data?.detail === 'string' && data.detail.trim()) return data.detail.trim();
  } catch {
    // ignore
  }
  return null;
}

export async function isAdminUser(): Promise<boolean> {
  const token = await getAuthTokenOrNullAsync();
  if (!token) return false;

  const res = await fetch(`${API_BASE_URL}/api/admin/me`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });

  return res.ok;
}

export type AdminUserRow = {
  uid: string | null;
  email: string | null;
  displayName: string | null;
  fullAccess: boolean;
  legacyApproved: boolean;
  blocked: boolean;
  isAdmin: boolean;
  accountStatus: string | null;
  disabled: boolean;
  canDuplicateSystemPrompts: boolean;
  createdAt: string | null;
  lastSignInAt: string | null;
};

export async function listAdminUsers(params?: {
  fullAccess?: boolean;
  query?: string;
  pageToken?: string;
  maxResults?: number;
}): Promise<{ users: AdminUserRow[]; nextPageToken: string | null }> {
  const token = await getAuthTokenOrNullAsync();
  if (!token) throw new Error('Not authenticated');

  const qs = new URLSearchParams();
  if (typeof params?.fullAccess === 'boolean') qs.set('fullAccess', String(params.fullAccess));
  if (params?.query) qs.set('query', params.query);
  if (params?.pageToken) qs.set('page_token', params.pageToken);
  if (typeof params?.maxResults === 'number') qs.set('max_results', String(params.maxResults));
  const url = `${API_BASE_URL}/api/admin/users${qs.toString() ? `?${qs.toString()}` : ''}`;

  const res = await fetch(url, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new Error(detail || 'Admin user listing failed.');
  }

  const data = (await res.json()) as { users?: unknown; nextPageToken?: unknown };
  const users = Array.isArray(data.users)
      ? (data.users as Array<Record<string, unknown>>).map((u) => ({
          uid: typeof u.uid === 'string' ? u.uid : null,
          email: typeof u.email === 'string' ? u.email : null,
          displayName: typeof u.displayName === 'string' ? u.displayName : null,
          fullAccess: u.fullAccess === true || u.approved === true,
          legacyApproved: u.legacyApproved === true,
          blocked: u.blocked === true,
          isAdmin: u.isAdmin === true,
          accountStatus: typeof u.accountStatus === 'string' ? u.accountStatus : null,
          disabled: u.disabled === true,
          canDuplicateSystemPrompts: u.canDuplicateSystemPrompts === true,
          createdAt: typeof u.createdAt === 'string' ? u.createdAt : null,
          lastSignInAt: typeof u.lastSignInAt === 'string' ? u.lastSignInAt : null,
        }))
      : [];
  const nextPageToken = typeof data.nextPageToken === 'string' ? data.nextPageToken : null;
  return { users, nextPageToken };
}

export async function setUserFullAccessByEmail(email: string, fullAccess: boolean): Promise<void> {
  const token = await getAuthTokenOrNullAsync();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(`${API_BASE_URL}/api/admin/users/full-access`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, fullAccess }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new Error(detail || 'Failed to update user access.');
  }
}

export async function setUserBlockedByEmail(email: string, blocked: boolean): Promise<void> {
  const token = await getAuthTokenOrNullAsync();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(`${API_BASE_URL}/api/admin/users/block`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, blocked }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new Error(detail || 'Failed to update user block status.');
  }
}

export async function setUserCanDuplicateSystemPromptsByEmail(
  email: string,
  canDuplicateSystemPrompts: boolean
): Promise<void> {
  const token = await getAuthTokenOrNullAsync();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(`${API_BASE_URL}/api/admin/users/system-prompt-copy`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, canDuplicateSystemPrompts }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new Error(detail || 'Failed to update system prompt copy permission.');
  }
}

async function getAuthTokenOrNullAsync(): Promise<string | null> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  return typeof token === 'string' && token.trim() ? token.trim() : null;
}
