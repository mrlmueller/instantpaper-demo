import 'server-only';

import {
  buildFastApiUrl,
  getSessionTokenOrNull,
  readFastApiErrorDetail,
} from '@/app/lib/server/fastapi';

export async function isAdminUser(): Promise<boolean> {
  const token = await getSessionTokenOrNull();
  if (!token) return false;

  const res = await fetch(buildFastApiUrl('/api/admin/me'), {
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
  canViewUsageInsights: boolean;
  canUseQuellenFinder: boolean;
  canUsePdfScan: boolean;
  billingBalance?: {
    totalCredits: number;
    subscriptionCredits: number;
    subscriptionExpiresAt: string | null;
    topupCredits: number;
    reservedCredits: number;
    availableCredits: number;
    isNegative: boolean;
  } | null;
  billingSubscription?: {
    id: string | null;
    status: string | null;
    cancelAtPeriodEnd: boolean;
    currentPeriodEnd: string | null;
  } | null;
  createdAt: string | null;
  lastSignInAt: string | null;
};

export async function listAdminUsers(params?: {
  fullAccess?: boolean;
  query?: string;
  pageToken?: string;
  maxResults?: number;
}): Promise<{ users: AdminUserRow[]; nextPageToken: string | null }> {
  const token = await getSessionTokenOrNull();
  if (!token) throw new Error('Not authenticated');

  const qs = new URLSearchParams();
  if (typeof params?.fullAccess === 'boolean') qs.set('fullAccess', String(params.fullAccess));
  if (params?.query) qs.set('query', params.query);
  if (params?.pageToken) qs.set('page_token', params.pageToken);
  if (typeof params?.maxResults === 'number') qs.set('max_results', String(params.maxResults));
  const url = buildFastApiUrl(`/api/admin/users${qs.toString() ? `?${qs.toString()}` : ''}`);

  const res = await fetch(url, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    throw new Error(detail || 'Admin user listing failed.');
  }

  const data = (await res.json()) as { users?: unknown; nextPageToken?: unknown };
  const users = Array.isArray(data.users)
      ? (data.users as Array<Record<string, unknown>>).map((u) => {
          const billingBalanceRaw =
            u.billingBalance && typeof u.billingBalance === 'object'
              ? (u.billingBalance as Record<string, unknown>)
              : null;
          const billingSubscriptionRaw =
            u.billingSubscription && typeof u.billingSubscription === 'object'
              ? (u.billingSubscription as Record<string, unknown>)
              : null;

          return {
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
            canViewUsageInsights: u.canViewUsageInsights === true,
            canUseQuellenFinder: u.canUseQuellenFinder === true,
            canUsePdfScan: u.canUsePdfScan === true,
            billingBalance:
              billingBalanceRaw
                ? {
                    totalCredits: Number(billingBalanceRaw.totalCredits ?? 0),
                    subscriptionCredits: Number(billingBalanceRaw.subscriptionCredits ?? 0),
                    subscriptionExpiresAt:
                      typeof billingBalanceRaw.subscriptionExpiresAt === 'string'
                        ? billingBalanceRaw.subscriptionExpiresAt
                        : null,
                    topupCredits: Number(billingBalanceRaw.topupCredits ?? 0),
                    reservedCredits: Number(billingBalanceRaw.reservedCredits ?? 0),
                    availableCredits: Number(billingBalanceRaw.availableCredits ?? 0),
                    isNegative: billingBalanceRaw.isNegative === true,
                  }
                : null,
            billingSubscription:
              billingSubscriptionRaw
                ? {
                    id: typeof billingSubscriptionRaw.id === 'string' ? billingSubscriptionRaw.id : null,
                    status:
                      typeof billingSubscriptionRaw.status === 'string'
                        ? billingSubscriptionRaw.status
                        : null,
                    cancelAtPeriodEnd: billingSubscriptionRaw.cancelAtPeriodEnd === true,
                    currentPeriodEnd:
                      typeof billingSubscriptionRaw.currentPeriodEnd === 'string'
                        ? billingSubscriptionRaw.currentPeriodEnd
                        : null,
                  }
                : null,
            createdAt: typeof u.createdAt === 'string' ? u.createdAt : null,
            lastSignInAt: typeof u.lastSignInAt === 'string' ? u.lastSignInAt : null,
          };
        })
      : [];
  const nextPageToken = typeof data.nextPageToken === 'string' ? data.nextPageToken : null;
  return { users, nextPageToken };
}

export async function setUserFullAccessByEmail(email: string, fullAccess: boolean): Promise<void> {
  const token = await getSessionTokenOrNull();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(buildFastApiUrl('/api/admin/users/full-access'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, fullAccess }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    throw new Error(detail || 'Failed to update user access.');
  }
}

export async function setUserBlockedByEmail(email: string, blocked: boolean): Promise<void> {
  const token = await getSessionTokenOrNull();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(buildFastApiUrl('/api/admin/users/block'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, blocked }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    throw new Error(detail || 'Failed to update user block status.');
  }
}

export async function setUserCanDuplicateSystemPromptsByEmail(
  email: string,
  canDuplicateSystemPrompts: boolean
): Promise<void> {
  const token = await getSessionTokenOrNull();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(buildFastApiUrl('/api/admin/users/system-prompt-copy'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, canDuplicateSystemPrompts }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    throw new Error(detail || 'Failed to update system prompt copy permission.');
  }
}

export async function setUserCanViewUsageInsightsByEmail(
  email: string,
  canViewUsageInsights: boolean
): Promise<void> {
  const token = await getSessionTokenOrNull();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(buildFastApiUrl('/api/admin/users/usage-insights'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, canViewUsageInsights }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    throw new Error(detail || 'Failed to update usage insights permission.');
  }
}

export async function setUserCanUseQuellenFinderByEmail(
  email: string,
  canUseQuellenFinder: boolean
): Promise<void> {
  const token = await getSessionTokenOrNull();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(buildFastApiUrl('/api/admin/users/quellen-finder'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, canUseQuellenFinder }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    throw new Error(detail || 'Failed to update Quellen-Finder permission.');
  }
}

export async function setUserCanUsePdfScanByEmail(email: string, canUsePdfScan: boolean): Promise<void> {
  const token = await getSessionTokenOrNull();
  if (!token) throw new Error('Not authenticated');

  const res = await fetch(buildFastApiUrl('/api/admin/users/pdf-scan'), {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, canUsePdfScan }),
    cache: 'no-store',
  });

  if (!res.ok) {
    const detail = await readFastApiErrorDetail(res);
    throw new Error(detail || 'Failed to update PDF-Scan permission.');
  }
}
