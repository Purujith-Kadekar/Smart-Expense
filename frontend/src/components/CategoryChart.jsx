import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";

// Category-breakdown pie chart. Computes the per-category totals
// client-side from the existing /api/expenses response — no new API
// call needed. Renders alongside the BudgetChart on the dashboard.
const CATEGORY_COLORS = {
  college: "#3b82f6", // blue
  mess: "#f59e0b",    // amber
  event: "#a855f7",   // purple
  other: "#64748b",   // slate
};
const FALLBACK_COLOR = "#cbd5e1";

export default function CategoryChart({ expenses }) {
  // Aggregate expenses by category. Expenses without a category (legacy
  // records from before categories existed) are grouped under "other".
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

  if (data.length === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <h3 className="text-lg font-medium text-slate-900 mb-2">By category</h3>
        <p className="text-sm text-slate-500 italic">
          No expenses to break down yet.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <h3 className="text-lg font-medium text-slate-900 mb-3">By category</h3>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius={45}
              outerRadius={75}
              paddingAngle={2}
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
                <span className="capitalize text-sm text-slate-700">
                  {value}
                </span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
