import { createFileRoute, redirect } from '@tanstack/react-router'

// The page moved to /de-identifier; keep old links and bookmarks working.
export const Route = createFileRoute('/intake/')({
  beforeLoad: () => {
    throw redirect({ to: '/de-identifier', replace: true })
  },
})
