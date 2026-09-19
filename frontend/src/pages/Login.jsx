import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../api/client.js";

// Login page — plain form, no frills. On submit, calls POST /api/login,
// stores the returned JWT in localStorage, and calls the parent's
// onLogin callback so the App-level auth state updates and the header
// re-renders immediately (no manual page refresh needed).
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
      // Tell App to re-read auth state so the header updates, then navigate.
      if (onLogin) onLogin();
      else navigate("/dashboard");
    } catch (err) {
      // The backend returns the same `invalid_credentials` error for both
      // wrong email and wrong password (anti-enumeration). Show a generic
      // message to the user.
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
    <div className="max-w-md mx-auto">
      <h2 className="text-2xl font-semibold text-slate-900 mb-6">Log in</h2>
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
            autoComplete="current-password"
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
          {loading ? "Logging in…" : "Log in"}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-600">
        Don't have an account?{" "}
        <Link to="/register" className="text-brand-700 hover:underline">
          Register
        </Link>
      </p>
    </div>
  );
}
