/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import { defineConfig } from "vite";

// The API is same-origin: these paths go to the Auth Server, everything else is this app.
const API_PATHS = ["/v1", "/oauth", "/bff", "/.well-known", "/health"];
const apiTarget = process.env.API_TARGET ?? "http://127.0.0.1:8000";
const port = Number(process.env.PORT ?? 5181);

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    tailwindcss(),
    mode === "analyze" && visualizer({ filename: "dist/stats.html", gzipSize: true, open: false }),
    mode === "analyze" && visualizer({ filename: "dist/stats.json", template: "raw-data", gzipSize: true }),
  ],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port,
    strictPort: true,
    // Keep the browser's Host header: the server's ISSUER, cookies and WebAuthn origin are this origin.
    proxy: Object.fromEntries(API_PATHS.map((path) => [path, { target: apiTarget, changeOrigin: false }])),
  },
  preview: { port, strictPort: true },
  build: {
    target: "es2022",
    sourcemap: false,
    rollupOptions: {
      output: {
        // Libraries the login page never uses get their own chunks, so they aren't folded into a shared
        // chunk that the login page (loaded by every app's users) would download.
        advancedChunks: {
          // Without this a group also captures its dependencies (React itself), forcing every page to load it.
          includeDependenciesRecursively: false,
          groups: [
            { name: "forms", test: /node_modules[\\/](zod|react-hook-form|@hookform)[\\/]/ },
            { name: "radix", test: /node_modules[\\/]@radix-ui[\\/](?!react-slot|react-compose-refs)/ },
            { name: "toasts", test: /node_modules[\\/]sonner[\\/]/ },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
}));
