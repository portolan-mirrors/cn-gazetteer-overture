// What one feature costs a browser, measured with the reader a browser uses.
//
//   node tools/measure_reads.mjs <file-or-url> [--rows 12] [--seed 7]
//                               [--columns a,b,c] [--footer-bytes N]
//
// Three numbers, in the order a client pays them:
//
//   1. the footer. A client that knows `footer_bytes` fetches the trailing
//      footer + page index in one exactly-sized request. One that does not
//      pays hyparquet's speculative 512 KiB tail and, when the footer is
//      larger than that, a second request. Both are measured, because the
//      difference is the whole argument for publishing `footer_bytes`.
//
//   2. one feature, by row number. This is `select()` resolving a names-index
//      `geometry_ref`: it knows the row, so the only question is how many
//      bytes the row group that holds it costs. Parquet has no sub-chunk
//      read in hyparquet -- asking for row 3 of a 512-row group fetches that
//      group's whole geometry column chunk -- so this number is set by the
//      row group size and by nothing else. It is the ~6 s ADM2 floor.
//
//   3. the same read against the display file, where one exists.
//
// It also measures the upstream Overture release directly, which is the
// comparison the catalog README rests on: pass the S3 HTTPS URL of a release
// part file and `--rows 0` to read only its footer and report its row group
// layout without pulling a row group.
//
// Every byte the reader asks for is counted through a wrapping AsyncBuffer,
// so "bytes" is what the network would have carried, not an estimate. A
// `https://` argument is read with real HTTP range requests, so the live
// catalog can be measured exactly as a browser meets it.
//
// hyparquet and hyparquet-compressors live outside the repository, with the
// staged data:
//
//   mkdir -p ../cn-geocoder-overture-staging/work/node
//   cd ../cn-geocoder-overture-staging/work/node && npm install hyparquet hyparquet-compressors

import { createRequire } from 'node:module'
import { open, stat } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const roots = [
  process.env.NODE_PATH,
  path.resolve('../cn-geocoder-overture-staging/work/node/node_modules'),
  path.resolve(import.meta.dirname, '../../cn-geocoder-overture-staging/work/node/node_modules'),
].filter(Boolean)

async function load (name) {
  for (const root of roots) {
    try { return await import(path.join(root, name, 'src/index.js')) } catch {}
    try { return await import(require.resolve(name, { paths: [root] })) } catch {}
  }
  return await import(name)
}

const { parquetMetadataAsync, parquetReadObjects, cachedAsyncBuffer } = await load('hyparquet')
const { compressors } = await load('hyparquet-compressors')

// ---------------------------------------------------------------------------
// Arguments
// ---------------------------------------------------------------------------
const argv = process.argv.slice(2)
const target = argv.find(a => !a.startsWith('--'))
if (!target) {
  console.error('usage: node tools/measure_reads.mjs <file-or-url> [--rows N] [--seed N] [--columns a,b] [--footer-bytes N] [--json]')
  process.exit(2)
}
function flag (name, fallback) {
  const i = argv.indexOf(`--${name}`)
  return i === -1 ? fallback : argv[i + 1]
}
const SAMPLES = Number(flag('rows', 12))  // 0 reads the footer and stops
const SEED = Number(flag('seed', 7))
const WANT_COLUMNS = flag('columns', null)?.split(',')
const DECLARED_FOOTER = flag('footer-bytes', null)
const AS_JSON = argv.includes('--json')

// ---------------------------------------------------------------------------
// Byte-counting buffers
// ---------------------------------------------------------------------------
function counter () {
  return { requests: 0, bytes: 0, slices: [] }
}

async function localBuffer (filePath) {
  const { size } = await stat(filePath)
  const handle = await open(filePath, 'r')
  const stats = counter()
  return {
    stats,
    size,
    buffer: {
      byteLength: size,
      async slice (start, end = size) {
        const from = start < 0 ? size + start : start
        const length = end - from
        stats.requests += 1
        stats.bytes += length
        stats.slices.push(length)
        const buf = Buffer.alloc(length)
        await handle.read(buf, 0, length, from)
        return buf.buffer.slice(buf.byteOffset, buf.byteOffset + length)
      },
    },
    close: () => handle.close(),
  }
}

async function urlBuffer (url) {
  // HEAD first, the way a client that has no manifest must. A client that has
  // the manifest knows `size` and `footer_bytes` and skips this entirely --
  // which is itself one round trip saved, and is noted in the output.
  const head = await fetch(url, { method: 'HEAD' })
  if (!head.ok) throw new Error(`HEAD ${url} -> ${head.status}`)
  const size = Number(head.headers.get('content-length'))
  if (!Number.isFinite(size)) throw new Error(`no content-length from ${url}`)
  if ((head.headers.get('accept-ranges') || '').indexOf('bytes') === -1) {
    console.error(`warning: ${url} does not advertise Accept-Ranges: bytes`)
  }
  const stats = counter()
  return {
    stats,
    size,
    headRequest: true,
    buffer: {
      byteLength: size,
      async slice (start, end = size) {
        const from = start < 0 ? size + start : start
        const last = end - 1
        stats.requests += 1
        stats.bytes += end - from
        stats.slices.push(end - from)
        const res = await fetch(url, { headers: { range: `bytes=${from}-${last}` } })
        if (res.status !== 206) {
          throw new Error(`range request returned ${res.status}, not 206 -- the host ignored Range`)
        }
        return await res.arrayBuffer()
      },
    },
    close: () => {},
  }
}

const isUrl = /^https?:\/\//.test(target)
const openTarget = () => (isUrl ? urlBuffer(target) : localBuffer(target))

function fmt (n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)} MB`
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)} KB`
  return `${n} B`
}

// A deterministic generator, so a reported number can be reproduced.
function rng (seed) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 2 ** 32
  }
}

function median (xs) {
  const s = [...xs].sort((a, b) => a - b)
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2
}

// ---------------------------------------------------------------------------
// 1. The footer, both ways
// ---------------------------------------------------------------------------
const result = { target, size: null, rows: null, row_groups: null }

// Speculative: hyparquet's own default, which is what a client without
// `footer_bytes` does.
{
  const { stats, size, buffer, close } = await openTarget()
  const t = performance.now()
  const metadata = await parquetMetadataAsync(buffer)
  const ms = performance.now() - t
  result.size = size
  result.rows = Number(metadata.num_rows)
  result.row_groups = metadata.row_groups.length
  result.footer_speculative = { bytes: stats.bytes, requests: stats.requests, ms: Math.round(ms), slices: stats.slices }
  await close()
}

// Exact: one request of exactly `footer_bytes`, the number the manifest
// publishes. hyparquet takes it as `initialFetchSize`.
{
  const { stats, buffer, close } = await openTarget()
  const initialFetchSize = DECLARED_FOOTER ? Number(DECLARED_FOOTER) : undefined
  const t = performance.now()
  const metadata = await parquetMetadataAsync(buffer, { initialFetchSize })
  const ms = performance.now() - t
  result.footer_exact = {
    bytes: stats.bytes,
    requests: stats.requests,
    ms: Math.round(ms),
    declared: initialFetchSize ?? null,
    slices: stats.slices,
  }
  result.metadata_rows = Number(metadata.num_rows)
  await close()
}

// ---------------------------------------------------------------------------
// 2. One feature, by row number
// ---------------------------------------------------------------------------
const { stats, buffer: rawBuffer, close } = await openTarget()
// cachedAsyncBuffer is what a client uses: the footer is read once and every
// later read is a row group read, not a footer re-read. Without it every
// per-feature figure below would be the footer plus the group.
const buffer = cachedAsyncBuffer(rawBuffer)
const metadata = await parquetMetadataAsync(buffer, {
  initialFetchSize: DECLARED_FOOTER ? Number(DECLARED_FOOTER) : undefined,
})
const rowGroups = metadata.row_groups
// Top-level column names, taken from the row group's chunk paths. A struct
// such as `bbox` is one top-level column with four leaves, and hyparquet
// names the whole struct, not its leaves, in `columns`.
const leaves = rowGroups[0].columns.map(c => c.meta_data.path_in_schema.join('.'))
const topLevel = [...new Set(rowGroups[0].columns.map(c => c.meta_data.path_in_schema[0]))]
const columns = WANT_COLUMNS ?? topLevel

// Row group boundaries, taken from the footer rather than assumed: a
// manifest's `row_group_rows` is a claim, and this is the check on it.
const starts = []
let acc = 0
for (const rg of rowGroups) { starts.push(acc); acc += Number(rg.num_rows) }
const totalRows = Number(metadata.num_rows)
const uniformRows = new Set(rowGroups.slice(0, -1).map(rg => Number(rg.num_rows)))
result.row_group_rows = uniformRows.size === 1 ? [...uniformRows][0] : [...uniformRows]

// Row group sizes straight from the footer. With --rows 0 this is the whole
// report: an upstream release part file can hold hundreds of megabytes in one
// row group, so measuring its layout must not require fetching one.
const groupBytes = rowGroups.map(rg =>
  rg.columns.reduce((n, c) => n + Number(c.meta_data.total_compressed_size), 0))
const sortedGroups = [...groupBytes].sort((a, b) => a - b)
result.row_group_bytes = {
  median: Math.round(median(sortedGroups)),
  min: sortedGroups[0],
  max: sortedGroups[sortedGroups.length - 1],
}

const rand = rng(SEED)
const picks = []
for (let i = 0; i < SAMPLES; i++) picks.push(Math.floor(rand() * totalRows))

const per = []
for (const row of picks) {
  const before = { requests: stats.requests, bytes: stats.bytes }
  const t = performance.now()
  const rows = await parquetReadObjects({
    // A fresh cache per sample, and the footer handed over rather than
    // re-read, so each figure is a *cold* read of one row group and nothing
    // else. Reusing one cache across samples measured 0 bytes whenever two
    // picks landed in the same group, which is true but is the warm case.
    file: cachedAsyncBuffer(rawBuffer),
    metadata,
    compressors,
    columns,
    rowStart: row,
    rowEnd: row + 1,
    // utf8:false keeps hyparquet from trying to decode the WKB geometry
    // column as a string, per the client contract.
    utf8: false,
  })
  const ms = performance.now() - t
  if (rows.length !== 1) throw new Error(`row ${row}: reader returned ${rows.length} rows`)
  const group = starts.findLastIndex(s => s <= row)
  per.push({
    row,
    group,
    bytes: stats.bytes - before.bytes,
    requests: stats.requests - before.requests,
    ms,
  })
}
await close()

// A second pass over the *same* rows, to separate a cold read from a warm
// one: the cache means the second read of a row group costs nothing, which is
// what makes a second keystroke on the same prefix free.
result.per_feature = {
  samples: per.length,
  columns: columns.length,
  bytes_median: Math.round(median(per.map(p => p.bytes))),
  bytes_min: Math.min(...per.map(p => p.bytes)),
  bytes_max: Math.max(...per.map(p => p.bytes)),
  ms_median: Number(median(per.map(p => p.ms)).toFixed(1)),
  ms_max: Number(Math.max(...per.map(p => p.ms)).toFixed(1)),
  requests_median: median(per.map(p => p.requests)),
}
result.first_select_bytes = result.footer_exact.bytes + result.per_feature.bytes_median

if (SAMPLES === 0) {
  await close()
  const r = result
  console.log(`file               ${isUrl ? target : path.basename(target)}`)
  console.log(`size               ${fmt(r.size)} (${r.size.toLocaleString()} bytes)`)
  console.log(`rows / row groups  ${r.rows.toLocaleString()} in ${r.row_groups} group(s) of ${JSON.stringify(r.row_group_rows)}`)
  console.log(`footer speculative ${fmt(r.footer_speculative.bytes)} in ${r.footer_speculative.requests} request(s), ${r.footer_speculative.ms} ms  [${r.footer_speculative.slices.join(', ')}]`)
  console.log(`footer exact       ${fmt(r.footer_exact.bytes)} in ${r.footer_exact.requests} request(s), ${r.footer_exact.ms} ms  (declared ${r.footer_exact.declared ?? 'none -- speculative'})`)
  console.log(`row group bytes    median ${fmt(r.row_group_bytes.median)}, min ${fmt(r.row_group_bytes.min)}, max ${fmt(r.row_group_bytes.max)}`)
  console.log(`columns            ${leaves.length} leaf column chunk(s)`)
  console.log(`sorted_by          ${rowGroups[0].sorting_columns ? JSON.stringify(rowGroups[0].sorting_columns) : 'NOT DECLARED'}`)
  if (AS_JSON) console.log(JSON.stringify(r, null, 2))
  process.exit(0)
}

if (AS_JSON) {
  console.log(JSON.stringify(result, null, 2))
} else {
  console.log(`file               ${isUrl ? target : path.basename(target)}`)
  console.log(`size               ${fmt(result.size)} (${result.size.toLocaleString()} bytes)`)
  console.log(`rows / row groups  ${result.rows.toLocaleString()} in ${result.row_groups} group(s) of ${JSON.stringify(result.row_group_rows)}`)
  console.log(`footer speculative ${fmt(result.footer_speculative.bytes)} in ${result.footer_speculative.requests} request(s), ${result.footer_speculative.ms} ms  [${result.footer_speculative.slices.join(', ')}]`)
  console.log(`footer exact       ${fmt(result.footer_exact.bytes)} in ${result.footer_exact.requests} request(s), ${result.footer_exact.ms} ms  (declared ${result.footer_exact.declared ?? 'none -- speculative'})`)
  console.log(`one feature        median ${fmt(result.per_feature.bytes_median)} in ${result.per_feature.requests_median} request(s), ${result.per_feature.ms_median} ms   (min ${fmt(result.per_feature.bytes_min)}, max ${fmt(result.per_feature.bytes_max)}, worst ${result.per_feature.ms_max} ms)`)
  console.log(`columns read       ${columns.length} of ${leaves.length}`)
  console.log(`FIRST SELECT       ${fmt(result.first_select_bytes)} = footer ${fmt(result.footer_exact.bytes)} + one group ${fmt(result.per_feature.bytes_median)}`)
}
