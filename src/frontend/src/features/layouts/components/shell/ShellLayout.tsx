import { type PropsWithChildren, useEffect, useState } from "react";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

const STORAGE_KEY = "transferts:sidebar-collapsed";

export function ShellLayout({ children }: PropsWithChildren) {
  const [collapsed, setCollapsed] = useState(false);

  // Hydrate collapse state from localStorage after mount so SSR and the
  // first client render agree.
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      // localStorage unavailable — default to expanded
    }
  }, []);

  const persist = (next: boolean) => {
    setCollapsed(next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      // ignore
    }
  };

  return (
    <div className="shell-layout">
      {!collapsed && <Sidebar />}
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
