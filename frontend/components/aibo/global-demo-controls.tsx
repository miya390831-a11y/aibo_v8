"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, Settings2 } from "lucide-react"
import type { ModeKey } from "./header"
import type { PortraitState } from "./portrait-mode"
import { demoBus } from "@/lib/demo-bus"
import { toast, type ToastKind } from "./toast-provider"

type Props = {
  mode: ModeKey
  onModeChange: (m: ModeKey) => void
  portraitState: PortraitState
  onPortraitStateChange: (s: PortraitState) => void
  onOpenLibrary: () => void
  onOpenSave: () => void
  onOpenConfirm: () => void
  onOpenEnlarge: () => void
}

const RESULT_SRC = "/cyberpunk-fashion-portrait.jpg"

export function GlobalDemoControls(props: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div
      className="fixed top-[60px] right-3 z-[900] font-mono"
      style={{ maxWidth: open ? 280 : 130 }}
    >
      {/* Toggle handle */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-2 w-full px-2 py-1.5 border border-[var(--cyber-cyan-dim)] bg-[rgba(20,20,30,0.85)] backdrop-blur-sm hover:border-[var(--cyber-cyan)] hover:shadow-[var(--glow-soft-cyan)] transition"
        style={{ color: "var(--cyber-cyan)" }}
      >
        <Settings2 size={12} />
        <span className="text-[10px] uppercase tracking-[1.5px]">
          Demo Controls
        </span>
        <span className="ml-auto">
          {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </span>
      </button>

      {open && (
        <div
          className="mt-1 cyber-panel cyber-grid p-3 space-y-2.5 max-h-[calc(100vh-100px)] overflow-y-auto animate-fade-in"
          style={{
            background: "rgba(10,10,12,0.92)",
            backdropFilter: "blur(8px)",
            boxShadow: "var(--glow-soft-cyan)",
          }}
        >
          {/* Mode */}
          <Group label="ACTIVE MODE">
            <Row>
              {(["portrait", "coordinate", "situation"] as const).map((m) => (
                <Chip
                  key={m}
                  active={props.mode === m}
                  onClick={() => props.onModeChange(m)}
                >
                  {m === "portrait" ? "PRT" : m === "coordinate" ? "COO" : "SIT"}
                </Chip>
              ))}
            </Row>
          </Group>

          {/* Portrait state */}
          {props.mode === "portrait" && (
            <Group label="PORTRAIT STATE">
              <Row>
                {(
                  [
                    { k: "initial", l: "Initial" },
                    { k: "quick_done", l: "Quick" },
                    { k: "neutral_done", l: "Neutral" },
                  ] as { k: PortraitState; l: string }[]
                ).map((s) => (
                  <Chip
                    key={s.k}
                    active={props.portraitState === s.k}
                    onClick={() => props.onPortraitStateChange(s.k)}
                  >
                    {s.l}
                  </Chip>
                ))}
              </Row>
            </Group>
          )}

          {/* Coordinate state */}
          {props.mode === "coordinate" && (
            <>
              <Group label="COORDINATE STATE">
                <Row>
                  {(
                    [
                      { k: "prep", l: "Ready" },
                      { k: "generating", l: "Gen" },
                      { k: "result", l: "Result" },
                    ] as const
                  ).map((s) => (
                    <Chip
                      key={s.k}
                      onClick={() =>
                        demoBus.emit({ type: "coord:setState", state: s.k })
                      }
                    >
                      {s.l}
                    </Chip>
                  ))}
                </Row>
              </Group>
              <Group label="COORD ACTIONS">
                <Btn
                  onClick={() => demoBus.emit({ type: "coord:openCatalog" })}
                >
                  Open Catalog
                </Btn>
                <Btn
                  onClick={() => demoBus.emit({ type: "coord:openTrimming" })}
                >
                  Open Trimming
                </Btn>
                <Btn
                  onClick={() =>
                    demoBus.emit({ type: "coord:toggleAdvancedSlots" })
                  }
                >
                  Toggle Slot 3-4
                </Btn>
              </Group>
            </>
          )}

          {/* Situation state */}
          {props.mode === "situation" && (
            <>
              <Group label="SITUATION STATE">
                <Row>
                  {(
                    [
                      { k: "pose", l: "Ready" },
                      { k: "generating", l: "Gen" },
                      { k: "result", l: "Result" },
                    ] as const
                  ).map((s) => (
                    <Chip
                      key={s.k}
                      onClick={() =>
                        demoBus.emit({ type: "sit:setState", state: s.k })
                      }
                    >
                      {s.l}
                    </Chip>
                  ))}
                </Row>
              </Group>
              <Group label="POSE EXTRACT">
                <Btn
                  onClick={() =>
                    demoBus.emit({ type: "sit:simulateExtraction" })
                  }
                >
                  Simulate Success
                </Btn>
                <Btn
                  onClick={() =>
                    demoBus.emit({ type: "sit:triggerPhase3Warning" })
                  }
                >
                  Phase 3 Warn
                </Btn>
              </Group>
              <Group label="POSE ERRORS">
                <Row>
                  {(["critical", "error", "warn", "info"] as const).map((s) => (
                    <Chip
                      key={s}
                      onClick={() =>
                        demoBus.emit({
                          type: "sit:triggerPoseError",
                          severity: s,
                        })
                      }
                    >
                      {s.slice(0, 4).toUpperCase()}
                    </Chip>
                  ))}
                </Row>
              </Group>
            </>
          )}

          {/* Modals */}
          <Group label="MODALS">
            <Btn onClick={props.onOpenLibrary}>Library Picker</Btn>
            <Btn onClick={props.onOpenSave}>Save to Library</Btn>
            <Btn onClick={props.onOpenConfirm}>Confirm Delete</Btn>
            <Btn onClick={props.onOpenEnlarge}>Enlarge Preview</Btn>
          </Group>

          {/* Toasts */}
          <Group label="TOAST">
            <Row>
              {(
                [
                  { k: "success", l: "OK" },
                  { k: "info", l: "INFO" },
                  { k: "warn", l: "WARN" },
                  { k: "error", l: "ERR" },
                ] as { k: ToastKind; l: string }[]
              ).map((t) => (
                <Chip
                  key={t.k}
                  onClick={() =>
                    toast.show(`Demo ${t.k.toUpperCase()} toast`, t.k)
                  }
                >
                  {t.l}
                </Chip>
              ))}
            </Row>
          </Group>

          <p className="font-mono text-[9px] uppercase tracking-[1.5px] text-white/30 leading-relaxed pt-1 border-t border-[var(--cyber-cyan-dim)]">
            v8.0 · debug panel · production hides
          </p>
        </div>
      )}
    </div>
  )
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="font-mono text-[9px] uppercase tracking-[1.5px] text-white/40 flex items-center gap-1.5">
        <span style={{ color: "var(--cyber-magenta)" }} aria-hidden>
          ▸
        </span>
        {label}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap gap-1">{children}</div>
}

function Chip({
  active,
  onClick,
  children,
}: {
  active?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-2 py-1 font-mono text-[9px] uppercase tracking-[1.5px] border transition flex-1 min-w-0"
      style={{
        background: active
          ? "var(--gradient-primary-soft)"
          : "rgba(20,20,30,0.6)",
        borderColor: active ? "var(--cyber-cyan)" : "var(--cyber-cyan-dim)",
        color: active ? "#fff" : "var(--text-secondary)",
        boxShadow: active ? "var(--glow-soft-cyan)" : "none",
      }}
    >
      {children}
    </button>
  )
}

function Btn({
  onClick,
  children,
}: {
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full px-2 py-1 font-mono text-[10px] uppercase tracking-[1.5px] border transition text-left hover:border-[var(--cyber-cyan)] hover:bg-[rgba(0,234,255,0.05)] hover:shadow-[var(--glow-soft-cyan)]"
      style={{
        background: "rgba(20,20,30,0.6)",
        borderColor: "var(--cyber-cyan-dim)",
        color: "var(--text-secondary)",
      }}
    >
      {children}
    </button>
  )
}

export const ENLARGE_DEMO_SRC = RESULT_SRC
