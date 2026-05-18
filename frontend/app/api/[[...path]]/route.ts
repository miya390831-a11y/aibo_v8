import type { NextRequest } from "next/server";

/** Colab / fullstack: Next サーバーから同一マシンの FastAPI へ中継（ブラウザは ngrok→Next のみ） */
const UPSTREAM =
  process.env.AIBO_API_INTERNAL_URL ?? "http://127.0.0.1:8000";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
]);

type RouteContext = { params: Promise<{ path?: string[] }> };

function buildTargetUrl(req: NextRequest, segments: string[]): string {
  const pathPart = segments.join("/");
  const base = pathPart ? `${UPSTREAM}/api/${pathPart}` : `${UPSTREAM}/api`;
  const u = new URL(base);
  u.search = req.nextUrl.search;
  return u.toString();
}

async function proxy(req: NextRequest, segments: string[]): Promise<Response> {
  const url = buildTargetUrl(req, segments);
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  const method = req.method;
  const hasBody = !["GET", "HEAD", "OPTIONS"].includes(method);
  const init: RequestInit = {
    method,
    headers,
    redirect: "manual",
  };
  if (hasBody) {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(url, init);
  const out = new Headers(upstream.headers);
  out.delete("connection");
  out.delete("transfer-encoding");

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  });
}

async function dispatch(
  req: NextRequest,
  ctx: RouteContext,
): Promise<Response> {
  const { path } = await ctx.params;
  return proxy(req, path ?? []);
}

export const GET = dispatch;
export const POST = dispatch;
export const PUT = dispatch;
export const DELETE = dispatch;
export const PATCH = dispatch;
export const OPTIONS = dispatch;
export const HEAD = dispatch;
