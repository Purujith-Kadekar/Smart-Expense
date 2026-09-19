/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Tailwind palette tuned for a campus-admin dashboard — calm
        // indigo primary with an amber accent for budget warnings.
        brand: {
          50: "#eef2ff",
          100: "#e0e7ff",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
        },
        warn: {
          50: "#fffbeb",
          500: "#f59e0b",
          700: "#b45309",
        },
      },
    },
  },
  plugins: [],
};
