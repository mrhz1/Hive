import {
  ClipboardList,
  FileCheck2,
  FileStack,
  LayoutDashboard,
  Shield,
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
  /** Omitted for items everyone may see (dashboard, profile). */
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
  { label: 'Roles', to: '/roles', icon: Shield, permission: 'role:view' },
  { label: 'Audit log', to: '/logs', icon: ClipboardList, permission: 'log:view' },
  { label: 'Profile', to: '/profile', icon: UserCircle },
]
