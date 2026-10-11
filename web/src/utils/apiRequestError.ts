export class ApiRequestError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validationMessages(issues: unknown): string {
  if (!Array.isArray(issues)) return "";
  return issues.filter(isRecord).map((item) => {
    const location = Array.isArray(item.loc)
      ? item.loc.filter((part) => part !== "body").join(".")
      : "";
    return `${location ? `${location}: ` : ""}${String(item.message ?? item.msg ?? "参数无效")}`;
  }).join("；");
}

/** Preserve outcome/retry information and explain FastAPI validation failures. */
export function parseApiRequestError(payload: unknown, status: number): ApiRequestError {
  const body = isRecord(payload) ? payload : {};
  const detail = body.error ?? body.detail;
  if (isRecord(detail)) {
    const fields = isRecord(detail.details) ? validationMessages(detail.details.issues) : "";
    const message = typeof detail.message === "string" ? detail.message : `请求失败 ${status}`;
    return new ApiRequestError(
      fields ? `${message}：${fields}` : message,
      status,
      typeof detail.code === "string" ? detail.code : undefined,
      detail.details ?? detail,
    );
  }
  if (Array.isArray(detail)) {
    return new ApiRequestError(validationMessages(detail) || "请求参数无效", status, "VALIDATION_ERROR", detail);
  }
  return new ApiRequestError(
    typeof detail === "string" ? detail : `请求失败 ${status}`,
    status,
  );
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
