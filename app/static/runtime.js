// Pages uses saved JSON and query routes; FastAPI keeps its existing URLs.
export const staticDemo = document.querySelector('meta[name="static-demo"]') !== null;
const base = new URL("../", import.meta.url);
export function apiURL(path) {
  if (!staticDemo) return path;
  return new URL(path.slice(1) + (path.endsWith(".zip") ? "" : ".json"), base).href;
}
export function routeURL(page) {
  const url = new URL(staticDemo ? base : "/" + page, location.origin);
  if (staticDemo && page !== "planner") url.searchParams.set("page", page);
  return url;
}
