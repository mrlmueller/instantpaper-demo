import type { NextRequest } from 'next/server';
import { proxyAdminJson } from '@/app/api/admin/_fastapiProxy';

export async function GET(request: NextRequest) {
  return proxyAdminJson(request, '/api/admin/costs/operations');
}

