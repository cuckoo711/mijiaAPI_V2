import { ref } from "vue";
import { ApiRequestError, type RequestBehavior } from "./useAdminSession";
import { errorMessage } from "../utils/apiRequestError";

type RequestFn = <T>(url: string, options?: RequestInit, behavior?: RequestBehavior) => Promise<T>;

export type SyncProgress = {
  task_id: string;
  status: string;
  step: string;
  progress: number;
  current_home: string;
  homes_total: number;
  homes_processed: number;
  devices_found: number;
  scenes_found: number;
  warnings: Array<{ kind: string; home_name: string; message: string }>;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  error: string | null;
};

type SyncStartResponse = {
  status: string;
  task_id?: string;
  message?: string;
};

export type UseSyncProgressOptions = {
  request: RequestFn;
  /** Called once a sync completes successfully, to reload admin data. */
  onCompleted: () => Promise<void>;
};

/**
 * Drives the mijia home/device/scene sync: kicking off a sync and polling
 * its progress with an adaptive interval (denser while running, sparser
 * otherwise) to keep the admin session and SQLite load low.
 *
 * When the start API returns ``task_id``, only progress payloads for that
 * run are applied — matching backend cleanup that keys on ``task_id``.
 */
export function useSyncProgress(options: UseSyncProgressOptions) {
  const syncing = ref(false);
  const syncProgress = ref<SyncProgress | null>(null);
  const syncError = ref("");
  const syncPollTimer = ref<number | null>(null);
  const isSyncPolling = ref(false);
  /** Current run id from POST /api/admin/sync; ignore mismatched progress. */
  const currentSyncTaskId = ref<string | null>(null);
  const notifiedTasks = new Set<string>();
  let generation = 0;

  function startSyncPolling(): void {
    if (isSyncPolling.value) return;
    isSyncPolling.value = true;
    scheduleSyncPoll(800);
  }

  function stopSyncPolling(): void {
    generation += 1;
    if (syncPollTimer.value) {
      window.clearTimeout(syncPollTimer.value);
      syncPollTimer.value = null;
    }
    isSyncPolling.value = false;
  }

  function scheduleSyncPoll(delayMs: number): void {
    if (!isSyncPolling.value) return;
    const run = generation;
    syncPollTimer.value = window.setTimeout(() => {
      void pollSyncProgress(run).then((nextDelay) => {
        if (isSyncPolling.value && generation === run) {
          scheduleSyncPoll(nextDelay);
        }
      });
    }, delayMs);
  }

  async function applyProgress(progress: SyncProgress, notify: boolean): Promise<void> {
    syncError.value = "";
    if (progress.status === "idle") {
      if (syncing.value) syncError.value = "同步任务已失效，可能已重启服务；请重新同步";
      stopSyncPolling();
      syncing.value = false;
      currentSyncTaskId.value = null;
      syncProgress.value = null;
      return;
    }
    syncProgress.value = progress;
    syncing.value = progress.status === "running";
    currentSyncTaskId.value = syncing.value ? progress.task_id : null;
    if (syncing.value) {
      startSyncPolling();
      return;
    }
    stopSyncPolling();
    if (!notify || notifiedTasks.has(progress.task_id)) return;
    notifiedTasks.add(progress.task_id);
    if (progress.status === "completed") {
      const warningText = progress.warnings?.length ? `，${progress.warnings.length} 个警告` : "";
      ElMessage.success(
        `同步完成：${progress.homes_total} 个家庭，${progress.devices_found} 个设备，${progress.scenes_found} 个场景${warningText}`,
      );
      try {
        await options.onCompleted();
      } catch (error) {
        syncError.value = `同步已完成，但列表刷新失败：${errorMessage(error, "请刷新重试")}`;
      }
    } else if (progress.status === "failed") {
      ElMessage.error(`同步失败：${progress.error || "请重新同步"}`);
    }
  }

  /** Read the server's task after reload, a lost start response, or a 409. */
  async function resumeSyncProgress(): Promise<boolean> {
    const run = generation;
    try {
      const progress = await options.request<SyncProgress>("/api/admin/sync/progress");
      if (run !== generation) return false;
      await applyProgress(progress, syncing.value);
      return true;
    } catch (error) {
      if (run !== generation) return false;
      syncError.value = `获取同步进度失败：${errorMessage(error, "请重试")}`;
      if (error instanceof ApiRequestError && [401, 403].includes(error.status)) stopSyncPolling();
      return false;
    }
  }

  async function pollSyncProgress(run: number): Promise<number> {
    try {
      const progress = await options.request<SyncProgress>("/api/admin/sync/progress");
      if (run !== generation) return 2000;
      const expectedTaskId = currentSyncTaskId.value;
      // 忽略上一轮终态 / 其它 task 的进度，避免误判本次同步已结束
      if (expectedTaskId && progress.task_id && progress.task_id !== expectedTaskId) {
        stopSyncPolling();
        syncing.value = false;
        currentSyncTaskId.value = null;
        syncError.value = "原同步任务已失效，请刷新进度查看当前任务";
        return 2000;
      }
      await applyProgress(progress, true);
      // 运行中稍密，其它状态放宽间隔，降低管理会话与 SQLite 压力
      return progress.status === "running" ? 1000 : 2000;
    } catch (error) {
      if (run !== generation) return 2000;
      syncError.value = `获取同步进度失败：${errorMessage(error, "网络异常")}`;
      if (error instanceof ApiRequestError && [401, 403].includes(error.status)) stopSyncPolling();
      return 5000;
    }
  }

  async function syncMijia(): Promise<void> {
    if (syncing.value) {
      ElMessage.warning("同步正在进行中，请稍候");
      return;
    }
    syncing.value = true;
    syncError.value = "";
    const run = generation;
    currentSyncTaskId.value = null;
    // 立即显示进度卡片，让用户知道同步已开始
    syncProgress.value = {
      task_id: "",
      status: "running",
      step: "准备同步...",
      progress: 0,
      current_home: "",
      homes_total: 0,
      homes_processed: 0,
      devices_found: 0,
      scenes_found: 0,
      warnings: [],
      started_at: "",
      updated_at: "",
      completed_at: null,
      error: null,
    };
    try {
      // POST 已非阻塞：先拿到 task_id 再轮询，避免读到上一轮 completed
      const started = await options.request<SyncStartResponse>("/api/admin/sync", {
        method: "POST",
        body: "{}",
      });
      if (run !== generation) return;
      if (started.task_id) {
        currentSyncTaskId.value = started.task_id;
        if (syncProgress.value) {
          syncProgress.value = { ...syncProgress.value, task_id: started.task_id };
        }
      }
      startSyncPolling();
    } catch (error) {
      if (run !== generation) return;
      // Never blindly re-send a start whose response may have been lost.
      if (await resumeSyncProgress()) {
        if (syncing.value) {
          ElMessage.info("已接回正在执行的同步任务");
          return;
        }
        if (syncProgress.value?.status === "completed") return;
      }
      syncing.value = false;
      currentSyncTaskId.value = null;
      stopSyncPolling();
      syncError.value = errorMessage(error, "同步失败，请刷新进度后重试");
      ElMessage.error(syncError.value);
    }
  }

  return {
    syncing,
    syncProgress,
    syncError,
    resumeSyncProgress,
    startSyncPolling,
    stopSyncPolling,
    syncMijia,
  };
}
