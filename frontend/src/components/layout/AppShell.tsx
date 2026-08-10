import { useCallback, useState, type ReactNode } from 'react'
import { Header } from './Header'
import { Sidebar } from './Sidebar'

export function AppShell({ children }: { children: ReactNode }) {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true)

  const toggleSidebar = useCallback(() => {
    setIsSidebarOpen((prev) => !prev)
  }, [])

  const handleNavigate = useCallback(() => {
    if (window.matchMedia('(max-width: 767px)').matches) {
      setIsSidebarOpen(false)
    }
  }, [])

  return (
    <div className="flex min-h-screen flex-col bg-[rgb(var(--background))] font-sans text-[rgb(var(--foreground))] antialiased transition-colors">
      <Header onToggleSidebar={toggleSidebar} isSidebarOpen={isSidebarOpen} />

      <div className="relative flex flex-1">
        <Sidebar isOpen={isSidebarOpen} onNavigate={handleNavigate} />

        <main
          id="main-content"
          role="main"
          className="min-w-0 flex-1 bg-[rgb(var(--background))] p-4 transition-all duration-300 ease-in-out sm:p-6 md:p-8"
        >
          <div className="mx-auto max-w-7xl">{children}</div>
        </main>
      </div>

      <footer className="border-t border-[rgb(var(--border))] bg-[rgb(var(--surface))] px-6 py-4 text-center text-xs text-[rgb(var(--foreground-muted))]">
        Hive Admin · FastAPI + HiveServer2 (ORC)
      </footer>
    </div>
  )
}
