import React from 'react';
import { Link } from '@tanstack/react-router';
import { Can } from '@/shared/components/Can';

interface SidebarProps {
  isOpen: boolean;
}

export const Sidebar = React.memo(({ isOpen }: SidebarProps) => {
  const SideBarLink = (to: string, text: string) => {
    return (
      <Link
        to={to}
        activeProps={{
          className:
            'text-[rgb(var(--nav-active-text))] bg-[rgb(var(--nav-active-bg))] shadow-sm shadow-[rgb(var(--nav-shadow)/0.5)]',
        }}
        className='flex items-center rounded-lg px-4 py-2.5 text-sm font-medium whitespace-nowrap text-[rgb(var(--nav-text))] transition hover:bg-[rgb(var(--nav-hover-bg))] hover:text-[rgb(var(--nav-active-text))]'
      >
        {text}
      </Link>
    );
  };

  return (
    <aside
      role='navigation'
      aria-label='Primary Navigation'
      aria-hidden={!isOpen}
      className={`fixed top-16 z-40 flex h-[calc(100vh-4rem)] flex-col justify-between overflow-hidden border-r border-slate-200 bg-white transition-colors duration-300 md:sticky dark:border-slate-800 dark:bg-slate-900 ${
        isOpen ? 'w-64' : 'pointer-events-none invisible w-0'
      }`}
    >
      <div className='grid w-64 space-y-2 p-4'>
        <Can perform='patient:read'>{SideBarLink('/patients', 'Patients')}</Can>

        <Can perform='user:read'>{SideBarLink('/users', 'Users')}</Can>
        <Can perform='permission:read'>{SideBarLink('/permissions', 'Permissions')}</Can>
        <Can perform='role:read'>{SideBarLink('/roles', 'Roles')}</Can>

        {SideBarLink('/logs', 'Logs')}
        {SideBarLink('/applications', 'Applications')}
      </div>

      <div className='w-64 border-t border-slate-100 p-4 text-center text-xs text-slate-400'>
        System Status: <span className='font-semibold text-emerald-600'>Online</span>
      </div>
    </aside>
  );
});

Sidebar.displayName = 'Sidebar';
