import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { App } from "./App";
import { decodeShareUrl } from "./lib/shareUrl";
import type { DecodedShare } from "./lib/shareUrl";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("No #root element found");

const initialShare: DecodedShare | null = await decodeShareUrl(
  window.location.hash,
);

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App initialShare={initialShare} />
    </QueryClientProvider>
  </StrictMode>,
);
