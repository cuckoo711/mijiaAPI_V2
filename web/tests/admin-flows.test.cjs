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

test("API Key expiry presets use submission time and custom expiry cannot be empty or past", () => {
  const { expiryForMode } = harness().load("src/utils/apiKeyForm.ts");
  for (const days of [30, 90, 180]) {
    const before = Date.now();
    const expiry = Date.parse(expiryForMode(String(days), "2000-01-01"));
    const after = Date.now();
    assert.ok(expiry >= before + days * 86_400_000);
    assert.ok(expiry <= after + days * 86_400_000);
  }
  assert.equal(expiryForMode("never", "2099-01-01"), null);
  assert.equal(expiryForMode("inherit", "2099-01-01"), undefined);
  assert.throws(() => expiryForMode("custom", ""), /请选择过期时间/);
  assert.throws(() => expiryForMode("custom", "2000-01-01"), /晚于当前时间/);
});

test("Key create and rotate submit the selected expiry mode without stale custom dates", () => {
  const h = harness();
  const { setup, emissions } = h.component("src/views/ApiKeysView.vue", { oneTimeApiKey: "", apiKeys: [], homes: [], devices: [], scenes: [], creating: false, busyKeyId: "" });
  setup.keyForm.name = "integration";
  setup.createExpiryMode.value = "custom";
  setup.onCreate();
  assert.equal(emissions.length, 0);
  setup.keyForm.expiresAt = "2099-01-01T10:00";
  setup.onCreate();
  assert.equal(emissions[0][1].expires_at, new Date("2099-01-01T10:00").toISOString());
  setup.createExpiryMode.value = "never";
  setup.onCreate();
  assert.equal(emissions[1][1].expires_at, null);
  const key = { id: "key-1", name: "app", expires_at: "2099-01-01T10:00:00Z" };
  setup.openRotate(key);
  setup.onRotate();
  assert.equal(Object.hasOwn(emissions[2][2], "expires_at"), false);
  setup.rotateExpiryMode.value = "90";
  setup.onRotate();
  assert.ok(Date.parse(emissions[3][2].expires_at) > Date.now() + 89 * 86_400_000);
  setup.rotateExpiryMode.value = "never";
  setup.onRotate();
  assert.equal(emissions[4][2].expires_at, null);
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

function deviceFixture(id = "device-1", overrides = {}) {
  return vue.reactive({ id, name: id, display_name: id, model: "test-model", home_id: "home-1", access_mode: "write", hidden: false, ...overrides });
}

function controlSpec() {
  return {
    model: "test-model", name: "Test device",
    properties: [
      { siid: 2, piid: 1, name: "power", type: "bool", access: "read_write" },
      { siid: 2, piid: 2, name: "level", type: "uint", access: "write", value_range: [0, 10, 2] },
    ],
    actions: [{ siid: 2, aiid: 1, name: "set level", parameters: [
      { piid: 2, name: "level", type: "uint", required: true, value_range: [0, 10, 2] },
      { piid: 3, name: "enabled", type: "bool", required: true },
    ] }],
  };
}

function controlReply(url) {
  if (url.endsWith("/spec")) return reply({ spec: controlSpec() });
  if (url.endsWith("/state")) return reply({ items: [{ siid: 2, piid: 1, value: false, code: 0 }] });
  if (url.endsWith("/actions")) return reply({ result: { code: 0 } });
  return reply({ success: true });
}

function deviceView(h, devices = [deviceFixture()]) {
  const request = h.load("src/composables/useAdminSession.ts").useAdminSession().request;
  return h.component("src/views/DevicesView.vue", { devices, homes: [], syncing: false, pendingIds: [], request }).setup;
}

test("device view reads state/spec on open and writes false only after explicit confirmation with CSRF", async () => {
  const h = harness(async (url) => controlReply(url));
  const device = deviceFixture();
  const view = deviceView(h, [device]);
  await view.openDevice(device);
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 0);
  assert.equal(view.state.value[0].value, false);
  view.draft.value.property = "2.1";
  view.draft.value.propertyValues["2.1"] = "false";
  await view.writeProperty();
  const writes = h.calls.filter((call) => call.options.method === "POST");
  assert.equal(writes.length, 1);
  assert.equal(writes[0].url, "/api/admin/devices/device-1/properties");
  assert.deepEqual(JSON.parse(writes[0].options.body), { siid: 2, piid: 1, value: false });
  assert.equal(writes[0].options.headers.get("X-CSRF-Token"), "test-csrf");
  assert.equal(view.outcome.value.status, "success");
});

test("state feedback distinguishes acknowledged false/null values from missing values and read errors", () => {
  const h = harness(async (url) => controlReply(url));
  const view = deviceView(h);
  assert.equal(view.stateReadLabel({ code: 0, value: false }), "已读取");
  assert.equal(view.stateReadLabel({ code: 0, value: null }), "已读取");
  assert.equal(view.stateReadLabel({ code: 0 }), "结果未确认");
  assert.equal(view.stateReadLabel({ value: false }), "结果未确认");
  assert.equal(view.stateReadLabel({ code: -1 }), "错误 -1");
  assert.equal(view.displayValue(undefined), "未返回值");
});

test("device forms reject invalid ranges and missing action parameters before any POST", async () => {
  const h = harness(async (url) => controlReply(url));
  const device = deviceFixture();
  const view = deviceView(h, [device]);
  await view.openDevice(device);
  view.draft.value.property = "2.2";
  view.draft.value.propertyValues["2.2"] = "3";
  await view.writeProperty();
  assert.match(view.outcome.value.message, /步长/);
  assert.equal(view.draft.value.propertyValues["2.2"], "3");
  view.chooseAction("2.1");
  view.draft.value.actionValues["2.1"]["2"] = "4";
  await view.callAction();
  assert.match(view.outcome.value.message, /enabled/);
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 0);
});

test("action form sends declared numeric parameter keys and typed values, keeps inputs on failed result", async () => {
  const h = harness(async (url) => url.endsWith("/actions") ? reply({ result: { code: -1 } }) : controlReply(url));
  const device = deviceFixture();
  const view = deviceView(h, [device]);
  await view.openDevice(device);
  view.chooseAction("2.1");
  view.draft.value.actionValues["2.1"] = { "3": "false", "2": "4" };
  await view.callAction();
  const call = h.calls.find((item) => item.options.method === "POST");
  assert.deepEqual(JSON.parse(call.options.body), { siid: 2, aiid: 1, params: { "2": 4, "3": false } });
  assert.equal(view.outcome.value.status, "failed");
  assert.equal(view.draft.value.actionValues["2.1"]["2"], "4");
});

test("read-only, hidden, and revoked device permissions cannot dispatch from the script", async () => {
  for (const override of [{ access_mode: "read" }, { hidden: true }, {}]) {
    const h = harness(async (url) => controlReply(url));
    const device = deviceFixture("device-1", override);
    const view = deviceView(h, [device]);
    await view.openDevice(device);
    view.draft.value.property = "2.1";
    view.draft.value.propertyValues["2.1"] = "true";
    if (!Object.keys(override).length) device.access_mode = "read";
    await view.writeProperty();
    assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 0);
  }
});

test("late state and spec responses for a previous device cannot replace the current selection", async () => {
  const h = harness();
  const waitingState = deferred();
  const waitingSpec = deferred();
  const first = deviceFixture("first"), second = deviceFixture("second");
  const control = h.load("src/composables/useDeviceControl.ts").useDeviceControl({
    getDevice: (id) => [first, second].find((device) => device.id === id),
    request: async (url) => url.includes("/first/")
      ? url.endsWith("/spec") ? waitingSpec.promise : waitingState.promise
      : url.endsWith("/spec") ? { spec: { ...controlSpec(), name: "Second spec" } } : { items: [{ siid: 2, piid: 1, value: "second" }] },
  });
  const openingFirst = control.openDevice(first);
  await control.openDevice(second);
  waitingSpec.resolve({ spec: { ...controlSpec(), name: "First spec" } });
  waitingState.resolve({ items: [{ siid: 2, piid: 1, value: "first" }] });
  await openingFirst;
  assert.equal(control.selectedId.value, "second");
  assert.equal(control.spec.value.name, "Second spec");
  assert.equal(control.state.value[0].value, "second");
});

test("cancel and reopen keep property/action drafts without causing a control request", async () => {
  const h = harness(async (url) => controlReply(url));
  const device = deviceFixture();
  const view = deviceView(h, [device]);
  await view.openDevice(device);
  view.draft.value.property = "2.2";
  view.draft.value.propertyValues["2.2"] = "8";
  view.chooseAction("2.1");
  view.draft.value.actionValues["2.1"] = { "2": "6", "3": "true" };
  view.closeDevice();
  await view.openDevice(device);
  assert.equal(view.draft.value.propertyValues["2.2"], "8");
  assert.equal(view.draft.value.actionValues["2.1"]["2"], "6");
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 0);
});

test("unknown property outcome queries state, keeps draft, and blocks replay until explicit acknowledgement", async () => {
  const h = harness(async (url) => url.endsWith("/properties")
    ? reply({ error: { code: "EXECUTION_UNKNOWN", message: "请求可能已执行，请先核对状态", details: { retry_safe: false } } }, 409)
    : controlReply(url));
  const device = deviceFixture();
  const view = deviceView(h, [device]);
  await view.openDevice(device);
  view.draft.value.property = "2.1";
  view.draft.value.propertyValues["2.1"] = "true";
  await view.writeProperty();
  assert.equal(view.outcome.value.status, "unknown");
  assert.equal(view.canAcknowledge.value, true);
  assert.equal(h.calls.at(-1).url, "/api/admin/devices/device-1/state");
  await view.writeProperty();
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
  assert.equal(view.draft.value.propertyValues["2.1"], "true");
  view.acknowledgeUnknown();
  assert.equal(view.canControl.value, true);
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
});

test("a lost browser control response is unknown, while a 422 validation response remains a failure", async () => {
  for (const lost of [true, false]) {
    const h = harness(async (url) => {
      if (!url.endsWith("/properties")) return controlReply(url);
      if (lost) throw new Error("connection lost");
      return reply({ error: { code: "INVALID_CONTROL_PARAMETERS", message: "属性值无效" } }, 422);
    });
    const device = deviceFixture();
    const view = deviceView(h, [device]);
    await view.openDevice(device);
    view.draft.value.property = "2.1";
    view.draft.value.propertyValues["2.1"] = "false";
    await view.writeProperty();
    assert.equal(view.outcome.value.status, lost ? "unknown" : "failed");
    assert.equal(view.draft.value.propertyValues["2.1"], "false");
    assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
  }
});

test("a pending write stays locked after dialog cancel/reopen and its result does not affect another device", async () => {
  const h = harness();
  const waiting = deferred();
  const first = deviceFixture("first"), second = deviceFixture("second");
  let writes = 0;
  const control = h.load("src/composables/useDeviceControl.ts").useDeviceControl({
    getDevice: (id) => [first, second].find((device) => device.id === id),
    request: async (url, options) => {
      if (options?.method === "POST") { writes += 1; return waiting.promise; }
      return url.endsWith("/spec") ? { spec: controlSpec() } : { items: [] };
    },
  });
  await control.openDevice(first);
  control.draft.value.property = "2.1";
  control.draft.value.propertyValues["2.1"] = "true";
  const writing = control.writeProperty();
  control.closeDevice();
  await control.openDevice(first);
  assert.equal(control.controlBusy.value, true);
  await control.writeProperty();
  assert.equal(writes, 1);
  await control.openDevice(second);
  waiting.resolve({ success: false });
  await writing;
  assert.equal(control.outcome.value, undefined);
  assert.equal(control.selectedId.value, "second");
});

test("device load failures expose a retry path and never dispatch a write without spec", async () => {
  const h = harness();
  let offline = true;
  const device = deviceFixture();
  const control = h.load("src/composables/useDeviceControl.ts").useDeviceControl({ getDevice: () => device, request: async (url) => {
    if (offline) throw new Error("offline");
    return url.endsWith("/spec") ? { spec: controlSpec() } : { items: [] };
  } });
  await control.openDevice(device);
  assert.match(control.loadError.value, /offline/);
  assert.match(control.stateError.value, /offline/);
  assert.equal(control.canControl.value, false);
  offline = false;
  await Promise.all([control.refreshSpec(), control.refreshState()]);
  assert.equal(control.loadError.value, "");
  assert.equal(control.stateError.value, "");
  assert.equal(control.canControl.value, true);
});

test("scene view requires an explicit execute click and retains unknown results without automatic replays", async () => {
  const h = harness(async () => reply({ error: { code: "EXECUTION_UNKNOWN", message: "场景结果未知，请先核对状态" } }, 409));
  const scene = vue.reactive({ id: "scene-1", scene_id: "remote-1", name: "Evening", home_id: "home-1", executable: true, hidden: false });
  const request = h.load("src/composables/useAdminSession.ts").useAdminSession().request;
  const view = h.component("src/views/ScenesView.vue", { scenes: [scene], homes: [], apiBaseUrl: "", oneTimeApiKey: "", pendingIds: [], request }).setup;
  view.openScene(scene);
  assert.equal(h.calls.length, 0);
  await view.executeScene();
  assert.equal(h.calls[0].url, "/api/admin/scenes/scene-1/execute");
  assert.equal(view.outcome.value.status, "unknown");
  await view.executeScene();
  view.closeScene();
  view.openScene(scene);
  await view.executeScene();
  assert.equal(h.calls.length, 1);
  view.acknowledgeUnknown();
  assert.equal(h.calls.length, 1);
  assert.equal(view.canExecute.value, true);
});

test("scene authorization is rechecked and late execution results stay with their original scene", async () => {
  const h = harness();
  const waiting = deferred();
  const first = vue.reactive({ id: "first", executable: true, hidden: false });
  const second = vue.reactive({ id: "second", executable: false, hidden: false });
  let calls = 0;
  const control = h.load("src/composables/useSceneControl.ts").useSceneControl({ getScene: (id) => [first, second].find((scene) => scene.id === id), request: async () => { calls += 1; return waiting.promise; } });
  control.openScene(first);
  const running = control.executeScene();
  control.openScene(second);
  await control.executeScene();
  waiting.resolve({ success: true });
  await running;
  assert.equal(calls, 1);
  assert.equal(control.outcome.value, undefined);
  control.openScene(first);
  assert.equal(control.outcome.value.status, "success");
  first.executable = false;
  await control.executeScene();
  assert.equal(calls, 1);
});

test("navigation memory preserves unresolved results and drafts across recreated views", async () => {
  const h = harness();
  const { useDeviceControl, createDeviceControlMemory } = h.load("src/composables/useDeviceControl.ts");
  const memory = createDeviceControlMemory();
  const device = deviceFixture();
  const request = async (url, options) => options?.method === "POST" ? {} : url.endsWith("/spec") ? { spec: controlSpec() } : { items: [] };
  const original = useDeviceControl({ request, getDevice: () => device, memory });
  await original.openDevice(device);
  original.draft.value.property = "2.1";
  original.draft.value.propertyValues["2.1"] = "true";
  await original.writeProperty();
  original.closeDevice();
  const recreated = useDeviceControl({ request, getDevice: () => device, memory });
  await recreated.openDevice(device);
  assert.equal(recreated.draft.value.propertyValues["2.1"], "true");
  assert.equal(recreated.outcome.value.status, "unknown");
  assert.equal(recreated.canControl.value, false);
});

test("audit view distinguishes unknown/warning results and keeps metadata as inert text until expansion", () => {
  const h = harness();
  const view = h.component("src/views/AuditView.vue", { audits: [], health: { pending: 1, invalid: 0, unavailable: 0 }, loading: false, replaying: false, error: "" }).setup;
  assert.equal(view.resultLabel("success"), "成功");
  assert.equal(view.resultLabel("failed"), "失败");
  assert.equal(view.resultLabel("unknown"), "结果未知");
  assert.equal(view.resultType("unknown"), "warning");
  assert.equal(view.resultType("failed"), "danger");
  assert.match(view.resultLabel("warning"), /警告/);
  const metadata = { operation_id: "op-1", payload: '<img src=x onerror="bad()">' };
  const text = view.metadataText(metadata);
  assert.deepEqual(JSON.parse(text), metadata);
  assert.equal(h.calls.length, 0);
});

test("audit replay requires an explicit call, sends CSRF, prevents duplicate clicks, and refreshes queue health", async () => {
  const waiting = deferred();
  const h = harness(async (url) => {
    if (url.endsWith("/replay")) return waiting.promise;
    if (url.endsWith("/health")) return reply({ pending: 0, invalid: 0, unavailable: 0 });
    return reply({ items: [{ id: "audit-1", result: "unknown", request_id: "request-1" }] });
  });
  const app = h.component("src/App.vue").setup;
  assert.equal(h.calls.length, 0);
  const replay = app.replayAudit();
  await settle();
  await app.replayAudit();
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 1);
  assert.equal(h.calls[0].options.headers.get("X-CSRF-Token"), "test-csrf");
  waiting.resolve(reply({ delivered: 2, pending: 0, invalid: 0, unavailable: 0 }));
  await replay;
  assert.equal(app.auditReplaying.value, false);
  assert.equal(app.auditHealth.value.pending, 0);
  assert.equal(app.audits.value[0].request_id, "request-1");
  assert.ok(h.messages.some((message) => message.kind === "success" && message.message.includes("已补写 2 条")));
});

test("audit replay failure is visible and can be explicitly retried without an automatic POST", async () => {
  let offline = true;
  const h = harness(async (url) => {
    if (url.endsWith("/replay")) {
      if (offline) throw new Error("offline");
      return reply({ delivered: 1, pending: 0, invalid: 0, unavailable: 0 });
    }
    return url.endsWith("/health") ? reply({ pending: 0, invalid: 0, unavailable: 0 }) : reply({ items: [] });
  });
  const app = h.component("src/App.vue").setup;
  await app.replayAudit();
  assert.match(app.auditError.value, /offline/);
  assert.equal(app.auditReplaying.value, false);
  assert.equal(h.calls.length, 1);
  offline = false;
  await app.replayAudit();
  assert.equal(app.auditError.value, "");
  assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 2);
});

test("historical unavailable audit events do not prevent replay of existing pending records", async () => {
  let deliveries = 0;
  const h = harness(async (url) => {
    if (url.endsWith("/replay")) { deliveries += 1; return reply({ delivered: 1, pending: 0, invalid: 0, unavailable: 2 }); }
    if (url.endsWith("/health")) return reply({ pending: 0, invalid: 0, unavailable: 2 });
    return reply({ items: [] });
  });
  const app = h.component("src/App.vue").setup;
  app.auditHealth.value = { pending: 1, invalid: 0, unavailable: 2 };
  await app.replayAudit();
  assert.equal(app.auditError.value, "");
  assert.equal(app.auditHealth.value.unavailable, 2);
  assert.equal(app.auditHealth.value.pending, 0);
  assert.ok(h.messages.some((message) => message.kind === "warning" && message.message.includes("历史未能保存 2 条")));
  assert.ok(!h.messages.some((message) => message.kind === "success"));
  await app.replayAudit();
  assert.equal(deliveries, 2);
});

test("logout clears audit queue state and a late audit read cannot repopulate it", async () => {
  const records = deferred(), queue = deferred();
  const h = harness(async (url) => url.endsWith("/logout") ? reply({ status: "ok" }) : url.endsWith("/health") ? queue.promise : records.promise);
  const app = h.component("src/App.vue").setup;
  app.auditHealth.value = { pending: 2, invalid: 1, unavailable: 0 };
  app.auditError.value = "previous error";
  const refresh = app.refreshAuditPage();
  await settle();
  await app.logout();
  await vue.nextTick();
  records.resolve(reply({ items: [{ id: "old-audit" }] }));
  queue.resolve(reply({ pending: 2, invalid: 1, unavailable: 0 }));
  await refresh;
  assert.equal(app.auditHealth.value, null);
  assert.equal(app.auditError.value, "");
  assert.equal(app.audits.value.length, 0);
  assert.equal(app.auditLoading.value, false);
});
