import {
  ClipboardCheck,
  ClipboardList,
  Eye,
  FileCheck2,
  FileStack,
  FileWarning,
  FolderDown,
  FolderKanban,
  ShieldAlert,
  Inbox,
  LayoutDashboard,
  PackageCheck,
  Shield,
  Table2,
  Users,
  UsersRound,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Permission } from '@/schemas/common'

export type NavItem = {
  label: string
  to: string
  icon: LucideIcon

  permission?: Permission
}

export type ZoneTone = 'zone1' | 'zone1x' | 'zone2' | 'admin'

export type NavGroup = {
  id: string
  label?: string
  tag?: string
  tone?: ZoneTone
  items: NavItem[]
}

export const ZONE_STYLES: Record<ZoneTone, { badge: string }> = {
  zone1: {
    badge: 'bg-sky-500/15 text-sky-700 dark:text-sky-300',
  },
  zone1x: {
    badge: 'bg-violet-500/15 text-violet-700 dark:text-violet-300',
  },
  zone2: {
    badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  },
  admin: {
    badge: 'bg-slate-500/15 text-slate-700 dark:text-slate-300',
  },
}

export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'home',
    items: [{ label: 'Dashboard', to: '/', icon: LayoutDashboard }],
  },
  {
    id: 'zone1',
    label: 'Intake & review',
    tag: 'Zone 1',
    tone: 'zone1',
    items: [
      {
        label: 'De-Identifier',
        to: '/de-identifier',
        icon: Inbox,
        permission: 'deidentifier:view',
      },
      {
        label: 'Applications',
        to: '/applications',
        icon: FileStack,
        permission: 'application:view',
      },
      {
        label: 'Files',
        to: '/files',
        icon: FileCheck2,
        permission: 'files:read',
      },
      {
        label: 'Rejections',
        to: '/rejections',
        icon: FileWarning,
        permission: 'rejection:view',
      },
      {
        label: 'Patients',
        to: '/patients',
        icon: UsersRound,
        permission: 'patient:view',
      },
      {
        label: 'Metadata',
        to: '/metadata',
        icon: Table2,
        permission: 'application:view',
      },
    ],
  },
  {
    id: 'zone1x',
    label: 'Preparation',
    tag: 'Zone 1X',
    tone: 'zone1x',
    items: [
      {
        label: 'Consent matrix',
        to: '/consents',
        icon: ClipboardCheck,
        permission: 'consent:view',
      },
      {
        label: 'Abstraction folders',
        to: '/abstraction',
        icon: FolderDown,
        permission: 'abstraction:view',
      },
      {
        label: 'Projects',
        to: '/projects',
        icon: FolderKanban,
        permission: 'project:view',
      },
    ],
  },
  {
    id: 'zone2',
    label: 'Release',
    tag: 'Zone 2',
    tone: 'zone2',
    items: [
      {
        label: 'Zone 2 inbox',
        to: '/zone2-inbox',
        icon: PackageCheck,
        permission: 'zone2:review',
      },
    ],
  },
  {
    id: 'admin',
    label: 'Administration',
    tone: 'admin',
    items: [
      { label: 'Users', to: '/users', icon: Users, permission: 'user:view' },
      { label: 'Roles', to: '/roles', icon: Shield, permission: 'role:view' },
      {
        label: 'Security',
        to: '/security',
        icon: ShieldAlert,
        permission: 'security:view',
      },
      {
        label: 'Audit log',
        to: '/logs',
        icon: ClipboardList,
        permission: 'log:view',
      },
      {
        label: 'Access log',
        to: '/access-logs',
        icon: Eye,
        permission: 'log:view',
      },
    ],
  },
]

const SECTION_PATHS: Record<string, string> = {
  '/intake': '/de-identifier',
}

export function groupForPath(pathname: string): NavGroup | undefined {
  const path = SECTION_PATHS[pathname.replace(/\/$/, '')] ?? pathname
  let best: { group: NavGroup; length: number } | undefined
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.to === '/') continue
      if (path === item.to || path.startsWith(`${item.to}/`)) {
        if (!best || item.to.length > best.length) {
          best = { group, length: item.to.length }
        }
      }
    }
  }
  return best?.group
}
