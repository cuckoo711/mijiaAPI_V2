const API_KEY_PLACEHOLDER = "YOUR_API_KEY";

export function normalizeApiBaseUrl(value: string, fallback: string): string {
  const rawValue = (value || fallback).trim();
  if (!rawValue) {
    return "";
  }
  const fallbackScheme = /^https?:\/\//i.exec(fallback)?.[0] || "https://";
  const withScheme = /^https?:\/\//i.test(rawValue) ? rawValue : `${fallbackScheme}${rawValue}`;
  return withScheme.replace(/\/+$/, "");
}

export function curlApiKey(oneTimeApiKey: string): string {
  return oneTimeApiKey.trim() || API_KEY_PLACEHOLDER;
}

export function buildSceneExecuteCurl(options: {
  sceneId: string;
  baseUrl: string;
  apiKey: string;
}): string {
  const sceneId = options.sceneId.trim();
  const baseUrl = options.baseUrl.replace(/\/+$/, "");
  const apiKey = curlApiKey(options.apiKey);
  return [
    "curl -X POST \\",
    `  -H "Authorization: Bearer ${apiKey}" \\`,
    `  ${baseUrl}/api/v1/scenes/${sceneId}/execute`,
  ].join("\n");
}
