import React, { useCallback } from "react";

import { Link, useNavigate } from "@tanstack/react-router";
import { queryClient } from "@/lib/query-client";
import { useAuth } from "@/features/auth/context/useAuth";
import { ThemeToggle } from "@/shared/components/theme-toggle";
import { Button } from "@/shared/ui/Button/Button";

interface HeaderProps {
  onToggleSidebar?: () => void; // Made optional to prevent crashes
  isSidebarOpen: boolean;
}

export const Header = React.memo(({ onToggleSidebar, isSidebarOpen }: HeaderProps) => {
  const { user } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    queryClient.clear();
    localStorage.removeItem("token");

    void navigate({ to: "/login" });
  }

  // Generate fallback initials based on email
  const getInitials = (email?: string) => {
    if (!email) return "U";
    return email.slice(0, 2).toUpperCase();
  };

  // Safe handler to prevent errors if the function is not passed yet
  const handleToggle = useCallback(
    (e: React.MouseEvent<HTMLButtonElement>) => {
      e.preventDefault();
      e.stopPropagation();

      if (typeof onToggleSidebar === "function") {
        onToggleSidebar();
      } else {
        console.warn("onToggleSidebar is not passed to the Header component.");
      }
    },
    [onToggleSidebar],
  );

  return (
    <header
      role="banner"
      className="sticky top-0 z-50 flex items-center justify-between px-6 h-16 bg-[rgb(var(--background))] border-b border-[rgb(var(--border))] shadow-sm"
    >
      <div className="flex items-center gap-4">
        <button
          onClick={handleToggle}
          aria-label={isSidebarOpen ? "Collapse navigation menu" : "Expand navigation menu"}
          aria-expanded={isSidebarOpen}
          type="button"
          className="p-2 rounded-md border border-[rgb(var(--border))] text-[rgb(var(--foreground))] hover:bg-slate-100 hover:text-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 transition"
        >
          <svg
            className="w-5 h-5 pointer-events-none"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M4 6h16M4 12h16M4 18h16"
            />
          </svg>
        </button>

        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-[rgb(var(--brand))] tracking-tight">
            UBRS Application
          </span>
        </div>
      </div>

      <div
        className="flex items-center gap-4 text-sm font-medium text-slate-700"
        aria-label="User Profile"
      >
        <ThemeToggle />
        {user ? (
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="w-8 h-8 rounded-full bg-teal-100 border border-teal-300 flex items-center justify-center font-bold text-teal-700">
                {getInitials(user?.email)}
              </span>
              <span className="hidden sm:inline-block font-medium text-[rgb(var(--foreground))]">
                {user?.first_name} {user?.last_name}
              </span>
            </div>
            <Button variant={"danger"} onClick={handleLogout}>
              Logout
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <Link
              to="/login"
              className="px-3 py-1.5 text-xs font-semibold text-slate-600 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-md transition"
            >
              Login
            </Link>
            <Link
              to="/register"
              className="px-3 py-1.5 text-xs font-semibold text-white bg-teal-600 hover:bg-teal-700 rounded-md transition"
            >
              Register
            </Link>
          </div>
        )}
      </div>
    </header>
  );
});

Header.displayName = "Header";
