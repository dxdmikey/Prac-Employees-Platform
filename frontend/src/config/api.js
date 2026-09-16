// Where the FastAPI backend lives.
//
// Vite exposes only variables that start with VITE_. Set VITE_API_BASE_URL in
// frontend/.env to override the default (see .env.example).
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'
