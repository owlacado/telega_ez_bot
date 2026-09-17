"use client";
import Link from "next/link";
import { ManagerMenu } from "./manager-menu";
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import {
  CalendarDays,
  ChevronsLeft,
  ChevronsRight,
  UsersRound,
  Wrench,
  ShieldCheck,
} from "lucide-react";
const key = "technician-hub:sidebar-collapsed";
const eventName = "hub-sidebar";
const subscribe = (callback: () => void) => {
  window.addEventListener(eventName, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(eventName, callback);
    window.removeEventListener("storage", callback);
  };
};
const snapshot = () => {
  try {
    return localStorage.getItem(key) === "true";
  } catch {
    return false;
  }
};
const serverSnapshot = () => false;
export function Sidebar() {
  const path = usePathname();
  const collapsed = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const toggle = () => {
    try {
      localStorage.setItem(key, String(!collapsed));
      window.dispatchEvent(new Event(eventName));
    } catch {
      /* Browser storage is optional. */
    }
  };
  return (
    <aside
      className={`sidebar ${collapsed ? "collapsed" : ""}`}
      aria-label="Main sidebar"
    >
      <Link
        href="/"
        className="brand"
        aria-label="Technician Hub dashboard"
        title="Dashboard"
      >
        <span className="brand-mark">
          <Wrench size={21} />
        </span>
        <span className="brand-text">
          Technician
          <span>
            Hub<span className="brand-dot">.</span>
          </span>
        </span>
      </Link>
      <div className="workspace-label">WORKSPACE</div>
      <nav aria-label="Primary navigation">
        {[
          { href: "/technicians", label: "Technicians", Icon: UsersRound },
          { href: "/calendars", label: "Calendars", Icon: CalendarDays },
        ].map(({ href, label, Icon }) => (
          <Link
            key={href}
            href={href}
            title={collapsed ? label : undefined}
            aria-label={label}
            aria-current={path.startsWith(href) ? "page" : undefined}
            className={`nav-link ${path.startsWith(href) ? "selected" : ""}`}
          >
            <Icon size={20} />
            <span className="nav-label">{label}</span>
            {collapsed && <span className="nav-tooltip">{label}</span>}
          </Link>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div className="environment-note">
          <ShieldCheck size={18} />
          <span>
            Local workspace<small>Stage 1 · Secure onboarding</small>
          </span>
        </div>
        <ManagerMenu />
        <button
          className="collapse-button"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
        >
          {collapsed ? (
            <ChevronsRight size={18} />
          ) : (
            <>
              <ChevronsLeft size={18} />
              <span>Collapse sidebar</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
