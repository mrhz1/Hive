import React from 'react';
import { useRouter } from '@tanstack/react-router';

interface CanProps {
  perform: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export function Can({ perform, children, fallback = null }: CanProps) {
  // Pull your global auth state from the TanStack Query cache
  const { user } = useRouter().options.context.auth;
  // Safely flatten out the assigned permission strings

  const userPermissions = React.useMemo(
    () => user?.role?.permissions.map((p) => p.name) ?? [],
    [user],
  );

  // Check if the current user has the required action capability
  const isAuthorized = userPermissions.includes(perform);

  return isAuthorized ? <>{children}</> : <>{fallback}</>;
}
