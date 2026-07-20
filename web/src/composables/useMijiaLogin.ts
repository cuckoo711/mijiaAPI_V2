import { ref } from "vue";
import type { RequestBehavior } from "./useAdminSession";

type RequestFn = <T>(url: string, options?: RequestInit, behavior?: RequestBehavior) => Promise<T>;

export type UseMijiaLoginOptions = {
  request: RequestFn;
  /** Called after a successful login or credential removal, to reload admin data. */
  onAccountChanged: () => Promise<void>;
};

/**
 * Handles the mijia QR login flow (start/poll) and credential removal.
 * Accepts an authenticated `request` function so it stays decoupled from
 * how the session token is stored.
 */
export function useMijiaLogin(options: UseMijiaLoginOptions) {
  const qrJob = ref<Record<string, string> | null>(null);
  let qrTimer: number | undefined;

  async function startQrLogin(): Promise<void> {
    qrJob.value = await options.request<Record<string, string>>("/api/admin/mijia/login/start", {
      method: "POST",
      body: "{}",
    });
    window.clearInterval(qrTimer);
    qrTimer = window.setInterval(() => void pollQrLogin(), 2500);
  }

  async function pollQrLogin(): Promise<void> {
    if (!qrJob.value?.id) {
      return;
    }
    qrJob.value = await options.request<Record<string, string>>(
      `/api/admin/mijia/login/${qrJob.value.id}`,
    );
    const status = String(qrJob.value.status);
    if (status === "success") {
      window.clearInterval(qrTimer);
      await options.onAccountChanged();
      ElMessage.success("米家登录成功");
      qrJob.value = null;
      return;
    }
    if (status === "failed") {
      window.clearInterval(qrTimer);
    }
  }

  async function deleteCredential(): Promise<void> {
    try {
      await options.request("/api/admin/mijia/credential", { method: "DELETE" });
      ElMessage.success("账号已移除");
      await options.onAccountChanged();
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "移除失败");
    }
  }

  function disposeMijiaLogin(): void {
    window.clearInterval(qrTimer);
  }

  return {
    qrJob,
    startQrLogin,
    pollQrLogin,
    deleteCredential,
    disposeMijiaLogin,
  };
}
