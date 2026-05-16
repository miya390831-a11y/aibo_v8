"use client"

import { useState } from "react"
import { X } from "lucide-react"

/* === Library Save Modal === */
export function LibraryModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  if (!open) return null
  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        onClick={(e) => e.stopPropagation()}
        className="cyber-panel cyber-grid w-[480px] max-w-[92vw] animate-fade-in-up"
        style={{ boxShadow: "var(--glow-strong-cyan)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-mono text-[14px] uppercase tracking-[2px] text-[var(--cyber-cyan)]">
            📥 素体ライブラリへ保存
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-white/60 hover:text-[var(--cyber-cyan)]"
          >
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3">
          <Field label="名前">
            <input className="cyber-input" defaultValue="私の素体001" />
          </Field>
          <Field label="メモ (任意)">
            <textarea className="cyber-textarea" rows={2} placeholder="このシードはお気に入り..." />
          </Field>
          <Field label="タグ (カンマ区切り)">
            <input className="cyber-input" placeholder="favorite, summer" />
          </Field>
          <div className="font-mono text-[10px] uppercase tracking-[1.5px] text-white/50">
            容量: 2/3 (Free)
          </div>
        </div>
        <div className="flex gap-3 mt-5">
          <button className="cyber-btn flex-1" onClick={onClose}>
            キャンセル
          </button>
          <button className="cyber-btn cyber-btn-primary flex-1" onClick={onClose}>
            💾 保存
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="block">
      <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80 block mb-1.5">
        {label}
      </span>
      {children}
    </label>
  )
}

/* === Trimming Modal === */
const QUICK_MODES = [
  { id: "all", icon: "🔄", label: "全体" },
  { id: "upper", icon: "👤", label: "上半身" },
  { id: "lower", icon: "👇", label: "下半身" },
  { id: "free", icon: "✋", label: "自由" },
]

export function TrimmingModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [quick, setQuick] = useState("all")
  const [aspect, setAspect] = useState("1:1")
  const [removeBg, setRemoveBg] = useState(false)
  if (!open) return null
  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        onClick={(e) => e.stopPropagation()}
        className="cyber-panel cyber-grid w-[1080px] max-w-[95vw] max-h-[92vh] overflow-auto animate-fade-in-up"
        style={{ boxShadow: "var(--glow-strong-cyan)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-mono text-[14px] uppercase tracking-[2px] text-[var(--cyber-cyan)]">
            ✂️ 着せ替えに使う部分を選択
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-white/60 hover:text-[var(--cyber-cyan)]">
            <X size={16} />
          </button>
        </div>

        {/* Quick modes */}
        <div className="grid grid-cols-4 gap-2 mb-4">
          {QUICK_MODES.map((q) => {
            const active = quick === q.id
            return (
              <button
                key={q.id}
                type="button"
                onClick={() => setQuick(q.id)}
                aria-pressed={active}
                className="aspect-[2/1] flex items-center justify-center gap-2 border transition font-mono text-[12px] uppercase tracking-[1.5px]"
                style={{
                  background: active
                    ? "var(--gradient-primary-soft)"
                    : "rgba(20,20,30,0.6)",
                  borderColor: active
                    ? "var(--cyber-cyan)"
                    : "var(--cyber-cyan-dim)",
                  boxShadow: active ? "var(--glow-soft-cyan)" : "none",
                  color: active ? "#fff" : "var(--text-secondary)",
                }}
              >
                <span className="text-[18px]" aria-hidden>
                  {q.icon}
                </span>
                <span>{q.label}</span>
              </button>
            )
          })}
        </div>
        <div className="font-mono text-[10px] uppercase tracking-[1.5px] text-white/40 mb-3">
          (クリックで枠が自動配置されます)
        </div>

        {/* Edit area */}
        <div className="grid grid-cols-2 gap-4">
          <div className="relative aspect-square scanlines border border-[var(--cyber-cyan-dim)] bg-[rgba(20,20,30,0.6)]">
            <div className="absolute inset-0 flex items-center justify-center text-white/40 text-xs font-mono">
              SOURCE IMAGE
            </div>
            {/* Animated crop frame */}
            <div
              className="absolute"
              style={{
                top: "12%",
                left: "12%",
                right: "12%",
                bottom: "12%",
                border: "2px solid var(--cyber-cyan)",
                boxShadow: "var(--glow-strong-cyan), inset 0 0 12px rgba(0,234,255,0.2)",
                animation: "cyber-pulse 2s ease-in-out infinite",
              }}
            />
          </div>
          <div className="relative aspect-square border border-[var(--cyber-magenta-dim)] bg-[rgba(20,20,30,0.6)]">
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white/40 text-xs font-mono">
              <span>LIVE PREVIEW</span>
              <span className="text-[var(--cyber-magenta)]">→ 1024×1024</span>
            </div>
          </div>
        </div>

        {/* Options */}
        <div className="mt-4 space-y-2">
          <div className="flex items-center gap-4">
            <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80">
              アスペクト比:
            </span>
            {[
              { v: "1:1", label: "1:1 (推奨)" },
              { v: "free", label: "自由" },
            ].map((a) => (
              <label key={a.v} className="flex items-center gap-1.5 text-[12px] cursor-pointer">
                <input
                  type="radio"
                  name="aspect"
                  checked={aspect === a.v}
                  onChange={() => setAspect(a.v)}
                  className="accent-[var(--cyber-cyan)]"
                />
                {a.label}
              </label>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-[12px] cursor-pointer">
            <input
              type="checkbox"
              checked={removeBg}
              onChange={(e) => setRemoveBg(e.target.checked)}
              className="accent-[var(--cyber-cyan)]"
            />
            背景を除去する (rembg)
          </label>
        </div>

        <div className="flex gap-3 mt-5 justify-end">
          <button className="cyber-btn">リセット</button>
          <button className="cyber-btn cyber-btn-primary" onClick={onClose}>
            ✓ 適用して閉じる
          </button>
        </div>
      </div>
    </div>
  )
}

/* === Catalog Modal === */
const CATEGORIES = ["全て", "カジュアル", "ビジネス", "ワンピース", "ストリート"] as const

const SAMPLE_GARMENTS = Array.from({ length: 20 }, (_, i) => ({
  id: i,
  name: i === 0 ? "白Tシャツ" : i === 1 ? "ブラックパーカー" : `アイテム ${i + 1}`,
  category: ["カジュアル", "ビジネス", "ワンピース", "ストリート"][i % 4],
  emoji: ["👕", "🧥", "👗", "👖", "🧢", "👚", "🥻", "🩳"][i % 8],
}))

export function CatalogModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [tier, setTier] = useState<1 | 2>(1)
  const [filter, setFilter] = useState<(typeof CATEGORIES)[number]>("全て")
  const [selected, setSelected] = useState<(typeof SAMPLE_GARMENTS)[number] | null>(null)

  if (!open) return null

  const items =
    filter === "全て"
      ? SAMPLE_GARMENTS
      : SAMPLE_GARMENTS.filter((s) => s.category === filter)

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        onClick={(e) => e.stopPropagation()}
        className="cyber-panel cyber-grid w-[1080px] max-w-[95vw] max-h-[92vh] overflow-auto animate-fade-in-up"
        style={{ boxShadow: "var(--glow-strong-cyan)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-mono text-[14px] uppercase tracking-[2px] text-[var(--cyber-cyan)]">
            {tier === 1
              ? "👗 AIBO 服カタログ (20着)"
              : `👕 ${selected?.name ?? ""}`}
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-white/60 hover:text-[var(--cyber-cyan)]">
            <X size={16} />
          </button>
        </div>

        {tier === 1 ? (
          <>
            {/* Filter */}
            <div className="flex gap-2 mb-4 flex-wrap">
              {CATEGORIES.map((c) => {
                const active = filter === c
                return (
                  <button
                    key={c}
                    onClick={() => setFilter(c)}
                    className="cyber-btn"
                    style={{
                      background: active
                        ? "var(--gradient-primary-soft)"
                        : undefined,
                      borderColor: active ? "var(--cyber-cyan)" : undefined,
                      boxShadow: active ? "var(--glow-soft-cyan)" : "none",
                    }}
                  >
                    {c}
                  </button>
                )
              })}
            </div>

            {/* Grid */}
            <div className="grid grid-cols-5 gap-3">
              {items.map((g) => (
                <button
                  key={g.id}
                  onClick={() => {
                    setSelected(g)
                    setTier(2)
                  }}
                  className="cyber-panel aspect-[3/4] flex flex-col items-center justify-center gap-2 hover:!shadow-[var(--glow-soft-cyan)] hover:border-[var(--cyber-cyan)]"
                  style={{ padding: 8 }}
                >
                  <span className="text-[42px]" aria-hidden>
                    {g.emoji}
                  </span>
                  <span className="font-mono text-[10px] uppercase tracking-wider text-white/80">
                    {g.name}
                  </span>
                  <span className="font-mono text-[9px] text-[var(--cyber-cyan)]/70">
                    {g.category}
                  </span>
                </button>
              ))}
            </div>

            <div className="flex justify-end mt-4">
              <button className="cyber-btn" onClick={onClose}>
                閉じる
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="cyber-panel scanlines aspect-square flex items-center justify-center text-[80px]">
                {selected?.emoji}
                <span className="absolute top-2 left-2 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider bg-[rgba(10,10,12,0.85)] text-[var(--cyber-cyan)] border border-[var(--cyber-cyan-dim)]">
                  サンプル (参考)
                </span>
              </div>
              <div className="cyber-panel cyber-panel-magenta scanlines aspect-square flex items-center justify-center text-white/30 font-mono text-[11px] uppercase tracking-wider">
                生成プレビュー
              </div>
            </div>
            <div className="mt-4 space-y-3">
              <Field label="プロンプト (編集可)">
                <textarea
                  className="cyber-textarea"
                  rows={4}
                  defaultValue={`a ${selected?.name?.toLowerCase()}, soft cotton, neutral lighting, high detail`}
                />
              </Field>
              <Field label="Seed">
                <input className="cyber-input" defaultValue="4815162342" />
              </Field>
            </div>
            <div className="flex gap-3 mt-5">
              <button className="cyber-btn flex-1" onClick={() => setTier(1)}>
                ← 戻る
              </button>
              <button className="cyber-btn cyber-btn-primary flex-1">
                ⚡ クイック (即送信)
              </button>
              <button className="cyber-btn cyber-btn-magenta flex-1">
                🔧 カスタム (編集して使う)
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/* === Confirm Modal === */
export function ConfirmModal({
  open,
  title = "確認",
  message,
  confirmLabel = "削除する",
  onConfirm,
  onClose,
}: {
  open: boolean
  title?: string
  message?: string
  confirmLabel?: string
  onConfirm?: () => void
  onClose: () => void
}) {
  if (!open) return null
  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        onClick={(e) => e.stopPropagation()}
        className="cyber-panel cyber-grid w-[420px] max-w-[92vw] animate-fade-in-up"
        style={{
          boxShadow: "0 0 30px rgba(255, 51, 102, 0.4), inset 0 0 12px rgba(255, 51, 102, 0.05)",
          borderColor: "var(--state-error)",
        }}
      >
        <div className="flex items-center justify-between mb-3">
          <h2
            className="font-mono text-[13px] uppercase tracking-[2px]"
            style={{ color: "var(--state-error)", textShadow: "0 0 8px rgba(255,51,102,0.6)" }}
          >
            {"⚠ "}
            {title}
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-white/60 hover:text-white">
            <X size={16} />
          </button>
        </div>
        <p className="text-[12px] leading-relaxed text-white/80 mb-5">
          {message ?? "この操作は取り消せません。続行しますか？"}
        </p>
        <div className="flex gap-3">
          <button className="cyber-btn flex-1" onClick={onClose}>
            キャンセル
          </button>
          <button
            className="cyber-btn flex-1"
            onClick={() => {
              onConfirm?.()
              onClose()
            }}
            style={{
              borderColor: "var(--state-error)",
              color: "var(--state-error)",
              boxShadow: "0 0 10px rgba(255,51,102,0.3)",
            }}
          >
            {"✕ "}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

/* === Enlarge Image Modal === */
export function EnlargeModal({
  open,
  src,
  caption,
  onClose,
}: {
  open: boolean
  src?: string
  caption?: string
  onClose: () => void
}) {
  if (!open) return null
  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        onClick={(e) => e.stopPropagation()}
        className="relative max-w-[90vw] max-h-[85vh] flex flex-col items-center gap-3 animate-fade-in-up"
      >
        <div
          className="relative cyber-panel !p-0 overflow-hidden"
          style={{ boxShadow: "var(--glow-strong-cyan)" }}
        >
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={src}
              alt={caption ?? "Enlarged preview"}
              className="block max-h-[75vh] max-w-[88vw] object-contain"
            />
          ) : (
            <div
              className="flex items-center justify-center font-mono text-[11px] uppercase tracking-[2px] text-white/40 scanlines"
              style={{ width: "min(72vw, 720px)", height: "min(72vh, 720px)" }}
            >
              NO IMAGE
            </div>
          )}
        </div>
        <div className="flex items-center justify-between w-full gap-3">
          <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80">
            {caption ?? "preview · 1024×1024"}
          </span>
          <button className="cyber-btn" onClick={onClose}>
            ✕ 閉じる
          </button>
        </div>
      </div>
    </div>
  )
}

/* === Library Picker Modal (素体 / マイポーズ) === */
const SAMPLE_LIBRARY = Array.from({ length: 12 }, (_, i) => ({
  id: i,
  name: i === 0 ? "私の素体001" : `アイテム ${String(i + 1).padStart(3, "0")}`,
  uses: [12, 7, 4, 3, 2, 2, 1, 1, 0, 0, 0, 0][i] ?? 0,
  emoji: ["💎", "🧬", "🌸", "🔥", "🌙", "❄️", "🎴", "🌿", "👑", "🥷", "✨", "🌌"][i],
}))

export function LibraryPickerModal({
  open,
  type = "素体",
  onClose,
  onSelect,
}: {
  open: boolean
  type?: string
  onClose: () => void
  onSelect?: (id: number) => void
}) {
  const [query, setQuery] = useState("")
  const [tag, setTag] = useState("全て")
  const [sort, setSort] = useState("使用回数順")
  const [selectedId, setSelectedId] = useState<number | null>(0)

  if (!open) return null

  const filtered = SAMPLE_LIBRARY.filter((g) =>
    query ? g.name.toLowerCase().includes(query.toLowerCase()) : true,
  )
  const selected = filtered.find((g) => g.id === selectedId) ?? null

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div
        onClick={(e) => e.stopPropagation()}
        className="cyber-panel cyber-grid w-[680px] max-w-[95vw] max-h-[92vh] overflow-auto animate-fade-in-up"
        style={{ boxShadow: "var(--glow-strong-cyan)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-mono text-[14px] uppercase tracking-[2px] text-[var(--cyber-cyan)]">
            📂 ライブラリから選択 ({type})
          </h2>
          <button onClick={onClose} aria-label="Close" className="text-white/60 hover:text-[var(--cyber-cyan)]">
            <X size={16} />
          </button>
        </div>

        {/* Filter row */}
        <div className="grid grid-cols-[1fr_140px_160px] gap-2 mb-4">
          <input
            className="cyber-input"
            placeholder="検索..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="cyber-input"
            value={tag}
            onChange={(e) => setTag(e.target.value)}
          >
            {["全て", "favorite", "summer", "casual"].map((t) => (
              <option key={t} className="bg-[#0a0a0c]">
                タグ: {t}
              </option>
            ))}
          </select>
          <select
            className="cyber-input"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            {["使用回数順", "新しい順", "古い順", "名前順"].map((t) => (
              <option key={t} className="bg-[#0a0a0c]">
                並び順: {t}
              </option>
            ))}
          </select>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-4 gap-3">
          {filtered.map((g) => {
            const active = selectedId === g.id
            return (
              <button
                key={g.id}
                onClick={() => setSelectedId(g.id)}
                className="cyber-panel relative aspect-square flex flex-col items-center justify-center gap-1 transition"
                style={{
                  padding: 6,
                  borderColor: active ? "var(--cyber-cyan)" : undefined,
                  boxShadow: active ? "var(--glow-soft-cyan)" : undefined,
                  background: active
                    ? "var(--gradient-primary-soft)"
                    : undefined,
                }}
              >
                <span className="text-[36px]" aria-hidden>
                  {g.emoji}
                </span>
                <span className="font-mono text-[9px] uppercase tracking-wider text-white/80 text-center px-1">
                  {g.name}
                </span>
                <span className="font-mono text-[8px] text-[var(--cyber-cyan)]/70">
                  {g.uses} 回
                </span>
              </button>
            )
          })}
        </div>

        {/* Detail */}
        <div
          className="mt-4 border border-[var(--cyber-cyan-dim)] bg-[rgba(20,20,30,0.5)] p-3"
        >
          {selected ? (
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="text-[28px]" aria-hidden>
                  {selected.emoji}
                </span>
                <div className="flex flex-col gap-0.5">
                  <span className="font-mono text-[12px] text-white">
                    {selected.name}
                  </span>
                  <span className="font-mono text-[10px] text-white/50">
                    使用回数: {selected.uses} 回 · seed · 4815162342
                  </span>
                </div>
              </div>
              <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80">
                READY
              </span>
            </div>
          ) : (
            <span className="font-mono text-[11px] text-white/40">
              アイテムを選択してください
            </span>
          )}
        </div>

        <div className="flex items-center justify-between mt-4">
          <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-white/50">
            容量: 2/3 (Free)
          </span>
          <div className="flex gap-2">
            <button className="cyber-btn" onClick={onClose}>
              キャンセル
            </button>
            <button
              className="cyber-btn cyber-btn-primary"
              onClick={() => {
                if (selected) onSelect?.(selected.id)
                onClose()
              }}
              disabled={!selected}
              style={{ opacity: selected ? 1 : 0.4 }}
            >
              ✓ 選択
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
