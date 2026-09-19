/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Calm indigo primary — kept from the original brand so the existing
        // Tailwind class names (`bg-brand-600`, `text-brand-700`, etc.) keep
        // working everywhere without a sweep of find-and-replace.
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
        },
        warn: {
          50: "#fffbeb",
          100: "#fef3c7",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
        },
        // Neutral surface palette tuned for layered translucent surfaces.
        ink: {
          50: "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
          950: "#020617",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        display: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
      },
      borderRadius: {
        // Slightly more generous radii for the soft, premium look.
        xl: "1rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      boxShadow: {
        // Soft, layered shadows used behind glass surfaces. The first value
        // is a tight ambient shadow, the second is a longer diffuse one —
        // together they simulate realistic light wrap-around.
        "soft-sm": "0 1px 2px rgba(15,23,42,0.04), 0 1px 3px rgba(15,23,42,0.06)",
        soft: "0 2px 6px rgba(15,23,42,0.05), 0 4px 16px rgba(15,23,42,0.06)",
        "soft-lg":
          "0 4px 12px rgba(15,23,42,0.06), 0 12px 32px rgba(15,23,42,0.08)",
        "soft-xl":
          "0 8px 24px rgba(15,23,42,0.08), 0 24px 64px rgba(15,23,42,0.10)",
        // Inset highlight used at the top edge of glass surfaces to simulate
        // a thin reflected light. Pair with `border-white/40` for full effect.
        "inset-highlight":
          "inset 0 1px 0 0 rgba(255,255,255,0.55), inset 0 -1px 0 0 rgba(15,23,42,0.04)",
        brand: "0 8px 24px rgba(79,70,229,0.25), 0 2px 6px rgba(79,70,229,0.18)",
      },
      backdropBlur: {
        xs: "2px",
        // 16px is the sweet spot for the liquid-glass effect — enough to
        // read content over without the surface feeling frosted opaque.
        glass: "16px",
        "glass-lg": "24px",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "scale(0.96)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        "slide-down": {
          "0%": { opacity: "0", transform: "translateY(-8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.4s ease-out both",
        "scale-in": "scale-in 0.3s ease-out both",
        "slide-down": "slide-down 0.4s ease-out both",
        shimmer: "shimmer 1.6s linear infinite",
        "pulse-soft": "pulse-soft 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
