import { Footer } from "@/shared/components/Footer";
import { Header } from "@/shared/components/Header";
import { Sidebar } from "@/shared/components/Sidebar";
import { Outlet } from "@tanstack/react-router";
import { useCallback, useState } from "react";

export function AppLayout() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const toggleSidebar = useCallback(() => {
    setIsSidebarOpen((prev) => !prev);
  }, []);
  return (
    <div
      className="
    flex min-h-screen flex-col
    bg-[rgb(var(--background))]
    text-[rgb(var(--foreground))]
    font-sans antialiased
    transition-colors
  "
    >
      <Header onToggleSidebar={toggleSidebar} isSidebarOpen={isSidebarOpen} />

      <div className="relative flex flex-1 overflow-hidden">
        <Sidebar isOpen={isSidebarOpen} />

        <main
          id="main-content"
          role="main"
          className="
        flex-1 overflow-y-auto p-6 md:p-8
        bg-[rgb(var(--background))]
        transition-all duration-300 ease-in-out
      "
        >
          <div className="mx-auto max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>

      <Footer />
    </div>
  );
}
