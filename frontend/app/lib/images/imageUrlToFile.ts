const CONTENT_TYPE_TO_EXT: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/jpg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
  'image/gif': 'gif',
  'image/svg+xml': 'svg',
  'image/avif': 'avif',
  'image/bmp': 'bmp',
};

function inferExt(contentType: string | null | undefined) {
  if (!contentType) return 'jpg';
  const ct = contentType.split(';')[0].trim().toLowerCase();
  return CONTENT_TYPE_TO_EXT[ct] || 'jpg';
}

function safeFilenameFromUrl(sourceUrl: string, ext: string) {
  try {
    const u = new URL(sourceUrl);
    const raw = u.pathname.split('/').filter(Boolean).pop() || '';
    const decoded = decodeURIComponent(raw);
    const base = decoded.replace(/[?#].*$/, '').trim();
    if (!base) return `image.${ext}`;
    if (base.includes('.')) return base;
    return `${base}.${ext}`;
  } catch {
    return `image.${ext}`;
  }
}

async function readErrorMessage(res: Response) {
  const ct = (res.headers.get('content-type') || '').toLowerCase();
  if (ct.includes('application/json')) {
    try {
      const data = await res.json();
      if (typeof data?.error === 'string' && data.error.trim()) return data.error;
    } catch {
      // ignore
    }
  }
  try {
    const text = await res.text();
    if (text.trim()) return text;
  } catch {
    // ignore
  }
  return `HTTP ${res.status}`;
}

export async function fetchImageUrlAsFile(sourceUrl: string, options?: { signal?: AbortSignal }) {
  const trimmed = sourceUrl.trim();
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error('Ungültige Bild-URL.');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('Nur http/https Bild-URLs sind erlaubt.');
  }

  const endpoint = `/api/external-image?url=${encodeURIComponent(trimmed)}`;
  const res = await fetch(endpoint, { signal: options?.signal });
  if (!res.ok) throw new Error(await readErrorMessage(res));

  const blob = await res.blob();
  const contentType = (res.headers.get('content-type') || blob.type || 'image/jpeg')
    .split(';')[0]
    .trim();
  const ext = inferExt(contentType);
  const filename = safeFilenameFromUrl(trimmed, ext);

  return new File([blob], filename, { type: contentType });
}

