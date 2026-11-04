import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import {
  ChevronLeft,
  ChevronRight,
  FileSpreadsheet,
  FileText,
  Play,
  RotateCcw,
  ShieldCheck,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { SelectField, TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { ApiError } from '@/lib/api/client'
import { qcApi, type QcIssueFilters } from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { QcRule, QcRun } from '@/schemas/qc'

export const Route = createFileRoute('/qc/')({
  component: () => (
    <RequirePermission permission="qc:view">
      <QcPage />
    </RequirePermission>
  ),
})

const muted = 'text-xs text-[rgb(var(--foreground-muted))]'

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function when(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function QcPage() {
  useDocumentTitle('Quality control')
  const client = useQueryClient()
  const overview = useQuery({
    queryKey: queryKeys.qc.overview(),
    queryFn: qcApi.overview,
    refetchInterval: (query) => (query.state.data?.state.running ? 3000 : false),
  })
  const running = overview.data?.state.running ?? false
  const [selected, setSelected] = useState<string | null>(null)
  const wasRunning = useRef(false)

  useEffect(() => {
    if (wasRunning.current && !running && overview.data) {
      void client.invalidateQueries({ queryKey: queryKeys.qc.all })
      if (overview.data.state.error)
        toast.error(`QC failed: ${overview.data.state.error}`)
      else toast.success('QC finished')
    }
    wasRunning.current = running
  }, [running, overview.data, client])

  const start = useMutation({
    mutationFn: qcApi.run,
    onSuccess: () => {
      setSelected(null)
      void client.invalidateQueries({ queryKey: queryKeys.qc.overview() })
    },
    onError: (error) => toast.error(message(error, 'Could not start QC')),
  })

  const runs = overview.data?.runs ?? []
  const run = runs.find((r) => r.name === selected) ?? runs[0]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Quality control"
        description="Checks the database for missing or contradictory values (protocol 9.1.13): dates, applications without documents, unknown document types, consent conflicts. Each run makes a PDF report for every cohort. Accepted issues can be suppressed so they stop coming back."
        actions={
          <Can permission="qc:run">
            <Button
              isLoading={running || start.isPending}
              leadingIcon={<Play className="size-4" aria-hidden="true" />}
              onClick={() => start.mutate()}
            >
              {running ? 'Running…' : 'Run QC now'}
            </Button>
          </Can>
        }
      />

      {overview.isLoading ? (
        <LoadingBlock label="Loading QC runs" />
      ) : overview.error ? (
        <p className="text-sm text-[rgb(var(--danger))]">
          {message(overview.error, 'Could not load QC')}
        </p>
      ) : !run ? (
        <Card className="p-5 text-sm">
          No QC run yet. Run it to make the first report.
        </Card>
      ) : (
        <>
          <RunCard
            run={run}
            runs={runs}
            rules={overview.data?.rules ?? []}
            onPick={setSelected}
          />
          <IssuesCard key={run.name} run={run} rules={overview.data?.rules ?? []} />
        </>
      )}
      <SuppressionsCard />
    </div>
  )
}

function RunCard({
  run,
  runs,
  rules,
  onPick,
}: {
  run: QcRun
  runs: QcRun[]
  rules: QcRule[]
  onPick: (name: string) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const cohorts = Object.entries(run.cohorts).sort(([a], [b]) => a.localeCompare(b))
  const counted = rules.filter((rule) => (run.rules[rule.code] ?? 0) > 0)

  async function download(kind: 'pdf' | 'xlsx', cohort?: string) {
    const key = `${kind}-${cohort ?? 'all'}`
    setBusy(key)
    try {
      const blob = await qcApi.report(run.name, kind, cohort)
      saveBlob(
        blob,
        `${run.name}${cohort ? `-${cohort}` : ''}.${kind === 'pdf' ? 'pdf' : 'xlsx'}`
      )
    } catch (error) {
      toast.error(message(error, 'Could not download the report'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="w-80">
          <SelectField
            label="Run"
            value={run.name}
            onChange={(event) => onPick(event.target.value)}
            options={runs.map((r) => ({
              value: r.name,
              label: `${when(r.made_at)}${r.run_by ? ` · ${r.run_by}` : ''}`,
            }))}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            isLoading={busy === 'pdf-all'}
            leadingIcon={<FileText className="size-4" aria-hidden="true" />}
            onClick={() => void download('pdf')}
          >
            Full report (PDF)
          </Button>
          <Button
            variant="outline"
            size="sm"
            isLoading={busy === 'xlsx-all'}
            leadingIcon={<FileSpreadsheet className="size-4" aria-hidden="true" />}
            onClick={() => void download('xlsx')}
          >
            Workbook
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <Badge tone={run.issues ? 'warning' : 'success'}>{run.issues ?? '?'} open</Badge>
        <Badge tone={run.high ? 'danger' : 'neutral'}>{run.high ?? '?'} high</Badge>
        <Badge tone="neutral">{run.suppressed ?? 0} suppressed</Badge>
        {run.stale_suppressions ? (
          <Badge tone="neutral">
            {run.stale_suppressions} suppression(s) no longer match
          </Badge>
        ) : null}
      </div>

      {cohorts.length > 0 ? (
        <div>
          <h3 className="text-sm font-semibold">Report per cohort</h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {cohorts.map(([cohort, counts]) => (
              <Button
                key={cohort}
                variant="outline"
                size="sm"
                isLoading={busy === `pdf-${cohort}`}
                leadingIcon={<FileText className="size-4" aria-hidden="true" />}
                onClick={() => void download('pdf', cohort)}
              >
                {cohort}: {counts.issues} ({counts.high} high)
              </Button>
            ))}
          </div>
        </div>
      ) : null}

      {counted.length > 0 ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className="py-1 pr-3 font-semibold">Rule</th>
              <th className="py-1 pr-3 font-semibold">Severity</th>
              <th className="py-1 pr-3 font-semibold">Problem</th>
              <th className="py-1 text-right font-semibold">Open</th>
            </tr>
          </thead>
          <tbody>
            {counted.map((rule) => (
              <tr key={rule.code} className="border-t border-[rgb(var(--border))]">
                <td className="py-1 pr-3 font-mono text-xs">{rule.code}</td>
                <td className="py-1 pr-3">
                  <Badge tone={rule.severity === 'high' ? 'danger' : 'warning'}>
                    {rule.severity}
                  </Badge>
                </td>
                <td className="py-1 pr-3">{rule.text}</td>
                <td className="py-1 text-right">{run.rules[rule.code]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className={muted}>No open issues in this run.</p>
      )}
    </Card>
  )
}

function IssuesCard({ run, rules }: { run: QcRun; rules: QcRule[] }) {
  const { can } = usePermissions()
  const client = useQueryClient()
  const [typed, setTyped] = useState('')
  const [filters, setFilters] = useState<QcIssueFilters>({
    page: 1,
    q: '',
    rule: '',
    cohort: '',
    suppressed: false,
  })
  const [target, setTarget] = useState<{ rule: string; record: string } | null>(null)

  useEffect(() => {
    const timer = setTimeout(
      () =>
        setFilters((f) =>
          f.q === typed.trim() ? f : { ...f, q: typed.trim(), page: 1 }
        ),
      400
    )
    return () => clearTimeout(timer)
  }, [typed])

  const issues = useQuery({
    queryKey: queryKeys.qc.issues(run.name, filters),
    queryFn: () => qcApi.issues(run.name, filters),
    placeholderData: keepPreviousData,
  })

  const suppress = useMutation({
    mutationFn: (v: { rule: string; record: string; reason: string }) =>
      qcApi.suppress(v.rule, v.record, v.reason),
    onSuccess: () => {
      setTarget(null)
      toast.success('Suppressed. It drops out of the reports from the next run.')
      void client.invalidateQueries({ queryKey: queryKeys.qc.suppressions() })
    },
    onError: (error) => toast.error(message(error, 'Could not suppress')),
  })

  const data = issues.data
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1
  const set = (patch: Partial<QcIssueFilters>) =>
    setFilters((f) => ({ ...f, ...patch, page: patch.page ?? 1 }))
  const canSuppress = can('qc:run') && !filters.suppressed

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-end gap-3">
        <h2 className="mr-auto text-sm font-bold">
          {filters.suppressed ? 'Suppressed issues' : 'Open issues'}
        </h2>
        <div className="w-56">
          <SelectField
            label="Rule"
            value={filters.rule}
            onChange={(event) => set({ rule: event.target.value })}
            options={[
              { value: '', label: 'All rules' },
              ...rules.map((r) => ({ value: r.code, label: `${r.code} ${r.text}` })),
            ]}
          />
        </div>
        <div className="w-36">
          <SelectField
            label="Cohort"
            value={filters.cohort}
            onChange={(event) => set({ cohort: event.target.value })}
            options={[
              { value: '', label: 'All' },
              ...Object.keys(run.cohorts)
                .sort()
                .map((c) => ({ value: c, label: c })),
            ]}
          />
        </div>
        <div className="w-56">
          <TextField
            label="Search"
            value={typed}
            placeholder="code, record, detail"
            onChange={(event) => setTyped(event.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input
            type="checkbox"
            checked={filters.suppressed}
            onChange={(event) => set({ suppressed: event.target.checked })}
          />
          Show suppressed
        </label>
      </div>

      {issues.isLoading ? (
        <LoadingBlock label="Loading issues" />
      ) : issues.error ? (
        <p className="text-sm text-[rgb(var(--danger))]">
          {message(issues.error, 'Could not load the issues')}
        </p>
      ) : data ? (
        <>
          <div className="overflow-auto rounded border border-[rgb(var(--border))]">
            <table className="w-full border-collapse text-xs">
              <thead className="bg-[rgb(var(--background-secondary))]">
                <tr>
                  {data.columns.map((column) => (
                    <th
                      key={column}
                      className="px-2 py-1.5 text-left font-semibold whitespace-nowrap"
                    >
                      {column}
                    </th>
                  ))}
                  {canSuppress ? <th className="px-2 py-1.5" /> : null}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, index) => (
                  <tr key={index} className="border-t border-[rgb(var(--border))]">
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex} className="px-2 py-1 align-top">
                        {cellIndex === 1 ? (
                          <Badge tone={cell === 'high' ? 'danger' : 'warning'}>
                            {cell}
                          </Badge>
                        ) : (
                          <span className={cellIndex === 3 ? 'font-mono break-all' : ''}>
                            {cell}
                          </span>
                        )}
                      </td>
                    ))}
                    {canSuppress ? (
                      <td className="px-2 py-1 text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          leadingIcon={
                            <ShieldCheck className="size-3.5" aria-hidden="true" />
                          }
                          onClick={() =>
                            setTarget({ rule: row[0] ?? '', record: row[3] ?? '' })
                          }
                        >
                          Suppress
                        </Button>
                      </td>
                    ) : null}
                  </tr>
                ))}
                {data.rows.length === 0 ? (
                  <tr>
                    <td
                      className={`px-2 py-3 ${muted}`}
                      colSpan={data.columns.length + 1}
                    >
                      Nothing here.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-end gap-2 text-sm">
            <span className={muted}>{data.total} issue(s)</span>
            <Button
              size="sm"
              variant="outline"
              aria-label="Previous page"
              disabled={filters.page <= 1 || issues.isFetching}
              onClick={() => set({ page: filters.page - 1 })}
            >
              <ChevronLeft className="size-4" aria-hidden="true" />
            </Button>
            <span>
              {filters.page} / {pages}
            </span>
            <Button
              size="sm"
              variant="outline"
              aria-label="Next page"
              disabled={filters.page >= pages || issues.isFetching}
              onClick={() => set({ page: filters.page + 1 })}
            >
              <ChevronRight className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </>
      ) : null}

      {target ? (
        <ReasonDialog
          title={`Suppress ${target.rule} on ${target.record}`}
          description="Use this when the issue was checked and the data is right (e.g. the patient really is that old). The issue stops appearing in reports from the next run; the reason and your name are kept."
          confirmLabel="Suppress"
          placeholder="e.g. date of birth confirmed with the site on 2026-11-03"
          isBusy={suppress.isPending}
          onConfirm={(reason) => suppress.mutate({ ...target, reason })}
          onCancel={() => setTarget(null)}
        />
      ) : null}
    </Card>
  )
}

function SuppressionsCard() {
  const { can } = usePermissions()
  const client = useQueryClient()
  const list = useQuery({
    queryKey: queryKeys.qc.suppressions(),
    queryFn: qcApi.suppressions,
  })
  const remove = useMutation({
    mutationFn: (v: { rule: string; record: string }) =>
      qcApi.unsuppress(v.rule, v.record),
    onSuccess: () => {
      toast.success('Suppression removed. The issue comes back from the next run.')
      void client.invalidateQueries({ queryKey: queryKeys.qc.suppressions() })
    },
    onError: (error) => toast.error(message(error, 'Could not remove the suppression')),
  })
  const rows = list.data ?? []

  return (
    <Card className="space-y-3 p-5">
      <div>
        <h2 className="text-sm font-bold">Suppressions</h2>
        <p className={muted}>
          Issues checked and accepted. They are left out of the reports and the email.
        </p>
      </div>
      {list.isLoading ? (
        <LoadingBlock label="Loading suppressions" />
      ) : rows.length === 0 ? (
        <p className={muted}>None.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th className="py-1 pr-3 font-semibold">Rule</th>
              <th className="py-1 pr-3 font-semibold">Record</th>
              <th className="py-1 pr-3 font-semibold">Reason</th>
              <th className="py-1 pr-3 font-semibold">By</th>
              <th className="py-1 pr-3 font-semibold">Date</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.rule}|${row.record}`}
                className="border-t border-[rgb(var(--border))]"
              >
                <td className="py-1 pr-3 font-mono text-xs">{row.rule}</td>
                <td className="py-1 pr-3 font-mono text-xs break-all">{row.record}</td>
                <td className="py-1 pr-3">{row.reason}</td>
                <td className="py-1 pr-3">{row.by}</td>
                <td className="py-1 pr-3">{row.date}</td>
                <td className="py-1 text-right">
                  {can('qc:run') ? (
                    <Button
                      size="sm"
                      variant="outline"
                      isLoading={
                        remove.isPending &&
                        remove.variables?.rule === row.rule &&
                        remove.variables.record === row.record
                      }
                      leadingIcon={<RotateCcw className="size-3.5" aria-hidden="true" />}
                      onClick={() =>
                        remove.mutate({ rule: row.rule, record: row.record })
                      }
                    >
                      Remove
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  )
}
