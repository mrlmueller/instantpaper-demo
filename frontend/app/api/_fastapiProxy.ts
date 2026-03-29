import { NextResponse } from 'next/server';
import {
  getSessionTokenOrNull,
  joinFastApiUrlWithRequestSearch,
  readFastApiErrorDetail,
} from '@/app/lib/server/fastapi';

export async function proxyFastApiJson(request: Request, path: string, init?: RequestInit): Promise<Response> {
  const token = await getSessionTokenOrNull();
  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  const url = joinFastApiUrlWithRequestSearch(path, request);
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
    const detail = await readFastApiErrorDetail(res);
    return NextResponse.json({ error: detail || 'Request failed.' }, { status: res.status });
  }

  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

