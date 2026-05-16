"use client"

import { Settings } from "lucide-react"

export type ModeKey = "portrait" | "coordinate" | "situation"

const MODES: { key: ModeKey; icon: string; label: string }[] = [
  { key: "portrait", icon: "👤", label: "PORTRAIT" },
  { key: "coordinate", icon: "👕", label: "COORDINATE" },
  { key: "situation", icon: "🎬", label: "SITUATION" },
]

export function CyberHeader({
  mode,
  onModeChange,
}: {
  mode: ModeKey
  onModeChange: (m: ModeKey) => void
}) {
  return (
    <header className="h-[48px] flex items-center justify-between px-5 border-b border-[var(--cyber-cyan-dim)] bg-[rgba(10,10,12,0.92)] backdrop-blur-sm sticky top-0 z-30">
      {/* LEFT: brand */}
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className="text-[20px] leading-none animate-flicker"
          style={{ filter: "drop-shadow(0 0 8px var(--cyber-cyan))" }}
        >
          🌌
        </span>
        <div className="flex items-baseline gap-2 leading-none">
          <span className="font-mono text-[12px] font-bold tracking-[2px] gradient-text">
            AIBO CYBER STUDIO
          </span>
          <span className="font-mono text-[9px] tracking-[1.5px] text-white/40">
            v8.0
          </span>
        </div>
      </div>

      {/* CENTER: mode tabs */}
      <nav role="tablist" aria-label="Generation modes" className="flex items-center gap-2">
        {MODES.map((m) => {
          const active = mode === m.key
          return (
            <button
              key={m.key}
              role="tab"
              aria-selected={active}
              data-active={active}
              onClick={() => onModeChange(m.key)}
              className="cyber-tab"
            >
              <span aria-hidden className="text-[14px] leading-none">
                {m.icon}
              </span>
              <span className="font-mono text-[10px] font-semibold tracking-[2px]">
                {m.label}
              </span>
            </button>
          )
        })}
      </nav>

      {/* RIGHT: system status */}
      <div className="flex items-center gap-4">
        <div className="font-mono text-[10px] uppercase tracking-[1.5px] text-[var(--cyber-cyan)]">
          GPU: A100 40GB
        </div>
        <button
          aria-label="Settings"
          className="w-8 h-8 flex items-center justify-center border border-[var(--cyber-cyan-dim)] bg-[rgba(20,20,30,0.6)] text-[var(--cyber-cyan)] hover:shadow-[var(--glow-soft-cyan)] hover:border-[var(--cyber-cyan)] transition"
        >
          <Settings size={14} />
        </button>
      </div>
    </header>
  )
}
