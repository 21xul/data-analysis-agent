const BASE = '/api/v1'

async function jsonFetch(url, options) {
  const resp = await fetch(BASE + url, options)
  if (!resp.ok) {
    let detail = ''
    try { detail = (await resp.json()).detail || '' } catch { /* ignore */ }
    throw new Error(detail || `请求失败 (${resp.status})`)
  }
  return resp.json()
}

async function consumeSSE(resp, onEvent) {
  if (!resp.ok || !resp.body) {
    let detail = ''
    try { detail = (await resp.json()).detail || '' } catch { /* ignore */ }
    throw new Error(detail || `运行失败 (${resp.status})`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      const lines = chunk.split('\n')
      const kind = (lines.find(l => l.startsWith('event:')) || '').slice(6).trim()
      const raw = (lines.find(l => l.startsWith('data:')) || '').slice(5).trim()
      if (!raw) continue
      try { onEvent(kind, JSON.parse(raw)) } catch { /* 跳过坏帧 */ }
    }
  }
}

async function streamPost(url, body, onEvent) {
  const resp = await fetch(BASE + url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  await consumeSSE(resp, onEvent)
}

export const health = () => jsonFetch('/health')

export const listDatasets = () => jsonFetch('/datasets')

export const previewDataset = (id, limit = 40) =>
  jsonFetch(`/datasets/${encodeURIComponent(id)}/preview?limit=${limit}`)

export const datasetStats = (id) =>
  jsonFetch(`/datasets/${encodeURIComponent(id)}/stats`)

export const datasetSchema = (id) => jsonFetch(`/datasets/${encodeURIComponent(id)}/schema`)

export function uploadDataset(file) {
  const form = new FormData()
  form.append('file', file)
  return jsonFetch('/datasets', { method: 'POST', body: form })
}

export const createDemo = () => jsonFetch('/datasets/demo', {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}'
})

/** P0 链路：ReAct 的 thought/action/observation 事件流 */
export const runAgent = (question, datasetId, onEvent) =>
  streamPost('/runs', { question, dataset_id: datasetId }, onEvent)

/** P1 链路：LangGraph 的 meta/node×N/final 逐节点事件流 */
export const runGraphStream = (question, datasetId, forceBranch, onEvent) =>
  streamPost('/graph/runs/stream', {
    question, dataset_id: datasetId, force_branch: forceBranch || ''
  }, onEvent)
