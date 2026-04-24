'use client'

type Outcome = 'success' | 'skipped' | 'error' | 'neutral'

interface TargetEntry {
  kind: 'target'
  outcome: Outcome
  coords?: { x: string; y?: string; z: string }
  waypoints?: string
  tag?: string
  detail?: string
  raw: string
}

interface BuildingEntry {
  kind: 'building'
  name: string
  survivorCount: number
  survivors: { id: string; coords?: string; submerged: boolean }[]
}

interface TextEntry {
  kind: 'text'
  text: string
}

type Entry = TargetEntry | BuildingEntry | TextEntry

interface Section {
  assetId: string
  entries: Entry[]
}

interface FooterRow {
  label: string
  value: string
  tone: Outcome
}

interface ParsedReport {
  title: string
  count?: { n: string; unit: string }
  sections: Section[]
  ungrouped: Entry[]
  footer: FooterRow[]
}

const HEAVY_RE = /^[═=]{3,}$/
const THIN_RE = /^[─-]{3,}$/
const ASSET_ID_RE = /^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$/

function parseReport(raw: string): ParsedReport | null {
  const lines = raw.replace(/\r\n/g, '\n').split('\n')

  let i = 0
  while (i < lines.length && !HEAVY_RE.test(lines[i].trim())) i++
  if (i >= lines.length) return null
  i++

  const titleLines: string[] = []
  while (i < lines.length && !HEAVY_RE.test(lines[i].trim())) {
    titleLines.push(lines[i])
    i++
  }
  if (i >= lines.length) return null
  const titleText = titleLines.map(l => l.trim()).filter(Boolean).join(' ')
  if (!titleText) return null

  const titleMatch = titleText.match(/^(.+?)\s+[—–-]\s+(\d+)\s*(.*)$/)
  const title = titleMatch ? titleMatch[1].trim() : titleText
  const count = titleMatch
    ? { n: titleMatch[2], unit: titleMatch[3].trim() || 'items' }
    : undefined

  i++

  const bodyLines: string[] = []
  while (
    i < lines.length &&
    !THIN_RE.test(lines[i].trim()) &&
    !HEAVY_RE.test(lines[i].trim())
  ) {
    bodyLines.push(lines[i])
    i++
  }

  const footerLines: string[] = []
  if (i < lines.length && THIN_RE.test(lines[i].trim())) {
    i++
    while (i < lines.length && !HEAVY_RE.test(lines[i].trim())) {
      footerLines.push(lines[i])
      i++
    }
  }

  const blocks: string[][] = []
  let cur: string[] = []
  for (const ln of bodyLines) {
    if (ln.trim() === '') {
      if (cur.length) blocks.push(cur)
      cur = []
    } else {
      cur.push(ln)
    }
  }
  if (cur.length) blocks.push(cur)

  const sections: Section[] = []
  const ungrouped: Entry[] = []

  for (const block of blocks) {
    const head = block[0].trim()
    if (ASSET_ID_RE.test(head) && block.length > 1) {
      sections.push({
        assetId: head,
        entries: consumeEntries(block, 1),
      })
    } else {
      ungrouped.push(...consumeEntries(block, 0))
    }
  }

  const footer: FooterRow[] = footerLines
    .map(l => l.trim())
    .filter(Boolean)
    .map(line => {
      const colonIdx = line.indexOf(':')
      if (colonIdx === -1) {
        return { label: '', value: line, tone: 'neutral' as Outcome }
      }
      const label = line.slice(0, colonIdx).trim()
      const value = line.slice(colonIdx + 1).trim()
      return { label, value, tone: footerTone(label, value) }
    })

  if (!sections.length && !ungrouped.length && !footer.length) return null

  return { title, count, sections, ungrouped, footer }
}

function consumeEntries(block: string[], start: number): Entry[] {
  const entries: Entry[] = []
  let j = start
  while (j < block.length) {
    const { entry, next } = parseEntry(block, j)
    entries.push(entry)
    j = next
  }
  return entries
}

function parseEntry(block: string[], idx: number): { entry: Entry; next: number } {
  const t = block[idx].trim()

  const outcomeMatch = t.match(/\bSUPPLY\s+(SENT|SKIPPED|ERROR)\b/)
  if (outcomeMatch) {
    const coordsMatch = t.match(/x=([-\d.]+)(?:,\s*y=([-\d.]+))?,\s*z=([-\d.]+)/)
    const wpMatch = t.match(/Waypoints:\s*(\d+)/)
    const detailMatch = t.match(/SUPPLY\s+(?:SENT|SKIPPED|ERROR)\s*[—–-]\s*(.+?)\.?\s*$/)
    const outcomeMap: Record<string, Outcome> = {
      SENT: 'success',
      SKIPPED: 'skipped',
      ERROR: 'error',
    }
    return {
      entry: {
        kind: 'target',
        outcome: outcomeMap[outcomeMatch[1]] ?? 'neutral',
        coords: coordsMatch
          ? {
              x: coordsMatch[1],
              y: coordsMatch[2] ?? undefined,
              z: coordsMatch[3],
            }
          : undefined,
        waypoints: wpMatch?.[1],
        tag: `SUPPLY ${outcomeMatch[1]}`,
        detail: detailMatch?.[1]?.trim(),
        raw: t,
      },
      next: idx + 1,
    }
  }

  const buildingMatch = t.match(/^(.+?):\s*(\d+)\s*survivor/i)
  if (buildingMatch) {
    const survivors: BuildingEntry['survivors'] = []
    let j = idx + 1
    while (j < block.length && /^\s*[-•]/.test(block[j])) {
      const s = block[j].trim().replace(/^[-•]\s*/, '')
      const idMatch = s.match(/Survivor\s+(\S+):\s*(.+?)(?:\s*\[SUBMERGED[^\]]*\])?$/i)
      survivors.push({
        id: idMatch?.[1] ?? String(survivors.length + 1),
        coords: idMatch?.[2]?.trim(),
        submerged: /SUBMERGED/i.test(s),
      })
      j++
    }
    return {
      entry: {
        kind: 'building',
        name: buildingMatch[1].trim(),
        survivorCount: parseInt(buildingMatch[2], 10),
        survivors,
      },
      next: j,
    }
  }

  return { entry: { kind: 'text', text: t }, next: idx + 1 }
}

function footerTone(label: string, value: string): Outcome {
  const n = Number(value)
  const upper = label.toUpperCase()
  if (upper.includes('FAIL') || upper.includes('ERROR')) {
    return Number.isFinite(n) && n === 0 ? 'neutral' : 'error'
  }
  if (upper.includes('SKIP')) {
    return Number.isFinite(n) && n === 0 ? 'neutral' : 'skipped'
  }
  if (upper.includes('TOTAL') || upper.includes('DISPATCH') || upper.includes('DETECTED') || upper.includes('RESCUED')) {
    return Number.isFinite(n) && n > 0 ? 'success' : 'neutral'
  }
  return 'neutral'
}

function toSentenceCase(s: string): string {
  const lower = s.toLowerCase().trim()
  if (!lower) return s
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

function smartPlural(unit: string, count: number): string {
  const trimmed = unit.trim()
  const parenMatch = trimmed.match(/^(\w+)\(s\)$/i)
  if (parenMatch) {
    return count === 1 ? parenMatch[1] : `${parenMatch[1]}s`
  }
  return trimmed
}

function humanFooterLabel(label: string): string {
  const up = label.toUpperCase().trim()
  const map: Record<string, string> = {
    'TOTAL SUPPLY DISPATCHED': 'SUPPLIES DELIVERED',
    'TOTAL SUPPLIES DISPATCHED': 'SUPPLIES DELIVERED',
    'FAILED TARGETS': 'DELIVERIES FAILED',
    'SKIPPED TARGETS': 'TARGETS SKIPPED',
    'TOTAL SURVIVORS DETECTED': 'SURVIVORS FOUND',
    'TOTAL BUILDINGS SCANNED': 'BUILDINGS SCANNED',
  }
  return map[up] ?? label
}

function extractXZ(text: string): { x: string; z: string } | null {
  const m = text.match(/x=([-\d.]+),\s*z=([-\d.]+)/)
  return m ? { x: m[1], z: m[2] } : null
}

function sectionSummary(section: Section): string | null {
  let sent = 0
  let skipped = 0
  let failed = 0
  let buildings = 0
  let buildingsWithHits = 0
  for (const e of section.entries) {
    if (e.kind === 'target') {
      if (e.outcome === 'success') sent++
      else if (e.outcome === 'skipped') skipped++
      else if (e.outcome === 'error') failed++
    } else if (e.kind === 'building') {
      buildings++
      if (e.survivorCount > 0) buildingsWithHits++
    }
  }
  const parts: string[] = []
  if (sent > 0) parts.push(`${sent} ${sent === 1 ? 'delivery' : 'deliveries'} sent`)
  if (skipped > 0) parts.push(`${skipped} skipped`)
  if (failed > 0) parts.push(`${failed} failed`)
  if (buildings > 0) {
    parts.push(
      buildingsWithHits > 0
        ? `scanned ${buildings} ${buildings === 1 ? 'building' : 'buildings'}, ${buildingsWithHits} with heat signatures`
        : `scanned ${buildings} ${buildings === 1 ? 'building' : 'buildings'}, no heat signatures`,
    )
  }
  return parts.length > 0 ? parts.join(' · ') : null
}

const OUTCOME_STYLES: Record<Outcome, { icon: string; iconBg: string; tagBg: string; tagText: string; label: string }> = {
  success: {
    icon: '✓',
    iconBg: 'bg-[rgba(68,221,136,0.15)] text-[#44dd88] ring-1 ring-[rgba(68,221,136,0.3)]',
    tagBg: 'bg-[rgba(68,221,136,0.12)]',
    tagText: 'text-[#44dd88]',
    label: 'SUCCESS',
  },
  skipped: {
    icon: '⊘',
    iconBg: 'bg-[rgba(255,170,51,0.15)] text-[#ffaa33] ring-1 ring-[rgba(255,170,51,0.3)]',
    tagBg: 'bg-[rgba(255,170,51,0.12)]',
    tagText: 'text-[#ffaa33]',
    label: 'SKIPPED',
  },
  error: {
    icon: '✗',
    iconBg: 'bg-[rgba(255,85,85,0.15)] text-[#ff5555] ring-1 ring-[rgba(255,85,85,0.3)]',
    tagBg: 'bg-[rgba(255,85,85,0.12)]',
    tagText: 'text-[#ff5555]',
    label: 'ERROR',
  },
  neutral: {
    icon: '·',
    iconBg: 'bg-[rgba(80,120,150,0.15)] text-[#8899bb] ring-1 ring-[rgba(80,120,150,0.25)]',
    tagBg: 'bg-[rgba(80,120,150,0.12)]',
    tagText: 'text-[#8899bb]',
    label: 'INFO',
  },
}

const TONE_TEXT: Record<Outcome, string> = {
  success: 'text-[#44dd88]',
  skipped: 'text-[#ffaa33]',
  error: 'text-[#ff5555]',
  neutral: 'text-[#cde]',
}

function Coords({ x, y, z }: { x: string; y?: string; z: string }) {
  const tooltip = y
    ? 'Target coordinates (x, y, z) in the world grid — y is the drop altitude.'
    : 'Target coordinates (x, z) in the world grid — y is auto-planned by the route planner.'
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border border-[rgba(80,170,210,0.4)] bg-[rgba(40,140,180,0.15)] px-2.5 py-[2px] align-baseline font-mono text-[13px] font-semibold tabular-nums text-[#aaccee] shadow-[inset_0_0_8px_rgba(40,140,180,0.1)]"
      title={tooltip}
    >
      <span className="text-[#55aaff]" aria-hidden>⌖</span>
      <span>
        <span className="text-[#66809a]">(</span>
        {x}
        <span className="text-[#66809a]">,&nbsp;</span>
        {y !== undefined && (
          <>
            {y}
            <span className="text-[#66809a]">,&nbsp;</span>
          </>
        )}
        {z}
        <span className="text-[#66809a]">)</span>
      </span>
    </span>
  )
}

function TargetRow({ entry }: { entry: TargetEntry }) {
  const s = OUTCOME_STYLES[entry.outcome]
  const coordsNode = entry.coords ? (
    <Coords
      x={entry.coords.x}
      y={entry.coords.y}
      z={entry.coords.z}
    />
  ) : (
    <span className="italic text-[#8899bb]">the target</span>
  )
  const wpNum = entry.waypoints ? Number.parseInt(entry.waypoints, 10) : null
  const wpPhrase =
    wpNum != null && Number.isFinite(wpNum) ? (
      <>
        {' '}via a{' '}
        <span
          className="font-semibold text-[#cde]"
          title="Number of navigation waypoints the drone flies through to reach the target"
        >
          {wpNum}-waypoint flight path
        </span>
      </>
    ) : null

  const detailNode = entry.detail ? (
    <>
      {' — '}
      <span className="italic text-[#a0b3c8]">{entry.detail.replace(/\.$/, '')}</span>
    </>
  ) : null

  let narrative: React.ReactNode
  if (entry.outcome === 'success') {
    narrative = (
      <>
        Supplies <span className="font-semibold text-[#44dd88]">delivered</span> to
        survivor at {coordsNode}
        {wpPhrase}.
      </>
    )
  } else if (entry.outcome === 'skipped') {
    narrative = (
      <>
        Delivery to survivor at {coordsNode}{' '}
        <span className="font-semibold text-[#ffaa33]">skipped</span>
        {detailNode}.
      </>
    )
  } else if (entry.outcome === 'error') {
    narrative = (
      <>
        Delivery to survivor at {coordsNode}{' '}
        <span className="font-semibold text-[#ff5555]">failed</span>
        {detailNode}.
      </>
    )
  } else {
    narrative = <span>{entry.raw}</span>
  }

  return (
    <li className="flex items-start gap-3.5 rounded border border-[rgba(40,140,180,0.15)] bg-[rgba(4,6,14,0.5)] px-3.5 py-3">
      <span
        className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[14px] font-bold ${s.iconBg}`}
        aria-label={s.label}
      >
        {s.icon}
      </span>
      <span className="min-w-0 flex-1 text-[14px] leading-relaxed text-[#cde]">
        {narrative}
      </span>
    </li>
  )
}

function BuildingRow({ entry }: { entry: BuildingEntry }) {
  const loc = extractXZ(entry.name)
  const n = entry.survivorCount
  const hit = n > 0
  const locNode = loc ? (
    <Coords x={loc.x} z={loc.z} />
  ) : (
    <span className="font-mono text-[#cde]">{entry.name}</span>
  )
  const verdict = hit ? (
    <span className="font-semibold text-[#44dd88]">
      {n} {n === 1 ? 'survivor' : 'survivors'} detected
    </span>
  ) : (
    <span className="font-semibold text-[#8899bb]">no heat signatures detected</span>
  )
  return (
    <li className="rounded border border-[rgba(40,140,180,0.15)] bg-[rgba(4,6,14,0.5)] px-3.5 py-3">
      <div className="flex items-start gap-3.5">
        <span
          className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[14px] ${
            hit
              ? 'bg-[rgba(68,221,136,0.15)] text-[#44dd88] ring-1 ring-[rgba(68,221,136,0.3)]'
              : 'bg-[rgba(80,120,150,0.15)] text-[#8899bb] ring-1 ring-[rgba(80,120,150,0.25)]'
          }`}
          aria-hidden
        >
          ⌕
        </span>
        <span className="min-w-0 flex-1 text-[14px] leading-relaxed text-[#cde]">
          Scanned building at {locNode} — {verdict}.
        </span>
      </div>
      {entry.survivors.length > 0 && (
        <ul className="ml-10 mt-2.5 space-y-1.5 text-[13px]">
          {entry.survivors.map((sv, i) => (
            <li key={i} className="flex items-center gap-3 text-[#cde]">
              <span
                className={`h-2 w-2 rounded-full shadow-[0_0_6px_currentColor] ${
                  sv.submerged
                    ? 'bg-[#ff5555] text-[#ff5555]'
                    : 'bg-[#44ff66] text-[#44ff66]'
                }`}
              />
              <span>
                {sv.submerged ? (
                  <>
                    <span className="font-semibold text-[#ff5555]">Submerged survivor</span>{' '}
                    found at
                  </>
                ) : (
                  <>Survivor found at</>
                )}{' '}
                {sv.coords && (
                  <span
                    className="font-mono text-[#cde]"
                    title="Survivor position (x, y, z) in the world grid"
                  >
                    {sv.coords}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function EntryRow({ entry }: { entry: Entry }) {
  if (entry.kind === 'target') return <TargetRow entry={entry} />
  if (entry.kind === 'building') return <BuildingRow entry={entry} />
  return (
    <li className="px-3 py-1.5 text-[12px] italic text-[#8899bb]">{entry.text}</li>
  )
}

function FooterPill({ row }: { row: FooterRow }) {
  const label = humanFooterLabel(row.label || 'NOTE')
  return (
    <div className="rounded border border-[rgba(40,140,180,0.18)] bg-[rgba(4,6,14,0.5)] px-3.5 py-2.5">
      <div className="text-[10px] font-bold tracking-[1.5px] text-[#556677]">
        {label}
      </div>
      <div className={`mt-1 text-[20px] font-bold leading-none tabular-nums ${TONE_TEXT[row.tone]}`}>
        {row.value}
      </div>
    </div>
  )
}

function Section({ section }: { section: Section }) {
  const summary = sectionSummary(section)
  return (
    <div>
      <div className="mb-2.5 flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-[#667788]">Drone</span>
        <span className="inline-flex items-center gap-1.5 rounded border border-[rgba(80,170,210,0.3)] bg-[rgba(40,140,180,0.12)] px-2.5 py-0.5 font-mono text-[12px] font-bold tracking-[1px] text-[#88bbdd]">
          <span className="h-1.5 w-1.5 rounded-full bg-[#55aaff]" />
          {section.assetId}
        </span>
        {summary && (
          <span className="text-[13px] text-[#8899bb]">{summary}</span>
        )}
        <div className="h-px flex-1 bg-gradient-to-r from-[rgba(40,140,180,0.2)] to-transparent" />
      </div>
      <ul className="space-y-2">
        {section.entries.map((e, i) => (
          <EntryRow key={i} entry={e} />
        ))}
      </ul>
    </div>
  )
}

function StructuredBody({ report }: { report: ParsedReport }) {
  return (
    <div className="space-y-6 px-5 py-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-[rgba(40,140,180,0.2)] pb-4">
        <div>
          <div className="text-[10px] font-bold tracking-[1.5px] text-[#556677]">
            SUMMARY
          </div>
          <div className="mt-1 text-[18px] font-semibold tracking-[0.2px] text-[#eef]">
            {toSentenceCase(report.title)}
          </div>
        </div>
        {report.count && (
          <span className="rounded-full border border-[rgba(80,170,210,0.35)] bg-[rgba(40,140,180,0.12)] px-3 py-1.5 text-[11px] font-bold tracking-[1.5px] text-[#88bbdd]">
            {report.count.n} {smartPlural(report.count.unit, Number(report.count.n)).toUpperCase()}
          </span>
        )}
      </div>

      {report.sections.length > 0 && (
        <div className="space-y-5">
          {report.sections.map(sec => (
            <Section key={sec.assetId} section={sec} />
          ))}
        </div>
      )}

      {report.ungrouped.length > 0 && (
        <div>
          <div className="mb-2.5 text-[11px] font-bold tracking-[1.5px] text-[#556677]">
            ADDITIONAL RESULTS
          </div>
          <ul className="space-y-2">
            {report.ungrouped.map((e, i) => (
              <EntryRow key={i} entry={e} />
            ))}
          </ul>
        </div>
      )}

      {report.footer.length > 0 && (
        <div className="grid grid-cols-2 gap-2.5 border-t border-[rgba(40,140,180,0.2)] pt-5 sm:grid-cols-3 md:grid-cols-4">
          {report.footer.map((row, i) => (
            <FooterPill key={i} row={row} />
          ))}
        </div>
      )}
    </div>
  )
}

export function MissionOutcomeReport({
  text,
}: {
  text: string
  toolCallCount?: number
}) {
  const report = parseReport(text)

  return (
    <div className="overflow-hidden rounded border border-[rgba(40,140,180,0.2)] bg-[rgba(2,4,10,0.7)]">
      {report ? (
        <StructuredBody report={report} />
      ) : (
        <pre className="whitespace-pre-wrap break-words px-5 py-4 font-mono text-[13.5px] leading-[1.65] text-[#cde]">
          {text}
        </pre>
      )}
    </div>
  )
}
