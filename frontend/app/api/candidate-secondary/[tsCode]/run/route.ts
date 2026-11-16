import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

const backendBase = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ tsCode: string }> },
) {
  if (!backendBase) {
    return Response.json(
      { detail: 'NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置，无法执行基本面分析' },
      { status: 500 },
    );
  }

  const { tsCode } = await context.params;
  const body = await request.text();
  const upstream = await fetch(
    `${backendBase}/api/candidate-secondary/${encodeURIComponent(tsCode)}/run`,
    {
      method: 'POST',
      headers: { 'Content-Type': request.headers.get('content-type') || 'application/json' },
      body,
      cache: 'no-store',
    },
  );

  return new Response(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('content-type') || 'application/json',
    },
  });
}
