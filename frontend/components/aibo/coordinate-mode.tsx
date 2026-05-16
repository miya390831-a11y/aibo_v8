"use client"

import { useEffect, useState } from "react"
import { Plus, ChevronDown, ChevronUp, Maximize2, Scissors, Trash2, Dice5 } from "lucide-react"
import { CyberPanel, SubHeader } from "./cyber-panel"
import { CatalogModal, TrimmingModal } from "./modals"
import { ProgressHud, type Stage } from "./progress-hud"
import { MakeupPalette } from "./makeup-palette"
import { ThumbWithControls } from "./thumb-with-controls"
import { demoBus, type CoordState } from "@/lib/demo-bus"

type Slot = {
  id: number
  expanded: boolean
  loaded: boolean
  role: string
  name: string
  emoji: string
}

const ROLES = ["服", "トップス", "ボトムス", "靴", "帽子", "バッグ", "アクセ", "全身"]

const NEUTRAL_SRC = "/neutral-body-mannequin-with-cyan-and-red-mask-over.jpg"
const RESULT_SRC = "/cyberpunk-fashion-portrait.jpg"

const PROGRESS_STAGES: Stage[] = [
  { name: "AFFINE TRANSFORM", status: "completed" },
  { name: "FILL INFERENCE", status: "active", progress: 80 },
  { name: "MASK REGEN", status: "pending" },
  { name: "PHASE 3", status: "pending" },
  { name: "ALPHA BLEND", status: "pending" },
]

export function CoordinateMode() {
  const [state, setState] = useState<CoordState>("prep")
  const [advancedSlots, setAdvancedSlots] = useState(false)
  const [showCatalog, setShowCatalog] = useState(false)
  const [showTrimming, setShowTrimming] = useState(false)
  const [showFaceMask, setShowFaceMask] = useState(true)
  const [showBodyMask, setShowBodyMask] = useState(true)
  const [showGarmentMask, setShowGarmentMask] = useState(true)
  const [makeupOpen, setMakeupOpen] = useState(false)
  const [viewMode, setViewMode] = useState<"before" | "after" | "compare">("compare")
  const [neutralSrc, setNeutralSrc] = useState<string | null>(NEUTRAL_SRC)

  const [slots, setSlots] = useState<Slot[]>([
    { id: 1, expanded: false, loaded: false, role: "服", name: "", emoji: "" },
    { id: 2, expanded: false, loaded: false, role: "服", name: "", emoji: "" },
    { id: 3, expanded: false, loaded: false, role: "服", name: "", emoji: "" },
    { id: 4, expanded: false, loaded: false, role: "服", name: "", emoji: "" },
  ])

  const visibleSlots = advancedSlots ? slots : slots.slice(0, 2)

  const updateSlot = (id: number, patch: Partial<Slot>) =>
    setSlots((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)))

  // Demo bus wiring — lets the global demo controls drive this mode
  useEffect(() => {
    return demoBus.on((e) => {
      if (e.type === "coord:setState") setState(e.state)
      else if (e.type === "coord:openCatalog") setShowCatalog(true)
      else if (e.type === "coord:openTrimming") setShowTrimming(true)
      else if (e.type === "coord:toggleAdvancedSlots")
        setAdvancedSlots((v) => !v)
    })
  }, [])

  return (
    <div className="grid grid-cols-[340px_minmax(0,1fr)_360px] gap-3 px-3 py-3 min-h-[calc(100vh-90px)]">
      {/* === LEFT === */}
      <div className="space-y-3 overflow-y-auto pr-1">
        <CyberPanel title="素体画像" numero="01">
          <div className="cyber-panel scanlines !p-0 h-[200px] flex items-center justify-center mb-2 cyber-panel-magenta">
            {neutralSrc ? (
              <ThumbWithControls
                src={neutralSrc}
                alt="素体画像"
                caption="私の素体001 · 1024×1024"
                onDelete={() => setNeutralSrc(null)}
                className="w-full h-full"
              />
            ) : (
              <button
                type="button"
                onClick={() => setNeutralSrc(NEUTRAL_SRC)}
                className="w-full h-full flex flex-col items-center justify-center gap-1 transition hover:bg-[rgba(255,0,183,0.05)]"
              >
                <Plus size={20} style={{ color: "var(--cyber-magenta)" }} />
                <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-white/50">
                  素体を選択
                </span>
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <button className="cyber-btn cyber-btn-primary !text-[10px]">
              ライブラリ
            </button>
            <button
              className="cyber-btn !text-[10px]"
              onClick={() => setNeutralSrc(NEUTRAL_SRC)}
            >
              アップロード
            </button>
          </div>
          <p className="mt-2 font-mono text-[10px] text-[var(--cyber-cyan)]/70 tracking-wider">
            {neutralSrc ? "✓ 私の素体001 · 12 回使用" : "素体未選択"}
          </p>
        </CyberPanel>

        <CyberPanel title="服参照 (最大 4 枚)" numero="02">
          <div className="space-y-2">
            {visibleSlots.map((slot) => (
              <GarmentSlot
                key={slot.id}
                slot={slot}
                onToggleExpand={() =>
                  updateSlot(slot.id, { expanded: !slot.expanded })
                }
                onUpdate={(p) => updateSlot(slot.id, p)}
                onOpenCatalog={() => setShowCatalog(true)}
                onOpenTrimming={() => setShowTrimming(true)}
              />
            ))}
            <button
              type="button"
              onClick={() => setAdvancedSlots((v) => !v)}
              className="w-full font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/70 hover:text-[var(--cyber-cyan)] py-1.5 border border-dashed border-[var(--cyber-cyan-dim)] hover:border-[var(--cyber-cyan)]"
            >
              {advancedSlots ? "▲ Slot 3-4 を隠す" : "▼ Slot 3-4 を表示 (上級モード)"}
            </button>
          </div>
        </CyberPanel>

        <CyberPanel title="服プロンプト (任意)" numero="03">
          <textarea
            className="cyber-textarea"
            rows={2}
            placeholder="例: a red leather jacket"
          />
          <p className="mt-1.5 font-mono text-[10px] text-white/40 leading-relaxed">
            ※ 補助的な記述。服参照画像が優先されます
          </p>
        </CyberPanel>
      </div>

      {/* === CENTER === */}
      <div className="space-y-3 overflow-y-auto">
        {/* Demo state switcher */}
        <div className="flex items-center gap-1 justify-end">
          {(["prep", "generating", "result"] as CoordState[]).map((s, i) => (
            <button
              key={s}
              onClick={() => setState(s)}
              className="cyber-btn !px-2 !py-1 text-[10px]"
              style={{
                background: state === s ? "var(--gradient-primary-soft)" : undefined,
                borderColor: state === s ? "var(--cyber-cyan)" : undefined,
              }}
            >
              Demo: State {String.fromCharCode(80 + i)}
            </button>
          ))}
        </div>

        {state === "prep" && (
          <div className="space-y-3 animate-fade-in">
            <h3 className="section-header">マスクプレビュー</h3>
            <div className="cyber-panel scanlines !p-0 relative h-[500px] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={NEUTRAL_SRC || "/placeholder.svg"}
                alt="Neutral body with masks"
                className="w-full h-full object-cover"
              />
              {/* Mask overlays */}
              {showFaceMask && (
                <div
                  className="absolute pointer-events-none"
                  style={{
                    top: "8%",
                    left: "38%",
                    width: "24%",
                    height: "18%",
                    background: "rgba(255,51,102,0.35)",
                    mixBlendMode: "screen",
                    borderRadius: "50%",
                  }}
                />
              )}
              {showBodyMask && (
                <div
                  className="absolute pointer-events-none"
                  style={{
                    top: "26%",
                    left: "30%",
                    width: "40%",
                    height: "60%",
                    background: "rgba(0,234,255,0.25)",
                    mixBlendMode: "screen",
                  }}
                />
              )}
              {showGarmentMask && (
                <div
                  className="absolute pointer-events-none"
                  style={{
                    top: "30%",
                    left: "33%",
                    width: "34%",
                    height: "30%",
                    background: "rgba(100,255,150,0.3)",
                    mixBlendMode: "screen",
                  }}
                />
              )}
            </div>
            <div className="flex gap-3 flex-wrap">
              <MaskCheckbox
                color="var(--state-error)"
                checked={showFaceMask}
                onChange={setShowFaceMask}
                label="顔マスクを表示 (赤色)"
              />
              <MaskCheckbox
                color="var(--cyber-cyan)"
                checked={showBodyMask}
                onChange={setShowBodyMask}
                label="体マスクを表示 (青色)"
              />
              <MaskCheckbox
                color="var(--state-success)"
                checked={showGarmentMask}
                onChange={setShowGarmentMask}
                label="服領域を表示 (緑色)"
              />
            </div>
          </div>
        )}

        {state === "generating" && (
          <div className="animate-fade-in">
            <ProgressHud
              title="GENERATING COORDINATE..."
              stages={PROGRESS_STAGES}
              overallPercent={56}
              elapsedSec={28}
              etaSec={24}
              onCancel={() => setState("prep")}
            />
          </div>
        )}

        {state === "result" && (
          <div className="space-y-3 animate-fade-in-up">
            <h3 className="section-header">RESULT</h3>
            <div className="grid grid-cols-2 gap-3">
              {(viewMode === "compare" || viewMode === "before") && (
                <div className="cyber-panel scanlines !p-0 h-[400px] relative">
                  <span className="absolute top-2 left-2 z-10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider bg-[rgba(10,10,12,0.85)] text-[var(--cyber-cyan)] border border-[var(--cyber-cyan-dim)]">
                    Before (素体)
                  </span>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={NEUTRAL_SRC || "/placeholder.svg"}
                    alt="Before coordinate"
                    className="w-full h-full object-cover"
                  />
                </div>
              )}
              {(viewMode === "compare" || viewMode === "after") && (
                <div className="cyber-panel cyber-panel-magenta scanlines !p-0 h-[400px] relative">
                  <span className="absolute top-2 left-2 z-10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider bg-[rgba(10,10,12,0.85)] text-[var(--cyber-magenta)] border border-[var(--cyber-magenta-dim)]">
                    After (着替後)
                  </span>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={RESULT_SRC || "/placeholder.svg"}
                    alt="After coordinate"
                    className="w-full h-full object-cover"
                  />
                </div>
              )}
            </div>
            <div className="flex items-center justify-between flex-wrap gap-3 border border-[var(--cyber-cyan-dim)] bg-[rgba(20,20,30,0.6)] px-3 py-2">
              <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-white/70">
                Mode: 👗 COORDINATE · seed · 4815162342 · 52.4s
              </span>
              <div className="flex gap-1">
                {[
                  { id: "before", label: "Before のみ" },
                  { id: "after", label: "After のみ" },
                  { id: "compare", label: "並べて比較" },
                ].map((v) => (
                  <button
                    key={v.id}
                    onClick={() => setViewMode(v.id as typeof viewMode)}
                    className="cyber-btn !text-[10px] !px-2 !py-1"
                    style={{
                      background:
                        viewMode === v.id
                          ? "var(--gradient-primary-soft)"
                          : undefined,
                      borderColor:
                        viewMode === v.id ? "var(--cyber-cyan)" : undefined,
                    }}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setMakeupOpen((v) => !v)}
              className="cyber-btn cyber-btn-magenta w-full !py-3"
            >
              💄 メイクパレット展開
            </button>
            <MakeupPalette
              expanded={makeupOpen}
              onToggle={() => setMakeupOpen((v) => !v)}
              beforeImage={RESULT_SRC}
              afterImage={RESULT_SRC}
            />
          </div>
        )}
      </div>

      {/* === RIGHT === */}
      <div className="space-y-3 overflow-y-auto pl-1">
        <CyberPanel title="MASK ADJUSTMENT">
          <SubHeader>Tier 1 ワンクリック修正</SubHeader>
          <SubHeader>顔マスク:</SubHeader>
          <div className="grid grid-cols-2 gap-2">
            {[
              "+ 髪含める",
              "- 髪除外",
              "+ 首含める",
              "- 首除外",
            ].map((b) => (
              <button key={b} className="cyber-btn !text-[10px] !py-1.5">
                {b}
              </button>
            ))}
          </div>
          <button className="cyber-btn w-full mt-3">🔄 マスク自動再生成</button>
        </CyberPanel>

        <CyberPanel title="GENERATION">
          <div className="space-y-2">
            <SubHeader>SEED</SubHeader>
            <label className="flex items-center gap-2 text-[12px] cursor-pointer">
              <input type="checkbox" defaultChecked className="accent-[var(--cyber-cyan)]" />
              Random seed
            </label>
            <div className="flex gap-2">
              <input className="cyber-input flex-1" placeholder="seed" />
              <button className="cyber-btn !px-3" aria-label="Roll seed">
                <Dice5 size={14} />
              </button>
            </div>
          </div>
          <div className="mt-4">
            <label className="flex items-center gap-2 text-[12px] cursor-pointer">
              <input type="checkbox" className="accent-[var(--cyber-magenta)]" />
              結果に対してメイクを適用
            </label>
            <p className="font-mono text-[10px] text-white/40 mt-1">
              (生成後にパレットが展開されます)
            </p>
          </div>
        </CyberPanel>

        <button
          className="cyber-btn cyber-btn-primary w-full !py-3.5 !text-[13px] !tracking-[2px]"
          onClick={() => setState("generating")}
        >
          👗 着せ替えを生成
        </button>
        <p className="font-mono text-[10px] text-[var(--cyber-cyan)]/70 tracking-wider text-center">
          推定時間: 50-60 秒 / VRAM ピーク: ~18GB
        </p>
      </div>

      <CatalogModal open={showCatalog} onClose={() => setShowCatalog(false)} />
      <TrimmingModal open={showTrimming} onClose={() => setShowTrimming(false)} />
    </div>
  )
}

function GarmentSlot({
  slot,
  onToggleExpand,
  onUpdate,
  onOpenCatalog,
  onOpenTrimming,
}: {
  slot: Slot
  onToggleExpand: () => void
  onUpdate: (p: Partial<Slot>) => void
  onOpenCatalog: () => void
  onOpenTrimming: () => void
}) {
  return (
    <div
      className="border transition"
      style={{
        borderColor: slot.loaded
          ? "var(--cyber-cyan-dim)"
          : "rgba(0,234,255,0.1)",
        background: "rgba(20,20,30,0.5)",
      }}
    >
      {/* Header */}
      <button
        type="button"
        onClick={onToggleExpand}
        aria-expanded={slot.expanded}
        className="w-full flex items-center gap-2 p-2 hover:bg-[rgba(0,234,255,0.05)] transition"
      >
        {/* Thumb */}
        <div
          className="w-[60px] h-[60px] flex items-center justify-center shrink-0"
          style={{
            border: slot.loaded
              ? "1px solid var(--cyber-cyan-dim)"
              : "1px dashed var(--cyber-cyan-dim)",
            background: "rgba(10,10,12,0.6)",
          }}
        >
          {slot.loaded ? (
            <span className="text-[28px]" aria-hidden>
              {slot.emoji || "👕"}
            </span>
          ) : (
            <Plus size={20} className="text-white/40" />
          )}
        </div>

        <div className="flex-1 text-left">
          <div className="font-mono text-[12px] text-[var(--cyber-cyan)] tracking-wider">
            Slot {slot.id}: 服 {slot.id === 1 && "*"}
          </div>
          <div className="font-mono text-[10px] text-white/60 tracking-wider mt-0.5">
            {slot.loaded
              ? slot.expanded
                ? `Role: ${slot.role}`
                : slot.name || "loaded"
              : "追加する"}
          </div>
        </div>
        {slot.expanded ? (
          <ChevronUp size={14} className="text-[var(--cyber-cyan)]" />
        ) : (
          <ChevronDown size={14} className="text-[var(--cyber-cyan)]" />
        )}
      </button>

      {/* Expanded content */}
      <div
        className="overflow-hidden"
        style={{
          maxHeight: slot.expanded ? 600 : 0,
          transition: "max-height 400ms ease-out",
        }}
      >
        <div className="p-3 border-t border-[var(--cyber-cyan-dim)] space-y-3">
          {!slot.loaded ? (
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={onOpenCatalog}
                className="cyber-btn cyber-btn-primary !text-[10px]"
              >
                👗 カタログから選ぶ
              </button>
              <button
                type="button"
                onClick={onOpenTrimming}
                className="cyber-btn !text-[10px]"
              >
                📥 アップロード
              </button>
            </div>
          ) : (
            <>
              <div className="cyber-panel scanlines !p-0 h-[200px] flex items-center justify-center text-[80px]">
                {slot.emoji}
              </div>
              <label className="block">
                <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80 block mb-1">
                  Role
                </span>
                <select
                  className="cyber-input"
                  value={slot.role}
                  onChange={(e) => onUpdate({ role: e.target.value })}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r} className="bg-[#0a0a0c]">
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              <textarea
                className="cyber-textarea"
                rows={2}
                placeholder="プロンプト記述 (任意)"
              />
              <div className="flex gap-1.5">
                <button className="cyber-btn !text-[10px] flex-1">
                  <Maximize2 size={11} /> 拡大
                </button>
                <button
                  className="cyber-btn !text-[10px] flex-1"
                  onClick={onOpenTrimming}
                >
                  <Scissors size={11} /> 編集
                </button>
                <button
                  className="cyber-btn cyber-btn-danger !text-[10px] flex-1"
                  onClick={() => onUpdate({ loaded: false, name: "", emoji: "" })}
                >
                  <Trash2 size={11} /> 削除
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function MaskCheckbox({
  color,
  checked,
  onChange,
  label,
}: {
  color: string
  checked: boolean
  onChange: (v: boolean) => void
  label: string
}) {
  return (
    <label
      className="flex items-center gap-2 px-3 py-2 border cursor-pointer text-[11px]"
      style={{
        borderColor: `${color}66`,
        background: `${color}0d`,
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={{ accentColor: color }}
      />
      {label}
    </label>
  )
}
