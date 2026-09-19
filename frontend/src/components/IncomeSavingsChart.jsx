import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";

// Liquid Glass IncomeSavingsChart.
// Logic preserved bit-for-bit:
//   - reads budget.income / budget.total_spent / budget.savings
//   - empty state when income === 0 && spent === 0
//   - savings can be negative — clamped to 0 for slice size, true value in tooltip
//   - same color mapping: Spent = red, Savings = green

const SLICE_COLORS = {
  Spent: "#ef4444",    // red
  Savings: "#10b981",  // green
};

export default function IncomeSavingsChart({ budget }) {
  // Same null guard as the original.
  if (!budget) return null;

  const income = Number(budget.income || 0);
  const spent = Number(budget.total_spent || 0);
  const savings = Number(budget.savings || 0);

  // Empty state — same intent as the original (hint to set income).
  if (income === 0 && spent === 0) {
    return (
      <div className="glass rounded-2xl p-5 shadow-soft">
        <p className="eyebrow mb-1">Savings</p>
        <h3 className="text-base font-semibold text-ink-900 tracking-tight mb-3">
          Income vs Spent — {budget.month}
        </h3>
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-600 mb-2">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
              strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
              <path d="M19 9a5 5 0 0 0-5-5H10a6 6 0 0 0-6 6v0a4 4 0 0 0 2 3.46V17h3v-2h2v2h3v-2.5a5 5 0 0 0 5-5.5Z" />
            </svg>
          </div>
          <p className="text-sm text-ink-500 italic">
            Set your income in Settings to see the breakdown.
          </p>
        </div>
      </div>
    );
  }

  // Build the pie data. Same filter as the original — savings can be
  // negative, clamp to 0 for slice size but keep the true value in the
  // tooltip payload.
  const data = [
    { name: "Spent", value: spent, trueValue: spent },
    { name: "Savings", value: Math.max(0, savings), trueValue: savings },
  ].filter((d) => d.value > 0 || d.trueValue !== 0);

  const total = income || 1;

  return (
    <div className="glass rounded-2xl p-5 shadow-soft transition-all duration-300 hover:shadow-soft-lg">
      <div className="flex items-start justify-between mb-1">
        <div>
          <p className="eyebrow mb-1">Savings</p>
          <h3 className="text-base font-semibold text-ink-900 tracking-tight">
            Income vs Spent — {budget.month}
          </h3>
        </div>
        <div className="text-right">
          <div className="text-xs text-ink-500">Savings</div>
          <div
            className={`text-lg font-bold tabular-nums ${
              savings >= 0 ? "text-emerald-700" : "text-rose-700"
            }`}
          >
            ₹{savings.toLocaleString()}
          </div>
        </div>
      </div>
      <div className="text-xs text-ink-500 mb-3 flex items-center gap-2">
        <span className="inline-flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-ink-400" />
          Income: ₹{income.toLocaleString()}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center">
        <div className="h-44 relative">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                innerRadius={45}
                outerRadius={70}
                paddingAngle={2}
                stroke="none"
              >
                {data.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={SLICE_COLORS[entry.name] || "#cbd5e1"}
                  />
                ))}
              </Pie>
              <Tooltip
                formatter={(value, name, props) =>
                  `₹${Number(props.payload.trueValue).toLocaleString()}`
                }
              />
              <Legend iconType="circle" iconSize={8} />
            </PieChart>
          </ResponsiveContainer>
          {/* Center overlay — show savings % */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none -mt-7">
            <div className="text-center">
              <div
                className={`text-lg font-bold tabular-nums ${
                  savings >= 0 ? "text-emerald-700" : "text-rose-700"
                }`}
              >
                {income > 0 ? Math.round((savings / income) * 100) : 0}%
              </div>
              <div className="text-[10px] text-ink-400 uppercase tracking-wider">
                saved
              </div>
            </div>
          </div>
        </div>

        {/* Side panel — mini metric cards */}
        <div className="space-y-2">
          <div className="glass-subtle rounded-xl p-3 flex items-center justify-between">
            <div>
              <div className="text-xs text-ink-500">Income</div>
              <div className="text-sm font-bold text-ink-900 tabular-nums">
                ₹{income.toLocaleString()}
              </div>
            </div>
            <div className="w-8 h-8 rounded-lg bg-ink-500/15 text-ink-700 inline-flex items-center justify-center">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                <path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
              </svg>
            </div>
          </div>
          <div className="glass-subtle rounded-xl p-3 flex items-center justify-between">
            <div>
              <div className="text-xs text-ink-500">Spent</div>
              <div className="text-sm font-bold text-rose-700 tabular-nums">
                ₹{spent.toLocaleString()}
              </div>
              <div className="text-[10px] text-ink-400 mt-0.5">
                {income > 0 ? Math.round((spent / income) * 100) : 0}% of income
              </div>
            </div>
            <div className="w-8 h-8 rounded-lg bg-rose-500/15 text-rose-700 inline-flex items-center justify-center">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                <path d="M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
                <path d="M16 13h2" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
