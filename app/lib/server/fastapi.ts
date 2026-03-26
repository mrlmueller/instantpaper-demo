import 'server-only';

import { cookies } from 'next/headers';

const FASTAPI_LOCAL_FALLBACK = 'http://localhost:8000';

export type FastApiErrorPayload = {
  detail?: unknown;
  error?: unknown;
  message?: unknown;
};

function normalizeBaseUrl(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

export function getFastApiBaseUrl(): string {
  const configured =
    process.env.FASTAPI_BASE_URL ||
    process.env.NEXT_PUBLIC_FASTAPI_URL ||
    FASTAPI_LOCAL_FALLBACK;

  return normalizeBaseUrl(configured);
}

export function buildFastApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${getFastApiBaseUrl()}${normalizedPath}`;
}

export function joinFastApiUrlWithRequestSearch(path: string, request: Request): string {
  const reqUrl = new URL(request.url);
  const out = new URL(buildFastApiUrl(path));
  out.search = reqUrl.search;
  return out.toString();
}

export async function getSessionTokenOrNull(): Promise<string | null> {
  const store = await cookies();
  const token = store.get('__session')?.value;
  return typeof token === 'string' && token.trim() ? token.trim() : null;
}

export async function readFastApiErrorDetail(res: Response): Promise<string | null> {
  try {
    const data = (await res.json()) as FastApiErrorPayload;
    const candidates = [data.error, data.detail, data.message];
    for (const candidate of candidates) {
      if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
    }
  } catch {
    // ignore
  }
  return null;
}
