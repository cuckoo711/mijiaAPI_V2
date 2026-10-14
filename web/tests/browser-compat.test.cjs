const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const ts = require("typescript");

function load(window) {
  const source = fs.readFileSync(path.resolve(__dirname, "../src/utils/browserCompat.ts"), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
  }).outputText;
  const context = { window, exports: {}, require };
  vm.runInNewContext(compiled, context);
  return context.exports;
}

test("old WebView media queries receive changes and remove the same legacy listener", () => {
  const window = {};
  const { observeMediaQuery } = load(window);
  assert.equal(typeof window.ResizeObserver, "function");
  let registered, removed, matches;
  const query = {
    addListener: (listener) => { registered = listener; },
    removeListener: (listener) => { removed = listener; },
  };
  const dispose = observeMediaQuery(query, (event) => { matches = event.matches; });
  registered({ matches: true });
  assert.equal(matches, true);
  dispose();
  assert.equal(removed, registered);
});

test("modern WebView keeps its native ResizeObserver and event API", () => {
  const native = function ResizeObserver() {};
  const window = { ResizeObserver: native };
  const { observeMediaQuery } = load(window);
  assert.equal(window.ResizeObserver, native);
  const calls = [];
  const listener = () => {};
  const dispose = observeMediaQuery({
    addEventListener: (...args) => calls.push(["add", ...args]),
    removeEventListener: (...args) => calls.push(["remove", ...args]),
  }, listener);
  dispose();
  assert.deepEqual(calls, [["add", "change", listener], ["remove", "change", listener]]);
});
