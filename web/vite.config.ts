import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API has no CORS middleware, so everything the client calls is proxied to
// the FastAPI server rather than fetched cross-origin. Keeps the backend
// untouched — nothing to configure there.
//
// Everything sits under one `/api` prefix on purpose. Proxying the bare route
// names instead (`/customers`, `/report`, …) collided with the SPA's own
// routes: Vite runs the proxy *before* the history fallback, so reloading
// `/customers/C_117580` in the address bar returned raw JSON instead of the
// app. A prefix that no page uses cannot collide.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
        // A cold /actions run can take minutes; do not let the proxy give up
        // before the server does.
        timeout: 10 * 60 * 1000,
        proxyTimeout: 10 * 60 * 1000,
      },
    },
  },
});
