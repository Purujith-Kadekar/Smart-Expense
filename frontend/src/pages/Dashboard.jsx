import { useEffect, useRef, useState } from "react";
import api from "../api/client.js";
import ExpenseTable from "../components/ExpenseTable.jsx";
import BudgetChart from "../components/BudgetChart.jsx";
import CategoryChart from "../components/CategoryChart.jsx";
import IncomeSavingsChart from "../components/IncomeSavingsChart.jsx";

// Liquid Glass Dashboard.
//
// Data-flow (post month-filter fix):
//   - month picker (defaults to current YYYY-MM)
//   - GET /expenses?month=YYYY-MM + GET /budget?month=YYYY-MM in parallel
//   - 15s auto-poll via setInterval
//   - re-fetch on month change (useEffect dependency = [month])
//   - errors surfaced from err.response.data.error
//   - the `expenses` array is ALREADY month-scoped by the backend, so the
//     stat cards, CategoryChart, and ExpenseTable all stay in sync with
//     the active month selector in the top-right
//   - three charts: budget status, income vs spent vs savings, category
//   - expense table below with multi-select + email feature
//
// Month-visibility fix:
//   Every widget is scoped to the selected month, and the selected month
//   defaults to *today's* month. A receipt is filed under the date printed
//   on it (OCR'd at ingest), not the date it was uploaded — so uploading a
//   receipt dated 2026-03-18 in September put a real row in DynamoDB that
//   the dashboard then filtered out, with no way to tell that apart from
//   "you have no receipts". We now also fetch GET /expenses/months (the
//   months that actually contain receipts) and, when the selected month is
//   empty but others are not, show a banner with one-click jumps plus an
//   "All time" view. Nothing is silently hidden any more.

const POLL_INTERVAL_MS = 15000;

// Sentinel understood by GET /expenses?month= and GET /budget?month=.
const ALL_TIME = "all";

function monthLabel(m) {
  if (m === ALL_TIME) return "all time";
  if (!m || m === "unknown") return "no date";
  const [y, mo] = m.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const name = names[Number(mo) - 1];
  return name ? `${name} ${y}` : m;
}

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
  // Months that actually contain receipts — powers the "your receipts are
  // in another month" banner below. Never used to filter anything.
  const [availableMonths, setAvailableMonths] = useState([]);
  // One-shot guard for the auto-jump below. Once the user has been moved
  // (or has touched the picker themselves) we never move them again — an
  // auto-jump that fires on every poll would fight the user's own choice.
  // A ref, not state: the 15s poll captures `refresh` in a closure that is
  // only rebuilt when `month` changes, so a state flag would read stale
  // inside the interval. A ref is always current.
  const autoJumped = useRef(false);
  const setAutoJumped = (v) => {
    autoJumped.current = v;
  };
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  // Fetch /expenses and /budget in parallel. BOTH are scoped to the
  // active `month` — passing { params: { month } } on /expenses is the
  // fix for the original bug where the category chart + expense table
  // were showing all-time data while the top stat cards were correctly
  // month-scoped. Now all three widgets pull from the same filtered
  // payload, so they can never drift out of sync.
  const refresh = async () => {
    setRefreshing(true);
    try {
      const [expRes, budgetRes, monthsRes] = await Promise.all([
        api.get("/expenses", { params: { month } }),
        api.get("/budget", { params: { month } }).catch((err) => {
          console.warn("budget fetch failed", err);
          return null;
        }),
        // Best-effort: an older backend without this route just means the
        // banner stays hidden — it must never break the dashboard.
        api.get("/expenses/months").catch((err) => {
          console.warn("month summary fetch failed", err);
          return null;
        }),
      ]);
      setExpenses(expRes.data || []);
      if (budgetRes) setBudget(budgetRes.data);
      const months = monthsRes ? monthsRes.data || [] : [];
      if (monthsRes) setAvailableMonths(months);

      // Land the user where their data actually is. The picker defaults to
      // today's month, but a receipt is filed under the date printed on it
      // — upload a March-dated receipt in September and the default view is
      // empty even though the record exists. On the FIRST load only, if the
      // default month has nothing and some other month does, jump to the
      // most recent month that has receipts. The banner still explains what
      // happened, and the picker still overrides this.
      if (!autoJumped.current && month === currentMonth() && (expRes.data || []).length === 0) {
        const newest = months.find((m) => m.month && m.month !== "unknown");
        setAutoJumped(true);
        if (newest && newest.month !== month) {
          setMonth(newest.month);
          return; // the month change re-triggers refresh via useEffect
        }
      }
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
  const isAllTime = month === ALL_TIME;

  // Receipts that exist but are NOT in the current view. This is what makes
  // the "processed but nowhere to be seen" case visible instead of silent.
  const elsewhere = (availableMonths || []).filter(
    (m) => !isAllTime && m.month !== month
  );
  const elsewhereCount = elsewhere.reduce((n, m) => n + Number(m.count || 0), 0);
  const showElsewhereBanner = elsewhereCount > 0;

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
            Live view of your spending vs. budget for {monthLabel(month)}.
            Auto-refreshes every 15s.
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
              value={isAllTime ? "" : month}
              onChange={(e) => {
                setAutoJumped(true);
                setMonth(e.target.value || currentMonth());
              }}
              disabled={isAllTime}
              className="bg-transparent text-sm text-ink-900 focus:outline-none focus:ring-0 border-0 p-0 cursor-pointer disabled:opacity-40"
            />
          </div>
          <button
            onClick={() => {
              setAutoJumped(true);
              setMonth(isAllTime ? currentMonth() : ALL_TIME);
            }}
            className={`btn-secondary !px-3 !py-2.5 ${isAllTime ? "!text-brand-700" : ""}`}
            title={isAllTime ? "Back to a single month" : "Show every receipt, any month"}
            aria-pressed={isAllTime}
          >
            <span>{isAllTime ? "Monthly" : "All time"}</span>
          </button>
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

      {/* ───────── "Your receipts are in another month" banner ─────────
          A receipt is filed under the date OCR'd from the receipt itself,
          which is often not the month you uploaded it in. Without this
          banner the dashboard just renders an empty table and the user has
          no way to know the record exists. */}
      {showElsewhereBanner && (
        <div className="flex flex-wrap items-center gap-2.5 text-amber-900 text-sm bg-amber-50/70 border border-amber-200/80 rounded-xl p-3 animate-fade-in">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 shrink-0">
            <rect x="3" y="4" width="18" height="17" rx="2" />
            <path d="M8 2v4M16 2v4M3 10h18" />
          </svg>
          <span>
            {(expenses || []).length === 0
              ? `No receipts dated ${monthLabel(month)}, but you have ${elsewhereCount} in other months.`
              : `${elsewhereCount} more receipt(s) are dated outside ${monthLabel(month)}.`}
            {" "}Receipts are filed by the date printed on them, not the upload date.
          </span>
          <span className="flex flex-wrap items-center gap-1.5">
            {elsewhere.slice(0, 6).map((m) => (
              <button
                key={m.month}
                onClick={() => {
                  setAutoJumped(true);
                  if (m.month !== "unknown") setMonth(m.month);
                }}
                disabled={m.month === "unknown"}
                className="px-2 py-1 rounded-lg bg-white/70 border border-amber-200 text-xs font-medium hover:bg-white disabled:opacity-60 disabled:cursor-default"
                title={m.month === "unknown" ? "Receipts with no readable date" : `Jump to ${monthLabel(m.month)}`}
              >
                {monthLabel(m.month)} · {m.count}
              </button>
            ))}
            <button
              onClick={() => {
                setAutoJumped(true);
                setMonth(ALL_TIME);
              }}
              className="px-2 py-1 rounded-lg bg-white/70 border border-amber-200 text-xs font-medium hover:bg-white"
            >
              All time
            </button>
          </span>
        </div>
      )}

      {/* ───────── Stat tiles ───────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          label={isAllTime ? "Spent (all time)" : "Spent (month)"}
          value={`₹${totalSpent.toLocaleString()}`}
          subtext={
            isAllTime || budgetLimit <= 0
              ? `${(expenses || []).length} receipt(s)`
              : `of ₹${budgetLimit.toLocaleString()} limit`
          }
          icon={Icon.Wallet}
          tone="brand"
        />
        {!isAllTime && <StatTile
          label="Income"
          value={`₹${income.toLocaleString()}`}
          subtext={`for ${monthLabel(month)}`}
          icon={Icon.Piggy}
          tone="emerald"
        />}
        {!isAllTime && <StatTile
          label="Savings"
          value={`₹${savings.toLocaleString()}`}
          subtext={savings >= 0 ? "under budget" : "overspent"}
          icon={Icon.Piggy}
          tone={savings >= 0 ? "emerald" : "rose"}
        />}
        <StatTile
          label="Over budget"
          value={String(overBudgetCount)}
          subtext={`of ${(expenses || []).length} receipts`}
          icon={Icon.Tag}
          tone={overBudgetCount > 0 ? "amber" : "ink"}
        />
      </div>

      {/* ───────── Chart row 1: budget status (left) + income/savings (right) ───────── */}
      {/* Budget/income charts are monthly by definition — there is no
          all-time budget row, so rendering them in the all-time view would
          just show "₹x of ₹0 limit". */}
      {!isAllTime && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {budget && <BudgetChart budget={budget} />}
          <IncomeSavingsChart budget={budget} />
        </div>
      )}

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
