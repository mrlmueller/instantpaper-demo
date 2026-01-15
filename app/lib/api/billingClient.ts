const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";

export type BillingBalance = {
  totalCredits: number;
  subscriptionCredits: number;
  subscriptionExpiresAt: string | null;
  topupCredits: number;
  isNegative: boolean;
};

export type BillingLedgerEntry = {
  id: string;
  type: string;
  source: string;
  credits: number;
  createdAt: string | null;
  expiresAt: string | null;
};

export type BillingSubscriptionStatus = {
  id: string;
  status: string | null;
  cancelAtPeriodEnd: boolean;
  currentPeriodEnd: string | null;
} | null;

async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {}
): Promise<T> {
  if (!token) {
    throw new Error("Keine Sitzung gefunden. Bitte melde dich erneut an.");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const detail = (await response.json().catch(() => ({})))?.detail;
    throw new Error(detail || "Anfrage fehlgeschlagen.");
  }

  return response.json() as Promise<T>;
}

export async function fetchBillingBalance(token: string): Promise<BillingBalance> {
  const res = await request<{ balance: BillingBalance }>("/api/billing/balance", token);
  return res.balance;
}

export async function fetchBillingLedger(
  token: string,
  params?: { limit?: number; cursor?: string | null }
): Promise<{ entries: BillingLedgerEntry[]; nextCursor: string | null }> {
  const limit = params?.limit ?? 30;
  const cursor = params?.cursor ?? null;

  const url = new URL(`${API_BASE_URL}/api/billing/ledger`);
  url.searchParams.set("limit", String(limit));
  if (cursor) url.searchParams.set("cursor", cursor);

  const res = await request<{ entries: BillingLedgerEntry[]; nextCursor: string | null }>(
    url.pathname + url.search,
    token
  );
  return res;
}

export async function fetchBillingSubscriptionStatus(token: string): Promise<BillingSubscriptionStatus> {
  const res = await request<{ subscription: BillingSubscriptionStatus }>("/api/billing/status", token);
  return res.subscription;
}

