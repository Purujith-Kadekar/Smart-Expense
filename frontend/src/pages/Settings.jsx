import { useEffect, useState } from "react";
import api from "../api/client.js";

// Settings page — let the user set their monthly budget limit + income
// for a given month. Calls POST /api/budget on save.
//
// The budget is per-month ("YYYY-MM") so the user can plan ahead for
// different months. Defaults to the current month on first load.
export default function Settings() {
  const [month, setMonth] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  });
  const [budgetLimit, setBudgetLimit] = useState("");
  const [income, setIncome] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Fetch the existing budget for the selected month so the form is
  // pre-populated when the user navigates to a month they've already
  // configured.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const { data } = await api.get(`/budget`, { params: { month } });
        if (cancelled) return;
        // If the backend returns 0 for both, show empty inputs (cleaner UX
        // than showing "0") — the user types their actual numbers.
        setBudgetLimit(data.budget_limit ? String(data.budget_limit) : "");
        setIncome(data.income ? String(data.income) : "");
      } catch (err) {
        if (cancelled) return;
        setError(err?.response?.data?.error || "Failed to load budget.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [month]);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const { data } = await api.post("/budget", {
        month,
        budget_limit: Number(budgetLimit) || 0,
        income: Number(income) || 0,
      });
      setMessage(
        `Saved — budget limit ₹${Number(data.budget_limit).toLocaleString()}, ` +
        `income ₹${Number(data.income).toLocaleString()} for ${data.month}.`
      );
    } catch (err) {
      setError(err?.response?.data?.error || "Failed to save budget.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-md mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-slate-900">Settings</h2>
        <p className="text-sm text-slate-500 mt-1">
          Set your monthly budget limit and income. The dashboard uses these
          to compute your savings (income − spent) for the month.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <label
            htmlFor="month"
            className="block text-sm font-medium text-slate-700 mb-1"
          >
            Month
          </label>
          <input
            type="month"
            id="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            required
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        <div>
          <label
            htmlFor="budget_limit"
            className="block text-sm font-medium text-slate-700 mb-1"
          >
            Monthly budget limit (₹)
          </label>
          <input
            type="number"
            id="budget_limit"
            value={budgetLimit}
            onChange={(e) => setBudgetLimit(e.target.value)}
            min="0"
            step="100"
            placeholder="0"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <p className="text-xs text-slate-400 mt-1">
            Your monthly spending cap. The dashboard shows how close you are
            to this limit.
          </p>
        </div>

        <div>
          <label
            htmlFor="income"
            className="block text-sm font-medium text-slate-700 mb-1"
          >
            Monthly income (₹)
          </label>
          <input
            type="number"
            id="income"
            value={income}
            onChange={(e) => setIncome(e.target.value)}
            min="0"
            step="100"
            placeholder="0"
            className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <p className="text-xs text-slate-400 mt-1">
            Savings = income − total spent this month.
          </p>
        </div>

        {error && (
          <div className="text-red-700 text-sm bg-red-50 border border-red-200 rounded-md p-2">
            {error}
          </div>
        )}
        {message && (
          <div className="text-green-700 text-sm bg-green-50 border border-green-200 rounded-md p-2">
            {message}
          </div>
        )}

        <button
          type="submit"
          disabled={saving || loading}
          className="w-full px-4 py-2 bg-brand-600 text-white rounded-md hover:bg-brand-700 disabled:opacity-60 transition-colors"
        >
          {saving ? "Saving…" : loading ? "Loading…" : "Save"}
        </button>
      </form>
    </div>
  );
}
