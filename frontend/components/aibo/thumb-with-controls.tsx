"use client"

import { useState, type ReactNode } from "react"
import { X } from "lucide-react"
import { EnlargeModal } from "./modals"

export function ThumbWithControls({
  src,
  alt,
  caption,
  onDelete,
  className,
  imgClassName = "w-full h-full object-cover",
  children,
  fallback,
}: {
  /** Image to display and enlarge. If omitted, `fallback` is rendered (and click still opens the modal with the same `src`). */
  src?: string
  alt: string
  /** Caption shown under the enlarged image. */
  caption?: string
  /** When provided, a small X button is rendered at the top-right (visible on hover). */
  onDelete?: () => void
  className?: string
  imgClassName?: string
  /** Children rendered ON TOP of the image (e.g. mask overlays). */
  children?: ReactNode
  /** Rendered instead of <img> when `src` is missing. */
  fallback?: ReactNode
}) {
  const [open, setOpen] = useState(false)

  const handleOpen = () => {
    if (!src && !fallback) return
    setOpen(true)
  }

  return (
    <>
      <div className={`relative group ${className ?? ""}`}>
        <button
          type="button"
          onClick={handleOpen}
          aria-label={`${alt} を拡大`}
          className="block w-full h-full cursor-zoom-in focus:outline-none"
        >
          {src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={src} alt={alt} className={imgClassName} />
          ) : (
            fallback
          )}
        </button>

        {/* overlay children (masks etc.) — not clickable */}
        {children && <div className="absolute inset-0 pointer-events-none">{children}</div>}

        {onDelete && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onDelete()
            }}
            aria-label={`${alt} を削除`}
            className="absolute top-1 right-1 w-5 h-5 flex items-center justify-center bg-[rgba(10,10,12,0.9)] border text-[var(--state-error)] hover:bg-[var(--state-error)] hover:text-white opacity-0 group-hover:opacity-100 focus:opacity-100 transition z-10"
            style={{
              borderColor: "var(--state-error)",
              boxShadow: "0 0 8px rgba(255,51,102,0.5)",
            }}
          >
            <X size={12} strokeWidth={2.5} />
          </button>
        )}
      </div>

      <EnlargeModal
        open={open}
        src={src}
        caption={caption ?? alt}
        onClose={() => setOpen(false)}
      />
    </>
  )
}
