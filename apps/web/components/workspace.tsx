"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState } from "react";
import {
  LayoutDashboard,
  Package,
  ClipboardList,
  FileCheck2,
  Truck,
  History,
  Store,
  LogOut,
  Menu,
} from "lucide-react";
import { api, ApiError, Identity } from "@/lib/api";
import { Wordmark } from "./wordmark";
import "./restock.css";
import "./workspace-spacing.css";

const DateContext = createContext<{
  day: string;
  setDay: (day: string) => void;
}>({ day: "2026-02-16", setDay: () => {} });
export const useServiceDate = () => useContext(DateContext);
const links = [
  ["overview", "Overview", LayoutDashboard],
  ["inventory", "Inventory", Package],
  ["daily", "Daily update", ClipboardList],
  ["sales", "Intraday sales", History],
  ["recommendations", "Recommendations", FileCheck2],
  ["deliveries", "Deliveries", Truck],
  ["suppliers", "Suppliers & promotions", Store],
  ["activity", "Activity", History],
] as const;

export function Workspace({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const cache = useQueryClient();
  const [day, setDay] = useState("2026-02-16");
  const [open, setOpen] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const identity = useQuery({
    queryKey: ["identity"],
    queryFn: ({ signal }) => api<Identity>("/auth/me", { signal }),
    retry: false,
  });
  useEffect(() => {
    const expire = () => {
      cache.clear();
      router.replace(`/login?expired=1&next=${encodeURIComponent(pathname)}`);
    };
    window.addEventListener("restock:session-expired", expire);
    return () => window.removeEventListener("restock:session-expired", expire);
  }, [cache, pathname, router]);
  useEffect(() => {
    const navigateTabs = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        target.getAttribute("role") !== "tab" ||
        !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
      )
        return;
      const tabs = Array.from(
        target.parentElement?.querySelectorAll<HTMLButtonElement>(
          '[role="tab"]',
        ) ?? [],
      );
      const current = tabs.indexOf(target as HTMLButtonElement);
      const index =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? tabs.length - 1
            : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
              tabs.length;
      event.preventDefault();
      tabs[index]?.focus();
      tabs[index]?.click();
    };
    window.addEventListener("keydown", navigateTabs);
    return () => window.removeEventListener("keydown", navigateTabs);
  }, []);
  useEffect(() => {
    if (identity.error instanceof ApiError && identity.error.status === 401)
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [identity.error, pathname, router]);
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
      cache.clear();
      router.replace("/login");
    } catch (e) {
      setLogoutError(e instanceof Error ? e.message : "Could not sign out.");
    }
  }
  if (identity.isPending)
    return (
      <div className="restock-app gate">
        <Wordmark />
        <p role="status">Opening your workspace…</p>
      </div>
    );
  if (identity.error)
    return (
      <div className="restock-app gate">
        <Wordmark />
        <ErrorNotice error={identity.error} retry={() => identity.refetch()} />
        <Link href="/login">Return to login</Link>
      </div>
    );
  if (identity.data.role !== "manager")
    return (
      <div className="restock-app gate">
        <h1>Manager access required</h1>
        <Link href="/login">Sign in as a manager</Link>
      </div>
    );
  return (
    <DateContext.Provider value={{ day, setDay }}>
      <div className="restock-app workspace">
        <a className="skip-link" href="#workspace-main">
          Skip to content
        </a>
        <aside className={`sidebar ${open ? "is-open" : ""}`}>
          <Wordmark />
          <p className="sidebar-caption">THE RESTAURANT WORKSPACE</p>
          <nav aria-label="Workspace navigation">
            {links.map(([path, label, Icon]) => (
              <Link
                key={path}
                href={`/workspace/${path}`}
                aria-current={
                  pathname === `/workspace/${path}` ? "page" : undefined
                }
                onClick={() => setOpen(false)}
              >
                <Icon size={18} />
                {label}
              </Link>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <span className="avatar">
              {identity.data.username.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{identity.data.username}</strong>
              <small>Restaurant manager</small>
            </div>
            <button
              className="icon-button"
              aria-label="Sign out"
              onClick={logout}
            >
              <LogOut size={17} />
            </button>
          </div>
          {logoutError && <p role="alert">{logoutError}</p>}
        </aside>
        <div className="workspace-body">
          <header className="workspace-header">
            <button
              className="icon-button mobile-menu"
              aria-label="Toggle navigation"
              aria-expanded={open}
              onClick={() => setOpen(!open)}
            >
              <Menu size={21} />
            </button>
            <span>Restaurant operations</span>
            <label className="service-date">
              Service date
              <input
                type="date"
                required
                value={day}
                onChange={(e) => {
                  if (e.target.value) setDay(e.target.value);
                }}
              />
            </label>
          </header>
          <main id="workspace-main" className="workspace-content">
            {children}
          </main>
          <footer className="workspace-footer">
            ReStock <span>All operational times in Singapore · UTC+8</span>
          </footer>
        </div>
      </div>
    </DateContext.Provider>
  );
}

export function ErrorNotice({
  error,
  retry,
}: {
  error: Error;
  retry?: () => void;
}) {
  return (
    <div className="notice notice-error" role="alert">
      <strong>
        {error instanceof ApiError && error.status === 409
          ? "This record has changed"
          : "Unable to complete this request"}
      </strong>
      <p>{error.message}</p>
      {retry && (
        <button className="button button-secondary" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Placeholder({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="placeholder">
      <span className="status-tag">Not connected yet</span>
      <h3>{title}</h3>
      <p>{children}</p>
    </section>
  );
}
export function PageHeading({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children}
    </div>
  );
}
export function Status({ value }: { value: string }) {
  return (
    <span className={`status-tag status-${value.toLowerCase()}`}>
      {value.replaceAll("_", " ").toLowerCase()}
    </span>
  );
}
