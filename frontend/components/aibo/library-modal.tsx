"use client"

import { useEffect, useState } from "react"
import { X } from "lucide-react"
import {
  deleteLibraryItem,
  loadLibraryItems,
  type LibraryItem,
} from "@/lib/api-portrait"
import { toast } from "./toast-provider"

/**
 * 素体ライブラリ一覧（localStorage 永続化）
 * modals.tsx の LibraryModal（保存スタブ）とは別コンポーネント。
 */
export function BodyLibraryModal({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const [items, setItems] = useState<LibraryItem[]>([])

  useEffect(() => {
    if (open) {
      setItems(loadLibraryItems())
    }
  }, [open])

  const handleDelete = (id: string) => {
    deleteLibraryItem(id)
    setItems(loadLibraryItems())
    toast.show("削除しました", "info")
  }

  const formatDate = (ts: number): string =>
    new Date(ts).toLocaleString("ja-JP", { hour12: false })

  if (!open) return null

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Body library"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="cyber-panel cyber-grid w-[min(920px,96vw)] max-h-[85vh] overflow-hidden flex flex-col animate-fade-in-up"
        style={{ boxShadow: "var(--glow-strong-cyan)" }}
      >
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h2 className="font-mono text-[13px] uppercase tracking-[2px] text-[var(--cyber-cyan)]">
            💎 LIBRARY · 素体ライブラリ
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="閉じる"
            className="text-white/60 hover:text-[var(--cyber-cyan)]"
          >
            <X size={18} />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 pr-1 -mr-1">
          {items.length === 0 ? (
            <div className="text-center py-14 text-white/45 font-mono text-[12px] leading-relaxed">
              まだ素体化された画像がありません
              <br />
              <span className="text-[10px] mt-3 inline-block text-[var(--cyber-magenta)]/80">
                「💎 この顔で素体化する」→「📚 ライブラリに保存」
              </span>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {items.map((item) => (
                <div
                  key={item.id}
                  className="relative border border-[var(--cyber-cyan-dim)] rounded-md p-2 bg-[rgba(10,10,14,0.85)]"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={item.image}
                    alt={item.name ?? "素体"}
                    className="w-full h-auto rounded object-cover max-h-[280px]"
                  />
                  <div className="mt-2 space-y-0.5 font-mono text-[9px] text-white/50">
                    <div className="text-[var(--cyber-cyan)]/90">
                      SEED {item.seed_used}
                    </div>
                    <div>{formatDate(item.created_at)}</div>
                    {item.body_shape_addendum ? (
                      <div
                        className="text-[var(--cyber-magenta)]/75 truncate"
                        title={item.body_shape_addendum}
                      >
                        {item.body_shape_addendum}
                      </div>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="cyber-btn w-full mt-2 !py-2 !text-[11px] border border-[var(--state-error)]/50 text-[var(--state-error)] hover:bg-[rgba(255,51,102,0.08)]"
                    onClick={() => handleDelete(item.id)}
                  >
                    削除
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="text-[10px] text-white/40 mt-4 pt-3 border-t border-[var(--cyber-cyan-dim)] font-mono leading-relaxed shrink-0">
          <p>※ ブラウザのローカルストレージに保存（端末・ブラウザ間では共有されません）</p>
          <p>※ 容量上限時は古い項目を削除してください</p>
        </div>
      </div>
    </div>
  )
}
