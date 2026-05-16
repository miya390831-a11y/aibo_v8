/**
 * AIBO FastAPI クライアント（#3c で拡張）。
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const NGROK_SKIP = process.env.NEXT_PUBLIC_NGROK_SKIP_WARNING === "true";

/** ngrok 無料版の警告 HTML を返さず API に届ける（ヘッダー無しだと CORS エラーに見える） */
function shouldAttachNgrokSkipHeader(): boolean {
  if (NGROK_SKIP) return true;
  try {
    return new URL(API_URL).hostname.includes("ngrok");
  } catch {
    return /ngrok/i.test(API_URL);
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  if (shouldAttachNgrokSkipHeader()) {
    headers["ngrok-skip-browser-warning"] = "true";
  }

  const url = `${API_URL}${path}`;
  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let detail: string;
    try {
      const errBody = await response.json();
      detail = (errBody as { detail?: string }).detail || JSON.stringify(errBody);
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }

  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

export interface SystemStatus {
  gpu_available: boolean;
  gpu_name?: string;
  vram_total_gb?: number;
  vram_used_gb?: number;
  vram_pct?: number;
  orchestrator_attached: boolean;
  error?: string;
}

export async function getSystemStatus(): Promise<SystemStatus> {
  return apiFetch<SystemStatus>("/api/system/status");
}
