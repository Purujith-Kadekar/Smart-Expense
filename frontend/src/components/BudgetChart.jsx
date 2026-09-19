import { Cell, Pie, PieChart, ResponsiveContainer, Legend } from "recharts";

// Liquid Glass BudgetChart.
// Logic preserved bit-for-bit — same data shape, same color for "Spent"
// (brand indigo), same "exhausted" warning when remaining === 0.
// Only the surface treatment (glass card + better hierarchy) is new.

export default function BudgetChart({ budget }) {
  const spent = Number(budget.total_spent || 0);
  const limit = Number(budget.budget_limit || 0);
  const remaining = Math.max(0, limit - spent);

  const data = [
    { name: "Spent", value: spent },
    { name: "Remaining", value: remaining },
  ];
  const colors = ["#4f46e5", "#e2e8f0"];

  // Progress percentage for the linear bar (purely cosmetic, complements
  // the pie without replacing it).
  const pct = limit > 0 ? Math.min(100, Math.round((spent / limit) * 100)) : 0;

  return (
    <div className="glass rounded-2xl p-5 shadow-soft transition-all duration-300 hover:shadow-soft-lg">
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="eyebrow mb-1">Budget status</p>
          <h3 className="text-base font-semibold text-ink-900 tracking-tight">
            Spent vs. remaining
          </h3>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold text-brand-700 tabular-nums">
            ₹{spent.toLocaleString()}
          </div>
          <div className="text-xs text-ink-500 mt-0.5">
            of ₹{limit.toLocaleString()} limit
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center">
        {/* Pie */}
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
                {data.map((_, i) => (
                  <Cell key={i} fill={colors[i % colors.length]} />
                ))}
              </Pie>
              <Legend
                verticalAlign="bottom"
                height={28}
                iconType="circle"
                iconSize={8}
              />
            </PieChart>
          </ResponsiveContainer>
          {/* Center label overlay */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none -mt-7">
            <div className="text-center">
              <div className="text-lg font-bold text-ink-900 tabular-nums">{pct}%</div>
              <div className="text-[10px] text-ink-400 uppercase tracking-wider">used</div>
            </div>
          </div>
        </div>

        {/* Side panel: linear progress + status text */}
        <div className="space-y-3">
          {/* Progress bar */}
          <div>
            <div className="flex items-center justify-between text-xs text-ink-500 mb-1.5">
              <span>Spent</span>
              <span className="tabular-nums font-medium">{pct}%</span>
            </div>
            <div className="h-2 rounded-full bg-ink-200/70 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  pct >= 100
                    ? "bg-gradient-to-r from-amber-500 to-rose-500"
                    : "bg-gradient-to-r from-brand-400 to-brand-600"
                }`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-xs text-ink-400 mt-1.5">
              <span className="tabular-nums">₹{spent.toLocaleString()}</span>
              <span className="tabular-nums">₹{limit.toLocaleString()}</span>
            </div>
          </div>

          <div className="text-sm text-ink-600">
            {remaining > 0 ? (
              <div className="flex items-start gap-2">
                <span className="inline-flex items-center justify-center w-5 h-5 rounded-md bg-emerald-500/15 text-emerald-700 mt-0.5 shrink-0">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                </span>
                <span>
                  <span className="font-semibold text-ink-900">
                    ₹{remaining.toLocaleString()}
                  </span>{" "}
                  remaining under your budget limit.
                </span>
              </div>
            ) : (
              <div className="flex items-start gap-2 text-amber-700">
                <span className="inline-flex items-center justify-center w-5 h-5 rounded-md bg-amber-500/15 mt-0.5 shrink-0">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                    <path d="M12 9v4M12 17h.01" />
                    <path d="M10.29 3.86l-8.18 14.18A2 2 0 0 0 3.83 21h16.34a2 2 0 0 0 1.72-2.96L13.71 3.86a2 2 0 0 0-3.42 0Z" />
                  </svg>
                </span>
                <span className="font-medium">
                  Budget exhausted — you've hit your spending limit for the month.
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
