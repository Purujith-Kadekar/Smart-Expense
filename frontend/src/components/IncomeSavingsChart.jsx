import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts";

// Income vs Spent vs Savings pie chart. Renders alongside the CategoryChart
// on the dashboard — NOT replacing it. Shows where the user's money went
// relative to what came in.
//
// If savings is negative (overspent), we clamp the slice to 0 — a negative
// pie slice isn't renderable. The Tooltip still shows the true (negative)
// value so the user sees the real number.
const SLICE_COLORS = {
  Spent: "#ef4444",    // red
  Savings: "#10b981",  // green
};

export default function IncomeSavingsChart({ budget }) {
  if (!budget) return null;

  const income = Number(budget.income || 0);
  const spent = Number(budget.total_spent || 0);
  const savings = Number(budget.savings || 0);

  // If no income and no spending, there's nothing to show — display a hint
  // instead of an empty pie.
  if (income === 0 && spent === 0) {
    return (
      <div className="bg-white border border-slate-200 rounded-lg p-4">
        <h3 className="text-lg font-medium text-slate-900 mb-2">
          Income vs Spent — {budget.month}
        </h3>
        <p className="text-sm text-slate-500 italic">
          Set your income in Settings to see the breakdown.
        </p>
      </div>
    );
  }

  // Build the pie data. Savings can be negative (overspent) — clamp to 0
  // for the slice size but keep the true value in the label.
  const data = [
    { name: "Spent", value: spent, trueValue: spent },
    { name: "Savings", value: Math.max(0, savings), trueValue: savings },
  ].filter((d) => d.value > 0 || d.trueValue !== 0);

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <h3 className="text-lg font-medium text-slate-900 mb-1">
        Income vs Spent — {budget.month}
      </h3>
      <div className="text-xs text-slate-500 mb-3">
        Income: ₹{income.toLocaleString()} · Savings: ₹{savings.toLocaleString()}
      </div>
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
                  fill={SLICE_COLORS[entry.name] || "#cbd5e1"}
                />
              ))}
            </Pie>
            <Tooltip
              formatter={(value, name, props) =>
                `₹${Number(props.payload.trueValue).toLocaleString()}`
              }
            />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
