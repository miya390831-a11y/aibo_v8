"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { X } from "lucide-react"

export type ToastKind = "success" | "info" | "warn" | "error"

type Toast = {
  id: number
  kind: ToastKind
  text: string
}

type ToastApi = {
  show: (text: string, kind?: ToastKind) => void
}

const ToastContext = createContext<ToastApi | null>(null)

// Module-level escape hatch so non-React code (e.g. demo bus handlers) can call toast.
let externalShow: ToastApi["show"] | null = null
export const toast = {
  show(text: string, kind: ToastKind = "info") {
    externalShow?.(text, kind)
  },
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const idRef = useRef(0)

  const show = useCallback<ToastApi["show"]>((text, kind = "info") => {
    const id = ++idRef.current
    setToasts((prev) => [...prev, { id, kind, text }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 3500)
  }, [])

  useEffect(() => {
    externalShow = show
    return () => {
      externalShow = null
    }
  }, [show])

  const value = useMemo<ToastApi>(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport
        toasts={toasts}
        onDismiss={(id) =>
          setToasts((prev) => prev.filter((t) => t.id !== id))
        }
      />
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    // Fall back to no-op if provider isn't mounted yet.
    return { show: () => {} }
  }
  return ctx
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: number) => void
}) {
  if (toasts.length === 0) return null
  return (
    <div className="fixed bottom-10 right-4 z-[1100] flex flex-col gap-2 pointer-events-none">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  )
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast
  onDismiss: () => void
}) {
  const palette = toastPalette(toast.kind)
  return (
    <div
      role="status"
      className="pointer-events-auto relative px-4 py-3 min-w-[280px] max-w-[420px] font-mono text-[12px] leading-relaxed animate-toast-in"
      style={{
        background: "rgba(20,20,30,0.95)",
        backdropFilter: "blur(8px)",
        border: `1px solid ${palette.border}`,
        boxShadow: palette.glow,
        color: "var(--text-primary)",
      }}
    >
      <span
        aria-hidden
        className="absolute top-0 left-0 w-2.5 h-2.5"
        style={{
          borderTop: `2px solid ${palette.border}`,
          borderLeft: `2px solid ${palette.border}`,
        }}
      />
      <span
        aria-hidden
        className="absolute bottom-0 right-0 w-2.5 h-2.5"
        style={{
          borderBottom: `2px solid ${palette.border}`,
          borderRight: `2px solid ${palette.border}`,
        }}
      />
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-0.5"
          style={{ color: palette.border, textShadow: palette.textShadow }}
        >
          {palette.icon}
        </span>
        <span className="flex-1">{toast.text}</span>
        <button
          aria-label="Close toast"
          onClick={onDismiss}
          className="text-white/40 hover:text-white"
        >
          <X size={12} />
        </button>
      </div>
    </div>
  )
}

function toastPalette(kind: ToastKind) {
  switch (kind) {
    case "success":
      return {
        border: "var(--state-success)",
        glow: "0 0 14px rgba(100,255,150,0.45)",
        textShadow: "0 0 8px rgba(100,255,150,0.7)",
        icon: "✓",
      }
    case "warn":
      return {
        border: "var(--cyber-magenta)",
        glow: "var(--glow-soft-magenta)",
        textShadow: "0 0 8px rgba(255,0,183,0.7)",
        icon: "⚠",
      }
    case "error":
      return {
        border: "var(--state-error)",
        glow: "0 0 14px rgba(255,51,102,0.5)",
        textShadow: "0 0 8px rgba(255,51,102,0.7)",
        icon: "✕",
      }
    case "info":
    default:
      return {
        border: "var(--cyber-cyan)",
        glow: "var(--glow-soft-cyan)",
        textShadow: "0 0 8px rgba(0,234,255,0.7)",
        icon: "ℹ",
      }
  }
}
