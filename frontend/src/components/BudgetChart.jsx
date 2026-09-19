import { Cell, Pie, PieChart, ResponsiveContainer, Legend } from "recharts";

// Simple two-slice pie: spent vs remaining. Chosen over a bar chart
// because it reads instantly in a 30-second demo pitch.
export default function BudgetChart({ budget }) {
  const spent = Number(budget.total_spent || 0);
  const limit = Number(budget.budget_limit || 0);
  const remaining = Math.max(0, limit - spent);

  const data = [
    { name: "Spent", value: spent },
    { name: "Remaining", value: remaining },
  ];
  const colors = ["#4f46e5", "#e2e8f0"];

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-medium text-slate-900">Budget status</h3>
        <div className="text-right">
          <div className="text-2xl font-semibold text-brand-700">
            ₹{spent.toLocaleString()}
          </div>
          <div className="text-xs text-slate-500">
            of ₹{limit.toLocaleString()} limit
          </div>
        </div>
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
              {data.map((_, i) => (
                <Cell key={i} fill={colors[i % colors.length]} />
              ))}
            </Pie>
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-2 text-sm text-slate-600">
        {remaining > 0 ? (
          <span>
            ₹{remaining.toLocaleString()} remaining under your budget limit.
          </span>
        ) : (
          <span className="text-warn-700 font-medium">
            Budget exhausted — you've hit your spending limit for the month.
          </span>
        )}
      </div>
    </div>
  );
}
