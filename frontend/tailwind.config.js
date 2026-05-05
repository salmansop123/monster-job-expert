/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        display: ["Outfit", "system-ui", "sans-serif"],
      },
      colors: {
        ink: { 950: "#0b1020", 900: "#121a2e", 800: "#1c2740" },
        accent: { DEFAULT: "#6366f1", dim: "#4f46e5" },
      },
      boxShadow: {
        card: "0 4px 24px -4px rgba(15, 23, 42, 0.35)",
      },
    },
  },
  plugins: [],
};
