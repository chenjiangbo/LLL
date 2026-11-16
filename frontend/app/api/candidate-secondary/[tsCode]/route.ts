import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

const backendBase = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ tsCode: string }> },
) {
  if (!backendBase) {
    return Response.json(
      { detail: 'NEXT_PUBLIC_MARKET_REVIEW_API_URL 未配置，无法读取股票详情' },
      { status: 500 },
    );
  }

  const { tsCode } = await context.params;
  const upstream = await fetch(
    `${backendBase}/api/candidate-secondary/${encodeURIComponent(tsCode)}${request.nextUrl.search}`,
    { cache: 'no-store' },
  );

  return new Response(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: {
      'Content-Type': upstream.headers.get('content-type') || 'application/json',
    },
  });
}
