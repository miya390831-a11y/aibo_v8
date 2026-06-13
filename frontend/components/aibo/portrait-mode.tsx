"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  Camera,
  ChevronDown,
  ChevronRight,
  Dice5,
  Download,
  HelpCircle,
  Sparkles,
  RotateCcw,
  Upload,
  Plus,
  X,
} from "lucide-react"
import { CyberPanel, SubHeader } from "./cyber-panel"
import { BodyLibraryModal } from "./library-modal"
import { LibraryModal } from "./modals"
import { MakeupPalette } from "./makeup-palette"
import { ThumbWithControls } from "./thumb-with-controls"
import { ProgressHud, type Stage } from "./progress-hud"
import { CropDialog } from "./crop-dialog"
import { toast } from "./toast-provider"
import {
  extractBodyShape,
  generateLibraryItemId,
  generatePortrait,
  getJobResult,
  neutralizeImage,
  saveLibraryItem,
  subscribeJobProgress,
  type BodyShape,
  type GenerateRequest,
  type JobProgressEvent,
  type JobResult,
} from "@/lib/api-portrait"
import { ApiError } from "@/lib/api"
import { estimateBase64Bytes, loadImage, shrinkForPreview } from "@/lib/image-utils"
import { rollRandomPrompt } from "@/lib/random_prompt_pool"

export type PortraitState = "initial" | "quick_done" | "neutral_done"
type AxisKey =
  | "base"
  | "proportion"
  | "silhouette"
  | "curves"
  | "posture"
  | "hips"
  | "shoulder"
  | "legs"
  | "bust"

const DEFAULT_PROMPT =
  "casual portrait photo, white ribbed knit top, fitted skinny pants, looking at camera, soft natural daylight, 50mm lens, photorealistic, sharp focus on face"
const DEFAULT_NEGATIVE =
  "lowres, blurry, low quality, distorted, deformed, bad anatomy, watermark, signature, text"
const NEUTRAL_PLACEHOLDER =
  "/neutral-body-mannequin-with-cyan-and-red-mask-over.jpg"

const AXIS_META: Record<AxisKey, { title: string; x: string; y: string }> = {
  base: { title: "BASE", x: "細身 ⇔ がっしり", y: "若め ⇔ 大人" },
  proportion: { title: "PROPORTION", x: "頭大 ⇔ 頭小", y: "丸顔 ⇔ 面長" },
  silhouette: { title: "SILHOUETTE", x: "直線的 ⇔ 曲線的", y: "華奢 ⇔ ふくよか" },
  curves: { title: "CURVES", x: "スレンダー ⇔ グラマー", y: "直線 ⇔ くびれ" },
  posture: { title: "POSTURE", x: "猫背 ⇔ 直立", y: "脱力 ⇔ きりっと" },
  hips: { title: "HIP", x: "細い腰 ⇔ ふくよか", y: "ヒップ位置 低 ⇔ 高" },
  shoulder: { title: "SHOULDER", x: "狭い肩 ⇔ 広い肩", y: "なで肩 ⇔ いかり肩" },
  legs: { title: "LEGS", x: "短い脚 ⇔ 長い脚", y: "細い脚 ⇔ しっかり" },
  bust: { title: "BUST", x: "控えめ ⇔ 豊か", y: "バスト位置 低 ⇔ 高" },
}
const TOP_AXES: AxisKey[] = ["base", "proportion", "silhouette"]
const MID_AXES: AxisKey[] = ["curves", "posture", "hips"]
const BOTTOM_AXES: AxisKey[] = ["shoulder", "legs", "bust"]

export function PortraitMode({
  state,
  onStateChange,
  onSendToCoordinate,
  onSendToSituation,
}: {
  state: PortraitState
  onStateChange: (s: PortraitState) => void
  onSendToCoordinate: () => void
  onSendToSituation: () => void
}) {
  const [showLibrary, setShowLibrary] = useState(false)
  const [showFaceMask, setShowFaceMask] = useState(true)
  const [showBodyMask, setShowBodyMask] = useState(true)
  const [bodyShapeExpanded, setBodyShapeExpanded] = useState(true)

  const [faceUploads, setFaceUploads] = useState<(string | null)[]>([
    null,
    null,
    null,
    null,
    null,
  ])
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT)
  const [userPrompt, setUserPrompt] = useState(DEFAULT_PROMPT)  // 手打ちの元文(OFF で復帰)
  const [randomMode, setRandomMode] = useState(false)           // 🎲 ランダムプロンプト ON/OFF
  const [negativePrompt, setNegativePrompt] = useState(DEFAULT_NEGATIVE)
  const [randomSeed, setRandomSeed] = useState(true)
  const [manualSeed, setManualSeed] = useState("")
  const [steps, setSteps] = useState(8)
  const [cfg, setCfg] = useState(4.0)
  const [bodyShape, setBodyShape] = useState<BodyShape>({
    base: { x: 0, y: 0 },
    proportion: { x: 0, y: 0 },
    silhouette: { x: 0, y: 0 },
    curves: { x: 0, y: 0 },
    posture: { x: 0, y: 0 },
    hips: { x: 0, y: 0 },
    shoulder: { x: 0, y: 0 },
    legs: { x: 0, y: 0 },
    bust: { x: 0, y: 0 },
  })
  const [shapeSource, setShapeSource] = useState<"extracted" | "manual" | null>(null)
  const [styleImage, setStyleImage] = useState<string | null>(null)
  const [extractingShape, setExtractingShape] = useState(false)
  const [shapeConfidence, setShapeConfidence] = useState<number | null>(null)

  const [generating, setGenerating] = useState(false)
  const [progressEvent, setProgressEvent] = useState<JobProgressEvent | null>(null)
  const [resultImage, setResultImage] = useState<string | null>(null)
  const [resultMeta, setResultMeta] = useState<JobResult["meta"] | null>(null)
  const [previewZoomOpen, setPreviewZoomOpen] = useState(false)
  const [previewZoomScale, setPreviewZoomScale] = useState(1)
  const [makeupOpen, setMakeupOpen] = useState(false)
  const [makeupAfterImage, setMakeupAfterImage] = useState<string | null>(null)
  const [neutralizing, setNeutralizing] = useState(false)
  const [neutralImage, setNeutralImage] = useState<string | null>(null)
  const [neutralMeta, setNeutralMeta] = useState<{
    seed_used: number
    body_shape_addendum: string
  } | null>(null)
  const [showBodyLibrary, setShowBodyLibrary] = useState(false)
  const sseStreamRef = useRef<{ close: () => void } | null>(null)

  const [cropTarget, setCropTarget] = useState<{
    slotIndex: number
    rawImage: string
  } | null>(null)
  const [dragOverSlot, setDragOverSlot] = useState<number | null>(null)

  useEffect(() => {
    return () => sseStreamRef.current?.close()
  }, [])

  const handleFile = useCallback(async (slotIndex: number, file: File) => {
    try {
      if (file.size > 8 * 1024 * 1024) toast.show("ファイルが大きいです", "info")
      const img = await loadImage(file)
      const shrunk = shrinkForPreview(img, 800)
      setCropTarget({ slotIndex, rawImage: shrunk })
    } catch (err) {
      toast.show(`画像の読込に失敗しました: ${String(err)}`, "error")
    }
  }, [])

  const openFilePicker = useCallback(
    (onFile: (file: File) => Promise<void> | void) => {
      const input = document.createElement("input")
      input.type = "file"
      input.accept = "image/*"
      input.style.display = "none"
      input.onchange = async (e) => {
        const file = (e.target as HTMLInputElement).files?.[0]
        if (file) await onFile(file)
      }
      document.body.appendChild(input)
      input.click()
      setTimeout(() => {
        if (document.body.contains(input)) document.body.removeChild(input)
      }, 1000)
    },
    [],
  )

  const handleSlotClick = useCallback(
    (slotIndex: number) => openFilePicker((file) => handleFile(slotIndex, file)),
    [handleFile, openFilePicker],
  )

  const handleDragOver = useCallback(
    (slotIndex: number) => (e: React.DragEvent) => {
      e.preventDefault()
      setDragOverSlot(slotIndex)
    },
    [],
  )
  const handleDragLeave = useCallback(() => setDragOverSlot(null), [])
  const handleDrop = useCallback(
    (slotIndex: number) => async (e: React.DragEvent) => {
      e.preventDefault()
      setDragOverSlot(null)
      const file = Array.from(e.dataTransfer.files).find((f) => f.type.startsWith("image/"))
      if (!file) {
        toast.show("画像ファイルではありません", "warn")
        return
      }
      await handleFile(slotIndex, file)
    },
    [handleFile],
  )

  const handleCropConfirm = useCallback(
    (croppedB64: string) => {
      if (!cropTarget) return
      const bytes = estimateBase64Bytes(croppedB64)
      if (bytes > 5 * 1024 * 1024) toast.show("画像サイズが大きいです", "warn")
      setFaceUploads((prev) =>
        prev.map((v, idx) => (idx === cropTarget.slotIndex ? croppedB64 : v)),
      )
      setCropTarget(null)
      toast.show(`スロット ${cropTarget.slotIndex + 1} に設定`, "success")
    },
    [cropTarget],
  )

  const handleStyleUpload = useCallback(
    () =>
      openFilePicker(async (file) => {
        const img = await loadImage(file)
        const shrunk = shrinkForPreview(img, 1024)
        setStyleImage(shrunk)
      }),
    [openFilePicker],
  )

  const handleExtractShape = useCallback(async () => {
    if (!styleImage || extractingShape) return
    setExtractingShape(true)
    try {
      const res = await extractBodyShape({ image: styleImage })
      // §6 マージ必須(置換禁止): 抽出は「抽出できた軸のみ」の partial。
      //   per-axis でマージし、抽出が返さない手動キー(bust 等)・手動軸(proportion.y 等)を保持する。
      setBodyShape((prev) => {
        const next: BodyShape = { ...prev }
        for (const key of Object.keys(res.body_shape) as AxisKey[]) {
          const incoming = res.body_shape[key]
          if (incoming) next[key] = { ...prev[key], ...incoming }
        }
        return next
      })
      setShapeSource("extracted")
      setShapeConfidence(Math.round(res.confidence * 100))
      toast.show("体型抽出が完了しました", "success")
    } catch (err) {
      toast.show(`抽出失敗: ${String(err)}`, "error")
    } finally {
      setExtractingShape(false)
    }
  }, [extractingShape, styleImage])

  const handleGenerate = useCallback(async () => {
    const validRefs = faceUploads.filter((v): v is string => v !== null)
    if (!validRefs.length) return toast.show("本人画像 (1 枚目) は必須です", "warn")
    if (!prompt.trim()) return toast.show("プロンプトを入力してください", "warn")

    let seed: number | null = null
    if (!randomSeed) {
      const parsed = parseInt(manualSeed, 10)
      if (!Number.isNaN(parsed)) seed = parsed
    }

    const hasFullBody =
      /full body|head to toe|standing pose/i.test(prompt)
    const finalPrompt = hasFullBody
      ? prompt
      : `full body shot, head to toe view, standing pose, ${prompt}`
    const finalNegative =
      `close-up, headshot, portrait crop, cropped legs, cropped feet, half body, ${negativePrompt || DEFAULT_NEGATIVE}`

    const req: GenerateRequest = {
      face_references: validRefs,
      prompt: finalPrompt,
      negative_prompt: finalNegative,
      body_shape: bodyShape,
      num_inference_steps: steps,
      guidance_scale: cfg,
      seed,
      width: 1024,
      height: 1536,
    }

    setGenerating(true)
    setProgressEvent({ status: "queued", progress: 0, stage: "QUEUED", elapsed_sec: 0, eta_sec: 0 })
    setResultImage(null)
    setResultMeta(null)
    setMakeupAfterImage(null)
    setNeutralImage(null)
    setNeutralMeta(null)

    try {
      const res = await generatePortrait(req)
      sseStreamRef.current?.close()
      sseStreamRef.current = subscribeJobProgress(res.job_id, {
        onEvent: (event) => {
          setProgressEvent(event)
          if (event.status === "completed") {
            getJobResult(res.job_id)
              .then((result) => {
                setResultImage(result.image)
                setResultMeta(result.meta)
                setGenerating(false)
                onStateChange("quick_done")
                toast.show(`生成完了 (${result.meta.elapsed_pass1_sec.toFixed(1)}s)`, "success")
              })
              .catch((err) => {
                setGenerating(false)
                toast.show(`結果取得失敗: ${String(err)}`, "error")
              })
          } else if (event.status === "failed") {
            setGenerating(false)
            toast.show(`生成失敗: ${event.error || event.message || "unknown"}`, "error")
          }
        },
        onError: () => {
          setGenerating(false)
          toast.show("進捗ストリームが切断されました", "error")
        },
      })
    } catch (err) {
      setGenerating(false)
      setProgressEvent(null)
      if (err instanceof ApiError) toast.show(`API エラー (${err.status}): ${err.detail}`, "error")
      else toast.show(`生成リクエスト失敗: ${String(err)}`, "error")
    }
  }, [bodyShape, cfg, faceUploads, manualSeed, negativePrompt, onStateChange, prompt, randomSeed, steps])

  const handleNeutralize = useCallback(async () => {
    const validRefs = faceUploads.filter((v): v is string => v !== null)
    if (!validRefs.length) {
      toast.show("本人画像 (1 枚目) は必須です", "warn")
      return
    }
    if (!resultImage) {
      toast.show("先に PORTRAIT を生成してください", "warn")
      return
    }
    setNeutralizing(true)
    try {
      const res = await neutralizeImage({
        face_refs: validRefs,
        body_shape: bodyShape,
        seed: null,
      })
      setNeutralImage(res.image)
      setNeutralMeta({
        seed_used: res.seed_used,
        body_shape_addendum: res.body_shape_addendum,
      })
      onStateChange("neutral_done")
      toast.show(`素体化完了 (${res.elapsed.toFixed(1)}秒)`, "success")
    } catch (err) {
      console.error("[PortraitMode] neutralize:", err)
      if (err instanceof ApiError) {
        toast.show(`素体化失敗 (${err.status}): ${err.detail}`, "error")
      } else {
        toast.show(`素体化失敗: ${String(err)}`, "error")
      }
    } finally {
      setNeutralizing(false)
    }
  }, [bodyShape, faceUploads, onStateChange, resultImage])

  const handleSaveToLibrary = useCallback(() => {
    if (!neutralImage || !neutralMeta) {
      toast.show("素体化済画像がありません", "warn")
      return
    }
    try {
      saveLibraryItem({
        id: generateLibraryItemId(),
        image: neutralImage,
        created_at: Date.now(),
        body_shape_addendum: neutralMeta.body_shape_addendum,
        seed_used: neutralMeta.seed_used,
        name: `素体_${new Date().toLocaleString("ja-JP", { hour12: false })}`,
      })
      toast.show("ライブラリに保存しました", "success")
    } catch (e) {
      toast.show(e instanceof Error ? e.message : "保存に失敗しました", "error")
    }
  }, [neutralImage, neutralMeta])

  const handleReset = useCallback(() => {
    sseStreamRef.current?.close()
    setFaceUploads([null, null, null, null, null])
    setPrompt(DEFAULT_PROMPT)
    setUserPrompt(DEFAULT_PROMPT)
    setRandomMode(false)
    setNegativePrompt(DEFAULT_NEGATIVE)
    setManualSeed("")
    setRandomSeed(true)
    setSteps(8)
    setCfg(4.0)
    setBodyShape({
      base: { x: 0, y: 0 },
      proportion: { x: 0, y: 0 },
      silhouette: { x: 0, y: 0 },
      curves: { x: 0, y: 0 },
      posture: { x: 0, y: 0 },
      hips: { x: 0, y: 0 },
      shoulder: { x: 0, y: 0 },
      legs: { x: 0, y: 0 },
      bust: { x: 0, y: 0 },
    })
    setShapeSource(null)
    setStyleImage(null)
    setShapeConfidence(null)
    setGenerating(false)
    setProgressEvent(null)
    setResultImage(null)
    setResultMeta(null)
    setPreviewZoomOpen(false)
    setPreviewZoomScale(1)
    setMakeupAfterImage(null)
    setMakeupOpen(false)
    setNeutralizing(false)
    setNeutralImage(null)
    setNeutralMeta(null)
    setShowBodyLibrary(false)
    onStateChange("initial")
  }, [onStateChange])

  const handleToggleRandom = () => {
    if (randomMode) {
      // ON → OFF: 保持した手打ち元文へ復帰
      setRandomMode(false)
      setPrompt(userPrompt)
    } else {
      // OFF → ON: 現在の手打ちを保持し、ランダム生成文を反映(編集可のまま)
      setUserPrompt(prompt)
      setPrompt(rollRandomPrompt())
      setRandomMode(true)
    }
  }
  const handleReroll = () => {
    if (!randomMode) return
    setPrompt(rollRandomPrompt())
  }
  const handlePromptChange = (v: string) => {
    setPrompt(v)
    if (!randomMode) setUserPrompt(v)  // OFF 時の編集は手打ち元文も更新(復帰先を最新化)
  }

  return (
    <div className="grid grid-cols-[340px_minmax(0,1fr)_440px] grid-rows-[minmax(0,1fr)] gap-3 px-3 py-3 h-full">
      <div className="space-y-3 overflow-y-auto pr-1 h-full min-h-0">
        <CyberPanel title="FACE REFERENCE" numero="01">
          <div className="grid grid-cols-3 gap-2">
            {faceUploads.map((src, i) =>
              src ? (
                <ThumbWithControls
                  key={i}
                  src={src}
                  alt={`Face reference slot ${i + 1}`}
                  caption={`face_ref_${String(i + 1).padStart(2, "0")} · 1024×1024`}
                  onDelete={() => setFaceUploads((prev) => prev.map((v, idx) => (idx === i ? null : v)))}
                  className="aspect-square"
                  imgClassName="w-full h-full object-cover border"
                />
              ) : (
                <button
                  key={i}
                  className="aspect-square flex items-center justify-center"
                  style={{ border: `1px dashed ${dragOverSlot === i ? "var(--cyber-cyan)" : i === 0 ? "var(--cyber-magenta)" : "var(--cyber-cyan-dim)"}` }}
                  onClick={() => handleSlotClick(i)}
                  onDragOver={handleDragOver(i)}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop(i)}
                >
                  <Plus size={20} style={{ color: i === 0 ? "var(--cyber-magenta)" : "var(--cyber-cyan)" }} />
                </button>
              ),
            )}
          </div>
        </CyberPanel>

        <CyberPanel title="PROMPT" numero="02">
          {/* ヘッダ右: 🎲ランダムトグル + 引き直し(.cyber-panel が relative なので絶対配置で右上へ) */}
          <div className="absolute top-3 right-3 z-10 flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleToggleRandom}
              aria-pressed={randomMode}
              title={randomMode ? "ランダムプロンプト ON(クリックで手打ちに復帰)" : "ランダムプロンプト OFF"}
              className="cyber-btn !px-2 !py-1 !text-[10px]"
              style={{
                background: randomMode ? "var(--gradient-primary-soft)" : undefined,
                borderColor: randomMode ? "var(--cyber-cyan)" : undefined,
                color: randomMode ? "var(--cyber-cyan)" : undefined,
              }}
            >
              🎲 ランダム{randomMode ? " ON" : ""}
            </button>
            <button
              type="button"
              onClick={handleReroll}
              disabled={!randomMode}
              title={randomMode ? "引き直す" : "ランダム ON 時のみ有効"}
              aria-label="プロンプトを引き直す"
              className="cyber-btn !px-2 !py-1 !text-[12px] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              🎲
            </button>
          </div>
          <textarea className="cyber-textarea" rows={4} value={prompt} onChange={(e) => handlePromptChange(e.target.value)} />
          <details className="mt-3">
            <summary className="cursor-pointer font-mono text-[10px] text-[var(--cyber-cyan)]/80">▸ ネガティブを編集する</summary>
            <textarea className="cyber-textarea mt-2" rows={3} value={negativePrompt} onChange={(e) => setNegativePrompt(e.target.value)} />
          </details>
        </CyberPanel>

        <details className="cyber-panel cyber-grid" open>
          <summary className="cursor-pointer section-header !mb-0 !pb-0 !border-b-0">
            <span className="text-white/60 mr-1">03 ·</span>
            <span>DETAIL SETTINGS</span>
          </summary>
          <div className="mt-3 space-y-3">
            <Slider label="STEPS" value={steps} min={1} max={30} onChange={setSteps} />
            <Slider label="CFG" value={cfg} min={1} max={10} step={0.1} onChange={setCfg} />
          </div>
        </details>
      </div>

      <div className="space-y-3 overflow-y-auto h-full min-h-0">
        <div className="cyber-panel cyber-grid !p-4">
          <button
            className="w-full flex items-center gap-2 border border-[var(--cyber-cyan-dim)] px-3 py-2"
            onClick={() => setBodyShapeExpanded((v) => !v)}
            type="button"
          >
            {bodyShapeExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span className="font-mono text-[12px] tracking-[2px] text-[var(--cyber-cyan)]">BODY SHAPE</span>
            <span className="font-mono text-[11px] text-white/60">体型 (任意)</span>
          </button>

          {bodyShapeExpanded && (
            <div className="mt-3 space-y-4 animate-fade-in">
              <StyleReferenceWidget
                image={styleImage}
                extracting={extractingShape}
                confidence={shapeConfidence}
                source={shapeSource}
                onUpload={handleStyleUpload}
                onRemove={() => setStyleImage(null)}
                onExtract={handleExtractShape}
              />

              <div className="flex items-center gap-3 py-1">
                <div className="flex-1 h-px bg-[rgba(0,234,255,0.18)]" />
                <span className="font-mono text-[10px] text-white/50">または手動で調整</span>
                <div className="flex-1 h-px bg-[rgba(0,234,255,0.18)]" />
              </div>

              <div className="space-y-3">
                {[TOP_AXES, MID_AXES, BOTTOM_AXES].map((row, rowIdx) => (
                  <div key={rowIdx} className="grid grid-cols-3 gap-3">
                    {row.map((axis) => (
                      <ShapeChart
                        key={axis}
                        title={AXIS_META[axis].title}
                        xLabel={AXIS_META[axis].x}
                        yLabel={AXIS_META[axis].y}
                        value={bodyShape[axis]}
                        onChange={(x, y) => {
                          setBodyShape((prev) => ({ ...prev, [axis]: { x, y } }))
                          if (shapeSource === "extracted") setShapeSource("manual")
                        }}
                      />
                    ))}
                  </div>
                ))}
              </div>

              <div className="flex justify-end">
                <button
                  className="cyber-btn !text-[10px] !px-3 !py-1.5"
                  onClick={() => {
                    setBodyShape({
                      base: { x: 0, y: 0 },
                      proportion: { x: 0, y: 0 },
                      silhouette: { x: 0, y: 0 },
                      curves: { x: 0, y: 0 },
                      posture: { x: 0, y: 0 },
                      hips: { x: 0, y: 0 },
                      shoulder: { x: 0, y: 0 },
                      legs: { x: 0, y: 0 },
                      bust: { x: 0, y: 0 },
                    })
                    setShapeSource(null)
                    setShapeConfidence(null)
                  }}
                >
                  <RotateCcw size={11} /> ALL RESET
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="space-y-3 overflow-y-auto pl-1 h-full min-h-0">
        <CyberPanel title="PREVIEW" numero="">
          <div className="mb-2 flex items-center gap-2">
            <button
              className="cyber-btn !px-3 !py-1.5 text-[11px]"
              type="button"
              onClick={() => setMakeupOpen((v) => !v)}
            >
              ◇ MAKE ▾
            </button>
            <button className="cyber-btn !px-3 !py-1.5 text-[11px]" type="button">
              <Upload size={11} /> IMPORT
            </button>
            <button className="cyber-btn !px-3 !py-1.5 text-[11px]" type="button" onClick={handleReset}>
              <RotateCcw size={11} /> RESET
            </button>
            <button className="cyber-btn !px-3 !py-1.5 text-[11px]" type="button">
              <HelpCircle size={11} /> HELP
            </button>
          </div>
          {makeupOpen && (
            <div className="mb-3 animate-fade-in-up">
              <MakeupPalette
                expanded
                onToggle={() => setMakeupOpen(false)}
                beforeImage={resultImage}
                afterImage={makeupAfterImage || resultImage}
                onApplied={(after) => setMakeupAfterImage(after || null)}
              />
            </div>
          )}
          <div className="cyber-panel scanlines relative h-[460px] overflow-hidden flex items-center justify-center sticky top-0 z-10" style={{ padding: 0 }}>
            {generating && progressEvent ? (
              <div className="w-[400px] max-w-[90%]">
                <ProgressHud
                  title="GENERATING PORTRAIT..."
                  stages={buildStagesFromProgressEvent(progressEvent)}
                  overallPercent={progressEvent.progress}
                  elapsedSec={progressEvent.elapsed_sec}
                  etaSec={progressEvent.eta_sec}
                />
              </div>
            ) : resultImage ? (
              <button
                type="button"
                className="w-full h-full bg-black/30 flex items-center justify-center group"
                onClick={() => {
                  setPreviewZoomScale(1)
                  setPreviewZoomOpen(true)
                }}
                aria-label="原寸で表示"
                title="クリックで100%表示"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={makeupAfterImage || resultImage}
                  alt="Generated portrait"
                  className="w-full h-full object-contain"
                />
                <span className="absolute bottom-2 right-2 px-2 py-1 font-mono text-[10px] border border-[var(--cyber-cyan-dim)] bg-[rgba(10,10,12,0.75)] text-[var(--cyber-cyan)] opacity-0 group-hover:opacity-100 transition-opacity">
                  100%表示
                </span>
              </button>
            ) : (
              <div className="text-center px-8 text-white/50">📸 ここに画像が表示されます</div>
            )}
          </div>
          <div className="flex items-center justify-between border border-[var(--cyber-cyan-dim)] px-2 py-1.5 mt-2 bg-[rgba(20,20,30,0.5)]">
            <span
              className="font-mono text-[10px] uppercase tracking-[1.5px] px-1.5 py-0.5 border"
              style={{
                color:
                  !resultImage && !generating
                    ? "rgba(255,255,255,0.4)"
                    : state === "neutral_done"
                      ? "var(--cyber-magenta)"
                      : "var(--cyber-cyan)",
                borderColor:
                  !resultImage && !generating
                    ? "rgba(255,255,255,0.2)"
                    : state === "neutral_done"
                      ? "var(--cyber-magenta)"
                      : "var(--cyber-cyan)",
              }}
            >
              {!resultImage && !generating
                ? "📸 EMPTY"
                : generating
                  ? "⏳ GENERATING"
                  : state === "neutral_done"
                    ? "💎 NEUTRAL BODY"
                    : "⚡ QUICK"}
            </span>
            <span className="font-mono text-[9px] text-white/50 tracking-wider truncate ml-2">
              {generating && progressEvent
                ? `${Math.round(progressEvent.progress)}% · ${progressEvent.stage || "RUNNING"}`
                : resultMeta
                  ? `seed · ${resultMeta.seed} · ${resultMeta.elapsed_pass1_sec.toFixed(1)}s`
                  : "Ready to generate"}
            </span>
          </div>
        </CyberPanel>

        <CyberPanel title="GENERATION" numero="">
          <div className="space-y-2">
            <SubHeader>SEED</SubHeader>
            <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={randomSeed} onChange={(e) => setRandomSeed(e.target.checked)} className="accent-[var(--cyber-cyan)]" />Random seed</label>
            <div className="flex gap-2">
              <input className="cyber-input flex-1" value={randomSeed ? "" : manualSeed} onChange={(e) => { setManualSeed(e.target.value.replace(/[^0-9]/g, "")); setRandomSeed(false) }} />
              <button className="cyber-btn !px-3" onClick={() => { const n = Math.floor(Math.random() * 2147483647); setManualSeed(String(n)); setRandomSeed(false) }}><Dice5 size={14} /></button>
            </div>
            <button className="cyber-btn cyber-btn-primary w-full !py-3.5 !text-[13px] !tracking-[2px] mt-2" onClick={handleGenerate} disabled={generating}>
              {generating ? "⏳ 生成中..." : "⚡ 生成"}
            </button>
            <p className="font-mono text-[10px] text-[var(--cyber-magenta)] tracking-wider">
              * 本人画像が必要
            </p>
          </div>
        </CyberPanel>

        {(state === "quick_done" || resultImage) && (
          <div className="space-y-3">
            <button className="cyber-btn w-full" onClick={handleGenerate}>⚡ 別 seed で再生成</button>
            <button className="cyber-btn w-full"><Download size={12} /> 保存・ダウンロード</button>
            <button
              type="button"
              className="cyber-btn cyber-btn-magenta w-full !py-3.5 !text-[13px] !tracking-[2px]"
              onClick={handleNeutralize}
              disabled={neutralizing || !resultImage}
            >
              {neutralizing ? "⏳ 素体化中..." : "💎 この顔で素体化する"}
            </button>
          </div>
        )}

        {state === "neutral_done" && (
          <div className="space-y-2">
            {neutralImage && (
              <div className="space-y-2 p-3 border border-[var(--cyber-magenta-dim)] rounded animate-fade-in-up bg-[rgba(255,0,183,0.03)]">
                <p className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-magenta)]">
                  NEUTRAL BODY
                </p>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={neutralImage}
                  alt="Neutral body"
                  className="w-full rounded border border-[var(--cyber-cyan-dim)] object-contain max-h-[320px] bg-black/40"
                />
                <button
                  type="button"
                  className="cyber-btn cyber-btn-primary w-full !py-2.5 !text-[12px]"
                  onClick={handleSaveToLibrary}
                >
                  📚 ライブラリに保存
                </button>
                <button
                  type="button"
                  className="cyber-btn w-full !py-2.5 !text-[12px]"
                  onClick={() => setShowBodyLibrary(true)}
                >
                  💎 ライブラリを開く
                </button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2 mt-2 animate-fade-in-up">
              <label className="flex items-center gap-1.5 px-2 py-1.5 border border-[var(--state-error)]/40 bg-[rgba(255,51,102,0.05)] cursor-pointer text-[10px]">
                <input type="checkbox" checked={showFaceMask} onChange={(e) => setShowFaceMask(e.target.checked)} className="accent-[var(--state-error)]" />
                <span>顔マスク</span>
              </label>
              <label className="flex items-center gap-1.5 px-2 py-1.5 border border-[var(--cyber-cyan-dim)] bg-[rgba(0,234,255,0.05)] cursor-pointer text-[10px]">
                <input type="checkbox" checked={showBodyMask} onChange={(e) => setShowBodyMask(e.target.checked)} className="accent-[var(--cyber-cyan)]" />
                <span>体マスク</span>
              </label>
            </div>
            <button className="cyber-btn cyber-btn-primary w-full !py-3 !text-[12px]" onClick={onSendToCoordinate}>👗 COORDINATE へ送る</button>
            <button className="cyber-btn cyber-btn-magenta w-full !py-3 !text-[12px]" onClick={onSendToSituation}>🎬 SITUATION へ送る</button>
          </div>
        )}
      </div>

      <LibraryModal open={showLibrary} onClose={() => setShowLibrary(false)} />
      <BodyLibraryModal open={showBodyLibrary} onClose={() => setShowBodyLibrary(false)} />
      <CropDialog
        open={cropTarget !== null}
        imageSrc={cropTarget?.rawImage || ""}
        outputSize={1024}
        onConfirm={handleCropConfirm}
        onCancel={() => setCropTarget(null)}
      />
      {previewZoomOpen && (makeupAfterImage || resultImage) && (
        <div
          className="fixed inset-0 z-[90] bg-black/85 flex items-center justify-center p-6"
          onClick={() => {
            setPreviewZoomOpen(false)
            setPreviewZoomScale(1)
          }}
          role="dialog"
          aria-modal="true"
          aria-label="100% preview"
        >
          <button
            type="button"
            className="absolute top-3 right-3 w-7 h-7 flex items-center justify-center border border-[var(--cyber-cyan-dim)] bg-[rgba(10,10,12,0.85)] text-[var(--cyber-cyan)] hover:text-white hover:border-[var(--cyber-cyan)] transition text-[14px] leading-none"
            onClick={() => {
              setPreviewZoomOpen(false)
              setPreviewZoomScale(1)
            }}
            aria-label="閉じる"
            title="閉じる"
          >
            ×
          </button>
          <div
            className="relative max-w-none max-h-none"
            onClick={(e) => e.stopPropagation()}
            onWheel={(e) => {
              e.preventDefault()
              const delta = e.deltaY > 0 ? -0.1 : 0.1
              setPreviewZoomScale((prev) => {
                const next = prev + delta
                return Math.max(0.2, Math.min(6, Math.round(next * 100) / 100))
              })
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={makeupAfterImage || resultImage || ""}
              alt="Generated portrait 100 percent"
              className="max-w-none max-h-none w-auto h-auto"
              style={{
                imageRendering: "auto",
                transform: `scale(${previewZoomScale})`,
                transformOrigin: "center center",
              }}
            />
            <div className="absolute top-3 left-3 px-2 py-1 font-mono text-[10px] border border-[var(--cyber-cyan-dim)] bg-[rgba(10,10,12,0.75)] text-[var(--cyber-cyan)]">
              {Math.round(previewZoomScale * 100)}%
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function StyleReferenceWidget({
  image,
  extracting,
  confidence,
  source,
  onUpload,
  onRemove,
  onExtract,
}: {
  image: string | null
  extracting: boolean
  confidence: number | null
  source: "extracted" | "manual" | null
  onUpload: () => void
  onRemove: () => void
  onExtract: () => void
}) {
  const isSuccess = confidence !== null
  return (
    <div className="cyber-panel cyber-grid !p-2 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]">
          📥 スタイル参照
        </span>
        {isSuccess && (
          <span className="font-mono text-[9px] tracking-wider px-1 py-0.5 border text-[var(--cyber-cyan)] border-[var(--cyber-cyan-dim)] bg-[rgba(0,234,255,0.06)]">
            {source === "manual" ? "MANUAL" : `EXTRACTED ${confidence}%`}
          </span>
        )}
      </div>
      <div className="border border-dashed border-[var(--cyber-cyan-dim)] min-h-[56px] flex items-center justify-center gap-2 bg-[rgba(10,10,12,0.6)]">
        {image ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={image} alt="style" className="h-[48px] w-[48px] object-cover border border-[var(--cyber-cyan-dim)]" />
            <button className="cyber-btn !px-2 !py-1 !text-[10px]" onClick={onExtract} disabled={extracting}>
              {extracting ? "⚡" : <Sparkles size={11} />}
              <span className="ml-1">抽出</span>
            </button>
            <button
              className="w-5 self-stretch flex items-center justify-center border text-[var(--state-error)] hover:bg-[var(--state-error)] hover:text-white transition"
              style={{ borderColor: "var(--state-error)" }}
              onClick={onRemove}
            >
              <X size={10} strokeWidth={2.5} />
            </button>
          </>
        ) : (
          <button className="w-full flex items-center justify-center gap-2 px-3 py-2" onClick={onUpload}>
            <Camera size={15} className="text-[var(--cyber-cyan)]" />
            <span className="cyber-btn cyber-btn-primary !text-[10px] !py-0.5 !px-2">📁 ファイル選択</span>
          </button>
        )}
      </div>
      <p className="font-mono text-[9px] leading-snug px-1.5 py-0.5 bg-[rgba(255,0,183,0.05)] border-l-2 border-[var(--cyber-magenta)]">
        <span style={{ color: "var(--cyber-magenta)" }}>※ 体型のみ抽出</span>
      </p>
    </div>
  )
}

function describeAxis(v: number, low: string, high: string): string {
  if (v <= -0.75) return low
  if (v <= -0.25) return `やや${low}`
  if (v < 0.25) return "標準"
  if (v < 0.75) return `やや${high}`
  return high
}

function ShapeChart({
  title,
  xLabel,
  yLabel,
  value = { x: 0, y: 0 },
  onChange,
}: {
  title: string
  xLabel: string
  yLabel: string
  value?: { x: number; y: number }
  onChange: (x: number, y: number) => void
}) {
  const xRel = (value.x + 1) / 2
  const yRel = (value.y + 1) / 2
  const [xLow, xHigh] = xLabel.split("⇔").map((s) => s.trim())
  const [yLow, yHigh] = yLabel.split("⇔").map((s) => s.trim())
  const xDesc = describeAxis(value.x, xLow || "低", xHigh || "高")
  const yDesc = describeAxis(value.y, yLow || "低", yHigh || "高")
  const isCenter = Math.abs(value.x) < 0.05 && Math.abs(value.y) < 0.05

  return (
    <div className="space-y-1">
      <SubHeader>{title}</SubHeader>
      <div
        className="relative aspect-square border border-[var(--cyber-cyan-dim)] cursor-crosshair"
        style={{
          background:
            "linear-gradient(rgba(0,234,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(0,234,255,0.06) 1px, transparent 1px)",
          backgroundSize: "25% 25%",
        }}
        onClick={(e) => {
          const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
          const px = (e.clientX - rect.left) / rect.width
          const py = (e.clientY - rect.top) / rect.height
          onChange(Math.max(-1, Math.min(1, px * 2 - 1)), Math.max(-1, Math.min(1, py * 2 - 1)))
        }}
      >
        <div className="absolute" style={{ top: 0, bottom: 0, left: `${xRel * 100}%`, width: "1px", background: "var(--cyber-magenta-dim)" }} />
        <div className="absolute" style={{ left: 0, right: 0, top: `${yRel * 100}%`, height: "1px", background: "var(--cyber-magenta-dim)" }} />
        <div className="absolute w-2 h-2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${xRel * 100}%`, top: `${yRel * 100}%`, background: "var(--cyber-magenta)", boxShadow: "var(--glow-soft-magenta)" }} />
      </div>
      <div className="font-mono text-[9px] text-[var(--cyber-cyan)] leading-tight truncate">
        {isCenter ? "標準" : `${xDesc} · ${yDesc}`}
      </div>
    </div>
  )
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/80">{label}</span>
        <span className="font-mono text-[11px] text-[var(--cyber-cyan)] tabular-nums">{value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value))} className="w-full accent-[var(--cyber-cyan)]" />
    </div>
  )
}

function buildStagesFromProgressEvent(event: JobProgressEvent): Stage[] {
  const allStages = ["VALIDATION", "PHASE 1 (HYPER-FLUX)", "PuLID FUSION", "PHASE 3A (GFPGAN)", "FINALIZING"]
  const current = (event.stage || "").toUpperCase()
  let activeIdx = 0
  if (current.includes("PHASE 1") || current.includes("HYPER")) activeIdx = 1
  else if (current.includes("PULID") || current.includes("FUSION")) activeIdx = 2
  else if (current.includes("PHASE 3") || current.includes("GFPGAN")) activeIdx = 3
  else if (current.includes("FINALIZ") || current.includes("ENCOD")) activeIdx = 4
  return allStages.map((name, idx) =>
    idx < activeIdx
      ? { name, status: "completed" as const }
      : idx === activeIdx
        ? {
            name,
            status: "active" as const,
            progress: Math.max(
              0,
              Math.min(100, ((event.progress - idx * (100 / allStages.length)) / (100 / allStages.length)) * 100),
            ),
          }
        : { name, status: "pending" as const },
  )
}
