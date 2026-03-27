import type { NextRequest } from 'next/server';
import { proxyFastApiJson } from '@/app/api/_fastapiProxy';

type RouteContext = { params: Promise<{ runId: string }> };

export async function GET(request: NextRequest, { params }: RouteContext) {
  const { runId } = await params;
  return proxyFastApiJson(request, `/api/usage-insights/run/${encodeURIComponent(runId)}`, { method: 'GET' });
}
