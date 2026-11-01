/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#14213d", soft: "#5b6478" },
        brand: { DEFAULT: "#1d4ed8", dark: "#1e3a8a", tint: "#eff4ff" },
        line: "#e3e7ee",
        canvas: "#f6f7fa",
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
    },
  },
  plugins: [],
};
