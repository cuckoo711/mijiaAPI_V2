import { ElMessage } from "element-plus";
import { ref } from "vue";
import type { RequestBehavior } from "./useAdminSession";

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

export type UseSyncProgressOptions = {
  request: RequestFn;
  /** Called once a sync completes successfully, to reload admin data. */
  onCompleted: () => Promise<void>;
};

/**
 * Drives the mijia home/device/scene sync: kicking off a sync and polling
 * its progress with an adaptive interval (denser while running, sparser
 * otherwise) to keep the admin session and SQLite load low.
 */
export function useSyncProgress(options: UseSyncProgressOptions) {
  const syncing = ref(false);
  const syncProgress = ref<SyncProgress | null>(null);
  const syncPollTimer = ref<number | null>(null);
  const isSyncPolling = ref(false);

  function startSyncPolling(): void {
    if (isSyncPolling.value) return;
    isSyncPolling.value = true;
    void scheduleSyncPoll(800);
  }

  function stopSyncPolling(): void {
    if (syncPollTimer.value) {
      window.clearTimeout(syncPollTimer.value);
      syncPollTimer.value = null;
    }
    isSyncPolling.value = false;
  }

  function scheduleSyncPoll(delayMs: number): void {
    if (!isSyncPolling.value) return;
    syncPollTimer.value = window.setTimeout(() => {
      void pollSyncProgress().then((nextDelay) => {
        if (isSyncPolling.value) {
          scheduleSyncPoll(nextDelay);
        }
      });
    }, delayMs);
  }

  async function pollSyncProgress(): Promise<number> {
    try {
      const progress = await options.request<SyncProgress>("/api/admin/sync/progress");
      // 如果后端返回 idle 但前端正在同步，保留前端的初始状态
      if (progress.status === "idle" && syncing.value) {
        return 1200;
      }
      syncProgress.value = progress;
      if (progress.status === "completed" || progress.status === "failed") {
        stopSyncPolling();
        syncing.value = false;
        if (progress.status === "completed") {
          const warningText = progress.warnings?.length ? `，${progress.warnings.length} 个警告` : "";
          ElMessage.success(
            `同步完成：${progress.homes_total} 个家庭，${progress.devices_found} 个设备，${progress.scenes_found} 个场景${warningText}`
          );
          await options.onCompleted();
        } else {
          ElMessage.error(`同步失败：${progress.error}`);
        }
        return 800;
      }
      // 运行中稍密，其它状态放宽间隔，降低管理会话与 SQLite 压力
      return progress.status === "running" ? 1000 : 2000;
    } catch (error) {
      console.error("获取同步进度失败:", error);
      return 2000;
    }
  }

  async function syncMijia(): Promise<void> {
    if (syncing.value) {
      ElMessage.warning("同步正在进行中，请稍候");
      return;
    }
    syncing.value = true;
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
    // 先开始轮询，再发起同步请求（同步请求是阻塞的）
    startSyncPolling();
    try {
      await options.request("/api/admin/sync", {
        method: "POST",
        body: "{}",
      });
    } catch (error) {
      ElMessage.error(error instanceof Error ? error.message : "同步失败");
      syncing.value = false;
      stopSyncPolling();
    }
  }

  return {
    syncing,
    syncProgress,
    startSyncPolling,
    stopSyncPolling,
    syncMijia,
  };
}
