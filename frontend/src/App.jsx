import { useState, useEffect, useCallback } from "react";
import { Routes, Route, NavLink, Navigate, useNavigate } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Upload from "./pages/Upload.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Settings from "./pages/Settings.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";

const linkBase =
  "px-3 py-2 rounded-md text-sm font-medium transition-colors";
const linkIdle = "text-slate-600 hover:text-brand-700 hover:bg-brand-50";
const linkActive = "bg-brand-50 text-brand-700";

// Wrapper for routes that require authentication. If no token is in
// localStorage, redirect to /login. This is intentionally simple — for
// a real app you'd validate the token (check expiry client-side), but
// for the hackathon the backend's 401 check is the real security gate.
function ProtectedRoute({ children, isLoggedIn }) {
  if (!isLoggedIn) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App() {
  const navigate = useNavigate();

  // Auth state lives here, at the top level, so the header re-renders
  // immediately when login/logout happens — no manual page refresh needed.
  // `isLoggedIn` is derived from whether a token exists in localStorage;
  // `authVersion` is a counter we bump to force re-render even when the
  // token value itself isn't observed directly by React.
  const [authVersion, setAuthVersion] = useState(0);
  const [email, setEmail] = useState(() => localStorage.getItem("email"));

  // Re-read email from localStorage whenever authVersion changes. This
  // keeps the header's "logged in as X" label in sync after login/logout.
  useEffect(() => {
    setEmail(localStorage.getItem("email"));
  }, [authVersion]);

  const isLoggedIn = !!localStorage.getItem("token");

  // Centralised login/logout so every component (header button, Login page,
  // Register page) triggers the same state update. The `bumpAuth` callback
  // forces App to re-render and the header to reflect the new state.
  const handleLogin = useCallback(() => {
    setAuthVersion((v) => v + 1);
    navigate("/dashboard");
  }, [navigate]);

  const handleLogout = useCallback(() => {
    localStorage.removeItem("token");
    localStorage.removeItem("user_id");
    localStorage.removeItem("email");
    setAuthVersion((v) => v + 1);
    navigate("/login");
  }, [navigate]);

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-5xl mx-auto px-4 py-4 flex items-center justify-between">
          {/* Logo — clicking it goes home. */}
          <NavLink to="/" className="flex items-center gap-2 text-slate-900">
            <span className="inline-block w-2 h-2 rounded-full bg-brand-600" />
            <span className="text-lg font-semibold">Outlay</span>
          </NavLink>
          <nav className="flex items-center gap-2">
            <NavLink
              to="/"
              className={({ isActive }) =>
                `${linkBase} ${isActive ? linkActive : linkIdle}`
              }
              end
            >
              Home
            </NavLink>
            {isLoggedIn ? (
              <>
                <NavLink
                  to="/dashboard"
                  className={({ isActive }) =>
                    `${linkBase} ${isActive ? linkActive : linkIdle}`
                  }
                >
                  Dashboard
                </NavLink>
                <NavLink
                  to="/upload"
                  className={({ isActive }) =>
                    `${linkBase} ${isActive ? linkActive : linkIdle}`
                  }
                >
                  Upload
                </NavLink>
                <NavLink
                  to="/settings"
                  className={({ isActive }) =>
                    `${linkBase} ${isActive ? linkActive : linkIdle}`
                  }
                >
                  Settings
                </NavLink>
                <span className="text-xs text-slate-400 px-2 hidden sm:inline">
                  {email}
                </span>
                <button
                  onClick={handleLogout}
                  className="px-3 py-2 rounded-md text-sm font-medium text-slate-600 hover:text-red-700 hover:bg-red-50 transition-colors"
                >
                  Log out
                </button>
              </>
            ) : (
              <>
                <NavLink
                  to="/login"
                  className={({ isActive }) =>
                    `${linkBase} ${isActive ? linkActive : linkIdle}`
                  }
                >
                  Log in
                </NavLink>
                <NavLink
                  to="/register"
                  className={({ isActive }) =>
                    `${linkBase} ${isActive ? linkActive : linkIdle}`
                  }
                >
                  Register
                </NavLink>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 py-8">
        <Routes>
          {/* Public routes — accessible without login. */}
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login onLogin={handleLogin} />} />
          <Route path="/register" element={<Register onLogin={handleLogin} />} />

          {/* Protected routes — redirect to /login if no token. */}
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute isLoggedIn={isLoggedIn}>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/upload"
            element={
              <ProtectedRoute isLoggedIn={isLoggedIn}>
                <Upload />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute isLoggedIn={isLoggedIn}>
                <Settings />
              </ProtectedRoute>
            }
          />

          {/* Fallback — unknown routes go to the landing page. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>

      <footer className="text-center text-xs text-slate-400 py-4">
        Outlay
      </footer>
    </div>
  );
}
