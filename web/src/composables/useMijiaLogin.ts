import { ref } from "vue";
import { ApiRequestError, type RequestBehavior } from "./useAdminSession";
import { errorMessage } from "../utils/apiRequestError";

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
  const qrError = ref("");
  const qrStarting = ref(false);
  const removingCredential = ref(false);
  let qrTimer: number | undefined;
  let generation = 0;
  let pollingJobId: string | null = null;

  function stopQrPolling(): void {
    generation += 1;
    window.clearTimeout(qrTimer);
  }

  function scheduleQrPoll(delay = 2500): void {
    const run = generation;
    qrTimer = window.setTimeout(() => {
      if (generation === run) void pollQrLogin();
    }, delay);
  }

  async function startQrLogin(): Promise<void> {
    if (qrStarting.value || removingCredential.value) return;
    stopQrPolling();
    const run = generation;
    qrStarting.value = true;
    qrError.value = "";
    try {
      const job = await options.request<Record<string, string>>("/api/admin/mijia/login/start", {
        method: "POST",
        body: "{}",
      });
      if (run !== generation) return;
      qrJob.value = job;
      scheduleQrPoll();
    } catch (error) {
      if (run !== generation) return;
      qrJob.value = null;
      qrError.value = errorMessage(error, "二维码生成失败，请重新扫码登录");
      ElMessage.error(qrError.value);
    } finally {
      qrStarting.value = false;
    }
  }

  async function pollQrLogin(): Promise<void> {
    if (!qrJob.value?.id) {
      return;
    }
    window.clearTimeout(qrTimer);
    const run = generation;
    const id = qrJob.value.id;
    if (pollingJobId === id) return;
    pollingJobId = id;
    try {
      const job = await options.request<Record<string, string>>(`/api/admin/mijia/login/${id}`);
      if (run !== generation || qrJob.value?.id !== id) return;
      qrJob.value = job;
      qrError.value = "";
      if (["success", "failed", "canceled"].includes(job.status)) {
        stopQrPolling();
        if (job.status === "success") {
          ElMessage.success("米家登录成功");
          qrJob.value = null;
          try {
            await options.onAccountChanged();
          } catch (error) {
            qrError.value = `登录已成功，但账号状态刷新失败：${errorMessage(error, "请刷新重试")}`;
          }
        }
        return;
      }
      scheduleQrPoll();
    } catch (error) {
      if (run !== generation || qrJob.value?.id !== id) return;
      qrError.value = `读取登录状态失败：${errorMessage(error, "网络异常，将自动重试")}`;
      if (error instanceof ApiRequestError && [401, 403, 404].includes(error.status)) {
        stopQrPolling();
        qrJob.value = {
          ...qrJob.value,
          status: error.status === 404 ? "canceled" : "failed",
          message: error.status === 404 ? "登录任务已失效，请重新扫码登录" : qrError.value,
        };
      } else {
        scheduleQrPoll(5000);
      }
    } finally {
      if (pollingJobId === id) pollingJobId = null;
    }
  }

  async function deleteCredential(): Promise<void> {
    if (removingCredential.value || qrStarting.value) return;
    removingCredential.value = true;
    try {
      await options.request("/api/admin/mijia/credential", { method: "DELETE" });
      stopQrPolling();
      qrJob.value = null;
      qrError.value = "";
      ElMessage.success("账号已移除");
      try {
        await options.onAccountChanged();
      } catch (error) {
        qrError.value = `账号已移除，但列表刷新失败：${errorMessage(error, "请刷新重试")}`;
      }
    } catch (error) {
      qrError.value = errorMessage(error, "移除失败，请重试");
      ElMessage.error(qrError.value);
    } finally {
      removingCredential.value = false;
    }
  }

  function disposeMijiaLogin(): void {
    stopQrPolling();
  }

  return {
    qrJob,
    qrError,
    qrStarting,
    removingCredential,
    startQrLogin,
    pollQrLogin,
    deleteCredential,
    disposeMijiaLogin,
  };
}
