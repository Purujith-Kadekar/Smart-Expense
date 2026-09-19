import { Link } from "react-router-dom";

// Minimalist landing page.
// Hero → 3-feature row → single primary CTA → footer-style hint.
// Deliberately short: a landing page's job is to get the user to the
// dashboard in one click, not to read like a brochure.
const features = [
  {
    title: "Drop a photo, done.",
    body: "Drag-and-drop a receipt. OCR runs locally to pull vendor, amount, and date automatically — no manual data entry, no paid API.",
    icon: "📸",
  },
  {
    title: "Live budget tracking.",
    body: "Dashboard polls every few seconds. Spent vs. remaining is one glance away; over-budget expenses are flagged red instantly.",
    icon: "📊",
  },
  {
    title: "Auto-alert the advisor.",
    body: "Cross the budget limit and the faculty advisor gets an email via SNS — no Slack ping, no paper trail to chase.",
    icon: "✉️",
  },
];

export default function Landing() {
  return (
    <div className="space-y-12">
      {/* Hero — left-aligned, no centered jumbo-tron. One short headline,
          one short subhead, one CTA. */}
      <section className="pt-10">
        <p className="text-sm font-medium text-brand-600 mb-3">
          Outlay
        </p>
        <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl max-w-2xl">
          Receipts in, reimbursements out. No spreadsheet required.
        </h1>
        <p className="mt-5 text-lg text-slate-600 max-w-2xl">
          Upload a photo of any club-event receipt. We OCR it, store it, and
          alert your faculty advisor automatically when something goes over
          budget.
        </p>
        <div className="mt-8 flex gap-3">
          <Link
            to="/dashboard"
            className="inline-flex items-center px-5 py-2.5 rounded-md bg-brand-600 text-white text-sm font-medium hover:bg-brand-700 transition-colors"
          >
            Open Dashboard
          </Link>
          <Link
            to="/upload"
            className="inline-flex items-center px-5 py-2.5 rounded-md border border-slate-300 bg-white text-slate-700 text-sm font-medium hover:bg-slate-50 transition-colors"
          >
            Upload a receipt
          </Link>
        </div>
      </section>

      {/* Feature row — three short cards, no icons-in-circles, no gradients. */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {features.map((f) => (
          <div
            key={f.title}
            className="bg-white border border-slate-200 rounded-lg p-5"
          >
            <div className="text-2xl mb-3" aria-hidden="true">
              {f.icon}
            </div>
            <h3 className="text-base font-semibold text-slate-900 mb-2">
              {f.title}
            </h3>
            <p className="text-sm text-slate-600 leading-relaxed">
              {f.body}
            </p>
          </div>
        ))}
      </section>

      {/* How it works — four steps in a single horizontal strip. */}
      <section className="border-t border-slate-200 pt-8">
        <h2 className="text-sm font-medium text-slate-500 mb-4">
          How it works
        </h2>
        <ol className="grid grid-cols-1 sm:grid-cols-4 gap-4 text-sm">
          <li>
            <span className="text-brand-600 font-semibold">1.</span>{" "}
            <span className="text-slate-700">Drop receipt photo</span>
          </li>
          <li>
            <span className="text-brand-600 font-semibold">2.</span>{" "}
            <span className="text-slate-700">S3 → Lambda → local OCR</span>
          </li>
          <li>
            <span className="text-brand-600 font-semibold">3.</span>{" "}
            <span className="text-slate-700">Record lands in DynamoDB</span>
          </li>
          <li>
            <span className="text-brand-600 font-semibold">4.</span>{" "}
            <span className="text-slate-700">Advisor emailed if over budget</span>
          </li>
        </ol>
      </section>
    </div>
  );
}
