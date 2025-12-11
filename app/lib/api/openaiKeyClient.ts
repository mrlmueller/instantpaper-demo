const API_BASE_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000';

export type OpenAIKeyStatus = {
  hasKey: boolean;
  last4: string | null;
  allowPlatformKey: boolean;
};

async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {}
): Promise<T> {
  if (!token) {
    throw new Error('Keine Sitzung gefunden. Bitte melde dich erneut an.');
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const detail = (await response.json().catch(() => ({})))?.detail;
    throw new Error(detail || 'Anfrage fehlgeschlagen.');
  }

  return response.json() as Promise<T>;
}

export async function fetchOpenAIKeyStatus(token: string): Promise<OpenAIKeyStatus> {
  const res = await request<{ has_key: boolean; last4?: string | null; allow_platform_key: boolean }>(
    '/api/user/openai-key',
    token
  );

  return {
    hasKey: Boolean(res.has_key),
    last4: res.last4 ?? null,
    allowPlatformKey: Boolean(res.allow_platform_key),
  };
}

export async function saveOpenAIKey(token: string, key: string): Promise<OpenAIKeyStatus> {
  const res = await request<{ has_key: boolean; last4?: string | null; allow_platform_key: boolean }>(
    '/api/user/openai-key',
    token,
    {
      method: 'POST',
      body: JSON.stringify({ key }),
    }
  );

  return {
    hasKey: Boolean(res.has_key),
    last4: res.last4 ?? null,
    allowPlatformKey: Boolean(res.allow_platform_key),
  };
}

export async function deleteOpenAIKey(token: string): Promise<OpenAIKeyStatus> {
  const res = await request<{ has_key: boolean; last4?: string | null; allow_platform_key: boolean }>(
    '/api/user/openai-key',
    token,
    {
      method: 'DELETE',
    }
  );

  return {
    hasKey: Boolean(res.has_key),
    last4: res.last4 ?? null,
    allowPlatformKey: Boolean(res.allow_platform_key),
  };
}
