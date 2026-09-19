import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../api/client.js";

// Liquid Glass Register page.
//
// Logic is identical to the original:
//   - client-side password match check
//   - min 8 char length check
//   - POST /api/register, store JWT/user_id/email on success, call onLogin()
//   - map known backend error codes to user-facing messages

export default function Register({ onLogin }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setLoading(true);
    try {
      const { data } = await api.post("/register", { email, password });
      localStorage.setItem("token", data.token);
      localStorage.setItem("user_id", data.user_id);
      localStorage.setItem("email", data.email);
      if (onLogin) onLogin();
      else navigate("/dashboard");
    } catch (err) {
      const code = err?.response?.data?.error;
      if (code === "email_already_registered") {
        setError("An account with this email already exists. Try logging in.");
      } else if (code === "invalid_email") {
        setError("Please enter a valid email address.");
      } else if (code === "password_too_short") {
        setError("Password must be at least 8 characters.");
      } else {
        setError(err?.response?.data?.error || err?.error || "Registration failed.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center py-10 px-2 animate-fade-in">
      <div className="w-full max-w-md">
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

          <p className="eyebrow mb-1.5">Get started</p>
          <h2 className="text-2xl font-bold text-ink-900 tracking-tight mb-1">
            Create an account
          </h2>
          <p className="text-sm text-ink-500 mb-6">
            Upload your first receipt in under a minute.
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
                autoComplete="new-password"
                placeholder="At least 8 characters"
                className="input-glass"
              />
              <p className="text-xs text-ink-400 mt-1.5 flex items-center gap-1">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                  strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 16v-4M12 8h.01" />
                </svg>
                Use at least 8 characters.
              </p>
            </div>
            <div>
              <label htmlFor="confirm" className="block text-sm font-medium text-ink-700 mb-1.5">
                Confirm password
              </label>
              <input
                id="confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                autoComplete="new-password"
                placeholder="Re-enter password"
                className="input-glass"
              />
              {/* Inline match hint */}
              {confirm && password !== confirm && (
                <p className="text-xs text-rose-600 mt-1.5 flex items-center gap-1 animate-fade-in">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                    strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                    <circle cx="12" cy="12" r="10" />
                    <path d="M15 9l-6 6M9 9l6 6" />
                  </svg>
                  Passwords don't match yet.
                </p>
              )}
              {confirm && password === confirm && password.length >= 8 && (
                <p className="text-xs text-emerald-600 mt-1.5 flex items-center gap-1 animate-fade-in">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                    strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                  Passwords match.
                </p>
              )}
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
                  Creating account…
                </>
              ) : (
                "Create account"
              )}
            </button>
          </form>

          <p className="mt-5 text-sm text-center text-ink-500">
            Already have an account?{" "}
            <Link to="/login" className="font-semibold text-brand-700 hover:text-brand-600 hover:underline transition-colors">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
