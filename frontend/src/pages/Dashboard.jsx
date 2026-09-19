import { useEffect, useState } from "react";
import api from "../api/client.js";
import ExpenseTable from "../components/ExpenseTable.jsx";
import BudgetChart from "../components/BudgetChart.jsx";
import CategoryChart from "../components/CategoryChart.jsx";
import IncomeSavingsChart from "../components/IncomeSavingsChart.jsx";

// Liquid Glass Dashboard.
//
// Logic preserved bit-for-bit:
//   - month picker (defaults to current YYYY-MM)
//   - GET /expenses + GET /budget?month=… in parallel
//   - 15s auto-poll via setInterval
//   - re-fetch on month change (useEffect dependency)
//   - errors surfaced from err.response.data.error
//   - expenses list is NOT filtered by month (only the budget is)
//   - three charts: budget status, income vs spent vs savings, category
//   - expense table below with multi-select + email feature

const POLL_INTERVAL_MS = 15000;

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

// Inline icons used in stat tiles and toolbar.
const Icon = {
  Refresh: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M21 12a9 9 0 1 1-3.5-7.1" />
      <path d="M21 4v5h-5" />
    </svg>
  ),
  Wallet: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v1" />
      <rect x="3" y="7" width="18" height="12" rx="2" />
      <path d="M16 13h2" />
    </svg>
  ),
  Piggy: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M19 9a5 5 0 0 0-5-5H10a6 6 0 0 0-6 6v0a4 4 0 0 0 2 3.46V17h3v-2h2v2h3v-2.5a5 5 0 0 0 5-5.5Z" />
      <path d="M9 11h.01" />
    </svg>
  ),
  Tag: (props) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 7v5.66a2 2 0 0 0 .59 1.42l7.34 7.34a2 2 0 0 0 2.83 0l5.66-5.66a2 2 0 0 0 0-2.83l-7.34-7.34a2 2 0 0 0-1.42-.59H5a2 2 0 0 0-2 2Z" />
      <circle cx="7" cy="11" r="1.5" />
    </svg>
  ),
};

export default function Dashboard() {
  const [expenses, setExpenses] = useState([]);
  const [budget, setBudget] = useState(null);
  const [month, setMonth] = useState(currentMonth());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  // Same fetch logic as the original — Promise.all on /expenses + /budget.
  // The only addition is the `refreshing` flag for the button spinner; it
  // doesn't change the underlying fetch behavior.
  const refresh = async () => {
    setRefreshing(true);
    try {
      const [expRes, budgetRes] = await Promise.all([
        api.get("/expenses"),
        api.get("/budget", { params: { month } }).catch((err) => {
          console.warn("budget fetch failed", err);
          return null;
        }),
      ]);
      setExpenses(expRes.data || []);
      if (budgetRes) setBudget(budgetRes.data);
      setError("");
    } catch (err) {
      console.error(err);
      setError(
        err?.response?.data?.error || err?.message || "Failed to load expenses."
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]); // re-fetch when the month changes

  // ───────── Loading skeleton ─────────
  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <div className="h-7 w-48 skeleton rounded-lg" />
            <div className="h-4 w-32 skeleton rounded-lg" />
          </div>
          <div className="h-9 w-32 skeleton rounded-lg" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="glass rounded-2xl p-5 h-44">
              <div className="h-5 w-24 skeleton rounded-lg mb-3" />
              <div className="h-32 w-full skeleton rounded-xl" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Compute summary stats — purely derived from existing state, no new API calls.
  const totalSpent = (expenses || []).reduce(
    (sum, e) => sum + Number(e.amount || 0),
    0
  );
  const budgetLimit = Number(budget?.budget_limit || 0);
  const income = Number(budget?.income || 0);
  const savings = Number(budget?.savings || 0);
  const overBudgetCount = (expenses || []).filter((e) => e.over_budget).length;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ───────── Page header + toolbar ───────── */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <p className="eyebrow mb-1.5">Dashboard</p>
          <h2 className="text-2xl sm:text-3xl font-bold text-ink-900 tracking-tight">
            Budget overview
          </h2>
          <p className="text-sm text-ink-500 mt-1">
            Live view of your spending vs. budget for {month}. Auto-refreshes every 15s.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 px-3 py-2 glass-subtle rounded-xl">
            <label htmlFor="month" className="text-xs font-medium text-ink-600">
              Month
            </label>
            <input
              type="month"
              id="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="bg-transparent text-sm text-ink-900 focus:outline-none focus:ring-0 border-0 p-0 cursor-pointer"
            />
          </div>
          <button
            onClick={refresh}
            disabled={refreshing}
            className="btn-secondary !px-3 !py-2.5"
            title="Refresh now"
            aria-label="Refresh dashboard"
          >
            <Icon.Refresh className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>

      {/* ───────── Error banner ───────── */}
      {error && (
        <div className="flex items-start gap-2.5 text-rose-800 text-sm bg-rose-50/70 border border-rose-200/80 rounded-xl p-3 animate-fade-in">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 mt-0.5 shrink-0">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <span>{error}</span>
        </div>
      )}

      {/* ───────── Stat tiles ───────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          label="Spent (month)"
          value={`₹${Number(budget?.total_spent || 0).toLocaleString()}`}
          subtext={`of ₹${budgetLimit.toLocaleString()} limit`}
          icon={Icon.Wallet}
          tone="brand"
        />
        <StatTile
          label="Income"
          value={`₹${income.toLocaleString()}`}
          subtext={`for ${month}`}
          icon={Icon.Piggy}
          tone="emerald"
        />
        <StatTile
          label="Savings"
          value={`₹${savings.toLocaleString()}`}
          subtext={savings >= 0 ? "under budget" : "overspent"}
          icon={Icon.Piggy}
          tone={savings >= 0 ? "emerald" : "rose"}
        />
        <StatTile
          label="Over budget"
          value={String(overBudgetCount)}
          subtext={`of ${(expenses || []).length} receipts`}
          icon={Icon.Tag}
          tone={overBudgetCount > 0 ? "amber" : "ink"}
        />
      </div>

      {/* ───────── Chart row 1: budget status (left) + income/savings (right) ───────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {budget && <BudgetChart budget={budget} />}
        <IncomeSavingsChart budget={budget} />
      </div>

      {/* ───────── Chart row 2: category breakdown — full width ───────── */}
      <CategoryChart expenses={expenses} />

      {/* ───────── Expense table ───────── */}
      <div>
        <div className="flex items-end justify-between mb-3">
          <div>
            <h3 className="text-lg font-semibold text-ink-900 tracking-tight">
              Recent expenses
            </h3>
            <p className="text-xs text-ink-500 mt-0.5">
              Select receipts to email them as a single bill to your advisor.
            </p>
          </div>
          <span className="text-xs text-ink-400">
            {(expenses || []).length} total
          </span>
        </div>
        <ExpenseTable expenses={expenses} />
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Stat tile — small glass card with an icon, label, value, and subtext.
// Used four-up on the dashboard above the charts.
// ────────────────────────────────────────────────────────────────────────────
function StatTile({ label, value, subtext, icon: IconComp, tone }) {
  const tones = {
    brand: "from-brand-500/15 to-brand-600/10 text-brand-700",
    emerald: "from-emerald-500/15 to-emerald-600/10 text-emerald-700",
    rose: "from-rose-500/15 to-rose-600/10 text-rose-700",
    amber: "from-amber-500/15 to-amber-600/10 text-amber-700",
    ink: "from-ink-500/15 to-ink-700/10 text-ink-700",
  };
  return (
    <div className="glass rounded-2xl p-4 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-soft">
      <div className={`inline-flex items-center justify-center w-9 h-9 rounded-xl bg-gradient-to-br ${tones[tone] || tones.ink} mb-2.5`}>
        <IconComp className="w-4 h-4" />
      </div>
      <div className="text-xs font-medium text-ink-500">{label}</div>
      <div className="text-xl font-bold text-ink-900 tracking-tight mt-0.5">{value}</div>
      <div className="text-[11px] text-ink-400 mt-0.5">{subtext}</div>
    </div>
  );
}
