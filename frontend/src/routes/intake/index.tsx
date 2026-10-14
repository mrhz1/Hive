import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/intake/')({
  beforeLoad: () => {
    throw redirect({ to: '/de-identifier', replace: true })
  },
})
