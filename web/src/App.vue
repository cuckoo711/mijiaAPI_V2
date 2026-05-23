<script setup lang="ts">
import {
  Connection,
  CopyDocument,
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";

type ApiList<T> = { items: T[] };
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
type CheckItem = {
  key: string;
  label: string;
  description: string;
  status: string;
  message: string;
};
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
type HomeItem = {
  id: string;
  name: string;
  uid: string;
  rooms?: Array<Record<string, unknown>>;
  last_synced_at?: string;
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
type ApiEndpointRow = {
  method: "GET" | "POST";
  path: string;
  purpose: string;
  permission: string;
  request: string;
  response: string;
  note: string;
  body?: string;
};
type AdminSessionPayload = {
  token: string;
  expires_at: string;
  admin?: { id: string; username: string };
};
type RequestBehavior = {
  skipAuthRedirect?: boolean;
};

class ApiRequestError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

const token = ref(localStorage.getItem("mijia_admin_token") || "");
const tokenExpiresAt = ref(localStorage.getItem("mijia_admin_expires_at") || "");
const activeMenu = ref("dashboard");
const loading = ref(false);
const syncing = ref(false);
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
const qrJob = ref<Record<string, string> | null>(null);
const proxyCidrs = ref("");
const devicePage = ref(1);
const devicePageSize = ref(20);
let qrTimer: number | undefined;
let adminRefreshTimer: number | undefined;

const defaultTrustedProxyCidrs = "127.0.0.1/32\n::1/128";

const adminForm = reactive({ username: "admin", password: "" });
const loginForm = reactive({ username: "admin", password: "" });
const keyForm = reactive({
  name: "",
  scopes: ["read:status", "read:devices"] as string[],
});
const configForm = reactive({ key: "PUBLIC_BASE_URL", value: "" });
const deviceFilters = reactive({
  home: "",
  status: "",
  access: "",
  hidden: "",
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

const apiPermissionRows: Array<{
  scope: string;
  name: string;
  description: string;
  level: "success" | "warning" | "danger" | "info";
}> = [
  {
    scope: "read:status",
    name: "读取服务状态",
    description: "允许调用方读取服务健康状态、版本和基础运行信息。",
    level: "success",
  },
  {
    scope: "read:devices",
    name: "读取家庭与设备",
    description: "允许读取已同步的家庭、设备列表、设备状态和设备规格。",
    level: "info",
  },
  {
    scope: "write:devices",
    name: "控制设备",
    description: "允许调用方修改设备属性、调用设备动作和批量控制设备。",
    level: "danger",
  },
  {
    scope: "write:scenes",
    name: "执行场景",
    description: "允许调用方执行已授权的米家场景。",
    level: "danger",
  },
  {
    scope: "manage:cache",
    name: "管理缓存",
    description: "允许刷新或清理 SDK 本地缓存。",
    level: "warning",
  },
  {
    scope: "read:logs",
    name: "读取审计日志",
    description: "允许读取接口调用记录和审计日志。",
    level: "warning",
  },
];

const securityRows = [
  {
    item: "管理员登录",
    status: "已启用",
    description: "管理台需要管理员会话才能进入，管理员密码只保存哈希。",
  },
  {
    item: "API Key",
    status: "已启用",
    description: "外部调用必须使用 Bearer API Key，并受权限 scope 限制。",
  },
  {
    item: "设备控制授权",
    status: "已启用",
    description: "设备默认为只读，只有切到可控后才允许外部控制。",
  },
  {
    item: "米家凭据",
    status: "本地保存",
    description: "扫码后的米家凭据保存在本机 credential 文件中，服务启动后读取。",
  },
  {
    item: "OpenAPI 文档",
    status: "默认关闭",
    description: "接口文档默认不公开，可通过环境变量按需开启。",
  },
  {
    item: "审计日志",
    status: "保留 30 天",
    description: "管理操作和外部 API 调用会写入 SQLite 审计日志。",
  },
];

const apiEndpointRows: ApiEndpointRow[] = [
  {
    method: "GET",
    path: "/api/v1/status",
    purpose: "读取服务状态",
    permission: "读取服务状态",
    request: "无请求体",
    response: "返回服务名称、版本、启动时间、运行秒数和初始化状态。",
    note: "适合健康探测或 AI Agent 启动前检查服务是否可用。",
  },
  {
    method: "GET",
    path: "/api/v1/account",
    purpose: "读取米家账号凭据状态",
    permission: "读取服务状态",
    request: "无请求体",
    response: "返回凭据是否存在、是否有效、用户 ID、过期时间和剩余秒数。",
    note: "只返回凭据状态，不会返回 serviceToken 等敏感信息。",
  },
  {
    method: "GET",
    path: "/api/v1/homes",
    purpose: "读取家庭列表",
    permission: "读取家庭与设备",
    request: "无请求体",
    response: "返回已同步家庭列表，包含家庭 ID、名称、uid、房间和同步时间。",
    note: "需要先在管理台完成“同步家庭/设备/场景”。",
  },
  {
    method: "GET",
    path: "/api/v1/devices",
    purpose: "读取设备列表",
    permission: "读取家庭与设备",
    request: "无请求体",
    response: "返回未隐藏设备列表，包含 slug、名称、型号、家庭 ID、访问模式和状态。",
    note: "后续读取状态或控制设备时，优先使用这里返回的 device_slug。",
  },
  {
    method: "GET",
    path: "/api/v1/devices/{device_slug}",
    purpose: "读取单个设备",
    permission: "读取家庭与设备",
    request: "无请求体",
    response: "返回单个设备的完整本地登记信息。",
    note: "{device_slug} 可以在“家庭与设备”页面查看和修改。",
  },
  {
    method: "GET",
    path: "/api/v1/devices/{device_slug}/state",
    purpose: "读取设备状态",
    permission: "读取家庭与设备",
    request: "无请求体",
    response: "返回设备可读属性的当前值列表。",
    note: "如果设备规格没有可读属性，items 可能为空。",
  },
  {
    method: "GET",
    path: "/api/v1/devices/{device_slug}/spec",
    purpose: "读取设备规格",
    permission: "读取家庭与设备",
    request: "无请求体",
    response: "返回设备 MiOT 规格，用于确认 siid、piid、aiid 和参数。",
    note: "控制设备前通常先看这个接口，确认要设置的属性或动作编号。",
  },
  {
    method: "POST",
    path: "/api/v1/devices/{device_slug}/properties",
    purpose: "设置设备属性",
    permission: "控制设备",
    request: "JSON：siid、piid、value。",
    response: "返回 success 布尔值。",
    note: "设备必须先在“家庭与设备”页面切到可控。",
    body: '{\n  "siid": 2,\n  "piid": 1,\n  "value": true\n}',
  },
  {
    method: "POST",
    path: "/api/v1/devices/{device_slug}/actions",
    purpose: "调用设备动作",
    permission: "控制设备",
    request: "JSON：siid、aiid、params。",
    response: "返回米家动作调用结果。",
    note: "params 按设备规格填写；无参数时传空对象。",
    body: '{\n  "siid": 2,\n  "aiid": 1,\n  "params": {}\n}',
  },
  {
    method: "POST",
    path: "/api/v1/batch/devices/properties",
    purpose: "批量设置属性",
    permission: "控制设备",
    request: "JSON：items 数组，每项包含 device、siid、piid、value。",
    response: "返回每个属性设置的结果列表。",
    note: "每个被控制设备都必须处于可控状态。",
    body:
      '{\n  "items": [\n    {\n      "device": "living-room-light",\n      "siid": 2,\n      "piid": 1,\n      "value": true\n    }\n  ]\n}',
  },
  {
    method: "GET",
    path: "/api/v1/scenes",
    purpose: "读取场景列表",
    permission: "读取家庭与设备",
    request: "无请求体",
    response: "返回未隐藏场景列表，包含 id、scene_id、名称、家庭 ID 和可执行状态。",
    note: "scene_id 可在“场景管理”页面复制，执行场景时使用。",
  },
  {
    method: "POST",
    path: "/api/v1/scenes/{scene_id}/execute",
    purpose: "执行米家场景",
    permission: "执行场景",
    request: "无请求体",
    response: "返回 success 布尔值。",
    note: "{scene_id} 在“场景管理”页面复制；场景必须开启“允许执行”。",
  },
  {
    method: "POST",
    path: "/api/v1/cache/refresh?home_id={home_id}",
    purpose: "刷新 SDK 缓存",
    permission: "管理缓存",
    request: "无请求体；home_id 是可选查询参数。",
    response: "返回 success 布尔值。",
    note: "不传 home_id 时刷新当前账号所有可刷新缓存。",
  },
  {
    method: "POST",
    path: "/api/v1/cache/clear",
    purpose: "清理 SDK 和本地缓存",
    permission: "管理缓存",
    request: "无请求体",
    response: "返回 success 和本地缓存删除数量。",
    note: "用于排查设备规格或本地缓存不一致问题。",
  },
  {
    method: "GET",
    path: "/api/v1/logs?limit=100",
    purpose: "读取审计日志",
    permission: "读取审计日志",
    request: "无请求体；limit 是可选查询参数，范围 1-500。",
    response: "返回审计日志列表。",
    note: "用于查看 API Key 调用和管理操作记录。",
  },
];

const isAuthed = computed(() => Boolean(token.value));
const initializedLabel = computed(() => (initialized.value ? "已初始化" : "待初始化"));
const activePage = computed(
  () => pages.find((page) => page.key === activeMenu.value) || dashboardPage
);
const runtimeConfig = computed(
  () => new Map(configs.value.map((item) => [String(item.key), item.value]))
);
const apiBaseUrl = computed(() => configText("PUBLIC_BASE_URL") || window.location.origin);
const homeNameMap = computed(() => new Map(homes.value.map((home) => [home.id, home.name])));
const filteredDevices = computed(() => {
  return devices.value.filter((device) => {
    if (deviceFilters.home && device.home_id !== deviceFilters.home) {
      return false;
    }
    if (deviceFilters.status && device.status !== deviceFilters.status) {
      return false;
    }
    if (deviceFilters.access && device.access_mode !== deviceFilters.access) {
      return false;
    }
    if (deviceFilters.hidden && String(device.hidden) !== deviceFilters.hidden) {
      return false;
    }
    return true;
  });
});
const paginatedDevices = computed(() => {
  const start = (devicePage.value - 1) * devicePageSize.value;
  return filteredDevices.value.slice(start, start + devicePageSize.value);
});

watch(deviceFilters, () => {
  devicePage.value = 1;
});

watch([filteredDevices, devicePageSize], () => {
  const maxPage = Math.max(1, Math.ceil(filteredDevices.value.length / devicePageSize.value));
  if (devicePage.value > maxPage) {
    devicePage.value = maxPage;
  }
});

function deviceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    online: "在线",
    offline: "离线",
    unknown: "未知",
  };
  return labels[status] || status || "-";
}

function deviceStatusTag(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "online") {
    return "success";
  }
  if (status === "offline") {
    return "danger";
  }
  if (status === "unknown") {
    return "warning";
  }
  return "info";
}

function checkStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pass: "通过",
    warn: "提醒",
    fail: "失败",
    info: "信息",
  };
  return labels[status] || status || "-";
}

function checkStatusTag(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "pass") {
    return "success";
  }
  if (status === "fail") {
    return "danger";
  }
  if (status === "warn") {
    return "warning";
  }
  return "info";
}

function methodTag(method: string): "success" | "warning" | "info" {
  return method === "POST" ? "warning" : method === "GET" ? "success" : "info";
}

function endpointCurl(row: ApiEndpointRow): string {
  const lines = [`curl -X ${row.method} \\`, `  -H "Authorization: Bearer YOUR_API_KEY" \\`];
  if (row.body) {
    lines.push(`  -H "Content-Type: application/json" \\`);
    lines.push(`  -d '${row.body.replace(/\n/g, "")}' \\`);
  }
  lines.push(`  ${apiBaseUrl.value}${row.path}`);
  return lines.join("\n");
}

async function copyText(value: string, message: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
  } else {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }
  ElMessage.success(message);
}

function homeName(homeId: string): string {
  return homeNameMap.value.get(homeId) || homeId || "-";
}

function resetDeviceFilters(): void {
  deviceFilters.home = "";
  deviceFilters.status = "";
  deviceFilters.access = "";
  deviceFilters.hidden = "";
}

function configBool(key: string, defaultValue = false): boolean {
  const value = runtimeConfig.value.get(key);
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    return ["1", "true", "yes", "on"].includes(value.toLowerCase());
  }
  if (value === undefined || value === null) {
    return defaultValue;
  }
  return Boolean(value);
}

function configText(key: string, defaultValue = ""): string {
  const value = runtimeConfig.value.get(key);
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join("\n");
  }
  if (typeof value === "string") {
    return value;
  }
  if (value === undefined || value === null) {
    return defaultValue;
  }
  return String(value);
}

function syncProxyCidrsForm(): void {
  proxyCidrs.value = configText("TRUSTED_PROXY_CIDRS", defaultTrustedProxyCidrs);
}

function parseProxyCidrs(): string[] {
  return proxyCidrs.value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function toggleApiKeyScope(scope: string, checked: string | number | boolean): void {
  const selected = Boolean(checked);
  const scopes = new Set(keyForm.scopes);
  if (selected) {
    scopes.add(scope);
  } else {
    scopes.delete(scope);
  }
  keyForm.scopes = Array.from(scopes);
}

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
  if (!token.value) {
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
  } finally {
    loading.value = false;
  }
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
    const payload = await request<AdminSessionPayload>("/api/admin/auth/login", {
      method: "POST",
      body: JSON.stringify(loginForm),
    });
    saveAdminSession(payload);
    ElMessage.success("登录成功");
    await refreshAll();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "登录失败");
  }
}

function logout(): void {
  clearAdminSession();
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
  const status = String(qrJob.value.status);
  if (status === "success") {
    window.clearInterval(qrTimer);
    await refreshAll();
    ElMessage.success("米家登录成功");
    qrJob.value = null;
    return;
  }
  if (status === "failed") {
    window.clearInterval(qrTimer);
  }
}

async function syncMijia(): Promise<void> {
  if (syncing.value) {
    ElMessage.warning("同步正在进行中，请稍候");
    return;
  }
  syncing.value = true;
  try {
    const result = await request<{
      homes: number;
      devices: number;
      scenes: number;
      warnings?: Array<{ kind: string; home_name: string; message: string }>;
    }>("/api/admin/sync", {
      method: "POST",
      body: "{}",
    });
    const warningText = result.warnings?.length ? `，${result.warnings.length} 个警告` : "";
    ElMessage.success(
      `同步完成：${result.homes} 个家庭，${result.devices} 个设备，${result.scenes} 个场景${warningText}`
    );
    await refreshAll();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "同步失败");
  } finally {
    syncing.value = false;
  }
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

async function setConfig(): Promise<void> {
  await request(`/api/admin/config/${configForm.key}`, {
    method: "PUT",
    body: JSON.stringify({ value: configForm.value }),
  });
  configForm.value = "";
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
}

onMounted(() => {
  void refreshAll();
});

onBeforeUnmount(() => {
  window.clearInterval(qrTimer);
  window.clearTimeout(adminRefreshTimer);
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
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <h1>{{ activePage.label }}</h1>
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
            <el-table-column label="检查项" min-width="180">
              <template #default="{ row }">
                <div class="check-name">{{ row.label || row.key }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="说明" min-width="280" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="checkStatusTag(row.status)">
                  {{ checkStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="结果" min-width="240" />
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
            <el-button :loading="syncing" :disabled="syncing" @click="syncMijia">
              同步家庭/设备/场景
            </el-button>
            <div v-if="qrJob" class="qr-box">
              <img :src="qrJob.qr_url" alt="米家登录二维码" />
              <div>{{ qrJob.status }} · {{ qrJob.message }}</div>
            </div>
          </el-card>
        </section>

        <section v-else-if="activeMenu === 'devices'" class="devices-page">
          <div class="device-filter-bar">
            <el-button :loading="syncing" :disabled="syncing" @click="syncMijia">重新同步</el-button>
            <el-select v-model="deviceFilters.home" clearable placeholder="家庭" class="filter-control">
              <el-option v-for="home in homes" :key="home.id" :label="home.name" :value="home.id" />
            </el-select>
            <el-select v-model="deviceFilters.status" clearable placeholder="状态" class="filter-control">
              <el-option label="在线" value="online" />
              <el-option label="离线" value="offline" />
              <el-option label="未知" value="unknown" />
            </el-select>
            <el-select v-model="deviceFilters.access" clearable placeholder="访问" class="filter-control">
              <el-option label="只读" value="read" />
              <el-option label="可控" value="write" />
            </el-select>
            <el-select v-model="deviceFilters.hidden" clearable placeholder="隐藏" class="filter-control">
              <el-option label="显示" value="false" />
              <el-option label="隐藏" value="true" />
            </el-select>
            <el-button @click="resetDeviceFilters">重置</el-button>
          </div>
          <el-table :data="paginatedDevices" border height="100%" class="devices-table">
            <el-table-column label="显示名" min-width="180">
              <template #default="{ row }">
                <span class="readonly-name">{{ row.display_name || row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Slug" min-width="180">
              <template #default="{ row }">
                <el-input v-model="row.slug" />
              </template>
            </el-table-column>
            <el-table-column label="家庭" min-width="160">
              <template #default="{ row }">
                {{ homeName(row.home_id) }}
              </template>
            </el-table-column>
            <el-table-column prop="model" label="型号" min-width="180" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="deviceStatusTag(row.status)" effect="light">
                  {{ deviceStatusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="访问" width="140">
              <template #default="{ row }">
                <el-switch
                  v-model="row.access_mode"
                  active-value="write"
                  inactive-value="read"
                  active-text="可控"
                  inactive-text="只读"
                  inline-prompt
                  class="access-switch"
                  @change="(value: string | number | boolean) => autoSaveDeviceAccess(row, value)"
                />
              </template>
            </el-table-column>
            <el-table-column label="隐藏" width="90">
              <template #default="{ row }">
                <el-switch
                  v-model="row.hidden"
                  @change="(value: string | number | boolean) => autoSaveDeviceHidden(row, value)"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" @click="updateDevice(row)">保存</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="table-pagination">
            <el-pagination
              v-model:current-page="devicePage"
              v-model:page-size="devicePageSize"
              :page-sizes="[20, 50, 100]"
              :total="filteredDevices.length"
              background
              layout="total, sizes, prev, pager, next"
            />
          </div>
        </section>

        <section v-else-if="activeMenu === 'scenes'">
          <el-table :data="scenes" border>
            <el-table-column prop="name" label="名称" min-width="180" />
            <el-table-column label="家庭" min-width="160">
              <template #default="{ row }">
                {{ homeName(row.home_id) }}
              </template>
            </el-table-column>
            <el-table-column label="场景 ID" min-width="260">
              <template #default="{ row }">
                <div class="copyable-id">
                  <code>{{ row.scene_id }}</code>
                  <el-button
                    :icon="CopyDocument"
                    circle
                    size="small"
                    title="复制场景 ID"
                    @click="copyText(row.scene_id, '场景 ID 已复制')"
                  />
                </div>
              </template>
            </el-table-column>
            <el-table-column label="允许执行" width="120">
              <template #default="{ row }">
                <el-switch
                  v-model="row.executable"
                  @change="(value: string | number | boolean) => autoSaveSceneExecutable(row, value)"
                />
              </template>
            </el-table-column>
            <el-table-column label="隐藏" width="90">
              <template #default="{ row }">
                <el-switch
                  v-model="row.hidden"
                  @change="(value: string | number | boolean) => autoSaveSceneHidden(row, value)"
                />
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
                <el-table :data="apiPermissionRows" border class="permission-table">
                  <el-table-column label="选择" width="80" align="center">
                    <template #default="{ row }">
                      <el-checkbox
                        :model-value="keyForm.scopes.includes(row.scope)"
                        @change="(checked: string | number | boolean) => toggleApiKeyScope(row.scope, checked)"
                      />
                    </template>
                  </el-table-column>
                  <el-table-column label="权限" width="170">
                    <template #default="{ row }">
                      <div class="permission-name">{{ row.name }}</div>
                    </template>
                  </el-table-column>
                  <el-table-column prop="description" label="说明" min-width="260" />
                  <el-table-column label="风险" width="90" align="center">
                    <template #default="{ row }">
                      <el-tag :type="row.level" effect="light">
                        {{ row.level === "danger" ? "高" : row.level === "warning" ? "中" : "低" }}
                      </el-tag>
                    </template>
                  </el-table-column>
                </el-table>
              </el-form-item>
              <el-button type="primary" @click="createApiKey">创建</el-button>
            </el-form>
            <el-alert v-if="oneTimeApiKey" class="one-time-key" type="warning" show-icon :closable="false">
              <template #title>一次性密钥，只显示这一次</template>
              <div class="api-key-value">{{ oneTimeApiKey }}</div>
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

        <section v-else-if="activeMenu === 'api-docs'" class="stack">
          <el-card shadow="never">
            <template #header>调用方式</template>
            <div class="usage-note">
              外部调用时，把 API Key 放到 HTTP Header：<code>Authorization: Bearer YOUR_API_KEY</code>
            </div>
            <div class="doc-link-row">
              <el-button tag="a" href="/docs" target="_blank">Swagger 文档</el-button>
              <el-button tag="a" href="/redoc" target="_blank">ReDoc 文档</el-button>
              <el-button tag="a" href="/api/v1/openapi.json" target="_blank">OpenAPI JSON</el-button>
            </div>
            <pre class="usage-code"><code>curl -H "Authorization: Bearer YOUR_API_KEY" \
  {{ apiBaseUrl }}/api/v1/devices</code></pre>
            <pre class="usage-code"><code>fetch("{{ apiBaseUrl }}/api/v1/devices", {
  headers: {
    Authorization: "Bearer YOUR_API_KEY"
  }
})</code></pre>
            <el-alert type="info" show-icon :closable="false">
              <template #title>
                API Key 创建后只显示一次。Swagger/ReDoc 和 OpenAPI JSON 可在“系统安全”中开启，切换后立即生效。
              </template>
            </el-alert>
          </el-card>
          <el-card shadow="never">
            <template #header>接口文档</template>
            <el-table :data="apiEndpointRows" border>
              <el-table-column type="expand" width="48">
                <template #default="{ row }">
                  <div class="endpoint-detail">
                    <el-descriptions :column="1" border>
                      <el-descriptions-item label="请求数据">{{ row.request }}</el-descriptions-item>
                      <el-descriptions-item label="返回数据">{{ row.response }}</el-descriptions-item>
                      <el-descriptions-item label="注意事项">{{ row.note }}</el-descriptions-item>
                    </el-descriptions>
                    <pre v-if="row.body" class="usage-code endpoint-body"><code>{{ row.body }}</code></pre>
                    <pre class="usage-code endpoint-curl"><code>{{ endpointCurl(row) }}</code></pre>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="方法" width="92" align="center">
                <template #default="{ row }">
                  <el-tag :type="methodTag(row.method)" effect="light">{{ row.method }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="路径" min-width="280">
                <template #default="{ row }">
                  <code class="endpoint-path">{{ row.path }}</code>
                </template>
              </el-table-column>
              <el-table-column prop="purpose" label="用途" min-width="180" />
              <el-table-column prop="permission" label="所需权限" min-width="160" />
              <el-table-column prop="request" label="请求数据" min-width="180" />
            </el-table>
          </el-card>
          <el-card shadow="never">
            <template #header>访问策略</template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="本机调用">
                服务监听 127.0.0.1 时，只能从同一台机器访问，适合脚本或反向代理转发。
              </el-descriptions-item>
              <el-descriptions-item label="局域网调用">
                在系统安全里开启“允许局域网请求”，再让服务监听可被局域网访问的地址。
              </el-descriptions-item>
              <el-descriptions-item label="公网调用">
                在系统安全里开启“允许公网请求”，并建议只通过 HTTPS 反向代理暴露。
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </section>

        <section v-else-if="activeMenu === 'security'" class="stack">
          <el-card shadow="never">
            <template #header>系统安全说明</template>
            <el-alert type="warning" show-icon :closable="false">
              <template #title>
                管理台只负责配置和授权，不负责暴露公网。部署到公网前，请在反向代理层启用 HTTPS 和访问控制。
              </template>
            </el-alert>
          </el-card>
          <el-card shadow="never">
            <template #header>访问来源</template>
            <div class="security-switch-list">
              <div class="security-switch-row">
                <div>
                  <div class="security-switch-title">允许局域网请求</div>
                  <div class="security-switch-desc">
                    允许 10.x、172.16-31.x、192.168.x、局域网 IPv6 等私有网段访问对外 API。
                  </div>
                </div>
                <el-switch
                  :model-value="configBool('ALLOW_LAN_ACCESS')"
                  active-text="允许"
                  inactive-text="关闭"
                  inline-prompt
                  @change="(value: string | number | boolean) => setRuntimeSwitch('ALLOW_LAN_ACCESS', value)"
                />
              </div>
              <div class="security-switch-row danger">
                <div>
                  <div class="security-switch-title">允许公网请求</div>
                  <div class="security-switch-desc">
                    允许公网客户端访问对外 API。开启前请确认 API Key 权限、HTTPS、反向代理和防火墙策略。
                  </div>
                </div>
                <el-switch
                  :model-value="configBool('ALLOW_PUBLIC_ACCESS')"
                  active-text="允许"
                  inactive-text="关闭"
                  inline-prompt
                  @change="(value: string | number | boolean) => setRuntimeSwitch('ALLOW_PUBLIC_ACCESS', value)"
                />
              </div>
              <div class="security-switch-row">
                <div>
                  <div class="security-switch-title">反向代理模式</div>
                  <div class="security-switch-desc">
                    信任来自可信代理的 X-Forwarded-For / X-Real-IP，再按真实客户端来源判断访问权限。
                  </div>
                </div>
                <el-switch
                  :model-value="configBool('TRUST_PROXY_HEADERS', true)"
                  active-text="开启"
                  inactive-text="关闭"
                  inline-prompt
                  @change="(value: string | number | boolean) => setRuntimeSwitch('TRUST_PROXY_HEADERS', value)"
                />
              </div>
              <div class="proxy-config">
                <div>
                  <div class="security-switch-title">可信代理地址</div>
                  <div class="security-switch-desc">
                    每行一个 IP 或 CIDR。只有这些代理传来的转发头会被采用。
                  </div>
                </div>
                <el-input
                  v-model="proxyCidrs"
                  type="textarea"
                  :rows="4"
                  placeholder="127.0.0.1/32&#10;::1/128&#10;192.168.1.10/32"
                />
                <div class="proxy-config-actions">
                  <el-button @click="syncProxyCidrsForm">还原</el-button>
                  <el-button type="primary" @click="saveTrustedProxyCidrs">保存可信代理</el-button>
                </div>
              </div>
            </div>
            <el-alert class="security-hint" type="info" show-icon :closable="false">
              <template #title>
                如果服务启动时仍监听 127.0.0.1，外部机器无法连进来。需要用
                MIJIA_SERVER_HOST=0.0.0.0 重启服务，或由反向代理转发到本服务。
              </template>
            </el-alert>
          </el-card>
          <el-card shadow="never">
            <template #header>API 文档</template>
            <div class="security-switch-list">
              <div class="security-switch-row">
                <div>
                  <div class="security-switch-title">启用交互式文档</div>
                  <div class="security-switch-desc">
                    开启 Swagger UI 与 ReDoc。开启后会同步允许文档页面加载 OpenAPI JSON。
                  </div>
                </div>
                <el-switch
                  :model-value="configBool('DOCS_ENABLED')"
                  active-text="开启"
                  inactive-text="关闭"
                  inline-prompt
                  @change="(value: string | number | boolean) => setRuntimeSwitch('DOCS_ENABLED', value)"
                />
              </div>
              <div class="security-switch-row">
                <div>
                  <div class="security-switch-title">开放 OpenAPI JSON</div>
                  <div class="security-switch-desc">
                    单独开放 /api/v1/openapi.json，方便工具或 Agent 读取接口定义；不会放开业务 API 访问来源。
                  </div>
                </div>
                <el-switch
                  :model-value="configBool('OPENAPI_ENABLED')"
                  active-text="开启"
                  inactive-text="关闭"
                  inline-prompt
                  @change="(value: string | number | boolean) => setRuntimeSwitch('OPENAPI_ENABLED', value)"
                />
              </div>
            </div>
          </el-card>
          <el-table :data="securityRows" border>
            <el-table-column prop="item" label="项目" width="160" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag type="success" effect="light">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="说明" />
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
          <el-empty description="暂未配置页面" />
        </section>
      </el-main>
    </el-container>
  </el-container>
</template>
