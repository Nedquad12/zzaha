import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["var(--font-display)", "monospace"],
        mono:    ["var(--font-mono)", "monospace"],
      },
      colors: {
        bg:       "#080c10",
        surface:  "#0d1117",
        card:     "#111820",
        border:   "#1e2a38",
        muted:    "#3a4a5c",
        text:     "#c9d1d9",
        dim:      "#8b949e",
        bull:     "#3fb950",
        bear:     "#f85149",
        gold:     "#d4a72c",
        accent:   "#388bfd",
        "bull-dim": "#1a3a22",
        "bear-dim": "#3a1a1a",
        "gold-dim": "#3a2e0a",
      },
      boxShadow: {
        glow:     "0 0 20px rgba(56,139,253,0.15)",
        "glow-bull": "0 0 16px rgba(63,185,80,0.2)",
        "glow-bear": "0 0 16px rgba(248,81,73,0.2)",
      },
    },
  },
  plugins: [],
};
export default config;
