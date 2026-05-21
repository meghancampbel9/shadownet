import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import { LayoutDashboard, Users, MessageSquare, LogOut } from "lucide-react";

const links = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/contacts", icon: Users, label: "Contacts" },
  { to: "/messages", icon: MessageSquare, label: "Messages" },
] as const;

export function Shell() {
  const { userName, logout } = useAuth();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border bg-surface-1 px-4 h-12 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-6">
          <span className="text-accent font-semibold text-sm tracking-wider">shadownet</span>
          <nav className="flex items-center gap-1">
            {links.map(({ to, icon: Icon, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-colors ${
                    isActive ? "bg-surface-3 text-accent" : "text-muted hover:text-fg"
                  }`
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted">{userName}</span>
          <button onClick={logout} className="text-muted hover:text-fg transition-colors" title="Sign out">
            <LogOut size={14} />
          </button>
        </div>
      </header>
      <main className="flex-1 p-6 max-w-5xl w-full mx-auto">
        <Outlet />
      </main>
    </div>
  );
}
