import { useEffect, useState } from "react";
import api from "../api/client.js";
import ExpenseTable from "../components/ExpenseTable.jsx";
import BudgetChart from "../components/BudgetChart.jsx";
import CategoryChart from "../components/CategoryChart.jsx";
import IncomeSavingsChart from "../components/IncomeSavingsChart.jsx";

// Dashboard page — shows:
//   1. Month picker (defaults to current month)
//   2. Three charts: budget status, income vs spent vs savings, category breakdown
//   3. The list of the authenticated user's expenses
//
// The month picker controls which month's budget + spending is shown.
// Expenses list is NOT filtered by month (the user might want to see
// all their receipts) — only the budget + savings charts are month-scoped.
const POLL_INTERVAL_MS = 15000;

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export default function Dashboard() {
  const [expenses, setExpenses] = useState([]);
  const [budget, setBudget] = useState(null);
  const [month, setMonth] = useState(currentMonth());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = async () => {
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
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]); // re-fetch when the month changes

  if (loading) {
    return <div className="text-slate-500 text-sm">Loading dashboard…</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-2xl font-semibold text-slate-900">Budget Dashboard</h2>
        <div className="flex items-center gap-3">
          <label htmlFor="month" className="text-sm text-slate-600">
            Month:
          </label>
          <input
            type="month"
            id="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="px-2 py-1 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <button
            onClick={refresh}
            className="text-sm text-brand-700 hover:text-brand-500"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded-md p-3">
          {error}
        </div>
      )}

      {/* Chart row 1: budget status (left) + income/savings (right). */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {budget && <BudgetChart budget={budget} />}
        <IncomeSavingsChart budget={budget} />
      </div>

      {/* Chart row 2: category breakdown — full width. */}
      <CategoryChart expenses={expenses} />

      <div>
        <h3 className="text-lg font-medium text-slate-900 mb-2">Recent expenses</h3>
        <ExpenseTable expenses={expenses} />
      </div>
    </div>
  );
}
