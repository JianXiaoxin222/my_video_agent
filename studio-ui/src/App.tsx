import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  addEdge, Background, Controls, Handle, MiniMap, Position, ReactFlow, useEdgesState, useNodesState,
  type Connection, type Edge, type Node,
} from '@xyflow/react'
import { ArrowDown, ArrowUp, CheckCircle2, ChevronDown, CircleHelp, FileImage, Film, GripVertical, History, ImagePlus, LayoutGrid, Plus, Save, Settings2, Sparkles, Terminal, Trash2, Upload, WandSparkles, XCircle } from 'lucide-react'
import '@xyflow/react/dist/style.css'

type NodeData = { label: ReactNode; kind: string; mode?: string; model?: string; prompt?: string; url?: string; localPreview?: string; fileName?: string; uploadState?: 'idle' | 'uploading' | 'uploaded' | 'error'; duration?: number; ratio?: string; resolution?: string; result?: { type: string; url?: string }; onSelect?: () => void }

// Start with one clean generation node. Inputs are configured in the inspector
// or supplied by connecting another generation node from the palette.
const initialNodes: Node<NodeData>[] = [
  { id: 'image-generate', type: 'default', position: { x: 360, y: 220 }, data: { label: '图片生成', kind: 'image_generate', model: 'doubao-seedream-5-0-pro-260628' } },
]

const initialEdges: Edge[] = []

const palette = [
  { kind: 'image_input', label: '图片素材', icon: FileImage, detail: '本地文件 / 公网 URL' },
  { kind: 'video_input', label: '视频素材', icon: Film, detail: '本地文件 / 公网 URL' },
  { kind: 'image_generate', label: '图片生成', icon: ImagePlus, detail: 'Text / image → image' },
  { kind: 'video_generate', label: '视频生成', icon: WandSparkles, detail: 'Text / image / video → video' },
]

function nodeClass(kind: string) {
  return `studio-node node-${kind.replace('_', '-')}`
}

function NodeCard({ node, selected, onSelect }: { node: Node<NodeData>; selected: boolean; onSelect: () => void }) {
  const icon = node.data.kind === 'image_input' ? <FileImage size={15} /> : node.data.kind === 'video_input' ? <Film size={15} /> : node.data.kind === 'image_generate' ? <ImagePlus size={15} /> : <WandSparkles size={15} />
  const assetPreview = node.data.localPreview || node.data.url
  return <div className={`${nodeClass(node.data.kind)} ${selected ? 'is-selected' : ''}`} onClick={onSelect} tabIndex={0} role="button" aria-label={`${node.data.label} node`}>
    <div className="node-head"><span className="node-icon">{icon}</span><span>{node.data.label}</span><span className="node-menu">•••</span></div>
    {(node.data.kind === 'image_generate' || node.data.kind === 'video_generate') && <div className="mode-chip">mode inferred from links</div>}
    {node.data.prompt && <p>{node.data.prompt}</p>}
    {assetPreview && <div className="asset-line"><Upload size={13} /> {node.data.fileName || assetPreview.replace(/^https?:\/\//, '').slice(0, 29)}{node.data.fileName ? '' : '…'}</div>}
    {assetPreview && node.data.kind === 'image_input' && <div className="node-asset-media"><img src={assetSrc(assetPreview)} alt="Image asset" /></div>}
    {assetPreview && node.data.kind === 'video_input' && <div className="node-asset-media"><video src={assetSrc(assetPreview)} controls muted /></div>}
    {node.data.result?.url && <div className="node-result-media">{node.data.result.type === 'video_result' ? <video src={assetSrc(node.data.result.url)} controls muted /> : <img src={assetSrc(node.data.result.url)} alt="Generated result" />}</div>}
    {node.data.kind === 'video_generate' && <div className="node-meta"><span>{node.data.ratio}</span><span>{node.data.duration}s</span><span>audio on</span></div>}
    <span className="port port-in" /><span className="port port-out" />
  </div>
}

function CanvasNode({ id, data, selected }: { id: string; data: NodeData; selected?: boolean }) {
  const node = { id, type: 'studio', position: { x: 0, y: 0 }, data } as Node<NodeData>
  const targetHandles = data.kind === 'image_generate' ? ['prompt', 'reference'] : data.kind === 'video_generate' ? ['prompt', 'image', 'video'] : data.kind === 'output' ? ['input'] : []
  const sourceHandle = data.kind === 'video_generate' ? 'video_result' : data.kind === 'image_generate' ? 'image' : data.kind === 'text_input' ? 'text' : data.kind === 'image_input' ? 'image' : data.kind === 'video_input' ? 'video' : 'output'
  return <>
    {targetHandles.map((handle, index) => <Handle key={handle} type="target" position={Position.Left} id={handle} style={{ top: `${35 + index * 22}%` }} />)}
    <NodeCard node={node} selected={Boolean(selected)} onSelect={data.onSelect ?? (() => {})} />
    <Handle type="source" position={Position.Right} id={sourceHandle} />
  </>
}

const nodeTypes = { studio: CanvasNode }

function inferMode(nodeId: string, nodes: Node<NodeData>[], edges: Edge[]) {
  const node = nodes.find((item) => item.id === nodeId)
  if (!node) return ''
  const upstream = new Set(edges.filter((edge) => edge.target === nodeId).map((edge) => nodes.find((item) => item.id === edge.source)?.data.kind))
  if (node.data.kind === 'image_generate') return upstream.has('image_input') || upstream.has('image_generate') ? 'image-to-image' : 'text-to-image'
  if (node.data.kind === 'video_generate') {
    if (upstream.has('video_input') || upstream.has('video_generate')) return 'video-to-video'
    if (upstream.has('image_input') || upstream.has('image_generate')) return 'image-to-video'
    return 'text-to-video'
  }
  return ''
}

function assetSrc(url?: string) {
  if (!url) return ''
  return url.startsWith('http://') || url.startsWith('https://') || url.startsWith('blob:') || url.startsWith('data:') ? url : `http://127.0.0.1:8000${url}`
}

const STUDIO_API = 'http://127.0.0.1:8000'
const PENDING_ERRORS_KEY = 'video-agent-studio.pending-errors'

function detailMessage(detail: unknown) {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const value = detail as { errors?: unknown; message?: unknown }
    if (Array.isArray(value.errors)) return value.errors.filter(Boolean).join('；')
    if (typeof value.message === 'string') return value.message
  }
  return ''
}

async function reportClientError(action: string, message: string, statusCode?: number) {
  const payload = { action, message, status_code: statusCode }
  try {
    const response = await fetch(`${STUDIO_API}/api/client-errors`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
  } catch {
    // Queue the error so it is written to studio_runs.jsonl after the backend
    // comes back. This preserves the diagnostic even during an outage.
    try {
      const pending = JSON.parse(localStorage.getItem(PENDING_ERRORS_KEY) || '[]')
      pending.push(payload)
      localStorage.setItem(PENDING_ERRORS_KEY, JSON.stringify(pending.slice(-50)))
    } catch { /* storage may be unavailable in private browser contexts */ }
  }
}

async function flushPendingClientErrors() {
  let pending: Array<{ action: string; message: string; status_code?: number }> = []
  try { pending = JSON.parse(localStorage.getItem(PENDING_ERRORS_KEY) || '[]') } catch { return }
  if (!pending.length) return
  const remaining: typeof pending = []
  for (const payload of pending) {
    try {
      const response = await fetch(`${STUDIO_API}/api/client-errors`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      })
      if (!response.ok) throw new Error()
    } catch { remaining.push(payload) }
  }
  try { localStorage.setItem(PENDING_ERRORS_KEY, JSON.stringify(remaining)) } catch { /* ignore */ }
}

async function studioFetch(path: string, init?: RequestInit, action = '请求后端') {
  try {
    const response = await fetch(`${STUDIO_API}${path}`, init)
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      const detail = detailMessage(body.detail) || detailMessage(body) || `HTTP ${response.status}`
      const message = `后端返回错误（${action}）：${detail}`
      void reportClientError(action, message, response.status)
      throw new Error(message)
    }
    return response
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('后端返回错误')) throw error
    const message = `无法连接后端服务（${STUDIO_API}）。请确认后端已启动后重试。`
    void reportClientError(action, `${message} ${error instanceof Error ? error.message : String(error)}`)
    throw new Error(message)
  }
}

function fileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('Could not read local file'))
    reader.onerror = () => reject(reader.error || new Error('Could not read local file'))
    reader.readAsDataURL(file)
  })
}

function Inspector({ selectedNode, nodes, edges, updateData, deleteSelected, onGenerate, onUpload, reorderReferences, runState }: {
  selectedNode?: Node<NodeData>
  nodes: Node<NodeData>[]
  edges: Edge[]
  updateData: (key: keyof NodeData, value: string | number) => void
  deleteSelected: () => void
  onGenerate: () => void
  onUpload: (file: File) => void
  reorderReferences: (nodeId: string, edgeIds: string[]) => void
  runState: string
}) {
  const kind = selectedNode?.data.kind
  const isImageInput = kind === 'image_input'
  const isVideoInput = kind === 'video_input'
  const isImage = kind === 'image_generate'
  const isVideo = kind === 'video_generate'
  const mode = selectedNode ? inferMode(selectedNode.id, nodes, edges) : ''
  const assetPreview = selectedNode?.data.localPreview || selectedNode?.data.url
  const inlineImage = isImageInput && selectedNode?.data.url?.startsWith('data:image/')
  const feedsVideo = Boolean(selectedNode && edges.some((edge) => {
    if (edge.source !== selectedNode.id) return false
    return nodes.find((node) => node.id === edge.target)?.data.kind === 'video_generate'
  }))
  const referenceEdges = selectedNode
    ? edges.filter((edge) => edge.target === selectedNode.id && ['image', 'video'].includes((edge.targetHandle || edge.sourceHandle || '') as string))
    : []
  const imageReferenceEdges = referenceEdges.filter((edge) => (edge.targetHandle || edge.sourceHandle || '') === 'image')
  const [draggingReference, setDraggingReference] = useState<string | null>(null)

  const appendReferenceToken = (token: string) => {
    if (!selectedNode) return
    const prompt = selectedNode.data.prompt || ''
    updateData('prompt', prompt.trimEnd() + (prompt.trim() ? ' ' : '') + token)
  }
  const moveReference = (edgeId: string, direction: -1 | 1) => {
    if (!selectedNode) return
    const index = imageReferenceEdges.findIndex((edge) => edge.id === edgeId)
    const targetIndex = index + direction
    if (index < 0 || targetIndex < 0 || targetIndex >= imageReferenceEdges.length) return
    const next = imageReferenceEdges.slice()
    const current = next[index]
    next[index] = next[targetIndex]
    next[targetIndex] = current
    reorderReferences(selectedNode.id, next.map((edge) => edge.id))
  }
  const dropReference = (targetId: string) => {
    if (!selectedNode || !draggingReference || draggingReference === targetId) return
    const from = imageReferenceEdges.findIndex((edge) => edge.id === draggingReference)
    const to = imageReferenceEdges.findIndex((edge) => edge.id === targetId)
    if (from < 0 || to < 0) return
    const next = imageReferenceEdges.slice()
    const moved = next.splice(from, 1)[0]
    next.splice(to, 0, moved)
    reorderReferences(selectedNode.id, next.map((edge) => edge.id))
    setDraggingReference(null)
  }

  return <aside className="inspector">
    <div className="inspector-head"><div><span className="eyebrow">SELECTED NODE</span><h2>{selectedNode?.data.label || 'Node'}</h2></div><button className="icon-btn danger-icon" onClick={deleteSelected} aria-label="Delete selected node"><Trash2 size={17} /></button></div>
    {(isImageInput || isVideoInput) && selectedNode ? <>
      <div className="inspector-section"><label htmlFor="asset-file">本地素材</label><input className="file-input" id="asset-file" type="file" accept={isImageInput ? 'image/*' : 'video/*'} onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(file); event.currentTarget.value = '' }} /><label className="file-picker" htmlFor="asset-file"><Upload size={15} /> {selectedNode.data.uploadState === 'uploading' ? '上传中…' : '选择本地文件'}</label><p className="helper">{inlineImage && feedsVideo ? '当前图片是内联素材，不能用于图生视频；请配置对象存储，或填写可访问的公网 URL。' : inlineImage ? '本地图片已转为内联素材，可直接用于图生图；连接视频节点仍需公网 URL。' : isImageInput ? '图片会自动上传；未配置对象存储时也可作为内联素材直接用于图生图。' : '视频真实生成前需要配置素材存储服务，以提供公网 URL。'}</p></div>
      <div className="inspector-section"><label htmlFor="asset-url">公网 URL</label><input id="asset-url" value={selectedNode.data.url || ''} placeholder="https://…" onChange={(event) => { updateData('url', event.target.value); updateData('localPreview', '') }} /><p className="helper">可以直接填写公网地址，也可以选择本地文件并上传。</p></div>
      {assetPreview && <div className="inspector-asset-preview">{isImageInput ? <img src={assetSrc(assetPreview)} alt="Selected image asset" /> : <video src={assetSrc(assetPreview)} controls muted />}</div>}
    </> : (isImage || isVideo) && selectedNode ? <>
      <div className="inspector-section"><label>Input mode</label><div className="auto-mode"><span className="status-dot green" /><b>{mode}</b><small>inferred from connected upstream nodes</small></div></div>
      {referenceEdges.length > 0 && <div className="inspector-section reference-guide"><label>提示词引用（按顺序）</label><div className="reference-list">
        {referenceEdges.map((edge, index) => {
          const source = nodes.find((node) => node.id === edge.source)
          const sourcePreview = source?.data.localPreview || source?.data.result?.url || source?.data.url
          const sourceLabel = source?.data.fileName || (typeof source?.data.label === 'string' ? source.data.label : source?.id) || 'asset'
          const handle = edge.targetHandle || edge.sourceHandle || ''
          const isVideoRef = handle === 'video'
          const imageNumber = referenceEdges.slice(0, index + 1).filter((item) => (item.targetHandle || item.sourceHandle || '') === 'image').length
          const videoNumber = referenceEdges.slice(0, index + 1).filter((item) => (item.targetHandle || item.sourceHandle || '') === 'video').length
          const token = isVideoRef ? '视频' + videoNumber : '图片' + imageNumber
          const canReorder = !isVideoRef
          const imageIndex = imageReferenceEdges.findIndex((item) => item.id === edge.id)
          return <div
            className={'reference-chip' + (draggingReference === edge.id ? ' is-dragging' : '')}
            key={edge.id}
            draggable={canReorder}
            onDragStart={() => canReorder && setDraggingReference(edge.id)}
            onDragOver={(event) => canReorder && event.preventDefault()}
            onDrop={() => canReorder && dropReference(edge.id)}
            onDragEnd={() => setDraggingReference(null)}
          >
            <button type="button" className="reference-token" onClick={() => appendReferenceToken(token)} aria-label={'插入 ' + token + ' 到提示词'}>
              {sourcePreview && <img src={assetSrc(sourcePreview)} alt={token} />}
              <span><b>{token}</b><small>{sourceLabel}</small></span>
            </button>
            {canReorder && <div className="reference-actions">
              <span className="reference-drag" aria-hidden="true"><GripVertical size={14} /></span>
              <button type="button" className="reference-move" onClick={() => moveReference(edge.id, -1)} disabled={imageIndex <= 0} aria-label={'将 ' + token + ' 上移'}><ArrowUp size={14} /></button>
              <button type="button" className="reference-move" onClick={() => moveReference(edge.id, 1)} disabled={imageIndex < 0 || imageIndex >= imageReferenceEdges.length - 1} aria-label={'将 ' + token + ' 下移'}><ArrowDown size={14} /></button>
            </div>}
          </div>
        })}
      </div><p className="helper">拖动图片卡片或使用上下箭头调整顺序；当前顺序就是提示词中的图片1、图片2……。点击标签可插入引用。</p></div>}
      <div className="inspector-section"><label htmlFor="prompt">Prompt</label><textarea id="prompt" value={selectedNode.data.prompt || ''} onChange={(event) => updateData('prompt', event.target.value)} /><p className="helper">输入提示词，或连接图片/视频素材；可点击上方图片1、图片2标签快速插入引用。</p></div>
      <div className="inspector-section"><label htmlFor="model">Model</label><select id="model" value={selectedNode.data.model || (isImage ? 'doubao-seedream-5-0-pro-260628' : 'doubao-seedance-2-0-mini-260615')} onChange={(event) => updateData('model', event.target.value)}>{isImage ? <option value="doubao-seedream-5-0-pro-260628">Seedream 5.0 Pro</option> : <><option value="doubao-seedance-2-0-mini-260615">Seedance 2.0 mini</option><option value="doubao-seedance-2-0-260128">Seedance 2.0</option></>}</select></div>
      {isVideo && <><div className="field-row"><div><label htmlFor="ratio">Ratio</label><select id="ratio" value={selectedNode.data.ratio || '16:9'} onChange={(event) => updateData('ratio', event.target.value)}><option>21:9</option><option>16:9</option><option>4:3</option><option>1:1</option><option>3:4</option><option>9:16</option></select></div><div><label htmlFor="duration">Duration</label><select id="duration" value={selectedNode.data.duration || 5} onChange={(event) => updateData('duration', Number(event.target.value))}><option value={4}>4 sec</option><option value={5}>5 sec</option><option value={10}>10 sec</option><option value={15}>15 sec</option></select></div></div><div className="field-row"><div><label htmlFor="resolution">Resolution</label><select id="resolution" value={selectedNode.data.resolution || '480p'} onChange={(event) => updateData('resolution', event.target.value)}><option>480p</option><option>720p</option><option>1080p</option><option>4k</option></select></div></div></>}
      <div className="cost-card"><div><span>Estimated generation</span><b>{isVideo ? ('~ ¥' + ((selectedNode.data.duration || 5) * 1).toFixed(0)) : 'Seedream 5.0'}</b></div><small>Review the connected inputs, then confirm to call the API.</small></div>
      <button className="run-btn node-generate-btn" onClick={onGenerate} disabled={runState === 'running'}><Sparkles size={15} /> {runState === 'running' ? 'Generating…' : 'Confirm generation'}</button>
    </> : <div className="empty-inspector"><Sparkles size={22} /><b>Choose a generation node</b><span>Connect prompts and assets, then configure the selected node here.</span></div>}
    {selectedNode && <button className="danger-btn" onClick={deleteSelected}><Trash2 size={14} /> Delete node</button>}
  </aside>
}
export default function App() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<NodeData>>(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)
  const [selected, setSelected] = useState('image-generate')
  const [activity, setActivity] = useState('Ready to build')
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewPayload, setPreviewPayload] = useState<unknown>(null)
  const [confirmationToken, setConfirmationToken] = useState<string | null>(null)
  const [runState, setRunState] = useState<'idle' | 'running' | 'success' | 'error'>('idle')
  const [resultPreview, setResultPreview] = useState<{ type: string; url?: string; path?: string } | null>(null)
  const [logOpen, setLogOpen] = useState(false)
  const [runLogs, setRunLogs] = useState<Array<Record<string, unknown>>>([])

  const selectedNode = useMemo(() => nodes.find((node) => node.id === selected), [nodes, selected])
  const onConnect = useCallback((params: Connection) => {
    if (!params.source || !params.target || params.source === params.target) return
    setEdges((eds) => addEdge({ ...params, animated: true }, eds))
    setActivity('Nodes linked — media dependencies are inferred automatically')
  }, [setEdges])
  const addNode = (kind: string, label: string) => {
    const id = `${kind}-${Date.now()}`
    setNodes((current) => [...current, { id, type: 'default', position: { x: 300 + current.length * 22, y: 120 + current.length * 16 }, data: { label, kind, model: kind === 'image_generate' ? 'doubao-seedream-5-0-pro-260628' : kind === 'video_generate' ? 'doubao-seedance-2-0-mini-260615' : undefined } }])
    setSelected(id)
    setActivity(`${label} added to canvas`)
  }
  const uploadAsset = async (file: File) => {
    if (!selectedNode || !['image_input', 'video_input'].includes(selectedNode.data.kind)) return
    const localPreview = URL.createObjectURL(file)
    setNodes((current) => current.map((node) => node.id === selectedNode.id ? { ...node, data: { ...node.data, localPreview, fileName: file.name, uploadState: 'uploading' } } : node))
    setActivity(`Uploading ${file.name}…`)
    const form = new FormData()
    form.append('file', file)
    try {
      const response = await studioFetch('/api/assets/upload', { method: 'POST', body: form }, '上传素材')
      const result = await response.json().catch(() => ({}))
      if (!result.url) throw new Error('后端未返回素材地址，请检查对象存储配置或素材格式。')
      setNodes((current) => current.map((node) => node.id === selectedNode.id ? { ...node, data: { ...node.data, url: result.url, localPreview, fileName: file.name, uploadState: 'uploaded' } } : node))
      setActivity(`${file.name} uploaded and ready to connect`)
    } catch (error) {
      if (error instanceof Error && error.message.startsWith('无法连接后端')) {
        setNodes((current) => current.map((node) => node.id === selectedNode.id ? { ...node, data: { ...node.data, localPreview, fileName: file.name, uploadState: 'error' } } : node))
        setActivity(error.message)
        return
      }
      // Without an S3/OSS provider, keep local images usable for Seedream by
      // embedding them as a data URL. Seedance still requires a public URL.
      if (selectedNode.data.kind === 'image_input') {
        try {
          const dataUrl = await fileAsDataUrl(file)
          setNodes((current) => current.map((node) => node.id === selectedNode.id ? { ...node, data: { ...node.data, url: dataUrl, localPreview, fileName: file.name, uploadState: 'uploaded' } } : node))
          setActivity(`${file.name} is ready for image-to-image (inline local asset)`)
          return
        } catch {
          // Fall through to the normal upload error below.
        }
      }
      setNodes((current) => current.map((node) => node.id === selectedNode.id ? { ...node, data: { ...node.data, localPreview, fileName: file.name, uploadState: 'error' } } : node))
      setActivity(error instanceof Error ? error.message : 'Asset upload failed — configure a storage provider')
    }
  }
  const save = async () => {
    setActivity('Saving workflow…')
    try {
      await studioFetch('/api/workflows', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(graphPayload()) }, '保存工作流')
      setActivity('Workflow saved')
    } catch (error) { setActivity(error instanceof Error ? error.message : '无法连接后端服务，请确认后端已启动后重试。') }
  }
  const reorderReferences = useCallback((nodeId: string, edgeIds: string[]) => {
    setEdges((current) => {
      const edgeSet = new Set(edgeIds)
      const currentReferences = current.filter((edge) => edge.target === nodeId && edgeSet.has(edge.id))
      if (currentReferences.length !== edgeIds.length) return current
      const byId = new Map(currentReferences.map((edge) => [edge.id, edge]))
      const ordered = edgeIds.map((id) => byId.get(id)).filter((edge): edge is Edge => Boolean(edge))
      let index = 0
      return current.map((edge) => {
        if (edge.target === nodeId && edgeSet.has(edge.id)) return ordered[index++]
        return edge
      })
    })
    setActivity('图片顺序已更新：提示词中的图片1、图片2同步变化')
  }, [setEdges])
  const deleteSelected = useCallback(() => {
    if (!selected) return
    setNodes((current) => current.filter((node) => node.id !== selected))
    setEdges((current) => current.filter((edge) => edge.source !== selected && edge.target !== selected))
    setSelected('')
    setActivity('Node deleted')
  }, [selected, setNodes, setEdges])
  useEffect(() => {
    void studioFetch('/api/health', undefined, '检查后端服务')
      .then(async () => { await flushPendingClientErrors(); setActivity('后端服务已连接，可以开始构建工作流') })
      .catch((error) => {
        setRunState('error')
        setActivity(error instanceof Error ? error.message : '无法连接后端服务，请确认后端已启动后重试。')
      })
  }, [])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement)?.tagName
      if ((event.key === 'Delete' || event.key === 'Backspace') && tag !== 'TEXTAREA' && tag !== 'INPUT' && tag !== 'SELECT') deleteSelected()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [deleteSelected])
  const graphPayload = () => ({ schema_version: 1, id: 'neon-fox', title: 'Neon Fox', nodes: nodes.map(({ id, position, data }) => { const { onSelect, localPreview, fileName, uploadState, ...serializableData } = data; return { id, type: data.kind, position, data: serializableData } }), edges })
  const applyRunResults = (status: any) => {
    const values = Object.entries(status.results || {}) as Array<[string, { type?: string; url?: string; path?: string }]>
    const resultById = new Map(values.filter(([, value]) => value.type === 'image_result' || value.type === 'video_result').map(([id, value]) => [id, value]))
    let propagated = true
    while (propagated) {
      propagated = false
      edges.forEach((edge) => {
        if (!resultById.has(edge.target) && resultById.has(edge.source)) { resultById.set(edge.target, resultById.get(edge.source)!); propagated = true }
      })
    }
    setNodes((current) => current.map((node) => {
      const value = resultById.get(node.id)
      return value?.type ? { ...node, data: { ...node.data, result: { type: value.type, url: value.url } } } : node
    }))
    const generated = values.reverse().map(([, value]) => value).find((value) => value.type === 'image_result' || value.type === 'video_result')
    setResultPreview(generated?.type ? { type: generated.type, url: generated.url, path: generated.path } : null)
  }
  const waitForRun = async (runId: string) => {
    setRunState('running'); setActivity('Generation started — waiting for result…')
    for (let attempt = 0; attempt < 900; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      const statusResponse = await studioFetch(`/api/runs/${runId}`, undefined, '查询生成状态')
      const status = await statusResponse.json()
      if (status.status === 'succeeded') { applyRunResults(status); setRunState('success'); setActivity('Generation complete — result is shown on the node'); return }
      if (status.status === 'failed') { setRunState('error'); setActivity(status.error || 'Generation failed'); return }
      const latestEvent = status.events && status.events.length ? status.events[status.events.length - 1] : null
      setActivity(`Generation in progress… ${latestEvent?.message || ''}`)
    }
    setRunState('error'); setActivity('Generation timed out; inspect studio_runs.jsonl')
  }
  const generateSelectedNode = async () => {
    if (!selectedNode || !['image_generate', 'video_generate'].includes(selectedNode.data.kind)) { setRunState('error'); setActivity('Select an image or video generation node first'); return }
    setRunState('running'); setActivity('Checking inputs…')
    try {
      const validationResponse = await studioFetch('/api/workflows/neon-fox/validate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(graphPayload()) }, '校验生成输入')
      const validation = await validationResponse.json()
      if (!validation.valid) {
        const errors = Array.isArray(validation.errors) ? validation.errors.filter(Boolean).join('；') : '输入素材未通过校验'
        setRunState('error')
        setActivity(errors)
        return
      }
      setActivity('Submitting selected node…')
      const response = await studioFetch(`/api/workflows/neon-fox/nodes/${selectedNode.id}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workflow: graphPayload(), confirmed: true }) }, '提交节点生成')
      const runInfo = await response.json()
      await waitForRun(runInfo.run_id)
    } catch (error) { setRunState('error'); setActivity(error instanceof Error ? error.message : 'Node generation request failed') }
  }
  const openLogs = async () => {
    try {
      const response = await studioFetch('/api/logs/runs', undefined, '读取运行日志')
      const result = await response.json()
      setRunLogs(result.entries || [])
      setLogOpen(true)
    } catch (error) {
      setRunState('error')
      setActivity(error instanceof Error ? error.message : '无法读取运行日志。')
    }
  }
  const preview = async () => {
    setPreviewOpen(true); setActivity('Building safe preview…')
    try {
      const payload = graphPayload()
      const response = await studioFetch('/api/workflows/neon-fox/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, '生成安全预览')
      const result = await response.json(); setConfirmationToken(result.confirmation_token || null); setPreviewPayload(result); setActivity(result.valid === false ? 'Preview found validation issues' : 'Preview ready — no API call made')
    } catch (error) { setPreviewOpen(false); setRunState('error'); setActivity(error instanceof Error ? error.message : '无法连接后端服务，请确认后端已启动后重试。') }
  }
  const run = async () => {
    if (!confirmationToken) { setRunState('error'); setActivity('Preview the workflow first, then confirm generation'); return }
    setRunState('running'); setActivity('Awaiting API confirmation…')
    try {
      const payload = { ...graphPayload(), confirmed: true, confirmation_token: confirmationToken }
      const response = await studioFetch('/api/workflows/neon-fox/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, '提交工作流生成')
      const runInfo = await response.json()
      setRunState('running'); setActivity('Generation started — waiting for result…')
      for (let attempt = 0; attempt < 900; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1000))
        const statusResponse = await studioFetch(`/api/runs/${runInfo.run_id}`, undefined, '查询生成状态')
        const status = await statusResponse.json()
        if (status.status === 'succeeded') {
          applyRunResults(status)
          const values = Object.values(status.results || {}) as Array<{ type?: string; url?: string; path?: string }>
          const generated = values.reverse().find((value) => value.type === 'image_result' || value.type === 'video_result')
          setResultPreview(generated?.type ? { type: generated.type, url: generated.url, path: generated.path } : null)
          setRunState('success'); setActivity('Generation complete — result is ready')
          break
        }
        if (status.status === 'failed') { setRunState('error'); setActivity(status.error || 'Generation failed'); break }
        const latestEvent = status.events && status.events.length ? status.events[status.events.length - 1] : null
        setActivity(`Generation in progress… ${latestEvent?.message || ''}`)
      }
    } catch (error) { setRunState('error'); setActivity(error instanceof Error ? error.message : '生成请求失败，请查看运行日志。') }
  }
  const updateData = (key: keyof NodeData, value: string | number) => setNodes((current) => current.map((node) => node.id === selected ? { ...node, data: { ...node.data, [key]: value } } : node))

  return <div className="studio-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Sparkles size={16} /></div><div><strong>Video Agent</strong><span>Studio</span></div><ChevronDown size={15} className="muted" /></div>
      <div className="project-title"><span className="live-dot" /> Neon Fox / <b>Untitled workflow</b><span className="saved-label">Saved just now</span></div>
      <div className="top-actions"><button className="icon-btn" aria-label="History"><History size={17} /></button><button className="icon-btn" aria-label="Settings"><Settings2 size={17} /></button><button className="secondary-btn" onClick={save}><Save size={15} /> Save</button></div>
    </header>
    <main className="workspace">
      <aside className="sidebar"><div className="sidebar-heading"><div><span className="eyebrow">WORKFLOW</span><h1>Build a scene</h1></div><button className="icon-btn" aria-label="Help"><CircleHelp size={17} /></button></div><div className="search-box"><LayoutGrid size={15} /><input placeholder="Search nodes" aria-label="Search nodes" /></div><div className="palette-label">NODES <span>+</span></div><div className="palette-list">{palette.map(({ kind, label, detail, icon: Icon }) => <button className="palette-item" key={kind} onClick={() => addNode(kind, label)}><span className={`palette-icon palette-${kind.replace('_', '-')}`}><Icon size={16} /></span><span><b>{label}</b><small>{detail}</small></span><Plus size={15} className="palette-plus" /></button>)}</div><div className="sidebar-footer"><div className="storage-status"><span className="status-dot green" /><div><b>Local workspace</b><small>API keys stay on device</small></div></div><button className="secondary-btn full" onClick={() => addNode('image_input', '图片素材')}><Upload size={15} /> Add asset node</button></div></aside>
      <section className="canvas-wrap"><div className="canvas-toolbar"><div className="toolbar-group"><button className="tool-btn active">Canvas</button><button className="tool-btn">Artifacts</button></div><div className="toolbar-group"><span className="zoom-label">100%</span><button className="tool-btn">Fit view</button><button className="tool-btn">Auto layout</button></div></div><div className="canvas"><ReactFlow nodes={nodes.map((node) => ({ ...node, type: 'studio', data: { ...node.data, onSelect: () => setSelected(node.id) } }))} nodeTypes={nodeTypes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} fitView proOptions={{ hideAttribution: true }}><Background color="#232936" gap={24} size={1} /><Controls showInteractive={false} /><MiniMap nodeColor="#3d4558" maskColor="rgba(6,8,12,.72)" /></ReactFlow></div><div className="canvas-hint"><span className="kbd">Space</span> pan <span className="kbd">Add</span> use the node palette <span className="kbd">Del</span> delete</div></section>
      <Inspector selectedNode={selectedNode} nodes={nodes} edges={edges} updateData={updateData} deleteSelected={deleteSelected} onGenerate={generateSelectedNode} onUpload={uploadAsset} reorderReferences={reorderReferences} runState={runState} />
    </main>
    {resultPreview?.url && <div className="result-preview"><div className="result-preview-head"><div><span className="eyebrow">GENERATED RESULT</span><b>Ready to review</b></div><button className="icon-btn" onClick={() => setResultPreview(null)} aria-label="Close result"><XCircle size={16} /></button></div>{resultPreview.type === 'video_result' ? <video src={assetSrc(resultPreview.url)} controls autoPlay muted /> : <img src={assetSrc(resultPreview.url)} alt="Generated result" />}</div>}
    <footer className={`runbar ${runState}`}><div className="runbar-status">{runState === 'success' ? <CheckCircle2 size={16} /> : runState === 'error' ? <XCircle size={16} /> : <span className={`status-dot ${runState === 'running' ? 'amber pulse' : 'blue'}`} />}<b>{activity}</b></div><div className="runbar-actions"><span>{runState === 'success' ? 'Result available' : '0 API calls this session'}</span><button className="log-btn" onClick={openLogs}><Terminal size={14} /> Open run log</button></div></footer>
    {previewOpen && <div className="modal-backdrop" role="dialog" aria-modal="true"><div className="preview-modal"><div className="modal-head"><div><span className="eyebrow">SAFE PREVIEW</span><h2>Review generation payload</h2></div><button className="icon-btn" onClick={() => setPreviewOpen(false)} aria-label="Close preview"><XCircle size={18} /></button></div><div className="preview-warning"><CircleHelp size={17} /><span>This preview does not call Seedream or Seedance. Review inputs before confirming a paid run.</span></div><pre>{JSON.stringify(previewPayload || { workflow: 'Neon Fox' }, null, 2)}</pre><div className="modal-actions"><button className="secondary-btn" onClick={() => setPreviewOpen(false)}>Close</button><button className="run-btn" disabled={!confirmationToken} onClick={() => { setPreviewOpen(false); run() }}><Sparkles size={15} /> {confirmationToken ? 'Confirm generation' : 'Fix preview issues first'}</button></div></div></div>}
    {logOpen && <div className="modal-backdrop" role="dialog" aria-modal="true"><div className="preview-modal log-modal"><div className="modal-head"><div><span className="eyebrow">STUDIO LOG</span><h2>Generation activity</h2></div><button className="icon-btn" onClick={() => setLogOpen(false)} aria-label="Close logs"><XCircle size={18} /></button></div><pre>{runLogs.length ? runLogs.map((entry) => JSON.stringify(entry)).join('\n') : 'No Studio run entries yet.'}</pre><div className="modal-actions"><button className="secondary-btn" onClick={() => setLogOpen(false)}>Close</button></div></div></div>}
  </div>
}
