import { NextRequest } from 'next/server';
import { isIP } from 'node:net';
import dns from 'node:dns/promises';

export const runtime = 'nodejs';

const MAX_REDIRECTS = 3;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024; // 8MB
const FETCH_TIMEOUT_MS = 10_000;

function jsonError(message: string, status = 400) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function isPrivateIpv4(ip: string) {
  const parts = ip.split('.').map((p) => Number(p));
  if (parts.length !== 4 || parts.some((p) => Number.isNaN(p) || p < 0 || p > 255)) return false;
  const [a, b] = parts;
  if (a === 10) return true;
  if (a === 127) return true;
  if (a === 0) return true;
  if (a === 169 && b === 254) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  if (a === 100 && b >= 64 && b <= 127) return true;
  return false;
}

function isPrivateIpv6(ip: string) {
  const normalized = ip.toLowerCase();
  if (normalized === '::1' || normalized === '::') return true;
  if (normalized.startsWith('fc') || normalized.startsWith('fd')) return true; // unique local
  if (normalized.startsWith('fe80:')) return true; // link-local
  return false;
}

function isPrivateIp(ip: string) {
  const v = isIP(ip);
  if (v === 4) return isPrivateIpv4(ip);
  if (v === 6) return isPrivateIpv6(ip);
  return false;
}

async function assertUrlAllowed(url: URL) {
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('Nur http/https URLs sind erlaubt.');
  }
  if (url.username || url.password) {
    throw new Error('URLs mit Benutzername/Passwort sind nicht erlaubt.');
  }
  const hostname = url.hostname.toLowerCase();
  if (hostname === 'localhost' || hostname.endsWith('.localhost')) {
    throw new Error('Lokale Hosts sind nicht erlaubt.');
  }

  const ipVersion = isIP(hostname);
  if (ipVersion) {
    if (isPrivateIp(hostname)) throw new Error('Private IPs sind nicht erlaubt.');
    return;
  }

  const records = await dns.lookup(hostname, { all: true, verbatim: true });
  if (!records.length) throw new Error('Host konnte nicht aufgelöst werden.');
  if (records.some((r) => isPrivateIp(r.address))) {
    throw new Error('Private Netzwerkziele sind nicht erlaubt.');
  }
}

async function fetchWithRedirects(initialUrl: URL) {
  let current = initialUrl;
  for (let i = 0; i <= MAX_REDIRECTS; i++) {
    await assertUrlAllowed(current);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const res = await fetch(current.toString(), {
        redirect: 'manual',
        signal: controller.signal,
        headers: {
          'User-Agent': 'instantpaper/1.0',
          Accept: 'image/*',
        },
      });

      if (res.status >= 300 && res.status < 400) {
        const location = res.headers.get('location');
        if (!location) throw new Error('Weiterleitung ohne Ziel.');
        current = new URL(location, current);
        continue;
      }

      return res;
    } finally {
      clearTimeout(timer);
    }
  }
  throw new Error('Zu viele Weiterleitungen.');
}

async function readBodyWithLimit(res: Response, maxBytes: number) {
  const contentLength = res.headers.get('content-length');
  if (contentLength) {
    const asNum = Number(contentLength);
    if (!Number.isNaN(asNum) && asNum > maxBytes) {
      throw new Error(`Bild ist zu groß (max. ${Math.floor(maxBytes / (1024 * 1024))}MB).`);
    }
  }

  if (!res.body) throw new Error('Antwort enthält keinen Body.');
  const reader = res.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > maxBytes) throw new Error(`Bild ist zu groß (max. ${Math.floor(maxBytes / (1024 * 1024))}MB).`);
    chunks.push(value);
  }

  return Buffer.concat(chunks.map((c) => Buffer.from(c)));
}

export async function GET(req: NextRequest) {
  const urlParam = req.nextUrl.searchParams.get('url');
  if (!urlParam) return jsonError('Query-Parameter "url" fehlt.');

  let target: URL;
  try {
    target = new URL(urlParam);
  } catch {
    return jsonError('Ungültige URL.');
  }

  try {
    const res = await fetchWithRedirects(target);
    if (!res.ok) {
      return jsonError(`Download fehlgeschlagen (HTTP ${res.status}).`, 400);
    }

    const contentType = (res.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    if (!contentType.startsWith('image/')) {
      return jsonError('URL liefert kein Bild (Content-Type ist nicht image/*).', 400);
    }

    const buffer = await readBodyWithLimit(res, MAX_IMAGE_BYTES);
    return new Response(buffer, {
      status: 200,
      headers: {
        'Content-Type': contentType || 'application/octet-stream',
        'Cache-Control': 'public, max-age=3600',
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unbekannter Fehler.';
    return jsonError(message, 400);
  }
}

