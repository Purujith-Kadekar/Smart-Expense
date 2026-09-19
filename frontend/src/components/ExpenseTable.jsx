import { useState } from "react";
import api from "../api/client.js";

// Expense table with:
//   - per-row checkboxes for selection
//   - a running "N selected, total ₹X" summary
//   - an inline email form (recipient + description + Send button) that
//     calls POST /api/expenses/email with the selected receipt_ids.
//
// The email form reuses the same success/error message pattern as
// Upload.jsx (green box on success, red box on error).
const CATEGORY_STYLES = {
  college: "bg-blue-50 text-blue-700",
  mess: "bg-amber-50 text-amber-700",
  event: "bg-purple-50 text-purple-700",
  other: "bg-slate-100 text-slate-600",
};

export default function ExpenseTable({ expenses }) {
  const [selected, setSelected] = useState(new Set());
  const [recipientEmail, setRecipientEmail] = useState("");
  const [description, setDescription] = useState("");
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  if (!expenses || expenses.length === 0) {
    return (
      <div className="text-sm text-slate-500 italic">
        No expenses recorded yet. Upload a receipt to get started.
      </div>
    );
  }

  const selectedItems = expenses.filter((e) => selected.has(e.expense_id));
  const selectedTotal = selectedItems.reduce(
    (sum, e) => sum + Number(e.amount || 0),
    0
  );

  const toggleRow = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === expenses.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(expenses.map((e) => e.expense_id)));
    }
  };

  const handleSendEmail = async (e) => {
    e.preventDefault();
    setSending(true);
    setError("");
    setMessage("");
    try {
      const ids = Array.from(selected);
      const { data } = await api.post("/expenses/email", {
        receipt_ids: ids,
        recipient_email: recipientEmail,
        description,
      });
      setMessage(
        `Bill emailed to ${data.recipient} — ${data.sent_count} receipt(s), ` +
          `total ₹${Number(data.total).toLocaleString()}.`
      );
      // Clear the form + selection after a successful send.
      setRecipientEmail("");
      setDescription("");
      setSelected(new Set());
    } catch (err) {
      const code = err?.response?.data?.error;
      if (code === "receipt_not_owned") {
        setError("One or more selected receipts don't belong to you. Deselect and try again.");
      } else if (code === "invalid_recipient_email") {
        setError("Please enter a valid recipient email address.");
      } else if (code === "no_receipt_ids") {
        setError("Select at least one receipt first.");
      } else if (code === "too_many_receipts") {
        setError("Too many receipts selected — limit is 50 per email.");
      } else {
        setError(err?.response?.data?.error || err?.error || "Failed to send email.");
      }
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto bg-white border border-slate-200 rounded-lg">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left w-10">
                <input
                  type="checkbox"
                  checked={selected.size === expenses.length && expenses.length > 0}
                  onChange={toggleAll}
                  className="rounded border-slate-300"
                  aria-label="Select all"
                />
              </th>
              <th className="px-4 py-2 text-left font-medium text-slate-600">Vendor</th>
              <th className="px-4 py-2 text-left font-medium text-slate-600">Category</th>
              <th className="px-4 py-2 text-left font-medium text-slate-600">Date</th>
              <th className="px-4 py-2 text-right font-medium text-slate-600">Amount</th>
              <th className="px-4 py-2 text-center font-medium text-slate-600">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {expenses.map((e) => {
              const cat = e.category || "other";
              const chipStyle = CATEGORY_STYLES[cat] || CATEGORY_STYLES.other;
              const isSelected = selected.has(e.expense_id);
              return (
                <tr
                  key={e.expense_id}
                  className={isSelected ? "bg-brand-50" : "hover:bg-slate-50"}
                >
                  <td className="px-4 py-2">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleRow(e.expense_id)}
                      className="rounded border-slate-300"
                      aria-label={`Select ${e.vendor}`}
                    />
                  </td>
                  <td className="px-4 py-2 text-slate-900">{e.vendor || "—"}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium capitalize ${chipStyle}`}
                    >
                      {cat}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-600">{e.date || "—"}</td>
                  <td className="px-4 py-2 text-right text-slate-900">
                    ₹{Number(e.amount || 0).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-center">
                    {e.over_budget ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-warn-50 text-warn-700">
                        Over budget
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-50 text-green-700">
                        Within budget
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Selection summary + email form — only show when at least one row is selected. */}
      {selected.size > 0 && (
        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
          <div className="text-sm text-slate-700">
            <span className="font-medium">{selected.size}</span> selected ·{" "}
            <span className="font-medium">₹{selectedTotal.toLocaleString()}</span> total
          </div>

          <form onSubmit={handleSendEmail} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Recipient email
              </label>
              <input
                type="email"
                value={recipientEmail}
                onChange={(e) => setRecipientEmail(e.target.value)}
                required
                placeholder="advisor@example.edu"
                className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Description (optional)
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="September cultural fest expenses"
                className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
            </div>
            <div className="sm:col-span-2 flex items-center gap-3">
              <button
                type="submit"
                disabled={sending}
                className="px-4 py-2 bg-brand-600 text-white rounded-md text-sm font-medium hover:bg-brand-700 disabled:opacity-60 transition-colors"
              >
                {sending ? "Sending…" : `Email ${selected.size} receipt${selected.size > 1 ? "s" : ""} as bill`}
              </button>
              <button
                type="button"
                onClick={() => setSelected(new Set())}
                className="px-3 py-2 text-sm text-slate-600 hover:text-slate-900"
              >
                Clear selection
              </button>
            </div>
          </form>

          {message && (
            <div className="bg-green-50 border border-green-200 text-green-800 text-sm rounded-md p-2">
              {message}
            </div>
          )}
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded-md p-2">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
