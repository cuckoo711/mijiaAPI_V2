const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const ts = require("typescript");
const vue = require("vue");
const { parse, compileScript } = require("@vue/compiler-sfc");

const root = path.resolve(__dirname, "..");
const expiry = () => new Date(Date.now() + 3_600_000).toISOString();
const reply = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};
const settle = () => new Promise((resolve) => setImmediate(resolve));

/** Run the actual TS/SFC script with isolated browser I/O; no generated files. */
function harness(fetchImpl = async () => reply({ items: [] })) {
  const storage = new Map([["mijia_admin_expires_at", expiry()]]);
  const timers = new Map();
  const calls = [];
  const messages = [];
  let timerId = 0;
  const context = vm.createContext({
    console, Error, Headers, Date, Promise,
    ElMessage: Object.fromEntries(["success", "warning", "error", "info"].map((kind) => [kind, (message) => messages.push({ kind, message })])),
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    document: { cookie: "mijia_csrf=test-csrf" },
    window: {
      location: { origin: "http://localhost", hash: "" },
      setTimeout(fn, delay) { timers.set(++timerId, { fn, delay }); return timerId; },
      clearTimeout(id) { timers.delete(id); },
      addEventListener() {}, removeEventListener() {},
    },
    fetch: async (url, options) => { calls.push({ url, options }); return fetchImpl(url, options); },
  });
  const cache = new Map();
  function load(file) {
    const absolute = path.resolve(root, file);
    if (cache.has(absolute)) return cache.get(absolute).exports;
    const module = { exports: {} };
    cache.set(absolute, module);
    let source = fs.readFileSync(absolute, "utf8");
    if (absolute.endsWith(".vue")) {
      source = compileScript(parse(source).descriptor, { id: path.basename(absolute) }).content;
    }
    const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
    const requireModule = (specifier) => {
      if (specifier === "vue") return { ...vue, onMounted() {}, onBeforeUnmount() {} };
      if (specifier === "element-plus") return { ElMessageBox: { confirm: async () => {} } };
      if (specifier === "@element-plus/icons-vue") return {};
      if (specifier.endsWith(".vue")) return {};
      if (specifier.startsWith(".")) {
        const target = path.resolve(path.dirname(absolute), specifier);
        return load(fs.existsSync(target) ? target : `${target}.ts`);
      }
      return require(specifier);
    };
    vm.runInContext(`(function(require,module,exports){${code}\n})`, context)(requireModule, module, module.exports);
    return module.exports;
  }
  function component(file, props = {}) {
    const emissions = [];
    const setup = load(file).default.setup(props, { expose() {}, emit: (...args) => emissions.push(args) });
    return { setup, emissions };
  }
  async function tick() {
    const entry = timers.entries().next().value;
    assert.ok(entry, "expected a scheduled poll");
    timers.delete(entry[0]);
    entry[1].fn();
    await settle();
  }
  return { load, component, calls, messages, timers, storage, context, tick };
}

function progress(status = "running", taskId = "task-1") {
  return { task_id: taskId, status, step: "同步", progress: status === "completed" ? 100 : 20, current_home: "", homes_total: 1, homes_processed: 1, devices_found: 2, scenes_found: 3, warnings: [], started_at: "", updated_at: "", completed_at: null, error: null };
}

test("logout failure keeps the authenticated session and can be retried", async () => {
  let offline = true;
  const h = harness(async () => {
    if (offline) throw new Error("offline");
    return reply({ status: "ok" });
  });
  const session = h.load("src/composables/useAdminSession.ts").useAdminSession();
  await assert.rejects(session.logout(), /offline/);
  assert.equal(session.isAuthed.value, true);
  assert.ok(h.storage.has("mijia_admin_expires_at"));
  assert.equal(session.loggingOut.value, false);
  offline = false;
  await session.logout();
  assert.equal(session.isAuthed.value, false);
  assert.equal(h.storage.has("mijia_admin_expires_at"), false);
});

test("logout waits for a pending refresh before revoking and blocks another refresh", async () => {
  const waiting = deferred();
  const h = harness(async (url) => url.endsWith("/refresh") ? waiting.promise : reply({ status: "ok" }));
  const session = h.load("src/composables/useAdminSession.ts").useAdminSession();
  const refresh = session.refreshAdminSession();
  await settle();
  const logout = session.logout();
  assert.equal(await session.refreshAdminSession(), false);
  assert.equal(h.calls.length, 1);
  waiting.resolve(reply({ expires_at: expiry() }));
  await Promise.all([refresh, logout]);
  assert.deepEqual(h.calls.map((call) => call.url), ["/api/admin/auth/refresh", "/api/admin/auth/logout"]);
  assert.equal(session.isAuthed.value, false);
  assert.equal(h.timers.size, 0);
});

test("request explains 422 fields and clears stale UI when the cookie is missing", async () => {
  const h = harness(async (url) => url.endsWith("/devices")
    ? reply({ detail: "Missing bearer token" }, 401)
    : reply({ detail: [{ loc: ["body", "name"], msg: "String should have at least 1 character" }] }, 422));
  const session = h.load("src/composables/useAdminSession.ts").useAdminSession();
  await assert.rejects(session.request("/api/admin/api-keys", { method: "POST" }), /name: String should have at least 1 character/);
  await assert.rejects(session.request("/api/admin/devices"), /Missing bearer token/);
  assert.equal(session.isAuthed.value, false);
});

test("request displays fields from the server's standard INVALID_REQUEST issues envelope", async () => {
  const issues = [
    { loc: ["body", "scopes", 0], message: "Input should be 'read:status' or 'read:devices'", type: "literal_error" },
    { loc: ["body", "expires_at"], message: "Input should be a valid datetime", type: "datetime_from_date_parsing" },
  ];
  const h = harness(async () => reply({ error: { code: "INVALID_REQUEST", message: "请求参数无效", details: { issues }, request_id: "test-request" } }, 422));
  const session = h.load("src/composables/useAdminSession.ts").useAdminSession();
  await assert.rejects(session.request("/api/admin/api-keys", { method: "POST" }), (error) => {
    assert.equal(error.code, "INVALID_REQUEST");
    assert.match(error.message, /scopes\.0: Input should be/);
    assert.match(error.message, /expires_at: Input should be a valid datetime/);
    assert.equal(error.details.issues.length, 2);
    return true;
  });
  assert.equal(session.isAuthed.value, true);
});

test("unknown control outcome retains retry_safe=false and is never replayed", async () => {
  const h = harness(async () => reply({ error: { code: "EXECUTION_UNKNOWN", message: "请先查询设备状态，勿直接重试", details: { outcome: "unknown", retry_safe: false } } }, 409));
  const session = h.load("src/composables/useAdminSession.ts").useAdminSession();
  await assert.rejects(session.request("/api/v1/devices/test/action", { method: "POST" }), (error) => {
    assert.equal(error.code, "EXECUTION_UNKNOWN");
    assert.equal(error.details.retry_safe, false);
    return true;
  });
  assert.equal(h.calls.length, 1);
});

test("expired Mijia credentials show their recovery message without logging the admin out", async () => {
  const h = harness(async () => reply({ error: { code: "MIJIA_AUTH_FAILED", message: "米家凭据已过期，请重新扫码登录" } }, 401));
  const session = h.load("src/composables/useAdminSession.ts").useAdminSession();
  await assert.rejects(session.request("/api/admin/mijia/credential/refresh", { method: "POST" }), /重新扫码登录/);
  assert.equal(session.isAuthed.value, true);
  assert.ok(h.storage.has("mijia_admin_expires_at"));
});

test("API Key form sends restricted IDs and a UTC expiry, rejects an empty restriction", () => {
  const h = harness();
  const { createKeyPayload, futureExpiry } = h.load("src/utils/apiKeyForm.ts");
  const form = { name: " app ", scopes: ["read:devices"], policy: { homes: ["home-1"], devices: ["device-1"], scenes: [] }, unrestricted: { homes: false, devices: false, scenes: true }, expiresAt: "2099-01-01T10:00" };
  const payload = createKeyPayload(form);
  assert.equal(payload.name, "app");
  assert.deepEqual(Array.from(payload.resource_policy.devices), ["device-1"]);
  assert.ok(payload.expires_at.endsWith("Z"));
  form.policy.devices = [];
  assert.throws(() => createKeyPayload(form), /至少选择一个资源/);
  assert.throws(() => futureExpiry("2000-01-01T00:00"), /晚于当前时间/);
});

test("Key and config views keep entered values until a successful creation", () => {
  const h = harness();
  const keyView = h.component("src/views/ApiKeysView.vue", { oneTimeApiKey: "", apiKeys: [], homes: [], devices: [], scenes: [], creating: false, busyKeyId: "" });
  keyView.setup.keyForm.name = "integration";
  keyView.setup.onCreate();
  assert.equal(keyView.emissions[0][0], "create");
  assert.equal(keyView.emissions[0][1].name, "integration");
  assert.equal(keyView.setup.keyForm.name, "integration");
  const configView = h.component("src/views/SettingsView.vue", { configs: [], saving: false });
  configView.setup.configForm.value = "https://example.com";
  configView.setup.onSave();
  assert.equal(configView.setup.configForm.value, "https://example.com");
});

test("App exposes working Key status, delete and atomic rotate actions", async () => {
  const h = harness(async (url, options) => {
    if (url.endsWith("/rotate")) return reply({ key: "new-plaintext" });
    if (options?.method === "PATCH") return reply({ is_active: false });
    return reply({ items: [] });
  });
  h.storage.clear(); // Avoid unrelated list requests: these actions test their own contracts.
  const app = h.component("src/App.vue").setup;
  const key = { id: "key-1", name: "app", scopes: ["read:devices"], is_active: true };
  await app.setApiKeyStatus(key, false);
  assert.equal(key.is_active, false);
  await app.rotateApiKey(key, { expires_at: null });
  assert.equal(app.oneTimeApiKey.value, "new-plaintext");
  await app.deleteApiKey(key);
  assert.deepEqual(h.calls.map((call) => [call.url, call.options.method]), [
    ["/api/admin/api-keys/key-1", "PATCH"],
    ["/api/admin/api-keys/key-1/rotate", "POST"],
    ["/api/admin/api-keys/key-1", "DELETE"],
  ]);
});

test("App mutation failure is shown and rolls back a permission switch without saving an edited slug", async () => {
  const h = harness(async () => reply({ error: { code: "FORBIDDEN", message: "permission denied" } }, 403));
  const app = h.component("src/App.vue").setup;
  const device = { id: "device-1", access_mode: "write", slug: "unsaved-edit" };
  await app.autoSaveDeviceAccess(device, "write");
  assert.equal(device.access_mode, "read");
  assert.equal(device.slug, "unsaved-edit");
  assert.deepEqual(JSON.parse(h.calls[0].options.body), { access_mode: "write" });
  assert.ok(h.messages.some((item) => item.kind === "error" && item.message === "permission denied"));
  assert.equal(app.pendingDeviceIds.value.length, 0);
});

test("App keeps a successful permission write when only list refresh fails", async () => {
  const h = harness(async (_url, options) => options.method === "PATCH" ? reply({}) : reply({ error: { message: "refresh failed" } }, 500));
  const app = h.component("src/App.vue").setup;
  const device = { id: "device-1", access_mode: "write" };
  await app.autoSaveDeviceAccess(device, "write");
  assert.equal(device.access_mode, "write");
  assert.ok(h.messages.some((item) => item.kind === "warning" && item.message.includes("操作已成功")));
});

test("reload restores an active sync and eventually refreshes the list once", async () => {
  const h = harness();
  let completed = false;
  let reloads = 0;
  const sync = h.load("src/composables/useSyncProgress.ts").useSyncProgress({ request: async () => progress(completed ? "completed" : "running"), onCompleted: async () => { reloads += 1; } });
  assert.equal(await sync.resumeSyncProgress(), true);
  assert.equal(sync.syncing.value, true);
  completed = true;
  await h.tick();
  assert.equal(sync.syncing.value, false);
  assert.equal(reloads, 1);
  assert.equal(h.timers.size, 0);
  await sync.resumeSyncProgress();
  assert.equal(reloads, 1);
});

test("409 sync conflict attaches the existing task without another start request", async () => {
  const h = harness();
  const { ApiRequestError } = h.load("src/composables/useAdminSession.ts");
  const calls = [];
  const sync = h.load("src/composables/useSyncProgress.ts").useSyncProgress({ request: async (url) => { calls.push(url); if (url.endsWith("/sync")) throw new ApiRequestError("busy", 409, "SYNC_IN_PROGRESS"); return progress("running", "existing"); }, onCompleted: async () => {} });
  await sync.syncMijia();
  assert.equal(sync.syncProgress.value.task_id, "existing");
  assert.equal(sync.syncing.value, true);
  assert.deepEqual(calls, ["/api/admin/sync", "/api/admin/sync/progress"]);
});

test("sync polling surfaces a transient error then clears it on retry", async () => {
  const h = harness();
  let offline = false;
  const sync = h.load("src/composables/useSyncProgress.ts").useSyncProgress({ request: async () => { if (offline) throw new Error("offline"); return progress(); }, onCompleted: async () => {} });
  await sync.resumeSyncProgress();
  offline = true;
  await h.tick();
  assert.match(sync.syncError.value, /offline/);
  assert.equal(sync.syncing.value, true);
  offline = false;
  await sync.resumeSyncProgress();
  assert.equal(sync.syncError.value, "");
  assert.equal(h.timers.size, 1);
});

test("sync idle after a server restart ends polling and permits retry", async () => {
  const h = harness();
  let idle = false;
  const sync = h.load("src/composables/useSyncProgress.ts").useSyncProgress({ request: async () => idle ? { status: "idle" } : progress(), onCompleted: async () => {} });
  await sync.resumeSyncProgress();
  idle = true;
  await h.tick();
  assert.equal(sync.syncing.value, false);
  assert.match(sync.syncError.value, /任务已失效/);
  assert.equal(h.timers.size, 0);
});

test("stopping sync while the start response is pending ignores the late response", async () => {
  const h = harness();
  const waiting = deferred();
  const sync = h.load("src/composables/useSyncProgress.ts").useSyncProgress({ request: async () => waiting.promise, onCompleted: async () => {} });
  const start = sync.syncMijia();
  sync.stopSyncPolling();
  waiting.resolve({ status: "started", task_id: "late" });
  await start;
  assert.equal(h.timers.size, 0);
});

test("QR start failure is visible and another start succeeds", async () => {
  const h = harness();
  let offline = true;
  const login = h.load("src/composables/useMijiaLogin.ts").useMijiaLogin({ request: async () => { if (offline) throw new Error("offline"); return { id: "job-1", status: "scanning" }; }, onAccountChanged: async () => {} });
  await login.startQrLogin();
  assert.match(login.qrError.value, /offline/);
  assert.equal(h.timers.size, 0);
  offline = false;
  await login.startQrLogin();
  assert.equal(login.qrError.value, "");
  assert.equal(login.qrJob.value.id, "job-1");
  assert.equal(h.timers.size, 1);
});

test("QR canceled and missing tasks stop polling and do not announce success", async () => {
  for (const terminal of ["canceled", "missing"]) {
    const h = harness();
    const { ApiRequestError } = h.load("src/composables/useAdminSession.ts");
    const login = h.load("src/composables/useMijiaLogin.ts").useMijiaLogin({ request: async (url) => { if (url.endsWith("/start")) return { id: "job-1", status: "scanning" }; if (terminal === "missing") throw new ApiRequestError("missing", 404); return { id: "job-1", status: "canceled" }; }, onAccountChanged: async () => { throw new Error("must not run"); } });
    await login.startQrLogin();
    await h.tick();
    assert.equal(login.qrJob.value.status, "canceled");
    assert.equal(h.timers.size, 0);
    assert.ok(!h.messages.some((message) => message.kind === "success"));
  }
});

test("QR account removal ignores a late success poll and clears the task", async () => {
  const h = harness();
  const waiting = deferred();
  let changed = 0;
  const login = h.load("src/composables/useMijiaLogin.ts").useMijiaLogin({ request: async (url) => url.endsWith("/start") ? { id: "job-1", status: "scanning" } : url.endsWith("/credential") ? undefined : waiting.promise, onAccountChanged: async () => { changed += 1; } });
  await login.startQrLogin();
  const poll = login.pollQrLogin();
  await login.deleteCredential();
  waiting.resolve({ id: "job-1", status: "success" });
  await poll;
  assert.equal(login.qrJob.value, null);
  assert.equal(changed, 1);
  assert.equal(h.timers.size, 0);
  assert.ok(!h.messages.some((message) => message.message === "米家登录成功"));
});
