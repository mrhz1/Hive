import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react'
import {
  GlobalWorkerOptions,
  getDocument,
  type PDFDocumentProxy,
  type RenderTask,
} from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Spinner } from '@/components/ui/Spinner'

GlobalWorkerOptions.workerSrc = workerUrl

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3]
const PAGE_GUTTER = 48

/**
 * Pages drawn by pdf.js onto canvases, with zoom and nothing else.
 *
 * The browser's own PDF viewer brings print, download, save and share
 * buttons the app cannot switch off; drawing the pages here leaves them out.
 * Downloading stays behind its own permission, on the viewer's Download
 * button.
 */
export function PdfViewer({ url, name }: { url: string; name: string }) {
  const [loaded, setLoaded] = useState<{
    url: string
    doc?: PDFDocumentProxy
    error?: string
  } | null>(null)
  const doc = loaded?.url === url ? (loaded.doc ?? null) : null
  const error = loaded?.url === url ? (loaded.error ?? null) : null
  const [zoom, setZoom] = useState<number | null>(null)
  const [fitScale, setFitScale] = useState(1)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const task = getDocument({ url, isEvalSupported: false })
    task.promise
      .then((opened) => setLoaded({ url, doc: opened }))
      .catch((err: unknown) => {
        setLoaded({
          url,
          error: err instanceof Error ? err.message : 'Could not open this PDF',
        })
      })
    return () => {
      void task.destroy()
    }
  }, [url])

  useEffect(() => {
    if (!doc) return
    let cancelled = false
    let observer: ResizeObserver | null = null

    void doc.getPage(1).then((page) => {
      if (cancelled) return
      const pageWidth = page.getViewport({ scale: 1 }).width
      const measure = () => {
        const available = (scrollRef.current?.clientWidth ?? pageWidth) - PAGE_GUTTER
        setFitScale(Math.max(0.25, available / pageWidth))
      }
      measure()
      if (scrollRef.current) {
        observer = new ResizeObserver(measure)
        observer.observe(scrollRef.current)
      }
    })

    return () => {
      cancelled = true
      observer?.disconnect()
    }
  }, [doc])

  const scale = zoom ?? fitScale

  function zoomIn() {
    setZoom(ZOOM_STEPS.find((step) => step > scale + 0.01) ?? scale)
  }

  function zoomOut() {
    setZoom([...ZOOM_STEPS].reverse().find((step) => step < scale - 0.01) ?? scale)
  }

  if (error) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-8 text-sm text-rose-600 dark:text-rose-400">
        {error}
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-8">
        <Spinner size="md" label="Opening document" />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-center gap-2 border-b border-[rgb(var(--border))] px-4 py-2">
        <Button
          size="sm"
          variant="outline"
          aria-label="Zoom out"
          disabled={scale <= ZOOM_STEPS[0]! + 0.01}
          onClick={zoomOut}
        >
          <ZoomOut className="size-4" aria-hidden="true" />
        </Button>
        <span className="w-14 text-center text-xs font-semibold tabular-nums">
          {Math.round(scale * 100)}%
        </span>
        <Button
          size="sm"
          variant="outline"
          aria-label="Zoom in"
          disabled={scale >= ZOOM_STEPS[ZOOM_STEPS.length - 1]! - 0.01}
          onClick={zoomIn}
        >
          <ZoomIn className="size-4" aria-hidden="true" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          aria-label="Fit to width"
          aria-pressed={zoom === null}
          leadingIcon={<Maximize2 className="size-3.5" aria-hidden="true" />}
          onClick={() => setZoom(null)}
        >
          Fit width
        </Button>
        <span className="ml-2 text-xs text-[rgb(var(--foreground-muted))]">
          {doc.numPages} page{doc.numPages === 1 ? '' : 's'}
        </span>
      </div>

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-auto bg-[rgb(var(--background-secondary))] py-6"
        aria-label={`Pages of ${name}`}
      >
        <div className="flex w-max min-w-full flex-col items-center gap-4 px-6">
          {Array.from({ length: doc.numPages }, (_, i) => (
            <PdfPage key={i} doc={doc} pageNumber={i + 1} scale={scale} />
          ))}
        </div>
      </div>
    </div>
  )
}

function PdfPage({
  doc,
  pageNumber,
  scale,
}: {
  doc: PDFDocumentProxy
  pageNumber: number
  scale: number
}) {
  const holderRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [size, setSize] = useState<{ width: number; height: number } | null>(null)
  const [visible, setVisible] = useState(pageNumber <= 2)

  // Only draw pages near the screen, so a long document opens quickly.
  useEffect(() => {
    const holder = holderRef.current
    if (!holder || visible) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setVisible(true)
      },
      { rootMargin: '800px' }
    )
    observer.observe(holder)
    return () => observer.disconnect()
  }, [visible])

  useEffect(() => {
    let cancelled = false
    let task: RenderTask | null = null

    void doc.getPage(pageNumber).then((page) => {
      if (cancelled) return
      const viewport = page.getViewport({ scale })
      setSize({ width: viewport.width, height: viewport.height })

      const canvas = canvasRef.current
      const context = canvas?.getContext('2d')
      if (!visible || !canvas || !context) return

      const ratio = window.devicePixelRatio || 1
      canvas.width = Math.floor(viewport.width * ratio)
      canvas.height = Math.floor(viewport.height * ratio)
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`

      task = page.render({
        canvasContext: context,
        viewport,
        ...(ratio !== 1 ? { transform: [ratio, 0, 0, ratio, 0, 0] } : {}),
      })
      task.promise.catch(() => undefined)
    })

    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [doc, pageNumber, scale, visible])

  return (
    <div
      ref={holderRef}
      className="bg-white shadow-md"
      style={size ? { width: size.width, height: size.height } : { minHeight: 200 }}
    >
      <canvas
        ref={canvasRef}
        aria-label={`Page ${pageNumber}`}
        onContextMenu={(event) => event.preventDefault()}
      />
    </div>
  )
}
