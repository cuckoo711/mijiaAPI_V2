import type { ApiKeyResourcePolicy, CreateApiKeyPayload } from "../types/admin";

export type ExpiryMode = "inherit" | "never" | "30" | "90" | "180" | "custom";

export function expiryForMode(mode: ExpiryMode, value: string): string | null | undefined {
  if (mode === "inherit") return undefined;
  if (mode === "never") return null;
  if (mode === "custom") {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("请选择到期日期");
    const date = new Date(`${value}T00:00:00`);
    if (!Number.isFinite(date.getTime()) || date.getFullYear() !== Number(value.slice(0, 4)) || date.getMonth() + 1 !== Number(value.slice(5, 7)) || date.getDate() !== Number(value.slice(8, 10))) {
      throw new Error("请选择有效的到期日期");
    }
    date.setDate(date.getDate() + 1);
    return futureExpiry(date.toISOString());
  }
  const date = new Date();
  date.setDate(date.getDate() + Number(mode) + 1);
  date.setHours(0, 0, 0, 0);
  return date.toISOString();
}

export function futureExpiry(value: string): string | null {
  if (!value.trim()) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) {
    throw new Error("过期时间必须晚于当前时间");
  }
  return date.toISOString();
}

export function createKeyPayload(form: {
  name: string;
  scopes: string[];
  policy: ApiKeyResourcePolicy;
  unrestricted: Record<keyof ApiKeyResourcePolicy, boolean>;
  expiresAt: string;
}): CreateApiKeyPayload {
  if (!form.name.trim()) throw new Error("请输入 API Key 名称");
  if (!form.scopes.length) throw new Error("请至少选择一项权限");
  const policy: ApiKeyResourcePolicy = { homes: [], devices: [], scenes: [] };
  for (const kind of ["homes", "devices", "scenes"] as const) {
    if (!form.unrestricted[kind]) {
      if (!form.policy[kind].length) throw new Error("限制资源时请至少选择一个资源；空列表表示不限制");
      policy[kind] = [...form.policy[kind]];
    }
  }
  return {
    name: form.name.trim(),
    scopes: [...form.scopes],
    resource_policy: policy,
    expires_at: futureExpiry(form.expiresAt),
  };
}
