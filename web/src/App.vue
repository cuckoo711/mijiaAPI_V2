<script setup lang="ts">
import {
  Connection,
  Cpu,
  Document,
  House,
  Key,
  Lock,
  Monitor,
  Setting,
  Tickets,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import type { Component } from "vue";
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { normalizeApiBaseUrl } from "./apiExamples";
import { useAdminSession } from "./composables/useAdminSession";
import { useMijiaLogin } from "./composables/useMijiaLogin";
import { useSyncProgress } from "./composables/useSyncProgress";
import type {
  ApiKeyItem,
  ApiList,
  AppInfo,
  CheckItem,
  DeviceItem,
  HomeItem,
  SceneItem,
  UpdateInfo,
} from "./types/admin";
import { configText } from "./utils/configHelpers";
import ApiDocsView from "./views/ApiDocsView.vue";
import ApiKeysView from "./views/ApiKeysView.vue";
import AuditView from "./views/AuditView.vue";
import ChecksView from "./views/ChecksView.vue";
import DashboardView from "./views/DashboardView.vue";
import DevicesView from "./views/DevicesView.vue";
import MijiaLoginView from "./views/MijiaLoginView.vue";
import ScenesView from "./views/ScenesView.vue";
import SecurityView from "./views/SecurityView.vue";
import SettingsView from "./views/SettingsView.vue";

type PageItem = {
  key: string;
  label: string;
  icon: Component;
};
type MenuSection = {
  key: string;
  label: string;
  icon: Component;
  pages: PageItem[];
};

const { isAuthed, request, refreshAdminSession, login: loginAdminSession, logout: logoutAdminSession, disposeAdminSession } =
  useAdminSession();

const activeMenu = ref(
  window.location.hash.slice(1) || localStorage.getItem("mijia_active_menu") || "dashboard"
);
const loading = ref(false);
const health = ref<{ status: string; version: string } | null>(null);
const initialized = ref(false);
const account = ref<Record<string, unknown>>({});
const checks = ref<CheckItem[]>([]);
const homes = ref<HomeItem[]>([]);
const devices = ref<DeviceItem[]>([]);
const scenes = ref<SceneItem[]>([]);
const apiKeys = ref<ApiKeyItem[]>([]);
const configs = ref<Array<Record<string, unknown>>>([]);
const audits = ref<Array<Record<string, unknown>>>([]);
const oneTimeApiKey = ref("");
const proxyCidrs = ref("");
const appInfo = ref<AppInfo | null>(null);
const updateInfo = ref<UpdateInfo | null>(null);
const aboutDialogVisible = ref(false);
const passwordDialogVisible = ref(false);
const changingPassword = ref(false);
const checkingUpdate = ref(false);

const { qrJob, startQrLogin, deleteCredential, disposeMijiaLogin } = useMijiaLogin({
  request,
  onAccountChanged: () => refreshAll(),
});
const { syncing, syncProgress, stopSyncPolling, syncMijia } = useSyncProgress({
  request,
  onCompleted: () => refreshAll(),
});

const defaultTrustedProxyCidrs = "127.0.0.1/32\n::1/128";

const adminForm = reactive({ username: "admin", password: "" });
const loginForm = reactive({ username: "admin", password: "" });
const passwordForm = reactive({
  currentPassword: "",
  newPassword: "",
  confirmPassword: "",
});

const dashboardPage: PageItem = { key: "dashboard", label: "总览", icon: Monitor };
const menuSections: MenuSection[] = [
  {
    key: "runtime",
    label: "运行管理",
    icon: Cpu,
    pages: [
      { key: "checks", label: "系统自检", icon: Cpu },
      { key: "mijia", label: "米家登录", icon: Connection },
    ],
  },
  {
    key: "resources",
    label: "资源管理",
    icon: House,
    pages: [
      { key: "devices", label: "家庭与设备", icon: House },
      { key: "scenes", label: "场景管理", icon: Tickets },
    ],
  },
  {
    key: "access",
    label: "访问控制",
    icon: Key,
    pages: [
      { key: "keys", label: "API Key", icon: Key },
      { key: "api-docs", label: "API 使用", icon: Document },
      { key: "security", label: "系统安全", icon: Lock },
    ],
  },
  {
    key: "system",
    label: "系统配置",
    icon: Setting,
    pages: [
      { key: "settings", label: "配置中心", icon: Setting },
      { key: "audit", label: "日志与审计", icon: Document },
    ],
  },
];
const pages = [dashboardPage, ...menuSections.flatMap((section) => section.pages)];

const initializedLabel = computed(() => (initialized.value ? "已初始化" : "待初始化"));
const activePage = computed(
  () => pages.find((page) => page.key === activeMenu.value) || dashboardPage
);
const runtimeConfig = computed(
  () => new Map(configs.value.map((item) => [String(item.key), item.value]))
);
const apiBaseUrl = computed(() =>
  normalizeApiBaseUrl(configText(runtimeConfig.value, "PUBLIC_BASE_URL"), window.location.origin)
);

function syncProxyCidrsForm(): void {
  proxyCidrs.value = configText(runtimeConfig.value, "TRUSTED_PROXY_CIDRS", defaultTrustedProxyCidrs);
}

function parseProxyCidrs(): string[] {
  return proxyCidrs.value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

async function loadPublic(): Promise<void> {
  const bootstrapPayload = await request<{
    initialized: boolean;
    status: string;
    version: string;
  }>("/api/admin/bootstrap/state");
  initialized.value = bootstrapPayload.initialized;
  health.value = {
    status: bootstrapPayload.status,
    version: bootstrapPayload.version,
  };
}

async function loadAdmin(): Promise<void> {
  if (!isAuthed.value) {
    return;
  }
  const [
    checkPayload,
    accountPayload,
    homePayload,
    devicePayload,
    scenePayload,
    keyPayload,
    configPayload,
    auditPayload,
  ] = await Promise.all([
    request<{ checks: CheckItem[] }>("/api/admin/system/check"),
    request<Record<string, unknown>>("/api/admin/mijia/account"),
    request<ApiList<HomeItem>>("/api/admin/homes"),
    request<ApiList<DeviceItem>>("/api/admin/devices?include_hidden=true"),
    request<ApiList<SceneItem>>("/api/admin/scenes?include_hidden=true"),
    request<ApiList<ApiKeyItem>>("/api/admin/api-keys"),
    request<ApiList<Record<string, unknown>>>("/api/admin/config"),
    request<ApiList<Record<string, unknown>>>("/api/admin/audit?limit=50"),
  ]);
  checks.value = checkPayload.checks;
  account.value = accountPayload;
  homes.value = homePayload.items;
  devices.value = devicePayload.items;
  scenes.value = scenePayload.items;
  apiKeys.value = keyPayload.items;
  configs.value = configPayload.items;
  audits.value = auditPayload.items;
  syncProxyCidrsForm();
}

async function refreshAll(): Promise<void> {
  loading.value = true;
  try {
    await loadPublic();
    await refreshAdminSession();
    await loadAdmin();
    void loadAppInfo();
    void checkForUpdates({ background: true });
  } finally {
    loading.value = false;
  }
}

async function loadAppInfo(): Promise<void> {
  if (!isAuthed.value) return;
  try {
    appInfo.value = await request<AppInfo>("/api/admin/app-info");
  } catch (error) {
    console.warn("加载应用信息失败", error);
  }
}

async function checkForUpdates(options: { background?: boolean; force?: boolean } = {}): Promise<void> {
  if (!isAuthed.value) return;
  const { background = false, force = false } = options;
  if (!background) checkingUpdate.value = true;
  try {
    const payload = await request<UpdateInfo>(
      `/api/admin/updates/check${force ? "?force=true" : ""}`
    );
    updateInfo.value = payload;
    if (!background && payload.error) {
      ElMessage.warning(`检查更新失败：${payload.error}`);
    } else if (!background && payload.update_available && payload.latest) {
      ElMessage.success(`发现新版本 ${payload.latest.latest_tag}`);
    } else if (!background && !payload.update_available) {
      ElMessage.success("已经是最新版本");
    }
  } catch (error) {
    if (!background) {
      ElMessage.warning(error instanceof Error ? error.message : "检查更新失败");
    } else {
      console.warn("后台检查更新失败", error);
    }
  } finally {
    if (!background) checkingUpdate.value = false;
  }
}

function openAboutDialog(): void {
  aboutDialogVisible.value = true;
  if (!appInfo.value) void loadAppInfo();
  if (!updateInfo.value) void checkForUpdates({ background: true });
}

function openReleasePage(): void {
  const url = updateInfo.value?.latest?.release_url;
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

function formatCheckedAt(epochSeconds: number): string {
  if (!epochSeconds) return "";
  const date = new Date(epochSeconds * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString();
}

async function createAdmin(): Promise<void> {
  try {
    await request("/api/admin/bootstrap/admin", {
      method: "POST",
      body: JSON.stringify(adminForm),
    });
    initialized.value = true;
    loginForm.username = adminForm.username;
    ElMessage.success("管理员已创建，请登录");
    await loadPublic();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "管理员创建失败");
    await loadPublic();
  }
}

async function login(): Promise<void> {
  try {
    await loginAdminSession(loginForm);
    ElMessage.success("登录成功");
    await refreshAll();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "登录失败");
  }
}

async function logout(): Promise<void> {
  await logoutAdminSession();
}

function openPasswordDialog(): void {
  passwordForm.currentPassword = "";
  passwordForm.newPassword = "";
  passwordForm.confirmPassword = "";
  passwordDialogVisible.value = true;
}

function resetPasswordForm(): void {
  passwordForm.currentPassword = "";
  passwordForm.newPassword = "";
  passwordForm.confirmPassword = "";
}

async function changePassword(): Promise<void> {
  if (passwordForm.newPassword.length < 8) {
    ElMessage.error("新密码至少需要 8 个字符");
    return;
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    ElMessage.error("两次输入的新密码不一致");
    return;
  }
  if (passwordForm.currentPassword === passwordForm.newPassword) {
    ElMessage.error("新密码不能与当前密码相同");
    return;
  }

  changingPassword.value = true;
  try {
    await request("/api/admin/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: passwordForm.currentPassword,
        new_password: passwordForm.newPassword,
      }),
    });
    passwordDialogVisible.value = false;
    ElMessage.success("密码已修改");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "修改密码失败");
  } finally {
    changingPassword.value = false;
  }
}

async function createApiKey(payload: { name: string; scopes: string[] }): Promise<void> {
  const response = await request<Record<string, string>>("/api/admin/api-keys", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  oneTimeApiKey.value = response.key;
  ElMessage.success("API Key 已创建，请保存一次性密钥");
  await loadAdmin();
}

async function updateDevice(device: DeviceItem, message = "设备已更新"): Promise<void> {
  await request(`/api/admin/devices/${device.id}`, {
    method: "PATCH",
    body: JSON.stringify({
      slug: device.slug,
      alias: device.alias,
      tags: device.tags,
      group_name: device.group_name,
      hidden: device.hidden,
      access_mode: device.access_mode,
    }),
  });
  ElMessage.success(message);
  await loadAdmin();
}

async function autoSaveDeviceAccess(
  device: DeviceItem,
  value: string | number | boolean
): Promise<void> {
  const nextValue = String(value);
  const previousValue = nextValue === "write" ? "read" : "write";
  try {
    await updateDevice(device, "访问权限已保存");
  } catch (error) {
    device.access_mode = previousValue;
    ElMessage.error(error instanceof Error ? error.message : "访问权限保存失败");
  }
}

async function autoSaveDeviceHidden(device: DeviceItem, value: string | number | boolean): Promise<void> {
  const previousValue = !Boolean(value);
  try {
    await updateDevice(device, "隐藏状态已保存");
  } catch (error) {
    device.hidden = previousValue;
    ElMessage.error(error instanceof Error ? error.message : "隐藏状态保存失败");
  }
}

async function updateScene(scene: SceneItem, message = "场景已更新"): Promise<void> {
  await request(`/api/admin/scenes/${scene.id}`, {
    method: "PATCH",
    body: JSON.stringify({ hidden: scene.hidden, executable: scene.executable }),
  });
  ElMessage.success(message);
  await loadAdmin();
}

async function autoSaveSceneExecutable(
  scene: SceneItem,
  value: string | number | boolean
): Promise<void> {
  const previousValue = !Boolean(value);
  try {
    await updateScene(scene, "执行权限已保存");
  } catch (error) {
    scene.executable = previousValue;
    ElMessage.error(error instanceof Error ? error.message : "执行权限保存失败");
  }
}

async function autoSaveSceneHidden(scene: SceneItem, value: string | number | boolean): Promise<void> {
  const previousValue = !Boolean(value);
  try {
    await updateScene(scene, "隐藏状态已保存");
  } catch (error) {
    scene.hidden = previousValue;
    ElMessage.error(error instanceof Error ? error.message : "隐藏状态保存失败");
  }
}

async function setConfig(payload: { key: string; value: string }): Promise<void> {
  await request(`/api/admin/config/${payload.key}`, {
    method: "PUT",
    body: JSON.stringify({ value: payload.value }),
  });
  ElMessage.success("配置已保存");
  await loadAdmin();
}

async function setRuntimeSwitch(key: string, value: string | number | boolean): Promise<void> {
  await request(`/api/admin/config/${key}`, {
    method: "PUT",
    body: JSON.stringify({ value: Boolean(value) }),
  });
  ElMessage.success("配置已保存");
  await loadAdmin();
}

async function saveTrustedProxyCidrs(): Promise<void> {
  await request("/api/admin/config/TRUSTED_PROXY_CIDRS", {
    method: "PUT",
    body: JSON.stringify({ value: parseProxyCidrs() }),
  });
  ElMessage.success("可信代理已保存");
  await loadAdmin();
}

function selectPage(index: string): void {
  activeMenu.value = index;
  window.location.hash = index;
  localStorage.setItem("mijia_active_menu", index);
}

function dismissSyncProgress(): void {
  syncProgress.value = null;
}

onMounted(() => {
  window.addEventListener("hashchange", () => {
    const hash = window.location.hash.slice(1);
    if (hash && hash !== activeMenu.value) {
      activeMenu.value = hash;
    }
  });
  void refreshAll();
});

onBeforeUnmount(() => {
  disposeMijiaLogin();
  disposeAdminSession();
  stopSyncPolling();
});
</script>

<template>
  <el-container class="app-shell">
    <el-aside class="sidebar" width="232px">
      <div class="brand">
        <div class="brand-mark">米</div>
        <div>
          <div class="brand-title">米家 API Server</div>
          <div class="brand-subtitle">管理台</div>
        </div>
      </div>
      <el-menu class="nav-menu" :default-active="activeMenu" @select="selectPage">
        <el-menu-item :index="dashboardPage.key">
          <el-icon><component :is="dashboardPage.icon" /></el-icon>
          <span>{{ dashboardPage.label }}</span>
        </el-menu-item>
        <el-sub-menu v-for="section in menuSections" :key="section.key" :index="section.key">
          <template #title>
            <el-icon><component :is="section.icon" /></el-icon>
            <span>{{ section.label }}</span>
          </template>
          <el-menu-item v-for="page in section.pages" :key="page.key" :index="page.key">
            <el-icon><component :is="page.icon" /></el-icon>
            <span>{{ page.label }}</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
      <div class="sidebar-footer">
        <button
          type="button"
          class="sidebar-about"
          :title="updateInfo?.update_available ? '发现新版本，点击查看' : '关于'"
          @click="openAboutDialog"
        >
          <span class="sidebar-about-version">v{{ health?.version || "..." }}</span>
          <span
            v-if="updateInfo?.update_available"
            class="sidebar-about-dot"
            aria-label="有可用更新"
          ></span>
          <span class="sidebar-about-label">关于</span>
        </button>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h1>{{ activePage.label }}</h1>
          <p>
            版本 {{ health?.version || "..." }}
            <button
              v-if="updateInfo?.update_available && updateInfo.latest"
              type="button"
              class="update-hint"
              @click="openAboutDialog"
            >
              有新版本 {{ updateInfo.latest.latest_tag }} 可用
            </button>
            · {{ initializedLabel }}
          </p>
        </div>
        <div class="toolbar">
          <el-button v-if="isAuthed" @click="openPasswordDialog">修改密码</el-button>
          <el-button v-if="isAuthed" @click="logout">退出</el-button>
          <el-button :loading="loading" :icon="Cpu" @click="refreshAll">刷新</el-button>
        </div>
      </el-header>

      <el-main class="content">
        <section v-if="!initialized" class="auth-panel">
          <el-card shadow="never">
            <template #header>创建管理员</template>
            <el-form label-width="96px">
              <el-form-item label="用户名">
                <el-input v-model="adminForm.username" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="adminForm.password" type="password" show-password />
              </el-form-item>
              <el-button type="primary" @click="createAdmin">初始化</el-button>
            </el-form>
          </el-card>
        </section>

        <section v-else-if="!isAuthed" class="auth-panel">
          <el-card shadow="never">
            <template #header>管理员登录</template>
            <el-form label-width="96px">
              <el-form-item label="用户名">
                <el-input v-model="loginForm.username" />
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="loginForm.password" type="password" show-password />
              </el-form-item>
              <el-button type="primary" @click="login">登录</el-button>
            </el-form>
          </el-card>
        </section>

        <DashboardView
          v-else-if="activeMenu === 'dashboard'"
          :health="health"
          :account="account"
          :devices="devices"
          :homes="homes"
          :scenes="scenes"
          :api-keys="apiKeys"
        />
        <ChecksView v-else-if="activeMenu === 'checks'" :checks="checks" />
        <MijiaLoginView
          v-else-if="activeMenu === 'mijia'"
          :account="account"
          :qr-job="qrJob"
          :syncing="syncing"
          :sync-progress="syncProgress"
          @start-qr-login="startQrLogin"
          @sync="syncMijia"
          @delete-credential="deleteCredential"
          @dismiss-sync-progress="dismissSyncProgress"
        />
        <DevicesView
          v-else-if="activeMenu === 'devices'"
          :devices="devices"
          :homes="homes"
          :syncing="syncing"
          @sync="syncMijia"
          @update-device="updateDevice"
          @auto-save-access="autoSaveDeviceAccess"
          @auto-save-hidden="autoSaveDeviceHidden"
        />
        <ScenesView
          v-else-if="activeMenu === 'scenes'"
          :scenes="scenes"
          :homes="homes"
          :api-base-url="apiBaseUrl"
          :one-time-api-key="oneTimeApiKey"
          @auto-save-executable="autoSaveSceneExecutable"
          @auto-save-hidden="autoSaveSceneHidden"
        />
        <ApiKeysView
          v-else-if="activeMenu === 'keys'"
          :api-keys="apiKeys"
          :one-time-api-key="oneTimeApiKey"
          @create="createApiKey"
        />
        <ApiDocsView
          v-else-if="activeMenu === 'api-docs'"
          :api-base-url="apiBaseUrl"
          :one-time-api-key="oneTimeApiKey"
        />
        <SecurityView
          v-else-if="activeMenu === 'security'"
          v-model:proxy-cidrs="proxyCidrs"
          :configs="configs"
          @set-runtime-switch="setRuntimeSwitch"
          @sync-proxy-cidrs="syncProxyCidrsForm"
          @save-proxy-cidrs="saveTrustedProxyCidrs"
        />
        <SettingsView
          v-else-if="activeMenu === 'settings'"
          :configs="configs"
          @set-config="setConfig"
        />
        <AuditView v-else-if="activeMenu === 'audit'" :audits="audits" />
        <section v-else class="placeholder-panel">
          <el-empty description="暂未配置页面" />
        </section>
      </el-main>
    </el-container>

    <el-dialog v-model="aboutDialogVisible" title="关于" width="480px" append-to-body>
      <div class="about-dialog">
        <div class="about-header">
          <div class="brand-mark about-mark">米</div>
          <div>
            <div class="about-name">{{ appInfo?.name || "米家 API Server" }}</div>
            <div class="about-version">
              <span>v{{ appInfo?.version || health?.version || "..." }}</span>
              <el-tag
                v-if="updateInfo?.update_available && updateInfo.latest"
                type="warning"
                size="small"
                effect="light"
              >
                可升级到 {{ updateInfo.latest.latest_tag }}
              </el-tag>
              <el-tag v-else-if="updateInfo && !updateInfo.error" type="success" size="small" effect="light">
                已是最新
              </el-tag>
            </div>
          </div>
        </div>

        <p v-if="appInfo?.description" class="about-desc">{{ appInfo.description }}</p>

        <dl class="about-meta">
          <div>
            <dt>许可证</dt>
            <dd>{{ appInfo?.license || "MIT" }}</dd>
          </div>
          <div v-if="appInfo?.authors">
            <dt>贡献者</dt>
            <dd>{{ appInfo.authors }}</dd>
          </div>
          <div v-if="appInfo?.repository_url">
            <dt>项目仓库</dt>
            <dd>
              <a :href="appInfo.repository_url" target="_blank" rel="noopener noreferrer">
                {{ appInfo.repository_url }}
              </a>
            </dd>
          </div>
          <div v-if="appInfo?.releases_url">
            <dt>发行版</dt>
            <dd>
              <a :href="appInfo.releases_url" target="_blank" rel="noopener noreferrer">
                查看所有版本
              </a>
            </dd>
          </div>
          <div v-if="appInfo?.issues_url">
            <dt>反馈问题</dt>
            <dd>
              <a :href="appInfo.issues_url" target="_blank" rel="noopener noreferrer">
                提交 Issue
              </a>
            </dd>
          </div>
        </dl>

        <div v-if="updateInfo?.update_available && updateInfo.latest" class="about-update-block">
          <div class="about-update-title">发现新版本 {{ updateInfo.latest.latest_tag }}</div>
          <div v-if="updateInfo.latest.published_at" class="about-update-meta">
            发布于 {{ new Date(updateInfo.latest.published_at).toLocaleString() }}
          </div>
          <div v-if="updateInfo.latest.release_notes" class="about-update-notes">
            <pre>{{ updateInfo.latest.release_notes }}</pre>
          </div>
          <el-button type="primary" size="small" @click="openReleasePage">
            前往下载
          </el-button>
        </div>

        <div v-else-if="updateInfo?.error" class="about-update-error">
          检查更新失败：{{ updateInfo.error }}
        </div>

        <div class="about-footer">
          <span v-if="updateInfo?.checked_at" class="about-checked-at">
            最近检查：{{ formatCheckedAt(updateInfo.checked_at) }}
          </span>
          <el-button
            size="small"
            :loading="checkingUpdate"
            @click="() => checkForUpdates({ force: true })"
          >
            立即检查
          </el-button>
        </div>

        <div class="about-copyright">
          © {{ new Date().getFullYear() }} {{ appInfo?.authors || "MijiaAPI Contributors" }}
        </div>
      </div>
    </el-dialog>

    <el-dialog
      v-model="passwordDialogVisible"
      title="修改密码"
      width="420px"
      append-to-body
      @closed="resetPasswordForm"
    >
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="当前密码">
          <el-input
            v-model="passwordForm.currentPassword"
            type="password"
            show-password
            autocomplete="current-password"
          />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input
            v-model="passwordForm.newPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="至少 8 个字符"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="passwordForm.confirmPassword"
            type="password"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="changingPassword" @click="changePassword">
          确认修改
        </el-button>
      </template>
    </el-dialog>
  </el-container>
</template>
