import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, host: "127.0.0.1" },
  // Production: `vite preview` serves the built dist/ on localhost only, and
  // nginx proxies server.idsservices.us to it. allowedHosts lets the proxied
  // Host header through.
  preview: {
    port: 8011,
    host: "127.0.0.1",
    strictPort: true,
    allowedHosts: ["server.idsservices.us"],
  },
});
