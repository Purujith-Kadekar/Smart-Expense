import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../api/client.js";

// Register page — plain form. On submit, calls POST /api/register, stores
// the returned JWT (register returns a token immediately so the user is
// logged in without a separate /login call), and calls the parent's
// onLogin callback so the header updates immediately.
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

    // Client-side password match check — the backend can't catch this
    // because it only receives one password field.
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
    <div className="max-w-md mx-auto">
      <h2 className="text-2xl font-semibold text-slate-900 mb-6">
        Create an account
      </h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Password
          </label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="new-password"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <p className="text-xs text-slate-400 mt-1">At least 8 characters.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Confirm password
          </label>
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            autoComplete="new-password"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>
        {error && (
          <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-md p-2">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={loading}
          className="w-full px-4 py-2 bg-brand-600 text-white rounded-md hover:bg-brand-700 disabled:opacity-60 transition-colors"
        >
          {loading ? "Creating account…" : "Register"}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-600">
        Already have an account?{" "}
        <Link to="/login" className="text-brand-700 hover:underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
