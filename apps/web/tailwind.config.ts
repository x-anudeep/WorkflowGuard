import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#15171a",
        panel: "#f6f7f9",
        line: "#d9dee6",
        ok: "#168463",
        warn: "#b7791f",
        danger: "#b42318",
        accent: "#2563eb"
      },
      boxShadow: {
        soft: "0 10px 30px rgba(18, 24, 38, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
