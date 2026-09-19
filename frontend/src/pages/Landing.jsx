import { Link } from "react-router-dom";

// Liquid Glass landing page.
// Structure preserved exactly: Hero → 3-feature row → How it works → CTA hint.
// Only visual presentation changed; all routes / links / copy intent intact.

const features = [
  {
    title: "Drop a photo, done.",
    body: "Drag-and-drop a receipt. OCR runs locally to pull vendor, amount, and date automatically — no manual data entry, no paid API.",
    icon: "camera",
  },
  {
    title: "Live budget tracking.",
    body: "Dashboard polls every few seconds. Spent vs. remaining is one glance away; over-budget expenses are flagged red instantly.",
    icon: "chart",
  },
  {
    title: "Auto-alert the advisor.",
    body: "Cross the budget limit and the faculty advisor gets an email via SNS — no Slack ping, no paper trail to chase.",
    icon: "mail",
  },
];

// Inline SVG icons — consistent line weight with the header icons.
const FeatureIcon = ({ name, ...props }) => {
  const paths = {
    camera: (
      <>
        <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.7a1 1 0 0 0 .85-.47l.5-.85A2 2 0 0 1 10.8 4h2.4a2 2 0 0 1 1.75 1.03l.5.85a1 1 0 0 0 .85.47h1.7A2.5 2.5 0 0 1 19 8.5v8A2.5 2.5 0 0 1 16.5 19h-9A2.5 2.5 0 0 1 5 16.5v-8Z" />
        <circle cx="12" cy="12" r="3.5" />
      </>
    ),
    chart: (
      <>
        <path d="M4 19V5" />
        <path d="M4 19h16" />
        <path d="M8 16v-4" />
        <path d="M12 16V8" />
        <path d="M16 16v-6" />
      </>
    ),
    mail: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2.5" />
        <path d="M4 7l8 6 8-6" />
      </>
    ),
  };
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
      {...props}>
      {paths[name]}
    </svg>
  );
};

const steps = [
  { n: "1", label: "Drop receipt photo" },
  { n: "2", label: "S3 → Lambda → local OCR" },
  { n: "3", label: "Record lands in DynamoDB" },
  { n: "4", label: "Advisor emailed if over budget" },
];

export default function Landing() {
  return (
    <div className="space-y-16 sm:space-y-20">
      {/* ──────────────────────────────────────────────────── Hero ──────────────────────────────────────────────────── */}
      <section className="pt-6 sm:pt-10">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-center">
          {/* Left — copy + CTAs */}
          <div className="lg:col-span-7 space-y-6">
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full glass-subtle text-xs font-medium text-brand-700 animate-fade-in">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-500 animate-pulse-soft" />
              Outlay · Smart receipt budgeting
            </span>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-ink-900 leading-[1.05]">
              Receipts in,{" "}
              <span className="relative">
                <span className="relative z-10 bg-gradient-to-r from-brand-600 via-brand-500 to-brand-700 bg-clip-text text-transparent">
                  reimbursements
                </span>
                <span className="absolute -bottom-1 left-0 right-0 h-2 bg-brand-100/80 rounded-full -z-0" />
              </span>{" "}
              out.
            </h1>
            <p className="text-lg text-ink-600 leading-relaxed max-w-2xl">
              Upload a photo of any club-event receipt. We OCR it, store it,
              and alert your faculty advisor automatically when something goes
              over budget — no spreadsheet required.
            </p>
            <div className="flex flex-wrap gap-3 pt-2">
              <Link to="/dashboard" className="btn-primary">
                <span>Open Dashboard</span>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  className="w-4 h-4">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </Link>
              <Link to="/upload" className="btn-secondary">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                  className="w-4 h-4">
                  <path d="M12 16V4M7 9l5-5 5 5M5 16v3a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3" />
                </svg>
                <span>Upload a receipt</span>
              </Link>
            </div>

            {/* Tiny stats row */}
            <div className="flex items-center gap-6 pt-4 text-sm text-ink-500">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                Local OCR — no API key
              </div>
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-brand-500" />
                Auto-email advisor
              </div>
            </div>
          </div>

          {/* Right — floating glass preview tile */}
          <div className="lg:col-span-5 relative">
            <div className="relative animate-scale-in">
              {/* Glow halo */}
              <div className="absolute -inset-4 bg-gradient-to-br from-brand-200/40 to-amber-100/30 blur-3xl rounded-full" />

              {/* Main glass card */}
              <div className="relative glass rounded-3xl p-6 shadow-soft-xl">
                <div className="flex items-center justify-between mb-5">
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-rose-400" />
                    <div className="w-2.5 h-2.5 rounded-full bg-amber-400" />
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
                  </div>
                  <span className="text-xs font-medium text-ink-400">dashboard</span>
                </div>

                {/* Mock metric row */}
                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className="glass-subtle rounded-xl p-3.5">
                    <div className="text-xs text-ink-500 mb-1">Spent</div>
                    <div className="text-xl font-bold text-ink-900">₹4,820</div>
                    <div className="text-[11px] text-ink-400 mt-0.5">of ₹6,000</div>
                  </div>
                  <div className="glass-subtle rounded-xl p-3.5">
                    <div className="text-xs text-ink-500 mb-1">Savings</div>
                    <div className="text-xl font-bold text-emerald-600">₹1,180</div>
                    <div className="text-[11px] text-ink-400 mt-0.5">this month</div>
                  </div>
                </div>

                {/* Mock mini chart */}
                <div className="glass-subtle rounded-xl p-3.5">
                  <div className="flex items-end gap-1.5 h-20 mb-2">
                    {[40, 65, 50, 80, 55, 70, 45].map((h, i) => (
                      <div
                        key={i}
                        className="flex-1 rounded-t bg-gradient-to-t from-brand-300 to-brand-600"
                        style={{ height: `${h}%` }}
                      />
                    ))}
                  </div>
                  <div className="text-[11px] text-ink-400">7-day spend trend</div>
                </div>
              </div>

              {/* Floating accent chip */}
              <div className="absolute -top-3 -right-3 glass-strong rounded-full px-3 py-1.5 text-xs font-semibold text-emerald-700 shadow-soft">
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-soft" />
                  Over budget → email sent
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ───────────────────────────────────────────────── Feature row ───────────────────────────────────────────────── */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {features.map((f, i) => (
          <div
            key={f.title}
            className="group glass rounded-2xl p-6 transition-all duration-300 ease-out hover:-translate-y-1 hover:shadow-soft-lg animate-fade-in"
            style={{ animationDelay: `${i * 70}ms` }}
          >
            <div className="inline-flex items-center justify-center w-11 h-11 rounded-xl bg-gradient-to-br from-brand-500/15 to-brand-600/10 text-brand-700 mb-4 group-hover:from-brand-500/25 group-hover:to-brand-600/15 transition-colors">
              <FeatureIcon name={f.icon} className="w-5 h-5" />
            </div>
            <h3 className="text-base font-semibold text-ink-900 mb-2 tracking-tight">
              {f.title}
            </h3>
            <p className="text-sm text-ink-600 leading-relaxed">
              {f.body}
            </p>
          </div>
        ))}
      </section>

      {/* ───────────────────────────────────────────────── How it works ───────────────────────────────────────────────── */}
      <section className="glass rounded-2xl p-6 sm:p-8">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-6">
          <div>
            <p className="eyebrow mb-1.5">Process</p>
            <h2 className="text-xl font-bold text-ink-900 tracking-tight">How it works</h2>
          </div>
          <span className="text-xs text-ink-400">Four steps · zero manual data entry</span>
        </div>
        <ol className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {steps.map((s, i) => (
            <li
              key={s.n}
              className="relative glass-subtle rounded-xl p-4 transition-all duration-300 hover:bg-white/70 animate-fade-in"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-brand-600 text-white text-sm font-semibold shadow-brand">
                  {s.n}
                </span>
                {i < steps.length - 1 && (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                    className="w-3.5 h-3.5 text-ink-300 hidden sm:block ml-auto">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                )}
              </div>
              <span className="text-sm text-ink-700 font-medium">{s.label}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
