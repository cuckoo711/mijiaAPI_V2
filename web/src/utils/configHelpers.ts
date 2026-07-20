export function configBool(
  runtimeConfig: Map<string, unknown>,
  key: string,
  defaultValue = false
): boolean {
  const value = runtimeConfig.get(key);
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    return ["1", "true", "yes", "on"].includes(value.toLowerCase());
  }
  if (value === undefined || value === null) {
    return defaultValue;
  }
  return Boolean(value);
}

export function configText(
  runtimeConfig: Map<string, unknown>,
  key: string,
  defaultValue = ""
): string {
  const value = runtimeConfig.get(key);
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join("\n");
  }
  if (typeof value === "string") {
    return value;
  }
  if (value === undefined || value === null) {
    return defaultValue;
  }
  return String(value);
}
