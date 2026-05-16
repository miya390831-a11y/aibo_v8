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
