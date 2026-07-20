import { ElMessage } from "element-plus";
import { computed, ref } from "vue";

export type AdminSessionPayload = {
  token?: string;
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

const EXPIRES_AT_KEY = "mijia_admin_expires_at";
const LEGACY_TOKEN_KEY = "mijia_admin_token";
const CSRF_COOKIE_NAME = "mijia_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Manages the admin session and the authenticated `request()` helper.
 *
 * Session tokens live in an HttpOnly cookie (`mijia_admin_session`). The SPA
 * keeps only `expires_at` in localStorage for refresh scheduling and UI state.
 * A one-time legacy Bearer fallback reads any pre-migration localStorage token
 * until the next successful login/refresh sets the cookie and clears it.
 *
 * Mutating requests send double-submit CSRF: readable `mijia_csrf` cookie value
 * is copied into the `X-CSRF-Token` header (Bearer auth skips CSRF on the server).
 */
export function useAdminSession() {
  // Migrate away from readable tokens; keep briefly for Bearer fallback.
  const legacyBearer = ref(localStorage.getItem(LEGACY_TOKEN_KEY) || "");
  if (legacyBearer.value) {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  }

  const tokenExpiresAt = ref(localStorage.getItem(EXPIRES_AT_KEY) || "");
  const sessionActive = ref(_hasUsableExpiry(tokenExpiresAt.value) || Boolean(legacyBearer.value));
  let adminRefreshTimer: number | undefined;
  let refreshInFlight: Promise<boolean> | null = null;

  const isAuthed = computed(() => sessionActive.value);
  /** @deprecated Token is HttpOnly; kept empty for callers that still destructure it. */
  const token = computed(() => "");

  function clearAdminSession(message?: string): void {
    const wasAuthed = sessionActive.value;
    sessionActive.value = false;
    tokenExpiresAt.value = "";
    legacyBearer.value = "";
    localStorage.removeItem(EXPIRES_AT_KEY);
    localStorage.removeItem(LEGACY_TOKEN_KEY);
    window.clearTimeout(adminRefreshTimer);
    if (message && wasAuthed) {
      ElMessage.warning(message);
    }
  }

  function saveAdminSession(payload: AdminSessionPayload): void {
    legacyBearer.value = "";
    localStorage.removeItem(LEGACY_TOKEN_KEY);
    tokenExpiresAt.value = payload.expires_at;
    localStorage.setItem(EXPIRES_AT_KEY, payload.expires_at);
    sessionActive.value = true;
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
    if (refreshInFlight) {
      return refreshInFlight;
    }
    refreshInFlight = (async () => {
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
          clearAdminSession(
            sessionActive.value || Boolean(legacyBearer.value)
              ? "登录已过期，请重新登录"
              : undefined,
          );
        } else if (sessionActive.value) {
          adminRefreshTimer = window.setTimeout(() => {
            void refreshAdminSession();
          }, 60_000);
        }
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
    return refreshInFlight;
  }

  async function ensureCsrfCookie(): Promise<void> {
    if (_readCookie(CSRF_COOKIE_NAME) || legacyBearer.value) {
      return;
    }
    if (!sessionActive.value) {
      return;
    }
    try {
      await fetch("/api/admin/auth/csrf", {
        method: "GET",
        credentials: "include",
      });
    } catch {
      // Mutating call will fail CSRF if the cookie still cannot be issued.
    }
  }

  async function request<T>(
    url: string,
    options: RequestInit = {},
    behavior: RequestBehavior = {},
  ): Promise<T> {
    const headers = new Headers(options.headers);
    headers.set("Content-Type", "application/json");
    if (legacyBearer.value) {
      headers.set("Authorization", `Bearer ${legacyBearer.value}`);
    }
    const method = (options.method || "GET").toUpperCase();
    if (UNSAFE_METHODS.has(method) && !headers.has("Authorization")) {
      await ensureCsrfCookie();
      const csrf = _readCookie(CSRF_COOKIE_NAME);
      if (csrf) {
        headers.set(CSRF_HEADER_NAME, csrf);
      }
    }
    const response = await fetch(url, {
      ...options,
      headers,
      credentials: "include",
    });
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

  async function logout(): Promise<void> {
    try {
      await request(
        "/api/admin/auth/logout",
        { method: "POST", body: "{}" },
        { skipAuthRedirect: true },
      );
    } catch {
      // Cookie/local state is cleared below even if the revoke call fails.
    }
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

function _hasUsableExpiry(expiresAt: string): boolean {
  if (!expiresAt) {
    return false;
  }
  const expiresAtMs = new Date(expiresAt).getTime();
  return Number.isFinite(expiresAtMs) && expiresAtMs > Date.now();
}

function _readCookie(name: string): string {
  if (typeof document === "undefined") {
    return "";
  }
  const prefix = `${encodeURIComponent(name)}=`;
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return "";
}
