import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { useAttachIntakeFiles, useCodeFiles } from '@/hooks/useResources'

type Props = {
  applicationId: string
  code: string
}

// Every de-identified document waiting under the patient code belongs to the
// application, so they are attached as soon as this step opens.
export function IntakeFilePicker({ applicationId, code }: Props) {
  const available = useCodeFiles(code)
  const attach = useAttachIntakeFiles(applicationId)
  const tried = useRef('')

  const ids = (available.data ?? []).map((f) => f.id)
  const key = ids.join('|')

  useEffect(() => {
    if (!key || tried.current === key) return
    tried.current = key
    attach.mutate(key.split('|'))
  }, [key, attach])

  if (available.isLoading || attach.isPending) {
    const label = attach.isPending
      ? `Attaching ${ids.length} document${ids.length === 1 ? '' : 's'} for ${code}...`
      : 'Loading documents...'
    return (
      <Card className="flex items-center gap-3 p-5 text-sm text-[rgb(var(--foreground-muted))]">
        <Spinner size="md" label="" />
        {label}
      </Card>
    )
  }

  if (attach.isError && ids.length > 0) {
    return (
      <Card className="flex flex-wrap items-center justify-between gap-3 p-5 text-sm">
        <span>
          {ids.length} document{ids.length === 1 ? '' : 's'} for{' '}
          <span className="font-mono font-bold">{code}</span> could not be attached.
        </span>
        <Button size="sm" onClick={() => attach.mutate(ids)}>
          Try again
        </Button>
      </Card>
    )
  }

  return null
}
