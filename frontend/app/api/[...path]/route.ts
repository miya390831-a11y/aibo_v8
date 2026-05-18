import { NextRequest } from "next/server";

const BACKEND =
  process.env.AIBO_API_INTERNAL_URL || "http://127.0.0.1:8000";

async function handler(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const url = new URL(req.url);
  const targetUrl = `${BACKEND}/api/${path.join("/")}${url.search}`;

  const body =
    req.method !== "GET" && req.method !== "HEAD"
      ? await req.text()
      : undefined;

  const response = await fetch(targetUrl, {
    method: req.method,
    headers: Object.fromEntries(req.headers.entries()),
    body,
  });

  return new Response(response.body, {
    status: response.status,
    headers: response.headers,
  });
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const DELETE = handler;
export const PATCH = handler;
export const OPTIONS = handler;
