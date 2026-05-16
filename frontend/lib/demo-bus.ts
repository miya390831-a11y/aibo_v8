/**
 * Demo Event Bus — GlobalDemoControls と各モードのデモ連携用。
 */

export type CoordState = "prep" | "generating" | "result";
export type SitState = "pose" | "generating" | "result";

export type DemoEvent =
  | { type: "coord:setState"; state: CoordState }
  | { type: "coord:openCatalog" }
  | { type: "coord:openTrimming" }
  | { type: "coord:toggleAdvancedSlots" }
  | { type: "sit:setState"; state: SitState }
  | { type: "sit:simulateExtraction" }
  | { type: "sit:triggerPhase3Warning" }
  | {
      type: "sit:triggerPoseError";
      severity: "critical" | "error" | "warn" | "info";
    };

type Listener = (event: DemoEvent) => void;

class DemoBus {
  private listeners = new Set<Listener>();

  emit(event: DemoEvent): void {
    this.listeners.forEach((listener) => {
      try {
        listener(event);
      } catch (err) {
        console.error("[demo-bus] listener error:", err);
      }
    });
  }

  on(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
}

export const demoBus = new DemoBus();
