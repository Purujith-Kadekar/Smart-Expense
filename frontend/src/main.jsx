import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import "./index.css";

// Opt into ALL v7 future flags now so React Router stops emitting
// development-only warnings. The behaviour is identical to v6 for each
// flag; the flag just silences the warning ahead of the v6 → v7 upgrade.
// Safe to leave on permanently — these will become defaults in v7.
//
// Warnings silenced:
//   v7_startTransition       — "React Router will begin wrapping state
//                              updates in React.startTransition in v7"
//   v7_relativeSplatPath     — "Relative route resolution within Splat
//                              routes is changing in v7"
//   v7_fetcherPersist        — fetchers persist on navigation
//   v7_normalizeFormMethod   — formMethod casing normalised
//   v7_partialSubmitSession  — partial form submissions preserve session
const routerFutureFlags = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
  v7_fetcherPersist: true,
  v7_normalizeFormMethod: true,
  v7_partialSubmitSession: true,
};

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter future={routerFutureFlags}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
