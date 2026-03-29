import { NextResponse } from 'next/server';
import { listPromptTemplates, createPromptTemplate } from '@/app/actions/promptTemplates';

export async function GET() {
  try {
    const data = await listPromptTemplates();
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const result = await createPromptTemplate(body);
    return NextResponse.json(result, { status: 201 });
  } catch (err: any) {
    return NextResponse.json({ error: err?.message || 'Unbekannter Fehler' }, { status: 400 });
  }
}
