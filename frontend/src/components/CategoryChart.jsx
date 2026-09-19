import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";

// Liquid Glass CategoryChart.
// Logic preserved bit-for-bit:
//   - client-side aggregation by category
//   - sort descending
//   - empty state when no expenses
//   - same per-category color palette (blue / amber / purple / slate)
//   - Tooltip formatted as ₹

const CATEGORY_COLORS = {
  college: "#3b82f6", // blue
  mess: "#f59e0b",    // amber
  event: "#a855f7",   // purple
  other: "#64748b",   // slate
};
const FALLBACK_COLOR = "#cbd5e1";

// Small dot + label for the side legend — purely cosmetic.
const CATEGORY_LABELS = {
  college: "College",
  mess: "Mess",
  event: "Event",
  other: "Other",
};

export default function CategoryChart({ expenses }) {
  // Aggregate expenses by category. Same reduce as the original.
  const totals = (expenses || []).reduce((acc, e) => {
    const cat = e.category || "other";
    acc[cat] = (acc[cat] || 0) + Number(e.amount || 0);
    return acc;
  }, {});

  const data = Object.entries(totals).map(([name, value]) => ({
    name,
    value: Math.round(value * 100) / 100, // avoid float artefacts
  }));

  // Sort descending so the biggest slice is first (clockwise from 12 o'clock).
  data.sort((a, b) => b.value - a.value);

  const grandTotal = data.reduce((sum, d) => sum + d.value, 0);

  // Empty state — same intent as the original.
  if (data.length === 0) {
    return (
      <div className="glass rounded-2xl p-5 shadow-soft">
        <p className="eyebrow mb-1">Breakdown</p>
        <h3 className="text-base font-semibold text-ink-900 tracking-tight mb-3">
          By category
        </h3>
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <div className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-ink-500/10 text-ink-500 mb-2">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
              strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
              <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
            </svg>
          </div>
          <p className="text-sm text-ink-500 italic">
            No expenses to break down yet.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="glass rounded-2xl p-5 shadow-soft transition-all duration-300 hover:shadow-soft-lg">
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="eyebrow mb-1">Breakdown</p>
          <h3 className="text-base font-semibold text-ink-900 tracking-tight">
            By category
          </h3>
        </div>
        <div className="text-right">
          <div className="text-xs text-ink-500">Total spent</div>
          <div className="text-lg font-bold text-ink-900 tabular-nums">
            ₹{grandTotal.toLocaleString()}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-center">
        {/* Pie */}
        <div className="h-52 relative">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                innerRadius={50}
                outerRadius={75}
                paddingAngle={2}
                stroke="none"
              >
                {data.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={CATEGORY_COLORS[entry.name] || FALLBACK_COLOR}
                  />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => `₹${Number(value).toLocaleString()}`}
              />
              <Legend
                formatter={(value) => (
                  <span className="capitalize text-sm text-ink-700">
                    {value}
                  </span>
                )}
                iconType="circle"
                iconSize={8}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Side legend with bars + totals */}
        <div className="space-y-2.5">
          {data.map((d) => {
            const color = CATEGORY_COLORS[d.name] || FALLBACK_COLOR;
            const pct = grandTotal > 0 ? (d.value / grandTotal) * 100 : 0;
            return (
              <div key={d.name} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 capitalize text-ink-700">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: color }}
                    />
                    {CATEGORY_LABELS[d.name] || d.name}
                  </div>
                  <div className="text-ink-900 font-semibold tabular-nums">
                    ₹{d.value.toLocaleString()}
                  </div>
                </div>
                <div className="h-1.5 rounded-full bg-ink-200/60 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${pct}%`,
                      backgroundColor: color,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
