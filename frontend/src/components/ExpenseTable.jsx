import { useState } from "react";
import api from "../api/client.js";

// Liquid Glass ExpenseTable.
//
// Logic preserved bit-for-bit:
//   - per-row checkboxes (Set-based selection)
//   - toggle all
//   - running "N selected, total ₹X" summary
//   - inline email form (recipient + description + Send)
//   - POST /api/expenses/email with receipt_ids, recipient_email, description
//   - success/error messages with the same error-code mapping as the original
//   - empty state when no expenses
//   - per-row "Over budget" / "Within budget" badge
//   - per-row category chip with color

// Category → glass chip color classes. Same hues as the original but the
// surfaces are translucent to match the glass aesthetic.
const CATEGORY_STYLES = {
  college: {
    glass: "bg-blue-500/15 text-blue-700 border-blue-400/30",
    dot: "bg-blue-500",
  },
  mess: {
    glass: "bg-amber-500/15 text-amber-700 border-amber-400/30",
    dot: "bg-amber-500",
  },
  event: {
    glass: "bg-purple-500/15 text-purple-700 border-purple-400/30",
    dot: "bg-purple-500",
  },
  other: {
    glass: "bg-ink-500/15 text-ink-700 border-ink-400/30",
    dot: "bg-ink-500",
  },
};

export default function ExpenseTable({ expenses }) {
  const [selected, setSelected] = useState(new Set());
  const [recipientEmail, setRecipientEmail] = useState("");
  const [description, setDescription] = useState("");
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Empty state — identical copy and intent as the original.
  if (!expenses || expenses.length === 0) {
    return (
      <div className="glass rounded-2xl p-10 text-center animate-fade-in">
        <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-gradient-to-br from-ink-500/15 to-ink-700/10 text-ink-500 mb-3">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
            strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
          </svg>
        </div>
        <p className="text-sm font-medium text-ink-700">No expenses recorded yet.</p>
        <p className="text-xs text-ink-400 mt-1">
          Upload a receipt to get started.
        </p>
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

  // handleSendEmail — identical to the original, including all the
  // backend error-code → user-message mappings.
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

  const allSelected = selected.size === expenses.length && expenses.length > 0;

  return (
    <div className="space-y-3 animate-fade-in">
      {/* ───────── Table card ───────── */}
      <div className="glass rounded-2xl overflow-hidden shadow-soft">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-white/40 text-sm">
            <thead>
              <tr className="bg-white/30">
                <th scope="col" className="px-4 py-3 text-left w-10">
                  <label className="inline-flex items-center justify-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="peer sr-only"
                      aria-label="Select all"
                    />
                    <span className="w-4.5 h-4.5 rounded-md border border-ink-300 bg-white/70 peer-checked:bg-brand-600 peer-checked:border-brand-600 peer-focus-visible:ring-2 peer-focus-visible:ring-brand-400/60 transition-all flex items-center justify-center">
                      {allSelected && (
                        <svg viewBox="0 0 16 16" fill="none" stroke="white" strokeWidth="2"
                          strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                          <path d="M3 8.5l3 3 7-7" />
                        </svg>
                      )}
                    </span>
                  </label>
                </th>
                <th scope="col" className="px-4 py-3 text-left font-medium text-ink-500">
                  Vendor
                </th>
                <th scope="col" className="px-4 py-3 text-left font-medium text-ink-500">
                  Category
                </th>
                <th scope="col" className="px-4 py-3 text-left font-medium text-ink-500">
                  Date
                </th>
                <th scope="col" className="px-4 py-3 text-right font-medium text-ink-500">
                  Amount
                </th>
                <th scope="col" className="px-4 py-3 text-center font-medium text-ink-500">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/40">
              {expenses.map((e, i) => {
                const cat = e.category || "other";
                const chipStyle = CATEGORY_STYLES[cat] || CATEGORY_STYLES.other;
                const isSelected = selected.has(e.expense_id);
                return (
                  <tr
                    key={e.expense_id}
                    className={`group transition-colors duration-200 ${
                      isSelected
                        ? "bg-brand-50/60"
                        : "hover:bg-white/45"
                    }`}
                    style={{ animationDelay: `${i * 30}ms` }}
                  >
                    <td className="px-4 py-3">
                      <label className="inline-flex items-center justify-center cursor-pointer">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRow(e.expense_id)}
                          className="peer sr-only"
                          aria-label={`Select ${e.vendor}`}
                        />
                        <span className={`w-4.5 h-4.5 rounded-md border transition-all flex items-center justify-center
                          ${isSelected
                            ? "bg-brand-600 border-brand-600"
                            : "border-ink-300 bg-white/70 group-hover:border-ink-400"}
                          peer-focus-visible:ring-2 peer-focus-visible:ring-brand-400/60`}>
                          {isSelected && (
                            <svg viewBox="0 0 16 16" fill="none" stroke="white" strokeWidth="2"
                              strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3">
                              <path d="M3 8.5l3 3 7-7" />
                            </svg>
                          )}
                        </span>
                      </label>
                    </td>
                    <td className="px-4 py-3 text-ink-900 font-medium">
                      {e.vendor || "—"}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`chip border ${chipStyle.glass}`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${chipStyle.dot}`} />
                        {cat}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-ink-600 tabular-nums">
                      {e.date || "—"}
                    </td>
                    <td className="px-4 py-3 text-right text-ink-900 font-semibold tabular-nums">
                      ₹{Number(e.amount || 0).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {e.over_budget ? (
                        <span className="chip border border-amber-400/30 bg-amber-500/15 text-amber-700">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                          Over budget
                        </span>
                      ) : (
                        <span className="chip border border-emerald-400/30 bg-emerald-500/15 text-emerald-700">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
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
      </div>

      {/* ───────── Selection summary + email form — only show when at least one row is selected ───────── */}
      {selected.size > 0 && (
        <div className="glass-tint rounded-2xl p-4 sm:p-5 space-y-3 animate-scale-in">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 text-sm text-ink-700">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-brand-600 text-white text-xs font-bold shadow-brand">
                {selected.size}
              </span>
              <span className="font-medium">{selected.size}</span> selected ·{" "}
              <span className="font-semibold text-ink-900">
                ₹{selectedTotal.toLocaleString()}
              </span>{" "}
              total
            </div>
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              className="btn-ghost !text-ink-500"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
              Clear selection
            </button>
          </div>

          <form
            onSubmit={handleSendEmail}
            className="grid grid-cols-1 sm:grid-cols-2 gap-3"
          >
            <div>
              <label className="block text-xs font-medium text-ink-600 mb-1">
                Recipient email
              </label>
              <input
                type="email"
                value={recipientEmail}
                onChange={(e) => setRecipientEmail(e.target.value)}
                required
                placeholder="advisor@example.edu"
                className="input-glass text-sm"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-ink-600 mb-1">
                Description (optional)
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="September cultural fest expenses"
                className="input-glass text-sm"
              />
            </div>
            <div className="sm:col-span-2 flex items-center gap-3 pt-1">
              <button
                type="submit"
                disabled={sending}
                className="btn-primary"
              >
                {sending ? (
                  <>
                    <span className="w-4 h-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
                    Sending…
                  </>
                ) : (
                  <>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                      strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                      <rect x="3" y="5" width="18" height="14" rx="2.5" />
                      <path d="M4 7l8 6 8-6" />
                    </svg>
                    {`Email ${selected.size} receipt${selected.size > 1 ? "s" : ""} as bill`}
                  </>
                )}
              </button>
            </div>
          </form>

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
        </div>
      )}
    </div>
  );
}
