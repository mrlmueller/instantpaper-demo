import { proxyFastApiJson } from '@/app/api/_fastapiProxy';

export async function POST(request: Request) {
  return proxyFastApiJson(request, '/api/gliederung/refine', { method: 'POST' });
}
