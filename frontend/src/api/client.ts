import axios from "axios";

const api = axios.create({
  // In dev: VITE_API_URL is unset, Vite proxy forwards /api → localhost:8000
  // In prod: VITE_API_URL=https://api.amaansiddiqi.me
  baseURL: import.meta.env.VITE_API_URL ?? "/api",
});

export default api;
