// web/tailwind.config.ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  // lib/ holds class-name tables (RATING_COLORS, COST_TIER_COLORS in
  // lib/catalog-fields.ts); leaving it out of the scan purged those classes
  // from the CSS, which is why only the neutral B/Low pills ever rendered.
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
    "./lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          slate: {
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
          accent: {
            DEFAULT: "#2563eb",
            hover: "#1d4ed8",
            muted: "#dbeafe",
          },
        },
      },
    },
  },
  plugins: [],
};

export default config;
