import { NextResponse } from 'next/server';
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

async function getAuthTokenOrNullAsync(): Promise<string | null> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  return typeof token === 'string' && token.trim() ? token.trim() : null;
}

function joinUrlWithSearchParams(baseUrl: string, request: Request): string {
  const reqUrl = new URL(request.url);
  const out = new URL(baseUrl);
  // Preserve search params from the incoming request.
  out.search = reqUrl.search;
  return out.toString();
}

export async function proxyAdminJson(request: Request, path: string, init?: RequestInit): Promise<Response> {
  try {
    const token = await getAuthTokenOrNullAsync();
    if (!token) {
      return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
    }

    const targetBase = `${API_BASE_URL}${path}`;
    const url = joinUrlWithSearchParams(targetBase, request);

    const method = init?.method || request.method || 'GET';
    const headers = new Headers(init?.headers || undefined);
    headers.set('Authorization', `Bearer ${token}`);

    let body: string | undefined = undefined;
    if (method !== 'GET' && method !== 'HEAD') {
      headers.set('Content-Type', 'application/json');
      body = await request.text();
      if (!body) body = undefined;
    }

    const res = await fetch(url, {
      method,
      headers,
      body,
      cache: 'no-store',
    });

    if (!res.ok) {
      const detail = await readErrorDetail(res);
      return NextResponse.json({ error: detail || 'Request failed.' }, { status: res.status });
    }

    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 500 });
  }
}

