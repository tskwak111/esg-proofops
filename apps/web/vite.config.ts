import { runIdFromResultPath } from "./src/features/hosted/hostedHistory";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "../..", "");
  const api = env.API_PUBLIC_BASE_URL || "http://localhost:8000";
  return {
    envDir: "../..",
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { "/hosted-api": { target: api, changeOrigin: true, rewrite: path => path.replace(/^\/hosted-api/, "") }, "/v1": { target: api, bypass: request => request.headers.accept?.includes("text/html") && runIdFromResultPath((request.url ?? "").split("?", 1)[0]) ? "/index.html" : undefined }, "/auth": api, "/local/uploads": api, "/local/sources": api },
    },
  };
});
