import {
  ClipboardList,
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

/**
 * Single source of truth for the sidebar. Each entry declares the
 * permission it needs, so the menu filters itself from the current user's
 * grants rather than every page hardcoding visibility rules.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', to: '/', icon: LayoutDashboard },
  { label: 'Users', to: '/users', icon: Users, permission: 'users:read' },
  {
    label: 'Patients',
    to: '/patients',
    icon: UsersRound,
    permission: 'patients:read',
  },
  { label: 'Roles', to: '/roles', icon: Shield, permission: 'roles:read' },
  { label: 'Audit log', to: '/logs', icon: ClipboardList, permission: 'logs:read' },
  { label: 'Profile', to: '/profile', icon: UserCircle },
]
