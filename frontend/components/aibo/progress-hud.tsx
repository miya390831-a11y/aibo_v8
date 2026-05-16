"use client"

import { X } from "lucide-react"

export type StageStatus = "completed" | "active" | "pending"
export type Stage = { name: string; status: StageStatus; progress?: number }

function formatTime(s: number) {
  const mm = Math.floor(s / 60)
    .toString()
    .padStart(2, "0")
  const ss = Math.floor(s % 60)
    .toString()
    .padStart(2, "0")
  return `${mm}:${ss}`
}

export function ProgressHud({
  title = "GENERATING SITUATION...",
  stages,
  overallPercent,
  elapsedSec,
  etaSec,
  onCancel,
}: {
  title?: string
  stages: Stage[]
  overallPercent: number
  elapsedSec: number
  etaSec: number
  onCancel?: () => void
}) {
  const longest = Math.max(...stages.map((s) => s.name.length), 18)

  return (
    <div
      className="cyber-panel cyber-grid relative font-mono"
      style={{
        boxShadow:
          "0 0 20px rgba(0,234,255,0.4), inset 0 0 10px rgba(0,234,255,0.05)",
        borderColor: "var(--cyber-cyan)",
        padding: 24,
      }}
    >
      <h4 className="text-[12px] uppercase tracking-[2px] text-[var(--cyber-cyan)]" aria-live="polite">
        ⚡ {title}
      </h4>

      <div className="mt-4 flex items-center gap-3">
        <div className="relative h-[6px] flex-1 overflow-hidden" style={{ background: "rgba(0,234,255,0.1)" }}>
          <div
            className="absolute inset-y-0 left-0 transition-[width] duration-300"
            style={{
              width: `${overallPercent}%`,
              background: "var(--gradient-primary)",
              boxShadow: "0 0 8px rgba(0,234,255,0.6)",
            }}
          />
          <div
            className="absolute top-0 h-full w-[20%] pointer-events-none"
            style={{
              left: `${Math.max(overallPercent - 20, 0)}%`,
              background:
                "linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent)",
              animation: "scan-bar 1.2s ease-in-out infinite",
            }}
          />
        </div>
        <span className="text-[11px] text-[var(--cyber-cyan)] tabular-nums w-[3.5ch] text-right">
          {Math.round(overallPercent)}%
        </span>
      </div>

      <ul className="mt-5 space-y-1.5 text-[12px]">
        {stages.map((s) => {
          const dots = ".".repeat(Math.max(longest - s.name.length + 4, 4))
          let color = "text-white/30"
          let statusText = "..."
          let extra = ""
          if (s.status === "completed") {
            color = "text-[var(--state-success)]"
            statusText = "OK"
            extra = "drop-shadow-[0_0_4px_rgba(100,255,150,0.6)]"
          } else if (s.status === "active") {
            color = "text-[var(--cyber-cyan)]"
            statusText = `${Math.round(s.progress ?? 0)}%`
          }
          return (
            <li key={s.name} className={`flex items-center font-mono ${color} ${extra}`}>
              <span className="text-[var(--cyber-magenta)] mr-2">&gt;</span>
              <span className="uppercase tracking-wider">{s.name}</span>
              <span className="opacity-50 mx-1">{dots}</span>
              <span className="ml-auto tabular-nums w-[4ch] text-right">{statusText}</span>
            </li>
          )
        })}
      </ul>

      <div className="mt-5 flex items-center justify-between text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]/70">
        <span>ELAPSED: {formatTime(elapsedSec)}</span>
        <span aria-hidden>·</span>
        <span>ETA: {formatTime(etaSec)}</span>
      </div>

      <button onClick={onCancel} className="cyber-btn cyber-btn-danger w-full mt-5" type="button">
        <X size={12} /> CANCEL
      </button>
    </div>
  )
}
