import { NextRequest } from "next/server";

const backendBase = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

async function forward(request: NextRequest, planId: string) {
  if (!backendBase) {
    return Response.json({ detail: "交易服务地址未配置" }, { status: 500 });
  }
  const upstream = `${backendBase}/api/trade-plans/${encodeURIComponent(planId)}${request.nextUrl.search}`;
  const response = await fetch(upstream, {
    method: "PUT",
    headers: { "Content-Type": request.headers.get("content-type") || "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  const payload = await response.text();
  if (!response.ok) {
    return Response.json({ detail: payload || `交易服务返回 HTTP ${response.status}` }, { status: response.status });
  }
  return new Response(payload, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}

export async function PUT(request: NextRequest, context: { params: Promise<{ planId: string }> }) {
  try {
    const { planId } = await context.params;
    return await forward(request, planId);
  } catch (error) {
    return Response.json({ detail: error instanceof Error ? error.message : "交易服务请求失败" }, { status: 502 });
  }
}
