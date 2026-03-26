export type BillingBalance = {
  totalCredits: number;
  subscriptionCredits: number;
  subscriptionExpiresAt: string | null;
  topupCredits: number;
  reservedCredits: number;
  availableCredits: number;
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
  options: RequestInit = {}
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || undefined);
  if (method !== "GET" && method !== "HEAD" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (response.status === 401) {
    throw new Error("Keine Sitzung gefunden. Bitte melde dich erneut an.");
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: unknown;
      detail?: unknown;
      message?: unknown;
    };
    const detail =
      (typeof payload.error === "string" && payload.error.trim() ? payload.error.trim() : null) ||
      (typeof payload.detail === "string" && payload.detail.trim() ? payload.detail.trim() : null) ||
      (typeof payload.message === "string" && payload.message.trim() ? payload.message.trim() : null);
    throw new Error(detail || "Anfrage fehlgeschlagen.");
  }

  return response.json() as Promise<T>;
}

export async function fetchBillingBalance(): Promise<BillingBalance> {
  const res = await request<{ balance: BillingBalance }>("/api/billing/balance");
  return res.balance;
}

export async function fetchBillingLedger(
  params?: { limit?: number; cursor?: string | null }
): Promise<{ entries: BillingLedgerEntry[]; nextCursor: string | null }> {
  const limit = params?.limit ?? 30;
  const cursor = params?.cursor ?? null;
  const qs = new URLSearchParams();
  qs.set("limit", String(limit));
  if (cursor) qs.set("cursor", cursor);
  const path = `/api/billing/ledger${qs.size ? `?${qs.toString()}` : ""}`;

  const res = await request<{ entries: BillingLedgerEntry[]; nextCursor: string | null }>(
    path
  );
  return res;
}

export async function fetchBillingSubscriptionStatus(): Promise<BillingSubscriptionStatus> {
  const res = await request<{ subscription: BillingSubscriptionStatus }>("/api/billing/status");
  return res.subscription;
}
