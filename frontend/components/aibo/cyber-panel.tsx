import type * as React from "react"
import { cn } from "@/lib/utils"

type CyberPanelProps = {
  title?: string
  numero?: string
  magenta?: boolean
  className?: string
  children: React.ReactNode
}

export function CyberPanel({ title, numero, magenta, className, children }: CyberPanelProps) {
  return (
    <section
      className={cn(
        "cyber-panel cyber-grid",
        magenta && "cyber-panel-magenta",
        className,
      )}
    >
      {title ? (
        <h3 className="section-header">
          {numero ? <span className="text-white/60 mr-1">{numero} ·</span> : null}
          <span>{title}</span>
        </h3>
      ) : null}
      {children}
    </section>
  )
}

export function SubHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] uppercase tracking-[1.5px] text-white/60 mb-2">
      {children}
    </div>
  )
}
