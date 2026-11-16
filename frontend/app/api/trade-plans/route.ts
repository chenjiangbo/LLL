import { NextRequest } from "next/server";

const backendBase = process.env.NEXT_PUBLIC_MARKET_REVIEW_API_URL;

async function forward(request: NextRequest) {
  if (!backendBase) {
    return Response.json({ detail: "交易服务地址未配置" }, { status: 500 });
  }
  const upstream = `${backendBase}/api/trade-plans${request.nextUrl.search}`;
  const response = await fetch(upstream, {
    method: "POST",
    headers: { "Content-Type": request.headers.get("content-type") || "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  return new Response(await response.arrayBuffer(), {
    status: response.status,
    headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
  });
}

export async function POST(request: NextRequest) {
  try {
    return await forward(request);
  } catch (error) {
    return Response.json({ detail: error instanceof Error ? error.message : "交易服务请求失败" }, { status: 502 });
  }
}
