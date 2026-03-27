import { proxyFastApiJson } from '@/app/api/_fastapiProxy';

export async function POST(request: Request) {
  return proxyFastApiJson(request, '/api/quellen-finder/pdf-scan', { method: 'POST' });
}
