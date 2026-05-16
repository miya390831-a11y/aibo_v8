"use client"

import { useState } from "react"
import { applyMakeup, type MakeupIntensity, type MakeupStyle } from "@/lib/api-portrait"
import { ApiError } from "@/lib/api"
import { toast } from "./toast-provider"

const MAKEUP_STYLES = [
  { id: "natural", emoji: "🌿", label: "ナチュラル" },
  { id: "pink", emoji: "💄", label: "ピンクフェミニン" },
  { id: "glam", emoji: "💋", label: "グラマラス" },
  { id: "kbeauty", emoji: "✨", label: "K-Beauty" },
  { id: "romantic", emoji: "🍑", label: "ロマンティック" },
  { id: "cool", emoji: "❄️", label: "クールビューティー" },
  { id: "mode", emoji: "🌙", label: "モード" },
  { id: "night", emoji: "🌟", label: "ナイトメイク" },
  { id: "nomakeup", emoji: "🌸", label: "ノーメイク風" },
  { id: "retro", emoji: "👑", label: "レトロ" },
] as const

const INTENSITIES = [
  { id: "light", visual: "◯○○", label: "薄め" },
  { id: "medium", visual: "●●○", label: "ふつう" },
  { id: "heavy", visual: "●●●", label: "濃いめ" },
] as const

export function MakeupPalette({
  expanded,
  onToggle,
  beforeImage,
  afterImage,
  onApplied,
}: {
  expanded: boolean
  onToggle?: () => void
  beforeImage?: string | null
  afterImage?: string | null
  onApplied?: (afterImage: string | null) => void
}) {
  const [selectedMakeup, setSelectedMakeup] = useState<MakeupStyle>("natural")
  const [selectedIntensity, setSelectedIntensity] =
    useState<MakeupIntensity>("medium")
  const [applying, setApplying] = useState(false)

  const handleReset = () => {
    onApplied?.(null)
    toast.show("メイクプレビューをリセットしました", "info")
  }

  const handleApply = async () => {
    if (!beforeImage?.trim()) {
      toast.show("元画像がありません。先にポートレートを生成してください。", "warn")
      return
    }

    setApplying(true)
    try {
      const result = await applyMakeup({
        base_image: beforeImage,
        makeup_style: selectedMakeup,
        intensity: selectedIntensity,
      })
      onApplied?.(result.image)

      const ws = result.meta?.warnings
      if (Array.isArray(ws) && ws.includes("face_mask_failed")) {
        toast.show(
          "顔が検出できませんでした。元画像をそのまま表示しています。",
          "warn",
        )
      } else {
        const sec =
          typeof result.meta?.elapsed_sec === "number"
            ? result.meta.elapsed_sec
            : typeof result.meta?.makeup_infer_sec === "number"
              ? result.meta.makeup_infer_sec
              : undefined
        toast.show(
          typeof sec === "number"
            ? `メイク適用完了 (${sec.toFixed(1)}s)`
            : "メイク適用完了",
          "success",
        )
      }
      onToggle?.()
    } catch (err) {
      console.error("[MakeupPalette] applyMakeup:", err)
      const msg =
        err instanceof ApiError
          ? `メイク適用失敗 (${err.status}): ${err.detail}`
          : `メイク適用失敗: ${String(err)}`
      toast.show(msg, "error")
    } finally {
      setApplying(false)
    }
  }

  if (!expanded) return null

  return (
    <section
      aria-label="Makeup palette"
      className="border border-[var(--cyber-magenta-dim)]"
      style={{
        background:
          "linear-gradient(180deg, rgba(255,0,183,0.05), rgba(10,10,12,0))",
      }}
    >
      <div className="p-4">
        {/* Header strip */}
        <div className="flex items-center justify-between mb-3">
          <h3
            className="font-mono text-[12px] uppercase tracking-[2px] text-[var(--cyber-magenta)]"
            style={{ textShadow: "0 0 8px rgba(255,0,183,0.6)" }}
          >
            💄 メイク加工
          </h3>
          <span className="font-mono text-[9px] tracking-wider text-[var(--cyber-magenta)]/70">
            MAKEUP PALETTE
          </span>
        </div>

        {/* Style grid 5x2 */}
          <div className="grid grid-cols-5 gap-2">
            {MAKEUP_STYLES.map((s) => {
              const active = selectedMakeup === s.id
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setSelectedMakeup(s.id)}
                  aria-pressed={active}
                  className="aspect-square flex flex-col items-center justify-center gap-1 p-2 border transition"
                  style={{
                    background: active
                      ? "linear-gradient(135deg, rgba(255,0,183,0.25), rgba(0,234,255,0.15))"
                      : "rgba(20,20,30,0.8)",
                    borderColor: active
                      ? "var(--cyber-magenta)"
                      : "var(--cyber-magenta-dim)",
                    boxShadow: active ? "var(--glow-strong-magenta)" : "none",
                    transform: active ? "translateY(-2px)" : "none",
                  }}
                >
                  <span className="text-[24px] leading-none" aria-hidden>
                    {s.emoji}
                  </span>
                  <span
                    className="font-mono text-[9px] uppercase tracking-wider text-center leading-tight"
                    style={{
                      color: active ? "#fff" : "var(--text-secondary)",
                    }}
                  >
                    {s.label}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Intensity */}
          <div className="grid grid-cols-3 gap-2 mt-4">
            {INTENSITIES.map((i) => {
              const active = selectedIntensity === i.id
              return (
                <button
                  key={i.id}
                  type="button"
                  onClick={() => setSelectedIntensity(i.id)}
                  aria-pressed={active}
                  className="py-2.5 flex items-center justify-center gap-2 border transition font-mono text-[11px] uppercase tracking-[1.5px]"
                  style={{
                    background: active
                      ? "rgba(0,234,255,0.12)"
                      : "rgba(20,20,30,0.6)",
                    borderColor: active
                      ? "var(--cyber-cyan)"
                      : "var(--cyber-cyan-dim)",
                    color: active ? "var(--cyber-cyan)" : "var(--text-secondary)",
                    boxShadow: active ? "var(--glow-soft-cyan)" : "none",
                  }}
                >
                  <span>{i.visual}</span>
                  <span>{i.label}</span>
                </button>
              )
            })}
          </div>

          {/* Before/after */}
          <div className="grid grid-cols-2 gap-0 mt-5 border border-[var(--cyber-cyan-dim)]">
            {[
              { label: "元画像", src: beforeImage, ml: false },
              { label: "メイク後", src: afterImage, ml: true },
            ].map((p, idx) => (
              <div
                key={idx}
                className={`relative h-[200px] cyber-panel scanlines ${
                  idx === 0 ? "" : "border-l border-[var(--cyber-cyan-dim)]"
                }`}
                style={{ padding: 0 }}
              >
                {p.src ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={p.src || "/placeholder.svg"}
                    alt={p.label}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-white/40 text-xs">
                    {p.label}
                  </div>
                )}
                <span
                  className="absolute top-2 left-2 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider bg-[rgba(10,10,12,0.85)] text-[var(--cyber-cyan)] border border-[var(--cyber-cyan-dim)]"
                >
                  {p.label}
                </span>
              </div>
            ))}
          </div>

        {/* Actions */}
        <div className="grid grid-cols-2 gap-3 mt-5">
          <button type="button" className="cyber-btn" onClick={handleReset}>
            元に戻す
          </button>
          <button
            type="button"
            onClick={handleApply}
            disabled={applying}
            className="cyber-btn cyber-btn-magenta"
          >
            {applying ? "⚡ 適用中..." : "💄 メイクを適用"}
          </button>
        </div>
      </div>
    </section>
  )
}
