import { ApiRequestError, errorMessage } from "./apiRequestError";
import type { ControlOutcome, SpecAction, SpecParameter, SpecProperty, SpecValue } from "../types/control";

export function propertyKey(property: Pick<SpecProperty, "siid" | "piid">): string {
  return `${property.siid}.${property.piid}`;
}

export function actionKey(action: Pick<SpecAction, "siid" | "aiid">): string {
  return `${action.siid}.${action.aiid}`;
}

export function parameterKey(parameter: SpecParameter): string {
  return parameter.piid == null ? parameter.name : String(parameter.piid);
}

export function parseSpecValue(spec: SpecValue, raw: string | undefined): unknown {
  if (raw === undefined) throw new Error(`请填写 ${spec.name}`);
  let value: unknown = raw;
  if (spec.type === "bool") {
    if (!["true", "false"].includes(raw)) throw new Error(`${spec.name} 请选择 true 或 false`);
    value = raw === "true";
  } else if (["int", "uint", "float"].includes(spec.type)) {
    const numeric = Number(raw);
    if (!raw.trim() || !Number.isFinite(numeric)) throw new Error(`${spec.name} 必须为有限数值`);
    if (spec.type !== "float" && !Number.isSafeInteger(numeric)) throw new Error(`${spec.name} 必须为安全整数`);
    if (spec.type === "uint" && numeric < 0) throw new Error(`${spec.name} 不能为负数`);
    value = numeric;
  } else if (spec.type !== "string") {
    throw new Error(`${spec.name} 的属性类型不受支持`);
  }
  if (spec.value_range != null) {
    const bounds = spec.value_range;
    if (![2, 3].includes(bounds.length) || bounds.some((bound) => !Number.isFinite(bound)) || typeof value !== "number") {
      throw new Error(`${spec.name} 的范围规格无效`);
    }
    const [min, max, step] = bounds;
    if (min > max || value < min || value > max) throw new Error(`${spec.name} 必须在 ${min} 至 ${max} 之间`);
    if (bounds.length === 3) {
      const count = (value - min) / step;
      if (step <= 0 || !Number.isFinite(count) || Math.abs(count - Math.round(count)) > 1e-7) {
        throw new Error(`${spec.name} 必须符合步长 ${step}`);
      }
    }
  }
  if (spec.value_list != null && !spec.value_list.some((choice) => choice === value)) {
    throw new Error(`${spec.name} 必须选择规格列出的枚举值`);
  }
  return value;
}

export function actionParameters(action: SpecAction, values: Record<string, string>): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  for (const parameter of action.parameters) {
    const key = parameterKey(parameter);
    const raw = values[key];
    if (parameter.required === false && (raw === undefined || raw === "")) continue;
    params[key] = parseSpecValue(parameter, raw);
  }
  return params;
}

export function controlError(error: unknown): ControlOutcome {
  if (error instanceof ApiRequestError) {
    if (error.code === "EXECUTION_UNKNOWN" || error.status >= 500) {
      return { status: "unknown", message: error.message || "执行结果未知，请先核对设备状态，勿直接重试", result: error.details };
    }
    return { status: "failed", message: error.message };
  }
  // A lost browser response cannot establish whether a submitted command ran.
  return { status: "unknown", message: `执行结果未知：${errorMessage(error, "连接异常")}。请先核对设备状态，勿直接重试` };
}

export function booleanOutcome(payload: { success?: unknown }, name: string): ControlOutcome {
  if (payload.success === true) return { status: "success", message: `${name}执行成功` };
  if (payload.success === false) return { status: "failed", message: `${name}执行失败，设备未接受请求` };
  return { status: "unknown", message: "执行响应缺少明确结果，请先核对设备状态，勿直接重试" };
}

export function actionOutcome(payload: { result?: unknown }): ControlOutcome {
  const result = payload.result;
  if (result !== null && typeof result === "object" && !Array.isArray(result) && "code" in result) {
    const code = result.code;
    if (typeof code === "number" && Number.isInteger(code)) {
      return code === 0
        ? { status: "success", message: "动作执行成功", result }
        : { status: "failed", message: `动作执行失败（错误码 ${code}）`, result };
    }
  }
  return { status: "unknown", message: "动作结果未确认，请先核对设备状态，勿直接重试", result };
}
