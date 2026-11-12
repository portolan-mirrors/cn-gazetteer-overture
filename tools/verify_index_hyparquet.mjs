// Read the search index the way the geocoder will, and report what it cost.
//
//   node tools/verify_index_hyparquet.mjs [path-to-index.parquet]
//
// hyparquet is what a browser client uses, so this is the check that matters:
// pyarrow reading its own output proves less than a different implementation
// reading it. Every byte the reader asks for is counted, so the numbers below
// are the actual cost of a keystroke rather than an estimate.
//
// Needs hyparquet and hyparquet-compressors. The index is zstd on every
// column chunk, so the compressors package is not optional. Install them
// outside the repository, for example:
//
//   mkdir -p ../cn-geocoder-overture-staging/work/node
//   cd ../cn-geocoder-overture-staging/work/node
//   npm install hyparquet hyparquet-compressors
//   NODE_PATH=$PWD/node_modules node ../../../cn-geocoder-overture/tools/verify_index_hyparquet.mjs

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
    try {
      return await import(path.join(root, name, 'src/index.js'))
    } catch {}
    try {
      return await import(require.resolve(name, { paths: [root] }))
    } catch {}
  }
  return await import(name)
}

const { parquetMetadataAsync, parquetReadObjects } = await load('hyparquet')
const { compressors } = await load('hyparquet-compressors')

const file = process.argv[2] ??
  path.resolve(
    import.meta.dirname,
    '../../cn-geocoder-overture-staging/publish/names/overture_division_names.parquet',
  )

// A byte-counting AsyncBuffer. Every slice the reader asks for is recorded, so
// "bytes fetched" below is what a browser would have pulled over the network.
async function countingBuffer (filePath) {
  const { size } = await stat(filePath)
  const handle = await open(filePath, 'r')
  const stats = { requests: 0, bytes: 0 }
  return {
    stats,
    buffer: {
      byteLength: size,
      async slice (start, end = size) {
        const from = start < 0 ? size + start : start
        const length = end - from
        stats.requests += 1
        stats.bytes += length
        const buf = Buffer.alloc(length)
        await handle.read(buf, 0, length, from)
        return buf.buffer.slice(buf.byteOffset, buf.byteOffset + length)
      },
    },
    close: () => handle.close(),
  }
}

function fmt (n) {
  if (n > 1e9) return `${(n / 1e9).toFixed(2)} GB`
  if (n > 1e6) return `${(n / 1e6).toFixed(2)} MB`
  if (n > 1e3) return `${(n / 1e3).toFixed(1)} KB`
  return `${n} B`
}

const { stats, buffer, close } = await countingBuffer(file)

// 1. The footer, read as one exactly-sized tail request. The index manifest
//    publishes `index.size` precisely so this does not have to be speculative.
const t0 = performance.now()
const metadata = await parquetMetadataAsync(buffer)
const footerCost = { ...stats }
const footerMs = performance.now() - t0

const rowGroups = metadata.row_groups
const names = metadata.schema.filter(s => s.num_children === undefined)
  .map(s => s.name)
const normIndex = rowGroups[0].columns.findIndex(
  c => c.meta_data.path_in_schema.join('.') === 'name_norm',
)
const sorting = rowGroups[0].sorting_columns

console.log(`file          ${path.basename(file)}`)
console.log(`size          ${fmt(Number(buffer.byteLength))}`)
console.log(`rows          ${Number(metadata.num_rows).toLocaleString()}`)
console.log(`row groups    ${rowGroups.length.toLocaleString()}`)
console.log(`columns       ${names.length}`)
console.log(`footer read   ${fmt(footerCost.bytes)} in ${footerCost.requests} request(s), ${footerMs.toFixed(0)} ms`)
console.log(`sorted_by     ${sorting ? JSON.stringify(sorting) : 'NOT DECLARED'}`)
console.log(`kv metadata   ${metadata.key_value_metadata.filter(kv => kv.key.startsWith('cnmw:') || kv.key.startsWith('overture:')).map(kv => `${kv.key}=${kv.value}`).join(', ')}`)

// 2. A prefix lookup. Binary-search the row group statistics on name_norm,
//    then read only the groups a match can live in. This is one keystroke.
const dec = new TextDecoder()
function statString (v) {
  return typeof v === 'string' ? v : dec.decode(v)
}
const ranges = rowGroups.map(rg => {
  const st = rg.columns[normIndex].meta_data.statistics
  return [statString(st.min_value ?? st.min), statString(st.max_value ?? st.max)]
})

function groupsFor (prefix) {
  const upper = prefix + '￿'
  const hit = []
  for (let g = 0; g < ranges.length; g++) {
    const [lo, hi] = ranges[g]
    if (hi >= prefix && lo <= upper) hit.push(g)
  }
  return hit
}

const SEARCH_COLUMNS = [
  'name', 'name_norm', 'level', 'country', 'feature_id', 'source',
  'name_lang', 'alt_of', 'parent_name', 'bbox', 'population', 'name_dupes',
  'has_boundary', 'geometry_ref',
]

for (const prefix of ['zur', 'sao pa', 'bengal', 'købe', 'wa']) {
  const groups = groupsFor(prefix)
  const first = groups[0]
  const last = groups[groups.length - 1]
  const rowsPerGroup = Number(rowGroups[0].num_rows)
  const before = { ...stats }
  const t = performance.now()
  const rows = await parquetReadObjects({
    file: buffer,
    compressors,
    columns: SEARCH_COLUMNS,
    rowStart: first * rowsPerGroup,
    rowEnd: Math.min((last + 1) * rowsPerGroup, Number(metadata.num_rows)),
  })
  const ms = performance.now() - t
  const matches = rows.filter(r => r.name_norm.startsWith(prefix))
  const top = matches
    .slice()
    .sort((a, b) => (a.level - b.level) || ((b.population ?? 0) - (a.population ?? 0)))
    .slice(0, 3)
    .map(r => `${r.name}${r.name_lang ? ` [${r.name_lang}]` : ''} (L${r.level} ${r.country})`)
  console.log(
    `\nprefix "${prefix}"  groups ${groups.length}  ` +
    `fetched ${fmt(stats.bytes - before.bytes)} in ${stats.requests - before.requests} request(s), ` +
    `${ms.toFixed(0)} ms  matches ${matches.length}`,
  )
  console.log(`  top: ${top.join(' | ')}`)
}

// 3. The contract's own assertions, checked from a second implementation.
const problems = []
for (const required of ['name', 'name_norm', 'level', 'country', 'feature_id', 'source', 'bbox']) {
  if (!names.includes(required) && required !== 'bbox') problems.push(`missing ${required}`)
}
if (!names.some(n => n === 'bbox.xmin' || n === 'xmin')) {
  if (!metadata.schema.some(s => s.name === 'bbox')) problems.push('missing bbox struct')
}
if (!sorting || sorting.length === 0) problems.push('footer declares no sorting_columns')
for (let g = 1; g < ranges.length; g++) {
  if (ranges[g][0] < ranges[g - 1][1]) {
    problems.push(`row group ${g} statistics overlap row group ${g - 1}`)
    break
  }
}
console.log(
  problems.length
    ? `\nFAIL\n  ${problems.join('\n  ')}`
    : '\nOK: required columns present, sort declared, row group ranges non-overlapping',
)
console.log(`total read    ${fmt(stats.bytes)} in ${stats.requests} request(s)`)
await close()
process.exit(problems.length ? 1 : 0)
