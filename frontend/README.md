# Outlay — Redesigned Frontend

Premium minimalist redesign with subtle Liquid Glass / glassmorphism aesthetic.
**100% feature parity with the original** — every page, button, input, API call,
auth flow, and state preserved.

## What changed

- **Visual system only.** Every component's logic, state hooks, API calls,
  error mappings, and event handlers are identical to the original.
- Liquid Glass surfaces (`.glass`, `.glass-strong`, `.glass-subtle`, `.glass-tint`)
  implemented via `backdrop-filter: blur()` + semi-transparent backgrounds +
  soft inset highlights.
- Premium typography: Inter, tight tracking on headings.
- Restrained palette: indigo primary (`brand`) + neutral slate (`ink`) + amber
  for budget warnings. WCAG-friendly contrast on all text.
- Micro-interactions: hover lifts, button feedback, modal/scale-in animations,
  shimmer skeletons for loading, slide-down for mobile nav.
- Responsive across desktop / tablet / mobile (mobile hamburger nav with glass dropdown).

## Functionality preserved (no regressions)

| Area | Status |
|---|---|
| Routes (Landing, Login, Register, Dashboard, Upload, Settings) | unchanged |
| Auth (localStorage token/user_id/email, 401 redirect, ProtectedRoute) | unchanged |
| API client interceptors (Bearer header, CORS hint) | unchanged |
| Dashboard 15s polling, month picker, refresh | unchanged |
| Upload flow (presigned PUT → S3 → trigger-ocr) | unchanged |
| Settings budget POST + pre-fill on month change | unchanged |
| ExpenseTable multi-select, email-bill feature, all error codes | unchanged |
| 3 charts (BudgetChart, CategoryChart, IncomeSavingsChart) — same data shape | unchanged |

## Local development

```bash
npm install
npm run dev          # http://localhost:5173
npm run build       # static dist/
```

To run with the full backend (Flask + LocalStack + Lambda):

```bash
# Backend files preserved in /_backend_backup
cd _backend_backup && docker-compose up
```
