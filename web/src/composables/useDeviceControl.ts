import { computed, reactive, ref } from "vue";
import type { DeviceItem } from "../types/admin";
import type { AdminRequest, ControlOutcome, DeviceSpec, DeviceState } from "../types/control";
import { actionKey, actionOutcome, actionParameters, booleanOutcome, controlError, propertyKey, parseSpecValue } from "../utils/controlForm";
import { errorMessage } from "../utils/apiRequestError";

type DeviceDraft = {
  property: string;
  propertyValues: Record<string, string>;
  action: string;
  actionValues: Record<string, Record<string, string>>;
};

type PropertyReadback = Readonly<{ siid: number; piid: number; value: unknown; readable: boolean }>;

export function createDeviceControlMemory() {
  return reactive({
    busyIds: {} as Record<string, boolean>,
    outcomes: {} as Record<string, ControlOutcome | undefined>,
    verifiedUnknown: {} as Record<string, boolean>,
    drafts: {} as Record<string, DeviceDraft>,
  });
}
export type DeviceControlMemory = ReturnType<typeof createDeviceControlMemory>;

export function useDeviceControl(options: { request: AdminRequest; getDevice: (id: string) => DeviceItem | undefined; memory?: DeviceControlMemory }) {
  const selectedId = ref("");
  const visible = ref(false);
  const spec = ref<DeviceSpec | null>(null);
  const state = ref<DeviceState[]>([]);
  const stateUpdatedAt = ref("");
  const loadError = ref("");
  const stateError = ref("");
  const specLoading = ref(false);
  const stateLoading = ref(false);
  const { busyIds, outcomes, verifiedUnknown, drafts } = options.memory ?? createDeviceControlMemory();
  let selectionGeneration = 0;
  let stateSequence = 0;
  let readbackWait: { timer: number; resume: () => void } | null = null;

  const selected = computed(() => options.getDevice(selectedId.value));
  const draft = computed(() => drafts[selectedId.value]);
  const outcome = computed(() => outcomes[selectedId.value]);
  const controlBusy = computed(() => Boolean(busyIds[selectedId.value]));
  const requiresVerification = computed(() => outcome.value?.status === "unknown");
  const canAcknowledge = computed(() => Boolean(verifiedUnknown[selectedId.value] && !controlBusy.value));
  const writableProperties = computed(() => spec.value?.properties.filter((property) => ["write", "read_write"].includes(property.access)) ?? []);
  const selectedProperty = computed(() => writableProperties.value.find((property) => propertyKey(property) === draft.value?.property));
  const selectedAction = computed(() => spec.value?.actions.find((action) => actionKey(action) === draft.value?.action));
  const canControl = computed(() => Boolean(visible.value && selected.value?.access_mode === "write" && !selected.value.hidden && spec.value && !specLoading.value && !controlBusy.value && !requiresVerification.value));

  function current(id: string, generation: number): boolean {
    return visible.value && selectedId.value === id && selectionGeneration === generation;
  }

  async function refreshState(): Promise<DeviceState[] | null> {
    const id = selectedId.value;
    if (!visible.value || !id) return null;
    const generation = selectionGeneration;
    const sequence = ++stateSequence;
    stateLoading.value = true;
    stateError.value = "";
    try {
      const payload = await options.request<{ items: DeviceState[] }>(`/api/admin/devices/${encodeURIComponent(id)}/state`);
      if (!current(id, generation) || sequence !== stateSequence) return null;
      if (!Array.isArray(payload.items)) throw new Error("状态响应缺少属性列表");
      state.value = payload.items;
      stateUpdatedAt.value = new Date().toLocaleString();
      if (outcomes[id]?.status === "unknown") verifiedUnknown[id] = true;
      return payload.items;
    } catch (error) {
      if (current(id, generation) && sequence === stateSequence) stateError.value = errorMessage(error, "状态读取失败，请重试");
    } finally {
      if (current(id, generation) && sequence === stateSequence) stateLoading.value = false;
    }
    return null;
  }

  function cancelReadbackWait(): void {
    if (!readbackWait) return;
    const waiting = readbackWait;
    readbackWait = null;
    window.clearTimeout(waiting.timer);
    waiting.resume();
  }

  function waitForReadback(): Promise<void> {
    return new Promise((resolve) => {
      const waiting = { timer: 0, resume: () => {
        if (readbackWait === waiting) readbackWait = null;
        resolve();
      } };
      waiting.timer = window.setTimeout(waiting.resume, 1000);
      readbackWait = waiting;
    });
  }

  async function confirmPropertyReadback(id: string, generation: number, target: PropertyReadback): Promise<void> {
    const unconfirmed = (message: string): void => {
      outcomes[id] = { status: "unknown", message: `写入请求已被接受，但${message}。请核对状态与实际设备；不会重复发送写入` };
    };
    const stillSelected = (): boolean => {
      if (current(id, generation)) return true;
      unconfirmed("读回核对已停止（对话框已关闭或切换），目标值尚未确认");
      return false;
    };
    if (!stillSelected()) return;
    if (!target.readable) {
      unconfirmed("该属性不可读，无法确认目标读值");
      await refreshState();
      return;
    }
    for (let attempt = 0; attempt < 5; attempt += 1) {
      if (!stillSelected()) return;
      const items = await refreshState();
      if (!stillSelected()) return;
      if (!items) {
        unconfirmed("状态读取失败，目标读值尚未确认");
        return;
      }
      const matching = items.filter((item) => item && item.siid === target.siid && item.piid === target.piid);
      if (matching.length !== 1) {
        unconfirmed("实时状态中没有唯一的目标属性，读回尚未确认");
        return;
      }
      const item = matching[0];
      if (item.code !== 0 || !Object.prototype.hasOwnProperty.call(item, "value") || item.value === undefined) {
        unconfirmed(typeof item.code === "number" && item.code !== 0
          ? `目标属性读取错误（错误码 ${item.code}），读回尚未确认`
          : "目标属性读取缺少成功码或读值，读回尚未确认");
        return;
      }
      if (item.value === target.value) {
        verifiedUnknown[id] = false;
        outcomes[id] = { status: "success", message: "写入请求已被接受，目标属性值已读回确认" };
        return;
      }
      if (attempt === 4) {
        unconfirmed("5 次读回均未匹配目标值，核对已超时");
        return;
      }
      await waitForReadback();
    }
  }

  async function refreshSpec(): Promise<void> {
    const id = selectedId.value;
    if (!visible.value || !id || specLoading.value) return;
    const generation = selectionGeneration;
    specLoading.value = true;
    loadError.value = "";
    try {
      const payload = await options.request<{ spec: DeviceSpec | null }>(`/api/admin/devices/${encodeURIComponent(id)}/spec`);
      if (!current(id, generation)) return;
      spec.value = payload.spec;
      if (!payload.spec) loadError.value = "设备规格不可用，无法执行控制；请重试读取规格";
    } catch (error) {
      if (current(id, generation)) loadError.value = errorMessage(error, "规格读取失败，请重试");
    } finally {
      if (current(id, generation)) specLoading.value = false;
    }
  }

  async function openDevice(device: DeviceItem): Promise<void> {
    cancelReadbackWait();
    selectionGeneration += 1;
    selectedId.value = device.id;
    visible.value = true;
    spec.value = null;
    state.value = [];
    stateUpdatedAt.value = "";
    loadError.value = "";
    stateError.value = "";
    specLoading.value = false;
    stateLoading.value = false;
    drafts[device.id] ??= { property: "", propertyValues: {}, action: "", actionValues: {} };
    await Promise.all([refreshSpec(), refreshState()]);
  }

  function closeDevice(): void {
    cancelReadbackWait();
    selectionGeneration += 1;
    visible.value = false;
  }

  function chooseAction(key: string): void {
    if (!draft.value) return;
    draft.value.action = key;
    draft.value.actionValues[key] ??= {};
  }

  function acknowledgeUnknown(): void {
    const id = selectedId.value;
    if (canAcknowledge.value && outcomes[id]?.status === "unknown") {
      outcomes[id] = undefined;
      verifiedUnknown[id] = false;
    }
  }

  async function submit(kind: "properties" | "actions", body: object, readback?: PropertyReadback): Promise<void> {
    if (!canControl.value) return;
    const id = selectedId.value;
    const generation = selectionGeneration;
    busyIds[id] = true;
    verifiedUnknown[id] = false;
    let result: ControlOutcome;
    try {
      const payload = await options.request<{ success?: unknown; result?: unknown }>(`/api/admin/devices/${encodeURIComponent(id)}/${kind}`, {
        method: "POST", body: JSON.stringify(body),
      });
      result = kind === "properties" ? booleanOutcome(payload, "属性写入") : actionOutcome(payload);
    } catch (error) {
      result = controlError(error);
    }
    // Keep an unresolved outcome with its original device, even if its dialog
    // was closed. It must not permit a blind replay when that device is reopened.
    if (kind === "properties" && result.status === "success" && readback) {
      outcomes[id] = { status: "unknown", message: "写入请求已被接受，正在核对最新读值；设备效果尚未确认" };
      try {
        await confirmPropertyReadback(id, generation, readback);
      } finally {
        busyIds[id] = false;
      }
      return;
    }
    outcomes[id] = result;
    busyIds[id] = false;
    if (!current(id, generation)) return;
    if (result.status === "success" || result.status === "unknown") await refreshState();
  }

  async function writeProperty(): Promise<void> {
    if (!canControl.value || !selectedProperty.value || !draft.value) return;
    const property = selectedProperty.value;
    try {
      const value = parseSpecValue(property, draft.value.propertyValues[propertyKey(property)]);
      const target = Object.freeze({ siid: property.siid, piid: property.piid, value,
        readable: ["read", "read_write"].includes(property.access) });
      await submit("properties", { siid: target.siid, piid: target.piid, value: target.value }, target);
    } catch (error) {
      outcomes[selectedId.value] = { status: "failed", message: errorMessage(error, "属性值无效") };
    }
  }

  async function callAction(): Promise<void> {
    if (!canControl.value || !selectedAction.value || !draft.value) return;
    const action = selectedAction.value;
    try {
      const params = actionParameters(action, draft.value.actionValues[actionKey(action)] ?? {});
      await submit("actions", { siid: action.siid, aiid: action.aiid, params });
    } catch (error) {
      outcomes[selectedId.value] = { status: "failed", message: errorMessage(error, "动作参数无效") };
    }
  }

  return { selectedId, selected, visible, spec, state, stateUpdatedAt, loadError, stateError, specLoading, stateLoading, controlBusy, draft, outcome, requiresVerification, canAcknowledge, canControl, writableProperties, selectedProperty, selectedAction, openDevice, closeDevice, refreshSpec, refreshState, chooseAction, acknowledgeUnknown, writeProperty, callAction };
}
