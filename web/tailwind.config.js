/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      colors: {
        "bg-0": "var(--bg-0)",
        "bg-1": "var(--bg-1)",
        "bg-2": "var(--bg-2)",
        "bg-3": "var(--bg-3)",
        "fg-0": "var(--fg-0)",
        "fg-1": "var(--fg-1)",
        "fg-2": "var(--fg-2)",
        "fg-3": "var(--fg-3)",
        "line-1": "var(--line-1)",
        "line-2": "var(--line-2)",
        "line-3": "var(--line-3)",
        accent: "var(--accent)",
        "accent-2": "var(--accent-2)",
        warn: "var(--warn)",
        danger: "var(--danger)",
        ok: "var(--ok)",
      },
    },
  },
  plugins: [],
};
