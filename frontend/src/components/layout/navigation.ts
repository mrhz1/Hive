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
  UserCircle,
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

export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard },
  { label: 'Users', to: '/users', icon: Users, permission: 'user:view' },
  {
    label: 'Patients',
    to: '/patients',
    icon: UsersRound,
    permission: 'patient:view',
  },
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
    label: 'Metadata',
    to: '/metadata',
    icon: Table2,
    permission: 'application:view',
  },
  {
    label: 'Abstraction folders',
    to: '/abstraction',
    icon: FolderDown,
    permission: 'abstraction:view',
  },
  {
    label: 'Consent matrix',
    to: '/consents',
    icon: ClipboardCheck,
    permission: 'consent:view',
  },
  {
    label: 'Projects',
    to: '/projects',
    icon: FolderKanban,
    permission: 'project:view',
  },
  {
    label: 'Zone 2 inbox',
    to: '/zone2-inbox',
    icon: PackageCheck,
    permission: 'zone2:review',
  },
  { label: 'Roles', to: '/roles', icon: Shield, permission: 'role:view' },
  {
    label: 'Security',
    to: '/security',
    icon: ShieldAlert,
    permission: 'security:view',
  },
  { label: 'Audit log', to: '/logs', icon: ClipboardList, permission: 'log:view' },
  {
    label: 'Access log',
    to: '/access-logs',
    icon: Eye,
    permission: 'log:view',
  },
  { label: 'Profile', to: '/profile', icon: UserCircle },
]
