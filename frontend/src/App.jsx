import { useState, useEffect, useCallback } from "react";
import { Routes, Route, NavLink, Navigate, useNavigate } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Upload from "./pages/Upload.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Settings from "./pages/Settings.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";

// Liquid Glass App shell.
//
// The original auth flow is preserved bit-for-bit:
//   - localStorage token / user_id / email
//   - authVersion counter forces re-render after login/logout
//   - ProtectedRoute redirects to /login when no token
//   - onLogin callback fires from Login/Register pages
//
// Only the visual chrome (header, nav, footer, layout grid) is new.
// Routes, route order, and the fallback '*' → '/' are unchanged.

const linkBase =
  "relative px-3.5 py-2 rounded-lg text-sm font-medium transition-all duration-200 ease-out focus-ring";
const linkIdle =
  "text-ink-600 hover:text-ink-900 hover:bg-white/55";
const linkActive =
  "text-brand-700 bg-white/65 shadow-soft-sm";

// Wrapper for routes that require authentication. If no token is in
// localStorage, redirect to /login. Same logic as the original.
function ProtectedRoute({ children, isLoggedIn }) {
  if (!isLoggedIn) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

// Small inline icon set — kept dependency-free so we don't pull a whole
// icon library. Each icon is a single stroke, sized to match the type ramp.
const Icon = {
  Logo: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M4 6.5C4 5.12 5.12 4 6.5 4H17.5C18.88 4 20 5.12 20 6.5V8H4V6.5Z" />
      <path d="M4 8V17.5C4 18.88 5.12 20 6.5 20H17.5C18.88 20 20 18.88 20 17.5V8" />
      <path d="M9 12H15" />
    </svg>
  ),
  Home: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 11.5L12 4l9 7.5" />
      <path d="M5 10v9a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-9" />
      <path d="M9.5 20v-6h5v6" />
    </svg>
  ),
  Dashboard: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="3" y="3" width="7.5" height="9" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="5" rx="1.5" />
      <rect x="13.5" y="11" width="7.5" height="10" rx="1.5" />
      <rect x="3" y="15" width="7.5" height="6" rx="1.5" />
    </svg>
  ),
  Upload: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M12 16V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M5 16v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3" />
    </svg>
  ),
  Settings: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
    </svg>
  ),
  Logout: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  ),
  Menu: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  ),
  Close: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  ),
};

// Single nav item. The active state shows a small floating dot under the
// label so the active route is unmistakable without being shouty.
function NavItem({ to, end, children, icon: IconComp, mobile, onClick }) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        `${linkBase} ${isActive ? linkActive : linkIdle} ${
          mobile ? "flex items-center gap-2.5 w-full text-left" : "inline-flex items-center gap-1.5"
        }`
      }
    >
      {({ isActive }) => (
        <>
          {IconComp && <IconComp className="w-4 h-4" />}
          <span>{children}</span>
          {isActive && !mobile && (
            <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-brand-600" />
          )}
        </>
      )}
    </NavLink>
  );
}

export default function App() {
  const navigate = useNavigate();

  // Auth state — identical to the original implementation. The authVersion
  // counter is bumped by handleLogin/handleLogout to force re-render even
  // when the underlying token value isn't observed directly by React.
  const [authVersion, setAuthVersion] = useState(0);
  const [email, setEmail] = useState(() => localStorage.getItem("email"));
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    setEmail(localStorage.getItem("email"));
  }, [authVersion]);

  const isLoggedIn = !!localStorage.getItem("token");

  const handleLogin = useCallback(() => {
    setAuthVersion((v) => v + 1);
    navigate("/dashboard");
  }, [navigate]);

  const handleLogout = useCallback(() => {
    localStorage.removeItem("token");
    localStorage.removeItem("user_id");
    localStorage.removeItem("email");
    setAuthVersion((v) => v + 1);
    setMobileNavOpen(false);
    navigate("/login");
  }, [navigate]);

  const closeMobileNav = useCallback(() => setMobileNavOpen(false), []);

  return (
    <div className="min-h-screen flex flex-col relative">
      {/* ───────── Sticky glass header ───────── */}
      <header className="sticky top-0 z-40">
        {/* The header is a translucent glass strip that picks up the page
            background gradient behind it. */}
        <div className="glass-strong border-x-0 border-t-0">
          <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="h-16 flex items-center justify-between gap-4">
              {/* Logo + brand */}
              <NavLink
                to="/"
                className="flex items-center gap-2.5 group focus-ring rounded-lg pr-2"
              >
                <span className="relative inline-flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-brand overflow-hidden">
                  <Icon.Logo className="w-5 h-5 relative" />
                  <span className="absolute inset-x-0 top-0 h-1/2 bg-white/25" />
                </span>
                <span className="text-[17px] font-bold tracking-tight text-ink-900 group-hover:text-brand-700 transition-colors">
                  Outlay
                </span>
              </NavLink>

              {/* Desktop nav */}
              <nav className="hidden md:flex items-center gap-1">
                <NavItem to="/" end icon={Icon.Home}>
                  Home
                </NavItem>
                {isLoggedIn ? (
                  <>
                    <NavItem to="/dashboard" icon={Icon.Dashboard}>
                      Dashboard
                    </NavItem>
                    <NavItem to="/upload" icon={Icon.Upload}>
                      Upload
                    </NavItem>
                    <NavItem to="/settings" icon={Icon.Settings}>
                      Settings
                    </NavItem>

                    {/* Logged-in user chip — glass subtle pill */}
                    {email && (
                      <span className="hidden lg:inline-flex items-center gap-1.5 ml-2 px-2.5 py-1 rounded-full glass-subtle text-xs font-medium text-ink-600">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        <span className="max-w-[180px] truncate">{email}</span>
                      </span>
                    )}

                    <button
                      onClick={handleLogout}
                      className="ml-2 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-ink-600 hover:text-rose-600 hover:bg-rose-50/70 transition-all duration-200 focus-ring"
                    >
                      <Icon.Logout className="w-4 h-4" />
                      Log out
                    </button>
                  </>
                ) : (
                  <>
                    <NavItem to="/login">Log in</NavItem>
                    <NavLink
                      to="/register"
                      className="btn-primary !px-4 !py-2 ml-1"
                    >
                      Register
                    </NavLink>
                  </>
                )}
              </nav>

              {/* Mobile toggle */}
              <button
                type="button"
                onClick={() => setMobileNavOpen((v) => !v)}
                className="md:hidden inline-flex items-center justify-center w-10 h-10 rounded-lg text-ink-700 hover:bg-white/60 transition-colors focus-ring"
                aria-label={mobileNavOpen ? "Close menu" : "Open menu"}
                aria-expanded={mobileNavOpen}
              >
                {mobileNavOpen ? (
                  <Icon.Close className="w-5 h-5" />
                ) : (
                  <Icon.Menu className="w-5 h-5" />
                )}
              </button>
            </div>
          </div>
        </div>

        {/* ───────── Mobile dropdown — glass panel that slides down ───────── */}
        {mobileNavOpen && (
          <div className="md:hidden absolute inset-x-0 top-16 animate-slide-down">
            <div className="mx-3 mt-2 glass-strong rounded-2xl p-3 shadow-soft-lg">
              <div className="flex flex-col gap-1">
                <NavItem to="/" end icon={Icon.Home} mobile onClick={closeMobileNav}>
                  Home
                </NavItem>
                {isLoggedIn ? (
                  <>
                    <NavItem to="/dashboard" icon={Icon.Dashboard} mobile onClick={closeMobileNav}>
                      Dashboard
                    </NavItem>
                    <NavItem to="/upload" icon={Icon.Upload} mobile onClick={closeMobileNav}>
                      Upload
                    </NavItem>
                    <NavItem to="/settings" icon={Icon.Settings} mobile onClick={closeMobileNav}>
                      Settings
                    </NavItem>
                    {email && (
                      <div className="mt-1 mb-1 px-3 py-2 text-xs text-ink-500 border-t border-white/40 pt-2">
                        Signed in as <span className="font-medium text-ink-700 break-all">{email}</span>
                      </div>
                    )}
                    <button
                      onClick={() => {
                        handleLogout();
                      }}
                      className="mt-1 flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm font-medium text-rose-600 hover:bg-rose-50/70 transition-colors"
                    >
                      <Icon.Logout className="w-4 h-4" />
                      Log out
                    </button>
                  </>
                ) : (
                  <>
                    <NavItem to="/login" mobile onClick={closeMobileNav}>
                      Log in
                    </NavItem>
                    <NavLink
                      to="/register"
                      onClick={closeMobileNav}
                      className="btn-primary mt-1 w-full"
                    >
                      Register
                    </NavLink>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </header>

      {/* ───────── Main content area ───────── */}
      <main className="flex-1 w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-10 animate-fade-in">
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

      {/* ───────── Footer ───────── */}
      <footer className="mt-auto">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-ink-400">
            <div className="flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand-500" />
              <span className="font-medium text-ink-500">Outlay</span>
              <span className="text-ink-300">·</span>
              <span>Receipts in, reimbursements out</span>
            </div>
            <span className="text-ink-400">
              Built with S3 + Lambda + OCR
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
