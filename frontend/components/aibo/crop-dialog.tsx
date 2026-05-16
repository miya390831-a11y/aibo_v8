"use client"

import { useCallback, useState } from "react"
import { X, Check, ZoomIn } from "lucide-react"
import Cropper from "react-easy-crop"
import { cropAndResize, loadImageFromUrl } from "@/lib/image-utils"

type AreaPixels = { x: number; y: number; width: number; height: number }

export function CropDialog({
  open,
  imageSrc,
  onConfirm,
  onCancel,
  outputSize = 1024,
}: {
  open: boolean
  imageSrc: string
  onConfirm: (croppedB64: string) => void
  onCancel: () => void
  outputSize?: number
}) {
  const [crop, setCrop] = useState({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const [croppedAreaPixels, setCroppedAreaPixels] = useState<AreaPixels | null>(null)
  const [busy, setBusy] = useState(false)

  const onCropComplete = useCallback((_: unknown, area: AreaPixels) => {
    setCroppedAreaPixels(area)
  }, [])

  const handleConfirm = useCallback(async () => {
    if (!imageSrc || !croppedAreaPixels) return
    setBusy(true)
    try {
      const img = await loadImageFromUrl(imageSrc)
      const out = cropAndResize(img, croppedAreaPixels, outputSize, 0.92)
      onConfirm(out)
    } catch (err) {
      console.error("[CropDialog] crop failed:", err)
    } finally {
      setBusy(false)
    }
  }, [croppedAreaPixels, imageSrc, onConfirm, outputSize])

  if (!open) return null

  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <div
        className="cyber-panel cyber-grid relative max-w-[860px] w-[90vw] max-h-[90vh] overflow-hidden flex flex-col"
        style={{
          background: "rgba(20,20,30,0.96)",
          borderColor: "var(--cyber-cyan)",
          boxShadow: "var(--glow-strong-cyan)",
          padding: 20,
        }}
      >
        <h3 className="section-header" style={{ marginBottom: 16 }}>
          <span>顔の枠を調整</span>
          <span className="ml-auto font-mono text-[10px] text-white/50 normal-case tracking-normal">
            {outputSize}×{outputSize} で出力
          </span>
        </h3>

        <div className="relative h-[60vh] min-h-[360px] bg-black/40">
          <Cropper
            image={imageSrc}
            crop={crop}
            zoom={zoom}
            aspect={1}
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={onCropComplete}
            cropShape="rect"
            showGrid
            objectFit="contain"
          />
        </div>

        <div className="mt-3 flex items-center gap-3">
          <ZoomIn size={14} style={{ color: "var(--cyber-cyan)" }} />
          <input
            type="range"
            min={1}
            max={3}
            step={0.01}
            value={zoom}
            onChange={(e) => setZoom(parseFloat(e.target.value))}
            className="w-full accent-[var(--cyber-cyan)]"
          />
        </div>

        <p className="font-mono text-[10px] text-white/50 leading-relaxed mt-3 px-1">
          ▸ 顔がフレーム中央に来るように調整してください (1:1 固定)。
        </p>

        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onCancel} className="cyber-btn" disabled={busy}>
            <X size={12} /> キャンセル
          </button>
          <button
            onClick={handleConfirm}
            className="cyber-btn cyber-btn-primary"
            disabled={!croppedAreaPixels || busy}
          >
            <Check size={12} /> トリミング適用
          </button>
        </div>
      </div>
    </div>
  )
}
