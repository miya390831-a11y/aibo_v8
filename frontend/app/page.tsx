"use client"

import { useState } from "react"
import { CyberHeader, type ModeKey } from "@/components/aibo/header"
import { CyberFooter } from "@/components/aibo/footer"
import { PortraitMode, type PortraitState } from "@/components/aibo/portrait-mode"
import { CoordinateMode } from "@/components/aibo/coordinate-mode"
import { SituationMode } from "@/components/aibo/situation-mode"
import { GlobalDemoControls } from "@/components/aibo/global-demo-controls"
import {
  LibraryModal,
  LibraryPickerModal,
  ConfirmModal,
  EnlargeModal,
} from "@/components/aibo/modals"
import { toast } from "@/components/aibo/toast-provider"

export default function AiboCyberStudioPage() {
  const [mode, setMode] = useState<ModeKey>("portrait")
  const [portraitState, setPortraitState] = useState<PortraitState>("initial")

  // Demo-driven shared modals (mounted at page level so the floating
  // demo panel can open them regardless of which mode is active).
  const [showLibraryPicker, setShowLibraryPicker] = useState(false)
  const [showSave, setShowSave] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [showEnlarge, setShowEnlarge] = useState(false)

  const handleSendToCoordinate = () => setMode("coordinate")
  const handleSendToSituation = () => setMode("situation")

  const status =
    mode === "portrait" && portraitState === "initial"
      ? "READY"
      : mode === "portrait" && portraitState === "quick_done"
        ? "QUICK GENERATED"
        : mode === "portrait" && portraitState === "neutral_done"
          ? "NEUTRAL READY"
          : "READY"

  return (
    <main className="h-dvh flex flex-col overflow-hidden">
      <CyberHeader mode={mode} onModeChange={setMode} />

      <GlobalDemoControls
        mode={mode}
        onModeChange={setMode}
        portraitState={portraitState}
        onPortraitStateChange={setPortraitState}
        onOpenLibrary={() => setShowLibraryPicker(true)}
        onOpenSave={() => setShowSave(true)}
        onOpenConfirm={() => setShowConfirm(true)}
        onOpenEnlarge={() => setShowEnlarge(true)}
      />

      <div className="flex-1 min-h-0">
        {mode === "portrait" && (
          <div key="portrait" className="animate-fade-in h-full">
            <PortraitMode
              state={portraitState}
              onStateChange={setPortraitState}
              onSendToCoordinate={handleSendToCoordinate}
              onSendToSituation={handleSendToSituation}
            />
          </div>
        )}
        {mode === "coordinate" && (
          <div key="coordinate" className="animate-fade-in h-full">
            <CoordinateMode />
          </div>
        )}
        {mode === "situation" && (
          <div key="situation" className="animate-fade-in h-full">
            <SituationMode />
          </div>
        )}
      </div>

      <CyberFooter
        mode={mode}
        status={status}
        progress={
          mode === "portrait" && portraitState === "quick_done"
            ? "seed · 4815162342 · 38.2s"
            : mode === "portrait" && portraitState === "neutral_done"
              ? "✓ FACE MASK · ✓ BODY MASK"
              : "—"
        }
      />

      {/* Shared demo modals */}
      <LibraryPickerModal
        open={showLibraryPicker}
        type="素体"
        onClose={() => setShowLibraryPicker(false)}
        onSelect={() => toast.show("素体を選択しました", "success")}
      />
      <LibraryModal open={showSave} onClose={() => setShowSave(false)} />
      <ConfirmModal
        open={showConfirm}
        title="削除確認"
        message="「私の素体001」を削除します。この操作は取り消せません。"
        confirmLabel="削除する"
        onConfirm={() => toast.show("削除しました", "info")}
        onClose={() => setShowConfirm(false)}
      />
      <EnlargeModal
        open={showEnlarge}
        src="/cyberpunk-fashion-portrait.jpg"
        caption="result · 1024×1024"
        onClose={() => setShowEnlarge(false)}
      />
    </main>
  )
}
