/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: "#7B61FF",
        surface: {
          0: "#0a0a0a",
          1: "#111111",
          2: "#1a1a1a",
          3: "#222222",
        },
        border: "#2a2a2a",
        muted: "#666666",
        fg: "#e0e0e0",
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"SF Mono"', "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
