const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const vue = require("vue");

const root = path.resolve(__dirname, "..");
const settle = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

function setup(readback, access = "read_write") {
  const calls = [];
  const timers = new Map();
  const delays = [];
  let nextTimer = 0, dispatched = false, postReads = 0;
  const context = vm.createContext({ Error, console, window: {
    setTimeout(callback, delay) { delays.push(delay); timers.set(++nextTimer, callback); return nextTimer; },
    clearTimeout(timer) { timers.delete(timer); },
  } });
  const cache = new Map();
  function load(file) {
    const absolute = path.resolve(root, file);
    if (cache.has(absolute)) return cache.get(absolute).exports;
    const module = { exports: {} };
    cache.set(absolute, module);
    const code = ts.transpileModule(fs.readFileSync(absolute, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const requireModule = (name) => name === "vue" ? vue : name.startsWith(".")
      ? load(`${path.resolve(path.dirname(absolute), name)}.ts`)
      : require(name);
    vm.runInContext(`(function(require,module,exports){${code}\n})`, context)(requireModule, module, module.exports);
    return module.exports;
  }
  const records = ["first", "second"].map((id) => vue.reactive({ id, name: id, access_mode: "write", hidden: false }));
  const control = load("src/composables/useDeviceControl.ts").useDeviceControl({
    getDevice: (id) => records.find((device) => device.id === id),
    request: async (url, options) => {
      calls.push({ url, options });
      if (options?.method === "POST") { dispatched = true; return { success: true }; }
      if (url.endsWith("/spec")) return { spec: { properties: [
        { siid: 2, piid: 1, name: "Switch", type: "bool", access },
        { siid: 2, piid: 2, name: "Other", type: "bool", access: "read_write" },
      ], actions: [] } };
      if (!dispatched || url.includes("/second/")) return { items: [{ siid: 2, piid: 1, code: 0, value: true }] };
      return readback(++postReads, load);
    },
  });
  async function open() {
    await control.openDevice(records[0]);
    control.draft.value.property = "2.1";
    control.draft.value.propertyValues["2.1"] = "false";
  }
  async function tick() {
    const timer = timers.entries().next().value;
    assert.ok(timer, "readback must be waiting before the next GET");
    timers.delete(timer[0]);
    timer[1]();
    await settle();
  }
  const posts = () => calls.filter((call) => call.options?.method === "POST");
  return { control, records, calls, timers, delays, open, tick, posts, postReads: () => postReads };
}

test("success ACK with stale state is pending, then one-second GET confirms the frozen typed value", async () => {
  const h = setup(async (attempt) => ({ items: [{ siid: 2, piid: 1, code: 0, value: attempt === 1 }] }));
  await h.open();
  const writing = h.control.writeProperty();
  await settle();
  assert.equal(h.control.outcome.value.status, "unknown");
  assert.match(h.control.outcome.value.message, /已被接受/);
  assert.match(h.control.outcome.value.message, /尚未确认/);
  assert.equal(h.control.controlBusy.value, true);
  assert.equal(h.control.canAcknowledge.value, false);
  // Changing the draft must not change the already dispatched target.
  h.control.draft.value.property = "2.2";
  h.control.draft.value.propertyValues["2.1"] = "true";
  await h.tick();
  await writing;
  assert.equal(h.control.outcome.value.status, "success");
  assert.match(h.control.outcome.value.message, /已读回确认/);
  assert.equal(h.control.state.value[0].value, false);
  assert.deepEqual(h.delays, [1000]);
  assert.equal(h.posts().length, 1);
  assert.deepEqual(JSON.parse(h.posts()[0].options.body), { siid: 2, piid: 1, value: false });
});

test("five stale GETs time out as acknowledged but unconfirmed and never resend POST", async () => {
  const h = setup(async () => ({ items: [{ siid: 2, piid: 1, code: 0, value: true }] }));
  await h.open();
  const writing = h.control.writeProperty();
  await settle();
  for (let attempt = 0; attempt < 4; attempt += 1) await h.tick();
  await writing;
  assert.equal(h.postReads(), 5);
  assert.deepEqual(h.delays, [1000, 1000, 1000, 1000]);
  assert.equal(h.control.outcome.value.status, "unknown");
  assert.match(h.control.outcome.value.message, /已被接受.*5 次.*超时/);
  assert.equal(h.control.requiresVerification.value, true);
  assert.equal(h.control.controlBusy.value, false);
  await h.control.writeProperty();
  assert.equal(h.posts().length, 1);
});

test("explicit property read error or missing value cannot confirm an accepted write", async () => {
  for (const item of [{ siid: 2, piid: 1, code: -704042011 }, { siid: 2, piid: 1, code: 0 }, { siid: 2, piid: 1, value: false }]) {
    const h = setup(async () => ({ items: [item] }));
    await h.open();
    await h.control.writeProperty();
    assert.equal(h.control.outcome.value.status, "unknown");
    assert.match(h.control.outcome.value.message, /已被接受/);
    assert.match(h.control.outcome.value.message, /读取错误|缺少/);
    assert.equal(h.posts().length, 1);
    assert.equal(h.postReads(), 1);
    assert.equal(h.timers.size, 0);
  }
});

test("write-only property retains ACK accepted versus unconfirmed readback without futile polling", async () => {
  const h = setup(async () => ({ items: [] }), "write");
  await h.open();
  await h.control.writeProperty();
  assert.equal(h.control.outcome.value.status, "unknown");
  assert.match(h.control.outcome.value.message, /已被接受.*不可读/);
  assert.equal(h.postReads(), 1); // One refresh of other state, not five target polls.
  assert.equal(h.timers.size, 0);
  assert.equal(h.posts().length, 1);
});

test("failed GET preserves acknowledged write, input and manual verification protection", async () => {
  const h = setup(async () => { throw new Error("read timeout"); });
  await h.open();
  await h.control.writeProperty();
  assert.equal(h.control.outcome.value.status, "unknown");
  assert.match(h.control.outcome.value.message, /已被接受.*状态读取失败/);
  assert.equal(h.control.stateError.value, "read timeout");
  assert.equal(h.control.draft.value.propertyValues["2.1"], "false");
  assert.equal(h.control.canAcknowledge.value, false);
  assert.equal(h.posts().length, 1);
});

test("close during readback delay cancels subsequent GETs and retains an unconfirmed result", async () => {
  const h = setup(async () => ({ items: [{ siid: 2, piid: 1, code: 0, value: true }] }));
  await h.open();
  const writing = h.control.writeProperty();
  await settle();
  h.control.closeDevice();
  await writing;
  assert.equal(h.postReads(), 1);
  assert.equal(h.timers.size, 0);
  assert.equal(h.control.outcome.value.status, "unknown");
  assert.match(h.control.outcome.value.message, /核对已停止/);
  assert.equal(h.posts().length, 1);
});

test("navigation during an in-flight GET ignores a late matching value and does not poll the new device", async () => {
  const waiting = deferred();
  const h = setup(async () => waiting.promise);
  await h.open();
  const writing = h.control.writeProperty();
  await settle();
  await h.control.openDevice(h.records[1]);
  waiting.resolve({ items: [{ siid: 2, piid: 1, code: 0, value: false }] });
  await writing;
  assert.equal(h.control.selectedId.value, "second");
  assert.equal(h.control.outcome.value, undefined);
  assert.equal(h.control.state.value[0].value, true);
  assert.equal(h.postReads(), 1);
  assert.equal(h.posts().length, 1);
  assert.equal(h.timers.size, 0);
});
