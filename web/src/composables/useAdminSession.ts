import { ElMessage } from "element-plus";
import { computed, ref } from "vue";

export type AdminSessionPayload = {
  token: string;
  expires_at: string;
  admin?: { id: string; username: string };
};

export type RequestBehavior = {
  skipAuthRedirect?: boolean;
};

export class ApiRequestError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

/**
 * Manages the admin session (token storage, refresh scheduling) and the
 * authenticated `request()` helper used across the app. `request()` is kept
 * here rather than in a standalone API client because it is tightly coupled
 * to the current token and to clearing the session on 401 responses.
 */
export function useAdminSession() {
  const token = ref(localStorage.getItem("mijia_admin_token") || "");
  const tokenExpiresAt = ref(localStorage.getItem("mijia_admin_expires_at") || "");
  let adminRefreshTimer: number | undefined;

  const isAuthed = computed(() => Boolean(token.value));

  function clearAdminSession(message?: string): void {
    const hadToken = Boolean(token.value);
    token.value = "";
    tokenExpiresAt.value = "";
    localStorage.removeItem("mijia_admin_token");
    localStorage.removeItem("mijia_admin_expires_at");
    window.clearTimeout(adminRefreshTimer);
    if (message && hadToken) {
      ElMessage.warning(message);
    }
  }

  function saveAdminSession(payload: AdminSessionPayload): void {
    token.value = payload.token;
    tokenExpiresAt.value = payload.expires_at;
    localStorage.setItem("mijia_admin_token", payload.token);
    localStorage.setItem("mijia_admin_expires_at", payload.expires_at);
    scheduleAdminTokenRefresh(payload.expires_at);
  }

  function scheduleAdminTokenRefresh(expiresAt: string): void {
    window.clearTimeout(adminRefreshTimer);
    const expiresAtMs = new Date(expiresAt).getTime();
    if (!Number.isFinite(expiresAtMs)) {
      return;
    }
    const refreshAtMs = expiresAtMs - 5 * 60 * 1000;
    const delayMs = Math.max(5000, refreshAtMs - Date.now());
    adminRefreshTimer = window.setTimeout(() => {
      void refreshAdminSession();
    }, delayMs);
  }

  async function refreshAdminSession(): Promise<boolean> {
    if (!token.value) {
      return false;
    }
    try {
      const payload = await request<AdminSessionPayload>(
        "/api/admin/auth/refresh",
        {
          method: "POST",
          body: "{}",
        },
        { skipAuthRedirect: true },
      );
      saveAdminSession(payload);
      return true;
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 401) {
        clearAdminSession("登录已过期，请重新登录");
      } else if (token.value) {
        adminRefreshTimer = window.setTimeout(() => {
          void refreshAdminSession();
        }, 60_000);
      }
      return false;
    }
  }

  async function request<T>(
    url: string,
    options: RequestInit = {},
    behavior: RequestBehavior = {},
  ): Promise<T> {
    const headers = new Headers(options.headers);
    headers.set("Content-Type", "application/json");
    if (token.value) {
      headers.set("Authorization", `Bearer ${token.value}`);
    }
    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const errorCode = payload?.error?.code;
      const errorMessage = payload?.error?.message || `请求失败 ${response.status}`;
      const requestError = new ApiRequestError(errorMessage, response.status, errorCode);
      if (
        response.status === 401 &&
        errorCode === "ADMIN_AUTH_FAILED" &&
        !behavior.skipAuthRedirect
      ) {
        clearAdminSession("登录已过期，请重新登录");
      }
      throw requestError;
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  async function login(loginForm: { username: string; password: string }): Promise<AdminSessionPayload> {
    const payload = await request<AdminSessionPayload>("/api/admin/auth/login", {
      method: "POST",
      body: JSON.stringify(loginForm),
    });
    saveAdminSession(payload);
    return payload;
  }

  function logout(): void {
    clearAdminSession();
  }

  function disposeAdminSession(): void {
    window.clearTimeout(adminRefreshTimer);
  }

  return {
    token,
    tokenExpiresAt,
    isAuthed,
    request,
    saveAdminSession,
    clearAdminSession,
    scheduleAdminTokenRefresh,
    refreshAdminSession,
    login,
    logout,
    disposeAdminSession,
  };
}
