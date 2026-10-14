import ResizeObserverPolyfill from "resize-observer-polyfill";

// Older Android WebViews have Proxy (required by Vue) but lack these DOM APIs.
if (typeof window.ResizeObserver === "undefined") {
  window.ResizeObserver = ResizeObserverPolyfill;
}

export function observeMediaQuery(
  query: MediaQueryList,
  listener: (event: MediaQueryListEvent) => void,
): () => void {
  if (typeof query.addEventListener === "function") {
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }
  query.addListener(listener);
  return () => query.removeListener(listener);
}
