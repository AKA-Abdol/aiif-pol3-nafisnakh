import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AppProvider } from "./state/app";
import "./styles.css";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      // Nothing here refetches on its own — some of these routes cost money and
      // a background refetch would spend it silently (API.md §745).
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      retry: false,
      staleTime: 5 * 60 * 1000,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AppProvider>
          <App />
        </AppProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
