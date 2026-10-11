import { computed, reactive, ref } from "vue";
import type { SceneItem } from "../types/admin";
import type { AdminRequest, ControlOutcome } from "../types/control";
import { booleanOutcome, controlError } from "../utils/controlForm";

export function createSceneControlMemory() {
  return reactive({ outcomes: {} as Record<string, ControlOutcome | undefined>, busyIds: {} as Record<string, boolean> });
}
export type SceneControlMemory = ReturnType<typeof createSceneControlMemory>;

export function useSceneControl(options: { request: AdminRequest; getScene: (id: string) => SceneItem | undefined; memory?: SceneControlMemory }) {
  const selectedId = ref("");
  const visible = ref(false);
  const { outcomes, busyIds } = options.memory ?? createSceneControlMemory();
  const selected = computed(() => options.getScene(selectedId.value));
  const outcome = computed(() => outcomes[selectedId.value]);
  const busy = computed(() => Boolean(busyIds[selectedId.value]));
  const canExecute = computed(() => Boolean(selected.value?.executable && !selected.value.hidden && !busy.value && outcome.value?.status !== "unknown"));

  function openScene(scene: SceneItem): void {
    selectedId.value = scene.id;
    visible.value = true;
  }

  function closeScene(): void {
    visible.value = false;
  }

  function acknowledgeUnknown(): void {
    if (outcome.value?.status === "unknown") outcomes[selectedId.value] = undefined;
  }

  async function executeScene(): Promise<void> {
    if (!visible.value || !canExecute.value) return;
    // Results are keyed by the dispatched scene's id; another selection cannot
    // receive this result, including after navigating away and returning.
    const id = selectedId.value;
    busyIds[id] = true;
    try {
      const payload = await options.request<{ success?: unknown }>(`/api/admin/scenes/${encodeURIComponent(id)}/execute`, { method: "POST", body: "{}" });
      outcomes[id] = booleanOutcome(payload, "场景");
    } catch (error) {
      outcomes[id] = controlError(error);
    } finally {
      busyIds[id] = false;
    }
  }

  return { selectedId, selected, visible, outcome, busy, canExecute, openScene, closeScene, acknowledgeUnknown, executeScene };
}
