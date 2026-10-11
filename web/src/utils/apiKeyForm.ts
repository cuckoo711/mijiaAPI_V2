import type { ApiKeyResourcePolicy, CreateApiKeyPayload } from "../types/admin";

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
