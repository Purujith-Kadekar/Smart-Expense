import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config — VITE_API_BASE_URL points the frontend at the Flask backend.
//   npm run dev        -> http://localhost:5000/api  (from frontend/.env)
//   docker-compose     -> /api                       (set in frontend/Dockerfile,
//                                                     proxied by nginx)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy is not needed since Flask has CORS enabled, but exposing the
    // port keeps the dev URL stable for testing.
  },
});
