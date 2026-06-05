/**
 * 画像処理ユーティリティ
 */

export async function loadImage(file: File | Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = (err) => {
      URL.revokeObjectURL(url)
      reject(new Error(`Failed to load image: ${String(err)}`))
    }
    img.src = url
  })
}

export async function loadImageFromUrl(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = "anonymous"
    img.onload = () => resolve(img)
    img.onerror = (err) =>
      reject(new Error(`Failed to load image from URL: ${String(err)}`))
    img.src = url
  })
}

export function cropAndResize(
  image: HTMLImageElement,
  crop: { x: number; y: number; width: number; height: number },
  outputSize: number = 1024,
  quality: number = 0.92,
): string {
  const canvas = document.createElement("canvas")
  canvas.width = outputSize
  canvas.height = outputSize
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("Failed to get canvas 2d context")

  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = "high"
  ctx.drawImage(
    image,
    crop.x,
    crop.y,
    crop.width,
    crop.height,
    0,
    0,
    outputSize,
    outputSize,
  )
  return canvas.toDataURL("image/jpeg", quality)
}

/**
 * IMPL-008 (案b): 確定したクロップ矩形を中心固定で拡張し、元画像から
 * 顔周辺の実コンテキスト(髪・首・肩)を取り込む。
 *
 * 目的: UI の顔ドアップ + 生成側 snipe の二重クロップで facexlib align face が
 * 失敗し PuLID 無注入になる事故を、フロントで根治する。ユーザーの枠 ≒ 顔枠 とみなし、
 * factor 倍に広げることで出力で顔が枠の約 1/factor に着地する(facexlib 成功帯 0.40-0.70)。
 *
 * 実機検証: factor=1.7 fail / 2.0 success(境界) / 2.5 success / 3.0 success
 *   → 安全マージン込みで factor=2.5 を採用。
 *
 * - aspect=1 を維持(正方形)。
 * - 元画像より大きくはしない(side を min(W,H) でクランプ)。これにより小さい画像でも
 *   グレー余白を作らず、拡張が抑制される分むしろ顔が大きく残る(成功帯下限を割らない)。
 * - はみ出し時は枠を元画像内側へシフトしてクランプ(常に実画像をサンプル)。
 */
export function expandCropWithContext(
  crop: { x: number; y: number; width: number; height: number },
  imageWidth: number,
  imageHeight: number,
  factor: number = 2.5,
): { x: number; y: number; width: number; height: number } {
  const cx = crop.x + crop.width / 2
  const cy = crop.y + crop.height / 2

  // 正方形を維持しつつ factor 倍に拡張。元画像サイズで頭打ち。
  let side = Math.max(crop.width, crop.height) * factor
  side = Math.min(side, imageWidth, imageHeight)

  // 中心固定で配置し、元画像範囲にクランプ(はみ出しは内側へシフト)。
  let x = cx - side / 2
  let y = cy - side / 2
  x = Math.max(0, Math.min(x, imageWidth - side))
  y = Math.max(0, Math.min(y, imageHeight - side))

  return { x, y, width: side, height: side }
}

export function shrinkForPreview(
  image: HTMLImageElement,
  maxSize: number = 800,
  quality: number = 0.85,
): string {
  const width = image.naturalWidth || image.width
  const height = image.naturalHeight || image.height
  if (width <= maxSize && height <= maxSize) {
    const canvas = document.createElement("canvas")
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext("2d")
    if (!ctx) throw new Error("Failed to get canvas 2d context")
    ctx.drawImage(image, 0, 0)
    return canvas.toDataURL("image/jpeg", quality)
  }

  const scale = Math.min(maxSize / width, maxSize / height)
  const newW = Math.round(width * scale)
  const newH = Math.round(height * scale)
  const canvas = document.createElement("canvas")
  canvas.width = newW
  canvas.height = newH
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("Failed to get canvas 2d context")
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = "high"
  ctx.drawImage(image, 0, 0, newW, newH)
  return canvas.toDataURL("image/jpeg", quality)
}

export function estimateBase64Bytes(b64: string): number {
  const commaIdx = b64.indexOf(",")
  const body = commaIdx >= 0 ? b64.substring(commaIdx + 1) : b64
  return Math.floor((body.length * 3) / 4)
}
