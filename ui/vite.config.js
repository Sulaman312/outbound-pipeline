// npm run dev: the screens on http://localhost:5173, with /api sent to `outbound serve` on :8000.
// npm run build: writes dist/, which `outbound serve` shows at http://127.0.0.1:8000.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
