import { Component, useEffect, type ErrorInfo, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import { useApp, useLink } from "./state/app";
import { EvidenceDrawer } from "./components/Evidence";
import QueuePage from "./pages/QueuePage";
import CustomersPage from "./pages/CustomersPage";
import DossierPage from "./pages/DossierPage";
import MeetingPage from "./pages/MeetingPage";
import SystemPage from "./pages/SystemPage";

function TopBar() {
  const { asOf, setAsOf } = useApp();
  const link = useLink();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, staleTime: Infinity });

  const state = health.isError ? "bad" : health.data?.llm_available ? "ok" : "warn";
  const title = health.isError
    ? "سرور در دسترس نیست"
    : health.data?.llm_available
      ? `مدل: ${health.data.llm_model}`
      : "کلید مدل تنظیم نیست — متن‌ها قالبی خواهند بود";

  return (
    <header className="topbar">
      <div className="brand">
        نفیس <span>نخ</span>
      </div>
      <nav className="nav">
        <NavLink to={link("/")} end>صف امروز</NavLink>
        <NavLink to={link("/customers")}>مشتریان</NavLink>
        <NavLink to={link("/system")}>سلامت سیستم</NavLink>
      </nav>
      <div className="asof">
        <label htmlFor="asof">تاریخ مبنا</label>
        <input
          id="asof"
          type="date"
          value={asOf}
          onChange={(e) => e.target.value && setAsOf(e.target.value)}
        />
      </div>
      <span className={`dot ${state}`} title={title} />
    </header>
  );
}

/**
 * A render error used to blank the whole window. The API returns loosely typed
 * dictionaries — `rfm`, `payment`, `quality` are `Record<string, unknown>` —
 * so a shape surprise on one customer should cost that page, not the session.
 */
class Boundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("render failed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="wrap">
        <div className="notice bad">
          <strong>این صفحه رندر نشد.</strong>
          <p className="small" style={{ margin: "8px 0 0" }}>
            خطا در نمایش رخ داده، نه در داده — تاریخ مبنا و بقیهٔ صفحه‌ها سالم‌اند.
          </p>
          <pre className="brief" style={{ marginTop: 10, direction: "ltr", textAlign: "left" }}>
            {this.state.error.message}
          </pre>
          <div className="btnrow" style={{ marginTop: 12 }}>
            <button className="primary" onClick={() => this.setState({ error: null })}>
              تلاش دوباره
            </button>
          </div>
        </div>
      </div>
    );
  }
}

/** Chrome hides the body of a closed `<details>` from the printer, so every
 *  «چرا؟» would print blank. Open them all before printing, restore after. */
function usePrintableDisclosures() {
  useEffect(() => {
    let closed: HTMLDetailsElement[] = [];
    const before = () => {
      closed = [...document.querySelectorAll<HTMLDetailsElement>("details:not([open])")];
      closed.forEach((d) => (d.open = true));
    };
    const after = () => {
      closed.forEach((d) => (d.open = false));
      closed = [];
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);
}

export default function App() {
  const { pathname } = useLocation();
  usePrintableDisclosures();
  return (
    <div className="app">
      <TopBar />
      <main className="main">
        {/* Keyed on the path so navigating away from a broken page clears it. */}
        <Boundary key={pathname}>
          <Routes>
            <Route path="/" element={<QueuePage />} />
            <Route path="/customers" element={<CustomersPage />} />
            <Route path="/customers/:id" element={<DossierPage />} />
            <Route path="/customers/:id/meeting" element={<MeetingPage />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Boundary>
      </main>
      <EvidenceDrawer />
    </div>
  );
}
