/**
 * PORTRAIT モード専用 API クライアント
 */

import { apiFetch } from "./api"

export interface BodyShapeAxis {
  x: number
  y: number
}

export interface BodyShape {
  base: BodyShapeAxis
  proportion: BodyShapeAxis
  silhouette: BodyShapeAxis
  curves: BodyShapeAxis
  posture: BodyShapeAxis
}

export interface GenerateRequest {
  face_references: string[]
  prompt: string
  negative_prompt?: string
  body_shape?: BodyShape
  num_inference_steps?: number
  guidance_scale?: number
  seed?: number | null
  width?: number
  height?: number
}

export interface GenerateResponse {
  job_id: string
  status: "queued" | "running" | "completed" | "failed"
}

export interface JobProgressEvent {
  status: "queued" | "running" | "completed" | "failed"
  progress: number
  stage: string
  elapsed_sec: number
  eta_sec: number
  message?: string
  error?: string
}

export interface JobResult {
  job_id: string
  image: string
  meta: {
    seed: number
    phase3_applied: boolean
    phase3_yaw_deg: number
    phase3_elapsed_sec: number
    elapsed_pass1_sec: number
    pulid_used: boolean
    prompt_used: string
    body_shape_addendum: string
  }
}

export interface ExtractBodyShapeRequest {
  image: string
}

export interface ExtractBodyShapeResponse {
  body_shape: BodyShape
  confidence: number
}

export type MakeupStyle =
  | "natural"
  | "pink"
  | "glam"
  | "kbeauty"
  | "romantic"
  | "cool"
  | "mode"
  | "night"
  | "nomakeup"
  | "retro"

export type MakeupIntensity = "light" | "medium" | "heavy"

export interface ApplyMakeupRequest {
  base_image: string
  makeup_style: MakeupStyle
  intensity: MakeupIntensity
}

export interface ApplyMakeupResponse {
  image: string
  meta: {
    makeup_style: string
    intensity: string
    denoising: number
    elapsed_sec: number
    /** e.g. ["face_mask_failed"] when Fill skipped */
    warnings?: string[]
    makeup_infer_sec?: number
    note?: string
  }
}

export async function generatePortrait(
  req: GenerateRequest,
): Promise<GenerateResponse> {
  return apiFetch<GenerateResponse>("/api/portrait/generate", {
    method: "POST",
    body: JSON.stringify(req),
  })
}

export async function getJobResult(jobId: string): Promise<JobResult> {
  return apiFetch<JobResult>(`/api/portrait/result/${jobId}`)
}

export async function extractBodyShape(
  req: ExtractBodyShapeRequest,
): Promise<ExtractBodyShapeResponse> {
  return apiFetch<ExtractBodyShapeResponse>("/api/portrait/extract_body_shape", {
    method: "POST",
    body: JSON.stringify(req),
  })
}

export async function applyMakeup(
  req: ApplyMakeupRequest,
): Promise<ApplyMakeupResponse> {
  return apiFetch<ApplyMakeupResponse>("/api/portrait/apply_makeup", {
    method: "POST",
    body: JSON.stringify(req),
  })
}

// ─── 素体化 (#3d-neutralize) ───

export interface NeutralizeRequest {
  face_refs: string[]
  body_shape?: BodyShape
  seed?: number | null
}

export interface NeutralizeResponse {
  image: string
  body_shape_addendum: string
  seed_used: number
  elapsed: number
  meta?: {
    neutralize_infer_sec?: number
    note?: string
    [key: string]: unknown
  }
}

export interface LibraryItem {
  id: string
  image: string
  thumbnail?: string
  created_at: number
  body_shape_addendum: string
  seed_used: number
  source_face_refs?: string[]
  name?: string
}

export async function neutralizeImage(
  req: NeutralizeRequest,
): Promise<NeutralizeResponse> {
  return apiFetch<NeutralizeResponse>("/api/portrait/neutralize", {
    method: "POST",
    body: JSON.stringify(req),
  })
}

const LIBRARY_STORAGE_KEY = "aibo_v8_library"

export function loadLibraryItems(): LibraryItem[] {
  if (typeof window === "undefined") return []
  try {
    const data = localStorage.getItem(LIBRARY_STORAGE_KEY)
    if (!data) return []
    return JSON.parse(data) as LibraryItem[]
  } catch (error) {
    console.error("[Library] load error:", error)
    return []
  }
}

export function saveLibraryItem(item: LibraryItem): void {
  if (typeof window === "undefined") return
  try {
    const items = loadLibraryItems()
    items.push(item)
    localStorage.setItem(LIBRARY_STORAGE_KEY, JSON.stringify(items))
  } catch (error) {
    console.error("[Library] save error:", error)
    if (
      error instanceof DOMException &&
      error.name === "QuotaExceededError"
    ) {
      throw new Error(
        "ブラウザの保存容量上限です。ライブラリから古い素体を削除してください。",
      )
    }
    throw new Error("ライブラリの保存に失敗しました")
  }
}

export function deleteLibraryItem(id: string): void {
  if (typeof window === "undefined") return
  try {
    const items = loadLibraryItems().filter((item) => item.id !== id)
    localStorage.setItem(LIBRARY_STORAGE_KEY, JSON.stringify(items))
  } catch (error) {
    console.error("[Library] delete error:", error)
  }
}

export function generateLibraryItemId(): string {
  return `lib_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`
}

export function subscribeJobProgress(
  jobId: string,
  callbacks: {
    onEvent: (event: JobProgressEvent) => void
    onError?: (error: Event | Error) => void
    onComplete?: () => void
  },
  options: {
    intervalMs?: number
    maxRetries?: number
  } = {},
): { close: () => void } {
  const intervalMs = options.intervalMs ?? 1000
  const maxRetries = options.maxRetries ?? 5
  let closed = false
  let consecutiveErrors = 0
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  const poll = async () => {
    if (closed) return

    try {
      const data = await apiFetch<JobProgressEvent>(`/api/portrait/poll/${jobId}`, {
        method: "GET",
      })
      consecutiveErrors = 0
      callbacks.onEvent(data)

      if (data.status === "completed" || data.status === "failed") {
        if (!closed) {
          closed = true
        }
        callbacks.onComplete?.()
        return
      }

      if (!closed) {
        timeoutId = setTimeout(poll, intervalMs)
      }
    } catch (err) {
      console.error("[subscribeJobProgress] poll error:", err)
      consecutiveErrors += 1
      if (consecutiveErrors >= maxRetries) {
        if (!closed) {
          closed = true
          callbacks.onError?.(err as Error)
        }
        return
      }
      const retryDelay = intervalMs * Math.min(2 ** consecutiveErrors, 8)
      if (!closed) {
        timeoutId = setTimeout(poll, retryDelay)
      }
    }
  }
  void poll()

  return {
    close: () => {
      if (!closed) {
        closed = true
        if (timeoutId !== null) {
          clearTimeout(timeoutId)
          timeoutId = null
        }
      }
    },
  }
}
