import { type PropsWithChildren, useEffect, useState } from "react";
import { useRouter } from "next/router";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const STORAGE_KEY = "transferts:sidebar-collapsed";
const MOBILE_QUERY = "(max-width: 768px)";

const isMobileViewport = () =>
  typeof window !== "undefined" && window.matchMedia(MOBILE_QUERY).matches;

export function ShellLayout({ children }: PropsWithChildren) {
  // ``collapsed`` is double-duty:
  // - desktop: sidebar shrinks to 0 width (icons-only style).
  // - mobile : sidebar slides out of view (drawer pattern); the backdrop
  //   below appears when it's open and dismisses it on click.
  // The toggle button in TopBar flips this regardless of viewport — only
  // the CSS visual interpretation differs.
  const [collapsed, setCollapsed] = useState(false);
  const router = useRouter();

  // Hydrate from localStorage on desktop; mobile always boots closed
  // (the drawer is a transient action, not a preference).
  useEffect(() => {
    if (isMobileViewport()) {
      setCollapsed(true);
      return;
    }
    try {
      setCollapsed(localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      // localStorage unavailable — default to expanded
    }
  }, []);

  // Close the mobile drawer on any route change (a sidebar link click is
  // the typical case). Desktop's collapsed state is a UI preference and
  // shouldn't be touched by navigation.
  useEffect(() => {
    const close = () => {
      if (isMobileViewport()) setCollapsed(true);
    };
    router.events.on("routeChangeStart", close);
    return () => router.events.off("routeChangeStart", close);
  }, [router.events]);

  const persist = (next: boolean) => {
    setCollapsed(next);
    // Don't write mobile drawer state — it's transient, not a preference.
    if (isMobileViewport()) return;
    try {
      localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // ignore
    }
  };

  return (
    <div
      className={`shell-layout${collapsed ? " shell-layout--sidebar-collapsed" : ""}`}
    >
      <Sidebar />
      {/* Backdrop — only visible (via CSS) when the mobile drawer is open;
          clicks anywhere outside the sidebar close it. */}
      <div
        className="shell-layout__backdrop"
        onClick={() => persist(true)}
        aria-hidden="true"
      />
      <div className="shell-layout__main">
        <TopBar
          sidebarCollapsed={collapsed}
          onToggle={() => persist(!collapsed)}
        />
        <main className="shell-layout__content">{children}</main>
      </div>
    </div>
  );
}
