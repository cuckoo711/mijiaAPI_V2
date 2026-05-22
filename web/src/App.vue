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
import { computed, onMounted, reactive, ref } from "vue";

type ApiList<T> = { items: T[] };
type CheckItem = { key: string; status: string; message: string };
type DeviceItem = {
  id: string;
  did_masked: string;
  slug: string;
  name: string;
  alias?: string;
  display_name: string;
  model: string;
  home_id: string;
  tags: string[];
  group_name?: string;
  hidden: boolean;
  access_mode: string;
  status: string;
};
type SceneItem = {
  id: string;
  scene_id: string;
  name: string;
  home_id: string;
  hidden: boolean;
  executable: boolean;
};
type ApiKeyItem = {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  is_active: boolean;
  created_at: string;
  last_used_at?: string;
  use_count: number;
};

const token = ref(localStorage.getItem("mijia_admin_token") || "");
const activeMenu = ref("dashboard");
const loading = ref(false);
const health = ref<{ status: string; version: string } | null>(null);
const initialized = ref(false);
const account = ref<Record<string, unknown>>({});
const checks = ref<CheckItem[]>([]);
const devices = ref<DeviceItem[]>([]);
const scenes = ref<SceneItem[]>([]);
const apiKeys = ref<ApiKeyItem[]>([]);
const configs = ref<Array<Record<string, unknown>>>([]);
const audits = ref<Array<Record<string, unknown>>>([]);
const oneTimeApiKey = ref("");
const qrJob = ref<Record<string, string> | null>(null);
let qrTimer: number | undefined;

const adminForm = reactive({ username: "admin", password: "" });
const loginForm = reactive({ username: "admin", password: "" });
const keyForm = reactive({
  name: "",
  scopes: ["read:status", "read:devices"] as string[],
});
const configForm = reactive({ key: "PUBLIC_BASE_URL", value: "" });

const pages = [
  { key: "dashboard", label: "总览", icon: Monitor },
  { key: "checks", label: "系统自检", icon: Cpu },
  { key: "mijia", label: "米家登录", icon: Connection },
  { key: "devices", label: "家庭与设备", icon: House },
  { key: "scenes", label: "场景管理", icon: Tickets },
  { key: "keys", label: "API Key", icon: Key },
  { key: "security", label: "系统安全", icon: Lock },
  { key: "settings", label: "配置中心", icon: Setting },
  { key: "audit", label: "日志与审计", icon: Document },
];

const isAuthed = computed(() => Boolean(token.value));
const initializedLabel = computed(() => (initialized.value ? "已初始化" : "待初始化"));

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token.value) {
    headers.set("Authorization", `Bearer ${token.value}`);
  }
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.error?.message || `请求失败 ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function loadPublic(): Promise<void> {
  const [healthPayload, bootstrapPayload] = await Promise.all([
    request<{ status: string; version: string }>("/healthz"),
    request<{ initialized: boolean }>("/api/admin/bootstrap/state"),
  ]);
  health.value = healthPayload;
  initialized.value = bootstrapPayload.initialized;
}

async function loadAdmin(): Promise<void> {
  if (!token.value) {
    return;
  }
  const [checkPayload, accountPayload, devicePayload, scenePayload, keyPayload, configPayload, auditPayload] =
    await Promise.all([
      request<{ checks: CheckItem[] }>("/api/admin/system/check"),
      request<Record<string, unknown>>("/api/admin/mijia/account"),
      request<ApiList<DeviceItem>>("/api/admin/devices?include_hidden=true"),
      request<ApiList<SceneItem>>("/api/admin/scenes?include_hidden=true"),
      request<ApiList<ApiKeyItem>>("/api/admin/api-keys"),
      request<ApiList<Record<string, unknown>>>("/api/admin/config"),
      request<ApiList<Record<string, unknown>>>("/api/admin/audit?limit=50"),
    ]);
  checks.value = checkPayload.checks;
  account.value = accountPayload;
  devices.value = devicePayload.items;
  scenes.value = scenePayload.items;
  apiKeys.value = keyPayload.items;
  configs.value = configPayload.items;
  audits.value = auditPayload.items;
}

async function refreshAll(): Promise<void> {
  loading.value = true;
  try {
    await loadPublic();
    await loadAdmin();
  } finally {
    loading.value = false;
  }
}

async function createAdmin(): Promise<void> {
  await request("/api/admin/bootstrap/admin", {
    method: "POST",
    body: JSON.stringify(adminForm),
  });
  ElMessage.success("管理员已创建");
  await loadPublic();
}

async function login(): Promise<void> {
  const payload = await request<{ token: string }>("/api/admin/auth/login", {
    method: "POST",
    body: JSON.stringify(loginForm),
  });
  token.value = payload.token;
  localStorage.setItem("mijia_admin_token", payload.token);
  ElMessage.success("登录成功");
  await refreshAll();
}

function logout(): void {
  token.value = "";
  localStorage.removeItem("mijia_admin_token");
}

async function startQrLogin(): Promise<void> {
  qrJob.value = await request<Record<string, string>>("/api/admin/mijia/login/start", {
    method: "POST",
    body: "{}",
  });
  window.clearInterval(qrTimer);
  qrTimer = window.setInterval(pollQrLogin, 2500);
}

async function pollQrLogin(): Promise<void> {
  if (!qrJob.value?.id) {
    return;
  }
  qrJob.value = await request<Record<string, string>>(`/api/admin/mijia/login/${qrJob.value.id}`);
  if (["success", "failed"].includes(String(qrJob.value.status))) {
    window.clearInterval(qrTimer);
    await refreshAll();
  }
}

async function syncMijia(): Promise<void> {
  const result = await request<Record<string, number>>("/api/admin/sync", {
    method: "POST",
    body: "{}",
  });
  ElMessage.success(`同步完成：${result.homes} 个家庭，${result.devices} 个设备，${result.scenes} 个场景`);
  await refreshAll();
}

async function createApiKey(): Promise<void> {
  const payload = await request<Record<string, string>>("/api/admin/api-keys", {
    method: "POST",
    body: JSON.stringify({ name: keyForm.name, scopes: keyForm.scopes }),
  });
  oneTimeApiKey.value = payload.key;
  keyForm.name = "";
  ElMessage.success("API Key 已创建，请保存一次性密钥");
  await loadAdmin();
}

async function updateDevice(device: DeviceItem): Promise<void> {
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
  ElMessage.success("设备已更新");
  await loadAdmin();
}

async function updateScene(scene: SceneItem): Promise<void> {
  await request(`/api/admin/scenes/${scene.id}`, {
    method: "PATCH",
    body: JSON.stringify({ hidden: scene.hidden, executable: scene.executable }),
  });
  ElMessage.success("场景已更新");
  await loadAdmin();
}

async function setConfig(): Promise<void> {
  await request(`/api/admin/config/${configForm.key}`, {
    method: "PUT",
    body: JSON.stringify({ value: configForm.value }),
  });
  configForm.value = "";
  ElMessage.success("配置已保存");
  await loadAdmin();
}

function selectPage(index: string): void {
  activeMenu.value = index;
}

onMounted(() => {
  void refreshAll();
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
        <el-menu-item v-for="page in pages" :key="page.key" :index="page.key">
          <el-icon><component :is="page.icon" /></el-icon>
          <span>{{ page.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h1>{{ pages.find((page) => page.key === activeMenu)?.label }}</h1>
          <p>版本 {{ health?.version || "..." }} · {{ initializedLabel }}</p>
        </div>
        <div class="toolbar">
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

        <section v-else-if="activeMenu === 'dashboard'" class="dashboard-grid">
          <el-card shadow="never">
            <template #header>服务状态</template>
            <div class="metric-line">
              <span>后端</span>
              <el-tag :type="health?.status === 'ok' ? 'success' : 'danger'">
                {{ health?.status || "unknown" }}
              </el-tag>
            </div>
          </el-card>
          <el-card shadow="never">
            <template #header>米家账号</template>
            <div class="metric-line">
              <span>凭据</span>
              <el-tag :type="account.valid ? 'success' : 'warning'">
                {{ account.valid ? "有效" : "未登录或已过期" }}
              </el-tag>
            </div>
          </el-card>
          <el-card shadow="never">
            <template #header>设备</template>
            <div class="metric-line">
              <span>已同步</span>
              <strong>{{ devices.length }}</strong>
            </div>
          </el-card>
          <el-card shadow="never">
            <template #header>API Key</template>
            <div class="metric-line">
              <span>总数</span>
              <strong>{{ apiKeys.length }}</strong>
            </div>
          </el-card>
        </section>

        <section v-else-if="activeMenu === 'checks'">
          <el-table :data="checks" border>
            <el-table-column prop="key" label="检查项" width="180" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="row.status === 'pass' ? 'success' : row.status === 'fail' ? 'danger' : 'warning'">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="结果" />
          </el-table>
        </section>

        <section v-else-if="activeMenu === 'mijia'" class="stack">
          <el-card shadow="never">
            <template #header>账号状态</template>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="凭据存在">{{ account.exists }}</el-descriptions-item>
              <el-descriptions-item label="有效">{{ account.valid }}</el-descriptions-item>
              <el-descriptions-item label="用户 ID">{{ account.user_id || "-" }}</el-descriptions-item>
              <el-descriptions-item label="过期时间">{{ account.expires_at || "-" }}</el-descriptions-item>
            </el-descriptions>
          </el-card>
          <el-card shadow="never">
            <template #header>二维码登录</template>
            <el-button type="primary" @click="startQrLogin">开始扫码登录</el-button>
            <el-button @click="syncMijia">同步家庭/设备/场景</el-button>
            <div v-if="qrJob" class="qr-box">
              <img :src="qrJob.qr_url" alt="米家登录二维码" />
              <div>{{ qrJob.status }} · {{ qrJob.message }}</div>
            </div>
          </el-card>
        </section>

        <section v-else-if="activeMenu === 'devices'">
          <el-button class="section-action" @click="syncMijia">重新同步</el-button>
          <el-table :data="devices" border>
            <el-table-column label="显示名" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.alias" :placeholder="row.name" />
              </template>
            </el-table-column>
            <el-table-column label="Slug" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.slug" />
              </template>
            </el-table-column>
            <el-table-column prop="model" label="型号" min-width="180" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column label="访问" width="140">
              <template #default="{ row }">
                <el-select v-model="row.access_mode">
                  <el-option label="只读" value="read" />
                  <el-option label="可控" value="write" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="隐藏" width="90">
              <template #default="{ row }">
                <el-switch v-model="row.hidden" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" @click="updateDevice(row)">保存</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-else-if="activeMenu === 'scenes'">
          <el-table :data="scenes" border>
            <el-table-column prop="name" label="名称" min-width="180" />
            <el-table-column prop="home_id" label="家庭" min-width="160" />
            <el-table-column label="允许执行" width="120">
              <template #default="{ row }">
                <el-switch v-model="row.executable" />
              </template>
            </el-table-column>
            <el-table-column label="隐藏" width="90">
              <template #default="{ row }">
                <el-switch v-model="row.hidden" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" @click="updateScene(row)">保存</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-else-if="activeMenu === 'keys'" class="stack">
          <el-card shadow="never">
            <template #header>创建 API Key</template>
            <el-form label-width="96px">
              <el-form-item label="名称">
                <el-input v-model="keyForm.name" />
              </el-form-item>
              <el-form-item label="权限">
                <el-checkbox-group v-model="keyForm.scopes">
                  <el-checkbox label="read:status" />
                  <el-checkbox label="read:devices" />
                  <el-checkbox label="write:devices" />
                  <el-checkbox label="write:scenes" />
                  <el-checkbox label="manage:cache" />
                  <el-checkbox label="read:logs" />
                </el-checkbox-group>
              </el-form-item>
              <el-button type="primary" @click="createApiKey">创建</el-button>
            </el-form>
            <el-alert v-if="oneTimeApiKey" class="one-time-key" type="warning" show-icon :closable="false">
              <template #title>一次性密钥：{{ oneTimeApiKey }}</template>
            </el-alert>
          </el-card>
          <el-table :data="apiKeys" border>
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="key_prefix" label="前缀" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'info'">
                  {{ row.is_active ? "启用" : "停用" }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="use_count" label="调用次数" width="100" />
          </el-table>
        </section>

        <section v-else-if="activeMenu === 'settings'" class="stack">
          <el-card shadow="never">
            <template #header>运行时配置</template>
            <el-form inline>
              <el-form-item label="Key">
                <el-input v-model="configForm.key" />
              </el-form-item>
              <el-form-item label="Value">
                <el-input v-model="configForm.value" />
              </el-form-item>
              <el-button type="primary" @click="setConfig">保存</el-button>
            </el-form>
          </el-card>
          <el-table :data="configs" border>
            <el-table-column prop="key" label="Key" />
            <el-table-column prop="value" label="Value" />
            <el-table-column prop="source" label="来源" width="120" />
          </el-table>
        </section>

        <section v-else-if="activeMenu === 'audit'">
          <el-table :data="audits" border>
            <el-table-column prop="occurred_at" label="时间" min-width="190" />
            <el-table-column prop="action" label="动作" min-width="180" />
            <el-table-column prop="actor_type" label="操作者" width="110" />
            <el-table-column prop="result" label="结果" width="100" />
          </el-table>
        </section>

        <section v-else class="placeholder-panel">
          <el-empty description="安全策略会在后续细化为独立表单" />
        </section>
      </el-main>
    </el-container>
  </el-container>
</template>
