import type { ModeKey } from "./header"

const MODE_LABEL: Record<ModeKey, string> = {
  portrait: "PORTRAIT",
  coordinate: "COORDINATE",
  situation: "SITUATION",
}

export function CyberFooter({
  mode,
  status = "READY",
  progress = "—",
  vram = "18/24GB (75%)",
}: {
  mode: ModeKey
  status?: string
  progress?: string
  vram?: string
}) {
  const cell =
    "px-4 flex items-center font-mono text-[10px] uppercase tracking-[1.5px] border-r border-[var(--cyber-cyan-dim)] last:border-r-0"
  return (
    <footer className="h-[30px] grid grid-cols-4 bg-[rgba(10,10,12,0.98)] border-t border-[var(--cyber-cyan-dim)] sticky bottom-0 z-20">
      <div className={`${cell} text-[var(--cyber-cyan)]`}>MODE: {MODE_LABEL[mode]}</div>
      <div className={`${cell} text-[var(--cyber-magenta)]`}>STATUS: {status}</div>
      <div className={`${cell} text-white/60`}>{progress}</div>
      <div className={`${cell} text-[var(--cyber-cyan)]/70 justify-end`}>
        VRAM: {vram}
      </div>
    </footer>
  )
}
