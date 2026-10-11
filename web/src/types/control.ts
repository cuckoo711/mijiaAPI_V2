import type { RequestBehavior } from "../composables/useAdminSession";

export type AdminRequest = <T>(url: string, options?: RequestInit, behavior?: RequestBehavior) => Promise<T>;

export type SpecValue = {
  name: string;
  type: "bool" | "int" | "uint" | "float" | "string";
  value_range?: number[] | null;
  value_list?: unknown[] | null;
};

export type SpecProperty = SpecValue & { siid: number; piid: number; access: string };
export type SpecParameter = SpecValue & { piid?: number | null; required?: boolean };
export type SpecAction = { siid: number; aiid: number; name: string; parameters: SpecParameter[] };
export type DeviceSpec = { model: string; name: string; properties: SpecProperty[]; actions: SpecAction[] };
export type DeviceState = { siid: number; piid: number; value?: unknown; code?: number; name?: string };
export type ControlOutcome = { status: "success" | "failed" | "unknown"; message: string; result?: unknown };
