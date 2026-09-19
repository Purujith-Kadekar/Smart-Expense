import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../api/client.js";

// Liquid Glass Login page.
//
// Logic is identical to the original:
//   - POST /api/login with email/password
//   - On success: store token / user_id / email in localStorage, call onLogin()
//   - On error: show user-facing message (anti-enumeration — single
//     "invalid_credentials" code maps to a generic message)
//
// Only visual presentation changed.

export default function Login({ onLogin }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await api.post("/login", { email, password });
      localStorage.setItem("token", data.token);
      localStorage.setItem("user_id", data.user_id);
      localStorage.setItem("email", data.email);
      if (onLogin) onLogin();
      else navigate("/dashboard");
    } catch (err) {
      const code = err?.response?.data?.error;
      if (code === "invalid_credentials") {
        setError("Wrong email or password.");
      } else {
        setError(err?.response?.data?.error || err?.error || "Login failed.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center py-10 px-2 animate-fade-in">
      <div className="w-full max-w-md">
        {/* Auth card */}
        <div className="glass rounded-3xl p-7 sm:p-8 shadow-soft-lg animate-scale-in">
          {/* Header — logo lockup */}
          <div className="flex items-center gap-2.5 mb-6">
            <span className="relative inline-flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-brand overflow-hidden">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5 relative">
                <path d="M4 6.5C4 5.12 5.12 4 6.5 4H17.5C18.88 4 20 5.12 20 6.5V8H4V6.5Z" />
                <path d="M4 8V17.5C4 18.88 5.12 20 6.5 20H17.5C18.88 20 20 18.88 20 17.5V8" />
                <path d="M9 12H15" />
              </svg>
              <span className="absolute inset-x-0 top-0 h-1/2 bg-white/25" />
            </span>
            <span className="text-[17px] font-bold tracking-tight text-ink-900">
              Outlay
            </span>
          </div>

          <p className="eyebrow mb-1.5">Welcome back</p>
          <h2 className="text-2xl font-bold text-ink-900 tracking-tight mb-1">
            Log in to your account
          </h2>
          <p className="text-sm text-ink-500 mb-6">
            Pick up where you left off — your receipts and budget are waiting.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-ink-700 mb-1.5">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                placeholder="you@example.com"
                className="input-glass"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-ink-700 mb-1.5">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                placeholder="••••••••"
                className="input-glass"
              />
            </div>

            {error && (
              <div className="flex items-start gap-2 text-rose-700 text-sm bg-rose-50/70 border border-rose-200/80 rounded-xl p-2.5 animate-fade-in">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                  strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 mt-0.5 shrink-0">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full !py-2.5"
            >
              {loading ? (
                <>
                  <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                  Logging in…
                </>
              ) : (
                "Log in"
              )}
            </button>
          </form>

          <p className="mt-5 text-sm text-center text-ink-500">
            Don't have an account?{" "}
            <Link to="/register" className="font-semibold text-brand-700 hover:text-brand-600 hover:underline transition-colors">
              Register
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
