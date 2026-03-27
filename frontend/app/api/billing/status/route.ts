import { proxyFastApiJson } from '@/app/api/_fastapiProxy';

export async function GET(request: Request) {
  return proxyFastApiJson(request, '/api/billing/status', { method: 'GET' });
}
