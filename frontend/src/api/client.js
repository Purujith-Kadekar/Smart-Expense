// Axios instance — base URL comes from Vite env. The Flask backend has
// CORS enabled so we hit it directly (no dev proxy needed).
//
// IMPORTANT: the baseURL must include the `/api` prefix because every
// route on the Flask side is registered under `/api/*` (see app.py
// `app.register_blueprint(..., url_prefix="/api")`). If the prefix is
// missing here, axios calls `/expenses` instead of `/api/expenses` →
// Flask returns 404 → flask-cors doesn't add an ACAO header to the 404
// (the resource pattern only matches `/api/*`) → the browser reports a
// misleading "CORS error" instead of the real 404. This is the #1 thing
// to check when you see "No 'Access-Control-Allow-Origin' header".
//
// Cross-origin gotchas to be aware of:
// 1. The Flask backend must include the React dev server origin in
//    ALLOWED_ORIGINS (or fall back to `*` when ALLOWED_ORIGINS is empty).
// 2. S3 itself must have CORS configured on the receipts bucket —
//    otherwise the PUT to the presigned URL fails silently in the
//    browser. localstack/init.py applies that CORS policy at startup.
// 3. When CORS is misconfigured, axios throws a `Network Error` with
//    no response body. The interceptor below translates that into a
//    user-facing hint pointing at the most likely cause.
//
// Auth: every request (except /login and /register) must carry an
// `Authorization: Bearer <token>` header. The request interceptor below
// attaches it automatically from localStorage. On 401, the response
// interceptor clears the token and redirects to /login.
import axios from "axios";

const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api";

// Defensive: if the user sets VITE_API_BASE_URL without the `/api` suffix
// (e.g. just `http://localhost:5000`), append it automatically. This
// prevents the misleading "CORS error" that actually means "404 from a
// URL missing the /api prefix".
const ensureApiPrefix = (url) => {
  if (!url) return url;
  // Strip any trailing slash so we don't end up with `//api`.
  const trimmed = url.replace(/\/+$/, "");
  if (trimmed.endsWith("/api")) return trimmed;
  return `${trimmed}/api`;
};

const finalBaseURL = ensureApiPrefix(baseURL);

const api = axios.create({
  baseURL: finalBaseURL,
  headers: { "Content-Type": "application/json" },
  // 30s — S3 presigned URL generation is fast, but the budget-status
  // endpoint scans DynamoDB and can be slower on cold starts.
  timeout: 30000,
  // We don't use cookies — keep credentials off so that wildcard CORS
  // origins (`*`) work. Flip to "include" only if/when we add sessions.
  withCredentials: false,
});

// ---------------------------------------------------------------------------
// Request interceptor — attach Authorization header from localStorage
// ---------------------------------------------------------------------------

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ---------------------------------------------------------------------------
// Response interceptor — handle 401 + translate CORS/network failures
// ---------------------------------------------------------------------------

api.interceptors.response.use(
  (response) => response,
  (error) => {
    // On 401, clear the stored token and redirect to /login. This handles
    // token expiry gracefully — the user gets sent back to login instead
    // of seeing a wall of "Unauthorized" errors on the dashboard.
    if (error.response && error.response.status === 401) {
      // Only redirect if we're not already on a public page (login/register).
      // Avoids a redirect loop if /login itself returns 401 for some reason.
      const path = window.location.pathname;
      if (path !== "/login" && path !== "/register") {
        localStorage.removeItem("token");
        localStorage.removeItem("user_id");
        localStorage.removeItem("email");
        // Use window.location for a hard redirect — simpler than wiring
        // react-router's navigate() into an axios interceptor.
        window.location.href = "/login";
      }
    }

    if (!error.response) {
      // No HTTP response — either the network is down, or (most commonly
      // during local dev) CORS is misconfigured. Re-shape the error so
      // the UI can surface a helpful message instead of "Network Error".
      const isCorsLike =
        error.message === "Network Error" ||
        /origin/i.test(error.message || "");
      const hint = isCorsLike
        ? `CORS or network error reaching ${finalBaseURL}. Check that (1) the Flask backend is running, (2) ALLOWED_ORIGINS includes ${window.location.origin}, and (3) the URL has the /api prefix.`
        : error.message || "Network request failed.";
      return Promise.reject({
        ...error,
        response: null,
        // `error` field is what our pages check for user-facing messages.
        error: hint,
      });
    }
    // Pass server errors through unchanged so pages can show
    // `err.response.data.error` directly.
    return Promise.reject(error);
  }
);

export default api;
