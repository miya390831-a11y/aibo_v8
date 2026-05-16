"use client"

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react"
import { Upload, X, Sparkles, Camera, FileWarning, AlertTriangle, CheckCircle2, Info } from "lucide-react"
import { CyberPanel } from "./cyber-panel"

export type PoseExtractionWidgetHandle = {
  runSimulatedExtraction: () => void
}

export type PoseVariant = "default" | "walking" | "sitting" | "looking_back"

type ExtractState = "idle" | "uploading" | "extracting" | "success" | "error"

type DemoErrorKind = "none" | "critical" | "error" | "warn" | "info"

type ToastKind = "success" | "error" | "warn" | "info"
type Toast = { id: number; kind: ToastKind; text: string }

export type PoseExtractionResult = {
  variant: PoseVariant
  presetLabel: string
  confidence: number
  keypointCount: number
  applyBodyShape: boolean
  applyHeadRotation: boolean
  headRotation: { yaw: number; pitch: number; roll: number }
  bodyShape: { base: number; proportion: number; silhouette: number }
}

type Props = {
  onExtractSuccess: (result: PoseExtractionResult) => void
}

const POSE_LIBRARY: {
  variant: PoseVariant
  label: string
  confidence: number
  count: number
  head: { yaw: number; pitch: number; roll: number }
  body: { base: number; proportion: number; silhouette: number }
}[] = [
  {
    variant: "walking",
    label: "extracted (画像から · walking)",
    confidence: 87,
    count: 16,
    head: { yaw: -8, pitch: 4, roll: 2 },
    body: { base: 0.32, proportion: -0.18, silhouette: 0.05 },
  },
  {
    variant: "sitting",
    label: "extracted (画像から · sitting)",
    confidence: 81,
    count: 14,
    head: { yaw: 0, pitch: 18, roll: 0 },
    body: { base: -0.12, proportion: 0.08, silhouette: -0.22 },
  },
  {
    variant: "looking_back",
    label: "extracted (画像から · looking_back)",
    confidence: 92,
    count: 17,
    head: { yaw: 48, pitch: -6, roll: 3 },
    body: { base: 0.05, proportion: 0.12, silhouette: 0.18 },
  },
]

export const PoseExtractionWidget = forwardRef<
  PoseExtractionWidgetHandle,
  Props
>(function PoseExtractionWidget({ onExtractSuccess }, forwardedRef) {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [extractBodyShape, setExtractBodyShape] = useState(true)
  const [extractHeadRotation, setExtractHeadRotation] = useState(true)
  const [state, setState] = useState<ExtractState>("idle")
  const [statusInfo, setStatusInfo] = useState<{
    confidence: number
    count: number
    label: string
  } | null>(null)
  const [demoError, setDemoError] = useState<DemoErrorKind>("none")
  const [criticalModal, setCriticalModal] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const toastIdRef = useRef(0)

  // Cleanup the object URL when the file changes / unmount
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const pushToast = useCallback((kind: ToastKind, text: string) => {
    const id = ++toastIdRef.current
    setToasts((prev) => [...prev, { id, kind, text }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 4200)
  }, [])

  useImperativeHandle(forwardedRef, () => ({
    runSimulatedExtraction: () => {
      if (state === "extracting") return
      runExtraction()
    },
  }))

  const setUploadedFile = useCallback(
    (f: File) => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
      const url = URL.createObjectURL(f)
      setFile(f)
      setPreviewUrl(url)
      setStatusInfo(null)
      setState("idle")
    },
    [previewUrl],
  )

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return
      const f = files[0]
      if (!f.type.startsWith("image/")) {
        pushToast("error", "対応していないファイル形式です")
        return
      }
      if (f.size > 20 * 1024 * 1024) {
        pushToast("error", "ファイルサイズが 20MB を超えています")
        return
      }
      setUploadedFile(f)
    },
    [pushToast, setUploadedFile],
  )

  const handleClear = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setFile(null)
    setPreviewUrl(null)
    setStatusInfo(null)
    setState("idle")
    if (inputRef.current) inputRef.current.value = ""
  }

  const handleExtract = () => {
    if (!file || state === "extracting") return
    runExtraction()
  }

  const runExtraction = () => {
    setState("extracting")
    setStatusInfo(null)

    // Simulate DWPose inference (3 seconds)
    setTimeout(() => {
      // CRITICAL error path → modal, no result
      if (demoError === "critical") {
        setCriticalModal(true)
        setState("error")
        return
      }

      // ERROR: keypoints insufficient → toast, no result
      if (demoError === "error") {
        pushToast("error", "ポーズを認識できません。別画像で試してください")
        setState("error")
        return
      }

      // Pick a random pose variant for the demo
      const picked = POSE_LIBRARY[Math.floor(Math.random() * POSE_LIBRARY.length)]

      // WARN: low confidence → still applies pose
      if (demoError === "warn") {
        pushToast("warn", "精度低のため微調整推奨 (信頼度: 42%)")
        const result: PoseExtractionResult = {
          variant: picked.variant,
          presetLabel: picked.label,
          confidence: 42,
          keypointCount: picked.count,
          applyBodyShape: extractBodyShape,
          applyHeadRotation: extractHeadRotation,
          headRotation: picked.head,
          bodyShape: picked.body,
        }
        onExtractSuccess(result)
        setStatusInfo({ confidence: 42, count: picked.count, label: picked.label })
        setState("success")
        return
      }

      // INFO: head unknown → body applied, head skipped
      if (demoError === "info") {
        pushToast("info", "頭の向きは手動で調整してください")
        const result: PoseExtractionResult = {
          variant: picked.variant,
          presetLabel: picked.label,
          confidence: 78,
          keypointCount: picked.count,
          applyBodyShape: extractBodyShape,
          applyHeadRotation: false,
          headRotation: { yaw: 0, pitch: 0, roll: 0 },
          bodyShape: picked.body,
        }
        onExtractSuccess(result)
        setStatusInfo({ confidence: 78, count: picked.count, label: picked.label })
        setState("success")
        return
      }

      // Default success path
      const result: PoseExtractionResult = {
        variant: picked.variant,
        presetLabel: picked.label,
        confidence: picked.confidence,
        keypointCount: picked.count,
        applyBodyShape: extractBodyShape,
        applyHeadRotation: extractHeadRotation,
        headRotation: picked.head,
        bodyShape: picked.body,
      }
      onExtractSuccess(result)
      setStatusInfo({
        confidence: picked.confidence,
        count: picked.count,
        label: picked.label,
      })
      pushToast("success", "ポーズを抽出しました")
      setState("success")
    }, 3000)
  }

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(true)
  }
  const onDragLeave = () => setDragActive(false)
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
    handleFiles(e.dataTransfer.files)
  }

  const isExtracting = state === "extracting"
  const canExtract = !!file && !isExtracting

  return (
    <CyberPanel title="ポーズ抽出 (ピクトグラム反映)" numero="EX">
      {/* Demo error toggles */}
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[9px] uppercase tracking-[1.5px] text-white/40">
          Demo Errors:
        </span>
        {(
          [
            { id: "none", label: "OK" },
            { id: "critical", label: "CRITICAL" },
            { id: "error", label: "ERROR" },
            { id: "warn", label: "WARN" },
            { id: "info", label: "INFO" },
          ] as { id: DemoErrorKind; label: string }[]
        ).map((opt) => (
          <button
            key={opt.id}
            type="button"
            onClick={() => setDemoError(opt.id)}
            className="cyber-btn !px-2 !py-1 !text-[9px]"
            style={{
              background: demoError === opt.id ? "var(--gradient-primary-soft)" : undefined,
              borderColor: demoError === opt.id ? "var(--cyber-cyan)" : undefined,
              color: demoError === opt.id ? "var(--cyber-cyan)" : undefined,
            }}
            aria-pressed={demoError === opt.id}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Upload zone or thumbnail */}
      {!file ? (
        <div
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault()
              inputRef.current?.click()
            }
          }}
          role="button"
          tabIndex={0}
          aria-label="画像をアップロードしてポーズを抽出"
          className="flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors"
          style={{
            border: dragActive
              ? "2px dashed var(--cyber-cyan)"
              : "2px dashed rgba(0, 234, 255, 0.4)",
            background: dragActive ? "rgba(0,234,255,0.06)" : "rgba(10, 10, 12, 0.6)",
            padding: "32px 16px",
            minHeight: 140,
          }}
        >
          <Camera size={32} className="text-[var(--cyber-cyan)]" aria-hidden />
          <p className="font-mono text-[13px] text-white tracking-wider">
            画像をドラッグ&ドロップ
          </p>
          <p className="font-mono text-[11px] text-white/50">または</p>
          <span className="cyber-btn cyber-btn-primary !text-[11px] pointer-events-none">
            <Upload size={12} /> ファイルを選択
          </span>
          <p className="font-mono text-[10px] text-white/40 mt-1 text-center">
            対応形式: JPEG / PNG / WebP / HEIC · 最大: 4096×4096 / 20MB
          </p>
          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            className="sr-only"
            aria-label="ポーズ抽出用の画像ファイル"
            onChange={(e) => handleFiles(e.target.files)}
          />
        </div>
      ) : (
        <div
          className="flex items-center gap-3 p-2"
          style={{
            border: "1px solid var(--cyber-cyan-dim)",
            background: "rgba(10, 10, 12, 0.6)",
          }}
        >
          <div
            className="relative w-[80px] h-[80px] shrink-0 overflow-hidden"
            style={{ border: "1px solid var(--cyber-cyan-dim)" }}
          >
            {previewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={previewUrl}
                alt={file.name}
                className="w-full h-full object-cover"
              />
            ) : null}
            {/* Scanline overlay */}
            <div className="pointer-events-none absolute inset-0 scanlines" aria-hidden />
            {/* Cyan vertical scan during extraction */}
            {isExtracting && (
              <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
                <div className="absolute left-0 right-0 h-[2px] animate-pose-scan"
                  style={{
                    background:
                      "linear-gradient(90deg, transparent, var(--cyber-cyan), transparent)",
                    boxShadow: "0 0 8px var(--cyber-cyan)",
                  }}
                />
              </div>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-mono text-[11px] text-[var(--cyber-cyan)] tracking-wider truncate">
              {file.name}
            </div>
            <div className="font-mono text-[10px] text-white/50 mt-1">
              {formatBytes(file.size)} · {file.type.replace("image/", "").toUpperCase()}
            </div>
            {statusInfo && (
              <div className="font-mono text-[9px] text-[var(--state-success)] mt-1 tracking-wider">
                ✓ 抽出済み
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={handleClear}
            aria-label="画像を削除"
            className="cyber-btn !p-1.5"
          >
            <X size={12} />
          </button>
        </div>
      )}

      {/* Options */}
      <div className="mt-3 space-y-1.5">
        <label className="flex items-center gap-2 text-[11px] cursor-pointer font-mono tracking-wider text-white/80">
          <input
            type="checkbox"
            checked={extractBodyShape}
            onChange={(e) => setExtractBodyShape(e.target.checked)}
            className="accent-[var(--cyber-cyan)]"
          />
          体型 6 軸も自動推定する
        </label>
        <label className="flex items-center gap-2 text-[11px] cursor-pointer font-mono tracking-wider text-white/80">
          <input
            type="checkbox"
            checked={extractHeadRotation}
            onChange={(e) => setExtractHeadRotation(e.target.checked)}
            className="accent-[var(--cyber-cyan)]"
          />
          顔の向き (頭 3 軸) も推定する
        </label>
      </div>

      <p className="mt-2 italic font-mono text-[10px] text-white/40">
        ※ 推定精度には限界があります。抽出後にスライダーで微調整できます
      </p>

      {/* Action button */}
      <button
        type="button"
        onClick={handleExtract}
        disabled={!canExtract}
        aria-label="アップロード画像からポーズを抽出してピクトグラムに反映"
        className="cyber-btn cyber-btn-primary w-full mt-3 !py-3 !text-[12px] !tracking-[2px] disabled:opacity-40 disabled:cursor-not-allowed disabled:[box-shadow:none] disabled:hover:translate-y-0"
        style={{
          animation: isExtracting ? "cyber-pulse 1.4s ease-in-out infinite" : undefined,
        }}
      >
        {isExtracting ? (
          <>
            <Sparkles size={13} className="animate-spin-slow" /> 抽出中...
          </>
        ) : (
          <>
            <Sparkles size={13} /> ポーズを抽出してピクトグラムに反映
          </>
        )}
      </button>

      {/* Loading hint */}
      {isExtracting && (
        <p
          className="mt-2 font-mono text-[10px] text-[var(--cyber-cyan)] tracking-wider text-center animate-text-pulse"
          aria-live="polite"
        >
          DWPose 推論中... (3-5 秒)
        </p>
      )}

      {/* Status info row */}
      {statusInfo && state === "success" && (
        <div
          className="mt-2 font-mono text-[10px] text-[var(--cyber-cyan-dim)] tracking-wider"
          aria-live="polite"
        >
          ✓ 抽出済み · 信頼度: {statusInfo.confidence}% · {statusInfo.count}/18 keypoints
        </div>
      )}

      {/* Toasts (fixed top-right) */}
      <div
        className="fixed top-[60px] right-4 z-50 flex flex-col gap-2 pointer-events-none"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} />
        ))}
      </div>

      {/* Critical error modal */}
      {criticalModal && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="pose-extract-critical-title"
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(255, 38, 38, 0.18)" }}
        >
          <div
            className="cyber-panel cyber-grid w-[min(420px,90vw)] !p-5"
            style={{
              border: "1px solid var(--state-error)",
              boxShadow: "0 0 40px rgba(255,38,38,0.4)",
              background: "rgba(20, 8, 10, 0.95)",
            }}
          >
            <div className="flex items-center gap-2 mb-3">
              <FileWarning size={18} className="text-[var(--state-error)]" />
              <h2
                id="pose-extract-critical-title"
                className="font-mono text-[12px] uppercase tracking-[2px] text-[var(--state-error)]"
              >
                人物が検出できません
              </h2>
            </div>
            <p className="text-[12px] text-white/80 leading-relaxed mb-4">
              正面寄りの全身写真を選んでください。
              顔・肩・腰・足が画面内に収まっていると認識精度が上がります。
            </p>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setCriticalModal(false)}
                className="cyber-btn cyber-btn-primary !text-[11px]"
                autoFocus
              >
                OK
              </button>
            </div>
          </div>
        </div>
      )}
    </CyberPanel>
  )
})

function ToastItem({ toast }: { toast: Toast }) {
  const palette = TOAST_PALETTE[toast.kind]
  const Icon = palette.icon
  return (
    <div
      role="status"
      className="pointer-events-auto flex items-center gap-2 px-3 py-2 font-mono text-[11px] tracking-wider animate-toast-in"
      style={{
        border: `1px solid ${palette.border}`,
        background: palette.bg,
        color: palette.fg,
        boxShadow: `0 0 16px ${palette.glow}`,
        minWidth: 220,
      }}
    >
      <Icon size={14} aria-hidden />
      <span>{toast.text}</span>
    </div>
  )
}

const TOAST_PALETTE: Record<
  ToastKind,
  { fg: string; bg: string; border: string; glow: string; icon: typeof CheckCircle2 }
> = {
  success: {
    fg: "var(--state-success)",
    bg: "rgba(0, 255, 136, 0.08)",
    border: "var(--state-success)",
    glow: "rgba(0,255,136,0.35)",
    icon: CheckCircle2,
  },
  error: {
    fg: "var(--state-error)",
    bg: "rgba(255, 38, 38, 0.1)",
    border: "var(--state-error)",
    glow: "rgba(255,38,38,0.35)",
    icon: AlertTriangle,
  },
  warn: {
    fg: "var(--cyber-magenta)",
    bg: "rgba(255, 0, 183, 0.1)",
    border: "var(--cyber-magenta)",
    glow: "rgba(255,0,183,0.35)",
    icon: AlertTriangle,
  },
  info: {
    fg: "var(--cyber-cyan)",
    bg: "rgba(0, 234, 255, 0.08)",
    border: "var(--cyber-cyan)",
    glow: "rgba(0,234,255,0.35)",
    icon: Info,
  },
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
