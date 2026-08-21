/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Where the FastAPI server lives. Defaults to `/api`, which the dev proxy
   *  rewrites onto `127.0.0.1:8000`. Set it only when the backend is not
   *  mounted under `/api` on the same origin as the built app. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
