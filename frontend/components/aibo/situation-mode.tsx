"use client"

import { useEffect, useRef, useState } from "react"
import { Plus, ChevronDown, ChevronUp, Maximize2, Scissors, Trash2, Dice5, Lock, RotateCcw, HelpCircle, Link as LinkIcon } from "lucide-react"
import { CyberPanel, SubHeader } from "./cyber-panel"
import { ProgressHud, type Stage } from "./progress-hud"
import { MakeupPalette } from "./makeup-palette"
import { ThumbWithControls } from "./thumb-with-controls"
import {
  PoseExtractionWidget,
  type PoseVariant,
  type PoseExtractionResult,
  type PoseExtractionWidgetHandle,
} from "./pose-extraction-widget"
import { demoBus, type SitState } from "@/lib/demo-bus"
import { toast } from "./toast-provider"

const POSE_PRESETS = [
  "standing_neutral - 自然な立ち",
  "standing_relaxed - リラックス立ち",
  "looking_back - 振り返り",
  "walking_forward - 前進歩行",
  "sitting_chair - 椅子に座る",
  "sitting_floor - 床に座る",
  "leaning_wall - 壁にもたれる",
  "running - 走る",
  "jumping - ジャンプ",
  "dancing - ダンス",
  "yoga_tree - ヨガ・ツリー",
  "yoga_warrior - ヨガ・戦士",
  "crouching - しゃがむ",
  "kneeling - ひざまずく",
  "lying_down - 横たわる",
  "stretching - ストレッチ",
  "praying - 祈る",
  "thinking - 考える",
  "waving - 手を振る",
  "pointing - 指差す",
  "embrace - 抱きしめる",
  "spinning - 回転",
  "looking_up - 見上げる",
  "looking_down - 見下ろす",
  "arms_crossed - 腕組み",
  "hands_on_hips - 腰に手",
  "victory_pose - 勝利ポーズ",
  "casting_spell - 魔法詠唱",
]

const NEUTRAL_SRC = "/neutral-body-mannequin-with-cyan-and-red-mask-over.jpg"
const RESULT_SRC = "/cyberpunk-anime-portrait-cherry-blossoms-sunset.jpg"

const PROGRESS_STAGES: Stage[] = [
  { name: "POSE TRANSFER", status: "completed" },
  { name: "BG SYNTH", status: "completed" },
  { name: "FILL INFERENCE", status: "active", progress: 64 },
  { name: "PHASE 3 RESTORE", status: "pending" },
  { name: "ALPHA BLEND", status: "pending" },
]

export function SituationMode() {
  const [state, setState] = useState<SitState>("pose")
  const [bgExpanded, setBgExpanded] = useState(false)
  const [bgLoaded, setBgLoaded] = useState(true)
  const [unifyTone, setUnifyTone] = useState(true)
  const [pose, setPose] = useState(POSE_PRESETS[2])
  const [yaw, setYaw] = useState(0)
  const [pitch, setPitch] = useState(0)
  const [roll, setRoll] = useState(0)
  const [headYaw, setHeadYaw] = useState(0)
  const [headPitch, setHeadPitch] = useState(0)
  const [headRoll, setHeadRoll] = useState(0)
  const [advancedClothes, setAdvancedClothes] = useState(false)
  const [makeupOpen, setMakeupOpen] = useState(false)
  const [phase3, setPhase3] = useState("auto")
  const [controlnet, setControlnet] = useState("openpose")
  const [poseVariant, setPoseVariant] = useState<PoseVariant>("default")
  const [poseOptions, setPoseOptions] = useState<string[]>(POSE_PRESETS)
  const [bodyShapeFlash, setBodyShapeFlash] = useState(false)
  const [headFlash, setHeadFlash] = useState(false)
  const [neutralSrc, setNeutralSrc] = useState<string | null>(NEUTRAL_SRC)
  const [bgSrc, setBgSrc] = useState<string | null>(RESULT_SRC)

  const phase3Warning = Math.abs(headYaw) > 35
  const widgetRef = useRef<PoseExtractionWidgetHandle | null>(null)

  // Demo bus wiring — lets global demo controls drive this mode
  useEffect(() => {
    return demoBus.on((e) => {
      if (e.type === "sit:setState") {
        setState(e.state)
      } else if (e.type === "sit:simulateExtraction") {
        widgetRef.current?.runSimulatedExtraction()
      } else if (e.type === "sit:triggerPhase3Warning") {
        setHeadYaw(45)
        toast.show("⚠ Phase 3 自動 OFF: 頭 Yaw 45°", "warn")
      } else if (e.type === "sit:triggerPoseError") {
        const map = {
          critical: "⚠ 人物が検出できません — 全身写真を選んでください",
          error: "ポーズを認識できません。別画像で試してください",
          warn: "精度低のため微調整推奨 (信頼度 42%)",
          info: "頭の向きは手動で調整してください",
        }
        const kindMap = {
          critical: "error",
          error: "error",
          warn: "warn",
          info: "info",
        } as const
        toast.show(map[e.severity], kindMap[e.severity])
      }
    })
  }, [])

  const handlePoseExtracted = (result: PoseExtractionResult) => {
    setPoseVariant(result.variant)

    // Inject "extracted" preset entry at the top + select it
    setPoseOptions((prev) => {
      const filtered = prev.filter((p) => !p.startsWith("extracted"))
      return [result.presetLabel, ...filtered]
    })
    setPose(result.presetLabel)

    if (result.applyHeadRotation) {
      setHeadYaw(result.headRotation.yaw)
      setHeadPitch(result.headRotation.pitch)
      setHeadRoll(result.headRotation.roll)
      setHeadFlash(true)
      setTimeout(() => setHeadFlash(false), 900)
    }

    if (result.applyBodyShape) {
      setBodyShapeFlash(true)
      setTimeout(() => setBodyShapeFlash(false), 900)
    }
  }

  return (
    <div className="grid grid-cols-[340px_minmax(0,1fr)_360px] grid-rows-[minmax(0,1fr)] gap-3 px-3 py-3 h-full">
      {/* === LEFT === */}
      <div className="space-y-3 overflow-y-auto pr-1 h-full min-h-0">
        <CyberPanel title="素体画像" numero="01">
          <div className="cyber-panel scanlines !p-0 h-[180px] flex items-center justify-center mb-2 cyber-panel-magenta">
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
        </CyberPanel>

        {/* Background ref slot */}
        <CyberPanel title="背景参照 (任意)" numero="02">
          <div className="border border-[var(--cyber-cyan-dim)] bg-[rgba(20,20,30,0.5)]">
            <button
              type="button"
              onClick={() => setBgExpanded((v) => !v)}
              aria-expanded={bgExpanded}
              className="w-full flex items-center gap-2 p-2 hover:bg-[rgba(0,234,255,0.05)] transition"
            >
              <div
                className="w-[60px] h-[60px] flex items-center justify-center shrink-0"
                style={{
                  border: bgLoaded
                    ? "1px solid var(--cyber-cyan-dim)"
                    : "1px dashed var(--cyber-cyan-dim)",
                  background: "rgba(10,10,12,0.6)",
                }}
              >
                {bgLoaded ? (
                  <span className="text-[28px]" aria-hidden>
                    🌅
                  </span>
                ) : (
                  <Plus size={20} className="text-white/40" />
                )}
              </div>
              <div className="flex-1 text-left">
                <div className="font-mono text-[12px] text-[var(--cyber-cyan)] tracking-wider">
                  背景参照 (任意)
                </div>
                <div className="font-mono text-[10px] text-white/60 tracking-wider mt-0.5">
                  {bgLoaded ? "桜並木 · 夕方" : "追加する"}
                </div>
              </div>
              {bgExpanded ? (
                <ChevronUp size={14} className="text-[var(--cyber-cyan)]" />
              ) : (
                <ChevronDown size={14} className="text-[var(--cyber-cyan)]" />
              )}
            </button>
            <div
              className="overflow-hidden"
              style={{
                maxHeight: bgExpanded ? 600 : 0,
                transition: "max-height 400ms ease-out",
              }}
            >
              <div className="p-3 border-t border-[var(--cyber-cyan-dim)] space-y-3">
                {!bgLoaded ? (
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => setBgLoaded(true)}
                      className="cyber-btn !text-[10px]"
                    >
                      📥 アップロード
                    </button>
                    <button
                      onClick={() => setBgLoaded(true)}
                      className="cyber-btn cyber-btn-primary !text-[10px]"
                    >
                      🌅 カタログから選ぶ
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="cyber-panel scanlines !p-0 h-[180px] relative overflow-hidden">
                      {bgSrc ? (
                        <ThumbWithControls
                          src={bgSrc}
                          alt="背景参照"
                          caption="桜並木 · 夕方 · 1024×1024"
                          onDelete={() => {
                            setBgSrc(null)
                            setBgLoaded(false)
                          }}
                          className="w-full h-full"
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => setBgSrc(RESULT_SRC)}
                          className="w-full h-full flex flex-col items-center justify-center gap-1 bg-[#1a1a24] hover:bg-[rgba(0,234,255,0.05)] transition"
                        >
                          <Plus size={20} className="text-[var(--cyber-cyan)]" />
                          <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-white/50">
                            背景を追加
                          </span>
                        </button>
                      )}
                    </div>
                    <label className="flex items-start gap-2 text-[11px] cursor-pointer">
                      <input
                        type="checkbox"
                        checked={unifyTone}
                        onChange={(e) => setUnifyTone(e.target.checked)}
                        className="accent-[var(--cyber-cyan)] mt-0.5"
                      />
                      <span>背景の色調を素体と統合する</span>
                    </label>
                    <p className="font-mono text-[10px] text-white/40">
                      ※ ON で素体のライティングと馴染ませます
                    </p>
                    <div className="flex gap-1.5">
                      <button className="cyber-btn !text-[10px] flex-1">
                        <Maximize2 size={11} /> 拡大
                      </button>
                      <button className="cyber-btn !text-[10px] flex-1">
                        <Scissors size={11} /> 編集
                      </button>
                      <button
                        className="cyber-btn cyber-btn-danger !text-[10px] flex-1"
                        onClick={() => setBgLoaded(false)}
                      >
                        <Trash2 size={11} /> 削除
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </CyberPanel>

        <CyberPanel title="シーン記述" numero="03">
          <textarea
            className="cyber-textarea"
            rows={3}
            placeholder="例: 桜並木の下、夕方、振り返って笑顔"
          />
          <details className="mt-3">
            <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80">
              ▸ ネガティブを編集する
            </summary>
            <textarea className="cyber-textarea mt-2" rows={2} />
          </details>
          <SubHeader>プロンプト補助:</SubHeader>
          <div className="grid grid-cols-3 gap-1.5">
            <select className="cyber-input !text-[10px] !py-1.5">
              <option className="bg-[#0a0a0c]">時刻 ▼</option>
              <option className="bg-[#0a0a0c]">朝</option>
              <option className="bg-[#0a0a0c]">昼</option>
              <option className="bg-[#0a0a0c]">夕方</option>
              <option className="bg-[#0a0a0c]">夜</option>
              <option className="bg-[#0a0a0c]">マジックアワー</option>
            </select>
            <select className="cyber-input !text-[10px] !py-1.5">
              <option className="bg-[#0a0a0c]">場所 ▼</option>
              <option className="bg-[#0a0a0c]">公園</option>
              <option className="bg-[#0a0a0c]">カフェ</option>
              <option className="bg-[#0a0a0c]">ビーチ</option>
              <option className="bg-[#0a0a0c]">街中</option>
              <option className="bg-[#0a0a0c]">桜並木</option>
            </select>
            <select className="cyber-input !text-[10px] !py-1.5">
              <option className="bg-[#0a0a0c]">ムード ▼</option>
              <option className="bg-[#0a0a0c]">笑顔</option>
              <option className="bg-[#0a0a0c]">クール</option>
              <option className="bg-[#0a0a0c]">ロマンティック</option>
              <option className="bg-[#0a0a0c]">ナチュラル</option>
              <option className="bg-[#0a0a0c]">ドラマティック</option>
            </select>
          </div>
          <p className="mt-1.5 font-mono text-[10px] text-white/40">
            (選択でプロンプトに自動追加されます)
          </p>
        </CyberPanel>

        <CyberPanel title="体型 (素体から)" numero="04">
          <div
            className="grid grid-cols-3 gap-2 transition-opacity duration-500"
            style={{
              opacity: bodyShapeFlash ? 1 : 0.5,
              filter: bodyShapeFlash
                ? "drop-shadow(0 0 8px var(--cyber-magenta))"
                : undefined,
            }}
          >
            {["BASE", "PROPORTION", "SILHOUETTE"].map((c) => (
              <div key={c} className="space-y-1">
                <SubHeader>
                  <span className="flex items-center gap-1">
                    <Lock size={9} /> {c}
                  </span>
                </SubHeader>
                <div
                  className="relative aspect-square border border-[var(--cyber-cyan-dim)]"
                  style={{
                    background:
                      "linear-gradient(rgba(0,234,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(0,234,255,0.06) 1px, transparent 1px)",
                    backgroundSize: "25% 25%",
                  }}
                >
                  <div
                    className="absolute w-2 h-2 -translate-x-1/2 -translate-y-1/2"
                    style={{
                      left: "50%",
                      top: "50%",
                      background: "var(--cyber-cyan-dim)",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-2 font-mono text-[10px] text-white/40">
            ※ 素体から自動継承
          </p>
        </CyberPanel>

        <details className="cyber-panel cyber-grid">
          <summary className="cursor-pointer section-header !mb-0 !pb-0 !border-b-0">
            <span className="text-white/60 mr-1">05 ·</span>
            <span>服参照 (任意, 上級モード)</span>
          </summary>
          <div className="mt-3 space-y-2">
            <label className="flex items-center gap-2 text-[11px] cursor-pointer">
              <input
                type="checkbox"
                checked={advancedClothes}
                onChange={(e) => setAdvancedClothes(e.target.checked)}
                className="accent-[var(--cyber-cyan)]"
              />
              シーン中で服も変える
            </label>
            {advancedClothes && (
              <div className="space-y-2 animate-fade-in">
                {[1, 2].map((i) => (
                  <div
                    key={i}
                    className="border border-[var(--cyber-cyan-dim)] p-2 flex items-center gap-2"
                  >
                    <div className="w-12 h-12 border border-dashed border-[var(--cyber-cyan-dim)] flex items-center justify-center">
                      <Plus size={14} className="text-white/40" />
                    </div>
                    <span className="font-mono text-[10px] text-[var(--cyber-cyan)]">
                      Slot {i}: 服
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>
      </div>

      {/* === CENTER === */}
      <div className="space-y-3 overflow-y-auto h-full min-h-0">
        <div className="flex items-center justify-between gap-2">
          <div className="flex gap-2">
            <button className="cyber-btn">
              <RotateCcw size={12} /> Reset Pose
            </button>
            <button className="cyber-btn">
              <LinkIcon size={12} /> Body→Coord Link
            </button>
            <button className="cyber-btn">
              <HelpCircle size={12} /> Help
            </button>
          </div>
          <div className="flex gap-1">
            {(["pose", "generating", "result"] as SitState[]).map((s, i) => (
              <button
                key={s}
                onClick={() => setState(s)}
                className="cyber-btn !px-2 !py-1 text-[10px]"
                style={{
                  background:
                    state === s ? "var(--gradient-primary-soft)" : undefined,
                  borderColor: state === s ? "var(--cyber-cyan)" : undefined,
                }}
              >
                Demo: State {String.fromCharCode(80 + i)}
              </button>
            ))}
          </div>
        </div>

        {state === "pose" && (
          <div className="space-y-3 animate-fade-in">
            <h3 className="section-header">ポーズエディター</h3>
            <select
              className="cyber-input"
              value={pose}
              onChange={(e) => {
                const v = e.target.value
                setPose(v)
                if (!v.startsWith("extracted")) setPoseVariant("default")
              }}
            >
              {poseOptions.map((p) => (
                <option key={p} className="bg-[#0a0a0c]">
                  {p}
                </option>
              ))}
            </select>

            <div
              className="cyber-panel scanlines !p-0 h-[400px] relative flex items-center justify-center overflow-hidden"
              style={{
                boxShadow: headFlash
                  ? "inset 0 0 40px rgba(0, 234, 255, 0.45)"
                  : undefined,
                transition: "box-shadow 600ms ease-out",
              }}
            >
              <StickFigure
                variant={poseVariant}
                yaw={yaw}
                pitch={pitch}
                roll={roll}
                headYaw={headYaw}
                headPitch={headPitch}
              />
              {bodyShapeFlash && (
                <div
                  className="absolute top-2 right-2 px-2 py-1 font-mono text-[9px] uppercase tracking-[1.5px] animate-fade-in"
                  style={{
                    color: "var(--cyber-magenta)",
                    border: "1px solid var(--cyber-magenta)",
                    background: "rgba(255, 0, 183, 0.1)",
                    boxShadow: "0 0 12px rgba(255, 0, 183, 0.4)",
                  }}
                >
                  ⚡ 体型 6 軸更新
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <SubHeader>体の回転</SubHeader>
                <CyberSlider label="Yaw" value={yaw} onChange={setYaw} min={-90} max={90} />
                <CyberSlider label="Pitch" value={pitch} onChange={setPitch} min={-45} max={45} />
                <CyberSlider label="Roll" value={roll} onChange={setRoll} min={-30} max={30} />
              </div>
              <div className="space-y-2">
                <SubHeader>頭の回転</SubHeader>
                <CyberSlider label="Yaw" value={headYaw} onChange={setHeadYaw} min={-90} max={90} />
                <CyberSlider label="Pitch" value={headPitch} onChange={setHeadPitch} min={-45} max={45} />
                <CyberSlider label="Roll" value={headRoll} onChange={setHeadRoll} min={-30} max={30} />
              </div>
            </div>

            {phase3Warning && (
              <div
                className="border border-[var(--cyber-magenta-dim)] bg-[rgba(255,0,183,0.08)] p-3 font-mono text-[11px] tracking-wider text-[var(--cyber-magenta)] animate-fade-in"
                role="alert"
              >
                ⚠️ 頭 Yaw {Math.abs(headYaw)}° 超: Phase 3 自動 OFF (横顔保護モード)
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <button className="cyber-btn">📥 マイポーズから読込</button>
              <button className="cyber-btn">💾 マイポーズに保存</button>
            </div>

            {/* ★ Pose Extraction Widget — placed at the bottom of the column */}
            <PoseExtractionWidget
              ref={widgetRef}
              onExtractSuccess={handlePoseExtracted}
            />
          </div>
        )}

        {state === "generating" && (
          <div className="animate-fade-in">
            <ProgressHud
              title="GENERATING SITUATION..."
              stages={PROGRESS_STAGES}
              overallPercent={64}
              elapsedSec={32}
              etaSec={28}
              onCancel={() => setState("pose")}
            />
          </div>
        )}

        {state === "result" && (
          <div className="space-y-3 animate-fade-in-up">
            <h3 className="section-header">SITUATION RESULT</h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="cyber-panel scanlines !p-0 h-[400px] relative flex items-center justify-center bg-[rgba(20,20,30,0.6)]">
                <span className="absolute top-2 left-2 z-10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider bg-[rgba(10,10,12,0.85)] text-[var(--cyber-cyan)] border border-[var(--cyber-cyan-dim)]">
                  Pose Ref
                </span>
                <StickFigure
                  variant={poseVariant}
                  yaw={yaw}
                  pitch={pitch}
                  roll={roll}
                  headYaw={headYaw}
                  headPitch={headPitch}
                />
              </div>
              <div className="cyber-panel cyber-panel-magenta scanlines !p-0 h-[400px] relative">
                <span className="absolute top-2 left-2 z-10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider bg-[rgba(10,10,12,0.85)] text-[var(--cyber-magenta)] border border-[var(--cyber-magenta-dim)]">
                  Result
                </span>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={RESULT_SRC || "/placeholder.svg"} alt="Result" className="w-full h-full object-cover" />
              </div>
            </div>
            <div className="border border-[var(--cyber-cyan-dim)] bg-[rgba(20,20,30,0.6)] px-3 py-2 font-mono text-[10px] uppercase tracking-[1.5px] text-white/70">
              Mode: 🎬 SITUATION · seed · 4815162342 · 64.8s · Phase 3:{" "}
              <span className="text-[var(--state-success)]">✓ APPLIED</span>
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
      <div className="space-y-3 overflow-y-auto pl-1 h-full min-h-0">
        <CyberPanel title="GENERATION">
          <SubHeader>SEED</SubHeader>
          <label className="flex items-center gap-2 text-[12px] cursor-pointer">
            <input type="checkbox" defaultChecked className="accent-[var(--cyber-cyan)]" />
            Random seed
          </label>
          <div className="flex gap-2 mt-2">
            <input className="cyber-input flex-1" placeholder="seed" />
            <button className="cyber-btn !px-3" aria-label="Roll">
              <Dice5 size={14} />
            </button>
          </div>

          <div className="mt-4">
            <SubHeader>Phase 3 顔復元</SubHeader>
            {[
              { id: "auto", label: "AUTO (推奨)" },
              { id: "on", label: "ON (強制適用)" },
              { id: "off", label: "OFF (なし)" },
            ].map((r) => (
              <label
                key={r.id}
                className="flex items-center gap-2 text-[11px] cursor-pointer py-1"
              >
                <input
                  type="radio"
                  name="phase3"
                  checked={phase3 === r.id}
                  onChange={() => setPhase3(r.id)}
                  className="accent-[var(--cyber-cyan)]"
                />
                {r.label}
              </label>
            ))}
          </div>

          <div className="mt-3">
            <SubHeader>ControlNet</SubHeader>
            {[
              { id: "openpose", label: "OpenPose (推奨)" },
              { id: "depth", label: "Depth" },
              { id: "canny", label: "Canny" },
              { id: "none", label: "なし" },
            ].map((r) => (
              <label
                key={r.id}
                className="flex items-center gap-2 text-[11px] cursor-pointer py-1"
              >
                <input
                  type="radio"
                  name="controlnet"
                  checked={controlnet === r.id}
                  onChange={() => setControlnet(r.id)}
                  className="accent-[var(--cyber-cyan)]"
                />
                {r.label}
              </label>
            ))}
          </div>

          <div className="mt-3">
            <SubHeader>メイク (オプション)</SubHeader>
            <label className="flex items-center gap-2 text-[11px] cursor-pointer">
              <input type="checkbox" className="accent-[var(--cyber-magenta)]" />
              生成後にメイクパレットを展開
            </label>
          </div>
        </CyberPanel>

        <button
          className="cyber-btn cyber-btn-primary w-full !py-3.5 !text-[13px] !tracking-[2px]"
          onClick={() => setState("generating")}
        >
          🎬 シーンを生成
        </button>
        <p className="font-mono text-[10px] text-[var(--cyber-cyan)]/70 tracking-wider text-center">
          推定時間: 60-70 秒 / VRAM ピーク: ~22GB
        </p>
      </div>
    </div>
  )
}

function CyberSlider({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80">
          {label}
        </span>
        <span className="font-mono text-[11px] text-[var(--cyber-cyan)] tabular-nums">
          {value}°
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full accent-[var(--cyber-cyan)]"
      />
    </div>
  )
}

type Joint = { x: number; y: number }
type Skeleton = {
  head: Joint
  neck: Joint
  shoulderL: Joint
  shoulderR: Joint
  elbowL: Joint
  elbowR: Joint
  handL: Joint
  handR: Joint
  hip: Joint
  hipL: Joint
  hipR: Joint
  kneeL: Joint
  kneeR: Joint
  footL: Joint
  footR: Joint
}

const SKELETONS: Record<PoseVariant, Skeleton> = {
  default: {
    head: { x: 100, y: 50 },
    neck: { x: 100, y: 72 },
    shoulderL: { x: 60, y: 90 },
    shoulderR: { x: 140, y: 90 },
    elbowL: { x: 50, y: 130 },
    elbowR: { x: 150, y: 130 },
    handL: { x: 40, y: 160 },
    handR: { x: 170, y: 150 },
    hip: { x: 100, y: 180 },
    hipL: { x: 75, y: 180 },
    hipR: { x: 125, y: 180 },
    kneeL: { x: 70, y: 225 },
    kneeR: { x: 130, y: 225 },
    footL: { x: 65, y: 270 },
    footR: { x: 135, y: 270 },
  },
  walking: {
    head: { x: 100, y: 50 },
    neck: { x: 100, y: 72 },
    shoulderL: { x: 60, y: 90 },
    shoulderR: { x: 140, y: 90 },
    elbowL: { x: 45, y: 120 },
    elbowR: { x: 160, y: 130 },
    handL: { x: 30, y: 100 },
    handR: { x: 175, y: 170 },
    hip: { x: 100, y: 180 },
    hipL: { x: 75, y: 180 },
    hipR: { x: 125, y: 180 },
    kneeL: { x: 60, y: 220 },
    kneeR: { x: 140, y: 220 },
    footL: { x: 50, y: 270 },
    footR: { x: 155, y: 268 },
  },
  sitting: {
    head: { x: 100, y: 70 },
    neck: { x: 100, y: 92 },
    shoulderL: { x: 65, y: 105 },
    shoulderR: { x: 135, y: 105 },
    elbowL: { x: 60, y: 145 },
    elbowR: { x: 140, y: 145 },
    handL: { x: 70, y: 180 },
    handR: { x: 130, y: 180 },
    hip: { x: 100, y: 195 },
    hipL: { x: 78, y: 195 },
    hipR: { x: 122, y: 195 },
    kneeL: { x: 55, y: 235 },
    kneeR: { x: 145, y: 235 },
    footL: { x: 50, y: 275 },
    footR: { x: 150, y: 275 },
  },
  looking_back: {
    head: { x: 118, y: 50 },
    neck: { x: 105, y: 72 },
    shoulderL: { x: 70, y: 92 },
    shoulderR: { x: 140, y: 88 },
    elbowL: { x: 55, y: 135 },
    elbowR: { x: 158, y: 130 },
    handL: { x: 50, y: 170 },
    handR: { x: 170, y: 165 },
    hip: { x: 100, y: 180 },
    hipL: { x: 78, y: 180 },
    hipR: { x: 122, y: 180 },
    kneeL: { x: 72, y: 225 },
    kneeR: { x: 128, y: 225 },
    footL: { x: 68, y: 270 },
    footR: { x: 132, y: 270 },
  },
}

function StickFigure({
  variant = "default",
  yaw,
  pitch,
  roll,
  headYaw,
  headPitch,
}: {
  variant?: PoseVariant
  yaw: number
  pitch: number
  roll: number
  headYaw: number
  headPitch: number
}) {
  const s = SKELETONS[variant]
  const headOffsetX = headYaw / 6
  const headOffsetY = headPitch / 6

  const joints: Joint[] = [
    s.shoulderL,
    s.shoulderR,
    s.elbowL,
    s.elbowR,
    s.handL,
    s.handR,
    s.hipL,
    s.hipR,
    s.kneeL,
    s.kneeR,
    s.footL,
    s.footR,
  ]

  return (
    <svg viewBox="0 0 200 300" className="w-[160px] h-[260px]" aria-label="Pose preview">
      <g
        style={{
          transform: `rotate(${roll}deg) skewX(${yaw / 6}deg) skewY(${pitch / 8}deg)`,
          transformOrigin: "100px 150px",
          transition: "transform 500ms ease",
        }}
      >
        <g style={{ transition: "all 500ms ease" }}>
          {/* Head */}
          <circle
            cx={s.head.x + headOffsetX}
            cy={s.head.y + headOffsetY}
            r="22"
            fill="none"
            stroke="var(--cyber-cyan)"
            strokeWidth="2"
            style={{
              filter: "drop-shadow(0 0 4px var(--cyber-cyan))",
              transition: "all 500ms ease",
            }}
          />
          {/* Spine */}
          <line
            x1={s.neck.x}
            y1={s.neck.y}
            x2={s.hip.x}
            y2={s.hip.y}
            stroke="var(--cyber-cyan)"
            strokeWidth="2"
            style={{ transition: "all 500ms ease" }}
          />
          {/* Shoulders */}
          <line
            x1={s.shoulderL.x}
            y1={s.shoulderL.y}
            x2={s.shoulderR.x}
            y2={s.shoulderR.y}
            stroke="var(--cyber-cyan)"
            strokeWidth="2"
            style={{ transition: "all 500ms ease" }}
          />
          {/* Left arm: shoulder → elbow → hand */}
          <polyline
            points={`${s.shoulderL.x},${s.shoulderL.y} ${s.elbowL.x},${s.elbowL.y} ${s.handL.x},${s.handL.y}`}
            stroke="var(--cyber-cyan)"
            strokeWidth="2"
            fill="none"
            style={{ transition: "all 500ms ease" }}
          />
          {/* Right arm */}
          <polyline
            points={`${s.shoulderR.x},${s.shoulderR.y} ${s.elbowR.x},${s.elbowR.y} ${s.handR.x},${s.handR.y}`}
            stroke="var(--cyber-magenta)"
            strokeWidth="2"
            fill="none"
            style={{ transition: "all 500ms ease" }}
          />
          {/* Hips */}
          <line
            x1={s.hipL.x}
            y1={s.hipL.y}
            x2={s.hipR.x}
            y2={s.hipR.y}
            stroke="var(--cyber-cyan)"
            strokeWidth="2"
            style={{ transition: "all 500ms ease" }}
          />
          {/* Left leg */}
          <polyline
            points={`${s.hipL.x},${s.hipL.y} ${s.kneeL.x},${s.kneeL.y} ${s.footL.x},${s.footL.y}`}
            stroke="var(--cyber-cyan)"
            strokeWidth="2"
            fill="none"
            style={{ transition: "all 500ms ease" }}
          />
          {/* Right leg */}
          <polyline
            points={`${s.hipR.x},${s.hipR.y} ${s.kneeR.x},${s.kneeR.y} ${s.footR.x},${s.footR.y}`}
            stroke="var(--cyber-cyan)"
            strokeWidth="2"
            fill="none"
            style={{ transition: "all 500ms ease" }}
          />
          {/* Joints */}
          {joints.map((j, i) => (
            <circle
              key={i}
              cx={j.x}
              cy={j.y}
              r="3"
              fill="var(--cyber-magenta)"
              style={{
                filter: "drop-shadow(0 0 4px var(--cyber-magenta))",
                transition: "all 500ms ease",
              }}
            />
          ))}
        </g>
      </g>
    </svg>
  )
}
