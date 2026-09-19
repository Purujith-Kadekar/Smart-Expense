import { useEffect, useState } from "react";
import api from "../api/client.js";

// Liquid Glass Settings page.
//
// Logic preserved bit-for-bit:
//   - GET /api/budget?month=YYYY-MM to pre-populate
//   - month defaults to current YYYY-MM
//   - empty inputs when backend returns 0
//   - POST /api/budget with month, budget_limit, income
//   - success message formatted with returned values
//   - error message from err.response.data.error

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

  // Fetch existing budget for the selected month — same logic as the
  // original, with the `cancelled` flag to avoid setState on unmounted
  // components during the brief window between month change and unmount.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const { data } = await api.get(`/budget`, { params: { month } });
        if (cancelled) return;
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

  // Same handleSave as the original — POST /budget with parsed numbers,
  // success message includes the formatted values from the response.
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

  // Derived helpers — show a small live "savings" preview as the user types.
  const previewSavings = (Number(income) || 0) - (Number(budgetLimit) || 0);

  return (
    <div className="max-w-xl mx-auto animate-fade-in">
      <div className="mb-6">
        <p className="eyebrow mb-1.5">Settings</p>
        <h2 className="text-2xl sm:text-3xl font-bold text-ink-900 tracking-tight">
          Monthly budget
        </h2>
        <p className="text-sm text-ink-500 mt-1.5 leading-relaxed">
          Set your monthly budget limit and income. The dashboard uses these
          to compute your savings (income − spent) for the month.
        </p>
      </div>

      <form onSubmit={handleSave} className="glass rounded-2xl p-6 sm:p-7 shadow-soft space-y-5">
        <div>
          <label
            htmlFor="month"
            className="block text-sm font-medium text-ink-700 mb-1.5"
          >
            Month
          </label>
          <input
            type="month"
            id="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            required
            className="input-glass"
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label
              htmlFor="budget_limit"
              className="block text-sm font-medium text-ink-700 mb-1.5"
            >
              Monthly budget limit (₹)
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 text-sm pointer-events-none">₹</span>
              <input
                type="number"
                id="budget_limit"
                value={budgetLimit}
                onChange={(e) => setBudgetLimit(e.target.value)}
                min="0"
                step="100"
                placeholder="0"
                className="input-glass pl-7"
              />
            </div>
            <p className="text-xs text-ink-400 mt-1.5 flex items-center gap-1">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4M12 8h.01" />
              </svg>
              Your monthly spending cap.
            </p>
          </div>

          <div>
            <label
              htmlFor="income"
              className="block text-sm font-medium text-ink-700 mb-1.5"
            >
              Monthly income (₹)
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 text-sm pointer-events-none">₹</span>
              <input
                type="number"
                id="income"
                value={income}
                onChange={(e) => setIncome(e.target.value)}
                min="0"
                step="100"
                placeholder="0"
                className="input-glass pl-7"
              />
            </div>
            <p className="text-xs text-ink-400 mt-1.5">
              Savings = income − total spent this month.
            </p>
          </div>
        </div>

        {/* Live savings preview — purely cosmetic, doesn't send any data */}
        {(Number(income) > 0 || Number(budgetLimit) > 0) && (
          <div className="glass-subtle rounded-xl p-3.5 flex items-center justify-between animate-fade-in">
            <div className="flex items-center gap-2.5">
              <div className={`inline-flex items-center justify-center w-9 h-9 rounded-xl
                ${previewSavings >= 0 ? "bg-emerald-500/15 text-emerald-700" : "bg-rose-500/15 text-rose-700"}`}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                  strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                  <path d="M19 9a5 5 0 0 0-5-5H10a6 6 0 0 0-6 6v0a4 4 0 0 0 2 3.46V17h3v-2h2v2h3v-2.5a5 5 0 0 0 5-5.5Z" />
                  <path d="M9 11h.01" />
                </svg>
              </div>
              <div>
                <div className="text-xs text-ink-500">Projected savings</div>
                <div className={`text-sm font-bold ${previewSavings >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                  ₹{Math.abs(previewSavings).toLocaleString()}
                  {previewSavings < 0 && " (overspent)"}
                </div>
              </div>
            </div>
            <span className="text-[11px] text-ink-400">income − limit</span>
          </div>
        )}

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
        {message && (
          <div className="flex items-start gap-2 text-emerald-700 text-sm bg-emerald-50/70 border border-emerald-200/80 rounded-xl p-2.5 animate-fade-in">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 mt-0.5 shrink-0">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <path d="M22 4L12 14.01l-3-3" />
            </svg>
            <span>{message}</span>
          </div>
        )}

        <div className="pt-1">
          <button
            type="submit"
            disabled={saving || loading}
            className="btn-primary w-full !py-2.5"
          >
            {saving ? (
              <>
                <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                Saving…
              </>
            ) : loading ? (
              "Loading…"
            ) : (
              "Save"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
