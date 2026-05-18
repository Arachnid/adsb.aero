import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // Bind to 0.0.0.0 so the nginx container can reach Vite when running in Docker
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    exclude: ["e2e/**", "node_modules/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**"],
      exclude: [
        "src/main.tsx",
        "src/types/**",
        "src/lib/api.ts",
        "src/components/map/MapView.tsx",
      ],
      thresholds: {
        lines: 78,
        functions: 50,
        branches: 78,
      },
    },
  },
});
