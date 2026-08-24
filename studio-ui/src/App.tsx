import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  addEdge, Background, Controls, Handle, MiniMap, Position, ReactFlow, useEdgesState, useNodesState,
  type Connection, type Edge, type Node,
} from '@xyflow/react'
import { CheckCircle2, ChevronDown, CircleHelp, FileImage, Film, History, ImagePlus, LayoutGrid, Plus, Save, Settings2, Sparkles, Terminal, Trash2, Upload, WandSparkles, XCircle } from 'lucide-react'
import '@xyflow/react/dist/style.css'

type NodeData = { label: ReactNode; kind: string; mode?: string; model?: string; prompt?: string; url?: string; localPreview?: string; fileName?: string; uploadState?: 'idle' | 'uploading' | 'uploaded' | 'error'; duration?: number; ratio?: string; resolution?: string; return_last_frame?: boolean; result?: { type: string; url?: string }; onSelect?: () => void }

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
  const targetHandles = data.kind === 'image_generate' ? ['prompt', 'reference'] : data.kind === 'video_generate' ? ['prompt', 'first_frame', 'last_frame', 'image', 'video'] : data.kind === 'output' ? ['input'] : []
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

function fileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error('Could not read local file'))
    reader.onerror = () => reject(reader.error || new Error('Could not read local file'))
    reader.readAsDataURL(file)
  })
}

function Inspector({ selectedNode, nodes, edges, updateData, deleteSelected, onGenerate, onUpload, runState }: { selectedNode?: Node<NodeData>; nodes: Node<NodeData>[]; edges: Edge[]; updateData: (key: keyof NodeData, value: string | number) => void; deleteSelected: () => void; onGenerate: () => void; onUpload: (file: File) => void; runState: string }) {
  const kind = selectedNode?.data.kind
  const isImageInput = kind === 'image_input'
  const isVideoInput = kind === 'video_input'
  const isImage = kind === 'image_generate'
  const isVideo = kind === 'video_generate'
  const mode = selectedNode ? inferMode(selectedNode.id, nodes, edges) : ''
  const assetPreview = selectedNode?.data.localPreview || selectedNode?.data.url
  const inlineImage = isImageInput && selectedNode?.data.url?.startsWith('data:image/')
  const referenceEdges = selectedNode ? edges.filter((edge) => edge.target === selectedNode.id && ['reference', 'image', 'first_frame', 'last_frame', 'video'].includes((edge as any).targetHandle || (edge as any).target_handle || '')) : []
  const appendReferenceToken = (token: string) => {
    if (!selectedNode) return
    const prompt = selectedNode.data.prompt || ''
    updateData('prompt', `${prompt.trimEnd()}${prompt.trim() ? ' ' : ''}${token}`)
  }
  return <aside className="inspector">
    <div className="inspector-head"><div><span className="eyebrow">SELECTED NODE</span><h2>{selectedNode?.data.label || 'Node'}</h2></div><button className="icon-btn danger-icon" onClick={deleteSelected} aria-label="Delete selected node"><Trash2 size={17} /></button></div>
    {(isImageInput || isVideoInput) && selectedNode ? <>
      <div className="inspector-section"><label htmlFor="asset-file">本地素材</label><input className="file-input" id="asset-file" type="file" accept={isImageInput ? 'image/*' : 'video/*'} onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(file); event.currentTarget.value = '' }} /><label className="file-picker" htmlFor="asset-file"><Upload size={15} /> {selectedNode.data.uploadState === 'uploading' ? '上传中…' : '选择本地文件'}</label><p className="helper">{inlineImage ? '本地图片已转为内联素材，可直接用于图生图；连接视频节点仍需公网 URL。' : isImageInput ? '图片会自动上传；未配置对象存储时也可作为内联素材直接用于图生图。' : '视频真实生成前需要配置素材存储服务，以提供公网 URL。'}</p></div>
      <div className="inspector-section"><label htmlFor="asset-url">公网 URL</label><input id="asset-url" value={selectedNode.data.url || ''} placeholder="https://…" onChange={(event) => { updateData('url', event.target.value); updateData('localPreview', '') }} /><p className="helper">可以直接填写公网地址，也可以选择本地文件并上传。</p></div>
      {assetPreview && <div className="inspector-asset-preview">{isImageInput ? <img src={assetSrc(assetPreview)} alt="Selected image asset" /> : <video src={assetSrc(assetPreview)} controls muted />}</div>}
    </> : (isImage || isVideo) && selectedNode ? <>
      <div className="inspector-section"><label>Input mode</label><div className="auto-mode"><span className="status-dot green" /><b>{mode}</b><small>inferred from connected upstream nodes</small></div></div>
      {(isImage || isVideo) && referenceEdges.length > 0 && <div className="inspector-section reference-guide"><label>Reference inputs</label><div className="reference-list">{(() => {
        const ordered = referenceEdges.slice().sort((a, b) => {
          const order = (edge: Edge) => ({ first_frame: 0, last_frame: 1, reference: 2, image: 2, video: 3 } as Record<string, number>)[((edge as any).targetHandle || (edge as any).target_handle || '')] ?? 4
          return order(a) - order(b)
        })
        let imageIndex = 0
        let videoIndex = 0
        return ordered.map((edge) => {
          const source = nodes.find((node) => node.id === edge.source)
          const sourcePreview = source?.data.localPreview || source?.data.result?.url || source?.data.url
          const sourceLabel = source?.data.fileName || (typeof source?.data.label === 'string' ? source.data.label : source?.id) || 'asset'
          const handle = (edge as any).targetHandle || (edge as any).target_handle || ''
          const isVideoRef = handle === 'video'
          const token = isVideoRef ? `视频${++videoIndex}` : `图片${++imageIndex}`
          const label = handle === 'first_frame' ? `首帧（${token}）` : handle === 'last_frame' ? `尾帧（${token}）` : token
          return <button type="button" className="reference-chip" key={edge.id} onClick={() => appendReferenceToken(token)} title={`Insert ${token} into prompt`}>
            {sourcePreview && <img src={assetSrc(sourcePreview)} alt={token} />}
            <span><b>{label}</b><small>{sourceLabel}</small></span>
          </button>
        })
      })()}</div><p className="helper">按请求顺序对应提示词中的图片1、图片2……视频1；首帧和尾帧使用严格 API 角色。</p></div>}
      <div className="inspector-section"><label htmlFor="prompt">Prompt</label><textarea id="prompt" value={selectedNode.data.prompt || ''} onChange={(event) => updateData('prompt', event.target.value)} /><p className="helper">Enter text here, or connect image/video asset nodes to supply media inputs.</p></div>
      <div className="inspector-section"><label htmlFor="model">Model</label><select id="model" value={selectedNode.data.model || (isImage ? 'doubao-seedream-5-0-pro-260628' : 'doubao-seedance-2-0-mini-260615')} onChange={(event) => updateData('model', event.target.value)}>{isImage ? <option value="doubao-seedream-5-0-pro-260628">Seedream 5.0 Pro</option> : <><option value="doubao-seedance-2-0-mini-260615">Seedance 2.0 mini</option><option value="doubao-seedance-2-0-260128">Seedance 2.0</option></>}</select></div>
      {isVideo && <><div className="field-row"><div><label htmlFor="ratio">Ratio</label><select id="ratio" value={selectedNode.data.ratio || '16:9'} onChange={(event) => updateData('ratio', event.target.value)}><option>21:9</option><option>16:9</option><option>4:3</option><option>1:1</option><option>3:4</option><option>9:16</option></select></div><div><label htmlFor="duration">Duration</label><select id="duration" value={selectedNode.data.duration || 5} onChange={(event) => updateData('duration', Number(event.target.value))}><option value={4}>4 sec</option><option value={5}>5 sec</option><option value={10}>10 sec</option><option value={15}>15 sec</option></select></div></div><div className="field-row"><div><label htmlFor="resolution">Resolution</label><select id="resolution" value={selectedNode.data.resolution || '480p'} onChange={(event) => updateData('resolution', event.target.value)}><option>480p</option><option>720p</option><option>1080p</option><option>4k</option></select></div><div><label htmlFor="return-last-frame">Output tail frame</label><select id="return-last-frame" value={selectedNode.data.return_last_frame ? 'yes' : 'no'} onChange={(event) => updateData('return_last_frame', event.target.value === 'yes' ? 1 : 0)}><option value="no">No</option><option value="yes">Yes</option></select></div></div></>}
      <div className="cost-card"><div><span>Estimated generation</span><b>{isVideo ? `~ ¥${((selectedNode.data.duration || 5) * 1).toFixed(0)}` : 'Seedream 5.0'}</b></div><small>Review the connected inputs, then confirm to call the API.</small></div>
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
      const response = await fetch('http://127.0.0.1:8000/api/assets/upload', { method: 'POST', body: form })
      const result = await response.json().catch(() => ({}))
      if (!response.ok || !result.url) throw new Error(result.detail || 'Asset upload failed — configure a storage provider')
      setNodes((current) => current.map((node) => node.id === selectedNode.id ? { ...node, data: { ...node.data, url: result.url, localPreview, fileName: file.name, uploadState: 'uploaded' } } : node))
      setActivity(`${file.name} uploaded and ready to connect`)
    } catch (error) {
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
      await fetch('http://127.0.0.1:8000/api/workflows', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(graphPayload()) })
      setActivity('Workflow saved')
    } catch { setActivity('Backend offline — canvas kept locally') }
  }
  const deleteSelected = useCallback(() => {
    if (!selected) return
    setNodes((current) => current.filter((node) => node.id !== selected))
    setEdges((current) => current.filter((edge) => edge.source !== selected && edge.target !== selected))
    setSelected('')
    setActivity('Node deleted')
  }, [selected, setNodes, setEdges])
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
      const statusResponse = await fetch(`http://127.0.0.1:8000/api/runs/${runId}`)
      if (!statusResponse.ok) continue
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
    setRunState('running'); setActivity('Submitting selected node…')
    try {
      const response = await fetch(`http://127.0.0.1:8000/api/workflows/neon-fox/nodes/${selectedNode.id}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workflow: graphPayload(), confirmed: true }) })
      if (!response.ok) { const detail = await response.json().catch(() => ({})); throw new Error(detail.detail?.errors?.join?.('; ') || detail.detail || 'Node generation request failed') }
      const runInfo = await response.json()
      await waitForRun(runInfo.run_id)
    } catch (error) { setRunState('error'); setActivity(error instanceof Error ? error.message : 'Node generation request failed') }
  }
  const openLogs = async () => {
    const response = await fetch('http://127.0.0.1:8000/api/logs/runs')
    const result = await response.json()
    setRunLogs(result.entries || [])
    setLogOpen(true)
  }
  const preview = async () => {
    setPreviewOpen(true); setActivity('Building safe preview…')
    try {
      const payload = graphPayload()
      const response = await fetch('http://127.0.0.1:8000/api/workflows/neon-fox/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      const result = await response.json(); setConfirmationToken(result.confirmation_token || null); setPreviewPayload(result); setActivity(result.valid === false ? 'Preview found validation issues' : 'Preview ready — no API call made')
    } catch { setActivity('Preview is available after starting the backend') }
  }
  const run = async () => {
    if (!confirmationToken) { setRunState('error'); setActivity('Preview the workflow first, then confirm generation'); return }
    setRunState('running'); setActivity('Awaiting API confirmation…')
    try {
      const payload = { ...graphPayload(), confirmed: true, confirmation_token: confirmationToken }
      const response = await fetch('http://127.0.0.1:8000/api/workflows/neon-fox/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      if (!response.ok) throw new Error()
      const runInfo = await response.json()
      setRunState('running'); setActivity('Generation started — waiting for result…')
      for (let attempt = 0; attempt < 900; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1000))
        const statusResponse = await fetch(`http://127.0.0.1:8000/api/runs/${runInfo.run_id}`)
        if (!statusResponse.ok) continue
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
    } catch { setRunState('error'); setActivity('Run blocked — check backend, API key, and public asset URLs') }
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
      <Inspector selectedNode={selectedNode} nodes={nodes} edges={edges} updateData={updateData} deleteSelected={deleteSelected} onGenerate={generateSelectedNode} onUpload={uploadAsset} runState={runState} />
    </main>
    {resultPreview?.url && <div className="result-preview"><div className="result-preview-head"><div><span className="eyebrow">GENERATED RESULT</span><b>Ready to review</b></div><button className="icon-btn" onClick={() => setResultPreview(null)} aria-label="Close result"><XCircle size={16} /></button></div>{resultPreview.type === 'video_result' ? <video src={assetSrc(resultPreview.url)} controls autoPlay muted /> : <img src={assetSrc(resultPreview.url)} alt="Generated result" />}</div>}
    <footer className={`runbar ${runState}`}><div className="runbar-status">{runState === 'success' ? <CheckCircle2 size={16} /> : runState === 'error' ? <XCircle size={16} /> : <span className={`status-dot ${runState === 'running' ? 'amber pulse' : 'blue'}`} />}<b>{activity}</b></div><div className="runbar-actions"><span>{runState === 'success' ? 'Result available' : '0 API calls this session'}</span><button className="log-btn" onClick={openLogs}><Terminal size={14} /> Open run log</button></div></footer>
    {previewOpen && <div className="modal-backdrop" role="dialog" aria-modal="true"><div className="preview-modal"><div className="modal-head"><div><span className="eyebrow">SAFE PREVIEW</span><h2>Review generation payload</h2></div><button className="icon-btn" onClick={() => setPreviewOpen(false)} aria-label="Close preview"><XCircle size={18} /></button></div><div className="preview-warning"><CircleHelp size={17} /><span>This preview does not call Seedream or Seedance. Review inputs before confirming a paid run.</span></div><pre>{JSON.stringify(previewPayload || { workflow: 'Neon Fox' }, null, 2)}</pre><div className="modal-actions"><button className="secondary-btn" onClick={() => setPreviewOpen(false)}>Close</button><button className="run-btn" onClick={() => { setPreviewOpen(false); run() }}><Sparkles size={15} /> Confirm generation</button></div></div></div>}
    {logOpen && <div className="modal-backdrop" role="dialog" aria-modal="true"><div className="preview-modal log-modal"><div className="modal-head"><div><span className="eyebrow">STUDIO LOG</span><h2>Generation activity</h2></div><button className="icon-btn" onClick={() => setLogOpen(false)} aria-label="Close logs"><XCircle size={18} /></button></div><pre>{runLogs.length ? runLogs.map((entry) => JSON.stringify(entry)).join('\n') : 'No Studio run entries yet.'}</pre><div className="modal-actions"><button className="secondary-btn" onClick={() => setLogOpen(false)}>Close</button></div></div></div>}
  </div>
}
