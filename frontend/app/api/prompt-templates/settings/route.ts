import { NextResponse } from 'next/server';
import { setAskOnEachProcess, listPromptTemplates } from '@/app/actions/promptTemplates';

export async function GET() {
  try {
    const data = await listPromptTemplates();
    return NextResponse.json({ askOnEachProcess: data.askOnEachProcess });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    await setAskOnEachProcess(Boolean(body.askOnEachProcess));
    return NextResponse.json({ ok: true });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}
