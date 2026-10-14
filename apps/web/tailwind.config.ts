import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["var(--font-display)", "system-ui", "sans-serif"],
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      colors: {
        paper: { 50: "#FAFAF9", 100: "#F5F5F4", 200: "#E7E5E4" },
        pine: {
          50: "#ECFDF5", 100: "#D1FAE5",
          600: "#059669", 700: "#047857", 800: "#065F46",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
