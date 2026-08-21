import {
  createContext, useCallback, useContext, useMemo, useState, type ReactNode,
} from "react";
import { useSearchParams } from "react-router-dom";
import type { Evidence } from "../api/types";

const DEFAULT_AS_OF = "2021-06-30";
const ISO = /^\d{4}-\d{2}-\d{2}$/;

interface AppState {
  asOf: string;
  setAsOf: (d: string) => void;
  /** Evidence already delivered by /customers/:id — lets a chip show its claim
   *  without a network round-trip, exactly as API.md §230 asks. */
  evidenceIndex: Map<string, Evidence>;
  indexEvidence: (items: Evidence[]) => void;
  openEvidence: string | null;
  showEvidence: (id: string | null) => void;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  // The anchor lives in the URL. Every claim in the app is computed against it,
  // so a link that loses it is a link to different numbers than the sender saw.
  const [params, setParams] = useSearchParams();
  const raw = params.get("as_of");
  const asOf = raw && ISO.test(raw) ? raw : DEFAULT_AS_OF;

  const [openEvidence, showEvidence] = useState<string | null>(null);
  const [evidenceIndex, setIndex] = useState<Map<string, Evidence>>(new Map());

  const indexEvidence = useCallback((items: Evidence[]) => {
    if (!items?.length) return;
    setIndex((prev) => {
      let changed = false;
      const next = new Map(prev);
      for (const e of items) {
        if (!next.has(e.id)) {
          next.set(e.id, e);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  // Changing as_of invalidates every cached claim — they were computed against
  // the old anchor and would be silently wrong.
  const setAsOf = useCallback(
    (d: string) => {
      if (!ISO.test(d)) return;
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("as_of", d);
          return next;
        },
        { replace: true },
      );
      setIndex(new Map());
      showEvidence(null);
    },
    [setParams],
  );

  const value = useMemo(
    () => ({ asOf, setAsOf, evidenceIndex, indexEvidence, openEvidence, showEvidence }),
    [asOf, setAsOf, evidenceIndex, indexEvidence, openEvidence],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used inside <AppProvider>");
  return v;
}

/**
 * Builds an in-app link that carries the anchor with it. Every `<Link>` must go
 * through this: the anchor now lives in the query string, so a bare `to` would
 * silently drop the user back onto the default date mid-session.
 */
export function useLink(): (to: string) => string {
  const { asOf } = useApp();
  return useCallback(
    (to: string) => `${to}${to.includes("?") ? "&" : "?"}as_of=${asOf}`,
    [asOf],
  );
}
