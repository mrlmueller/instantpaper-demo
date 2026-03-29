import { NextResponse } from 'next/server';
import { getActivePromptInstructions, setActivePrompt } from '@/app/actions/promptTemplates';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const stage = searchParams.get('stage');
    if (!stage) {
      return NextResponse.json({ error: 'stage is required' }, { status: 400 });
    }
    const instructions = await getActivePromptInstructions(stage as any);
    return NextResponse.json({ instructions });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    if (!body.stage || typeof body.templateId === 'undefined') {
      return NextResponse.json({ error: 'stage and templateId required' }, { status: 400 });
    }
    await setActivePrompt(body.stage, body.templateId);
    return NextResponse.json({ ok: true });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}
