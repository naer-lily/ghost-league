import * as Dialog from '@radix-ui/react-dialog'
import { GripVertical, Pencil, Plus, Trash2, X } from 'lucide-react'
import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import {
  useCreateTaskDefinition,
  useDeleteTaskDefinition,
  useReorderTaskDefinitions,
  useTaskDefinitions,
  useUpdateTaskDefinition,
} from '../api/queries'
import type { TaskDefinition } from '../api/types'
import { describeApiError } from '../lib/home'
import { useUiStore } from '../store/useUiStore'
import styles from './TaskSettingsDialog.module.css'

const DIFFICULTIES = [
  { value: 1, label: '轻' },
  { value: 2, label: '中' },
  { value: 3, label: '重' },
] as const

const DRAG_THRESHOLD = 4

interface DragState {
  pointerId: number
  id: string
  startY: number
  moved: boolean
  original: TaskDefinition[]
}

interface TaskSettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TaskSettingsDialog({
  open,
  onOpenChange,
}: TaskSettingsDialogProps) {
  const definitions = useTaskDefinitions(open)
  const createDefinition = useCreateTaskDefinition()
  const updateDefinition = useUpdateTaskDefinition()
  const deleteDefinition = useDeleteTaskDefinition()
  const reorderDefinitions = useReorderTaskDefinitions()
  const notify = useUiStore((state) => state.notify)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [difficulty, setDifficulty] = useState<number>(1)
  const [order, setOrder] = useState<TaskDefinition[]>([])
  const [draggingId, setDraggingId] = useState<string | null>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const orderRef = useRef<TaskDefinition[]>([])
  const dragRef = useRef<DragState | null>(null)

  function applyOrder(next: TaskDefinition[]) {
    orderRef.current = next
    setOrder(next)
  }

  useEffect(() => {
    if (dragRef.current) return
    applyOrder(definitions.data ?? [])
  }, [definitions.data])

  useEffect(() => {
    if (!open) {
      setEditingId(null)
      setFormOpen(false)
      setTitle('')
      setDescription('')
      setDifficulty(1)
      dragRef.current = null
      setDraggingId(null)
    }
  }, [open])

  function startNew() {
    setEditingId(null)
    setTitle('')
    setDescription('')
    setDifficulty(1)
    setFormOpen(true)
  }

  function startEdit(definition: TaskDefinition) {
    setEditingId(definition.id)
    setTitle(definition.title)
    setDescription(definition.description)
    setDifficulty(definition.difficulty)
    setFormOpen(true)
  }

  const saving = createDefinition.isPending || updateDefinition.isPending

  function save() {
    const trimmed = title.trim()
    if (!trimmed || saving) return
    const input = {
      title: trimmed,
      description: description.trim(),
      difficulty,
    }
    const handlers = {
      onSuccess: () => {
        setFormOpen(false)
        setEditingId(null)
        notify('任务已保存。')
      },
      onError: (error: Error) => notify(describeApiError(error), 'error'),
    }
    if (editingId) {
      updateDefinition.mutate({ id: editingId, ...input }, handlers)
    } else {
      createDefinition.mutate(input, handlers)
    }
  }

  function deactivate(definition: TaskDefinition) {
    deleteDefinition.mutate(definition.id, {
      onSuccess: () => notify('任务已停用。'),
      onError: (error) => notify(describeApiError(error), 'error'),
    })
  }

  function startDrag(
    event: ReactPointerEvent<HTMLButtonElement>,
    definition: TaskDefinition,
  ) {
    if (reorderDefinitions.isPending) return
    if (event.pointerType === 'mouse' && event.button !== 0) return
    if (event.isPrimary === false) return
    event.preventDefault()
    event.stopPropagation()
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // Older WebViews can reject capture; touch still has implicit capture.
    }
    dragRef.current = {
      pointerId: event.pointerId,
      id: definition.id,
      startY: event.clientY,
      moved: false,
      original: [...orderRef.current],
    }
    setDraggingId(definition.id)
  }

  function moveDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const state = dragRef.current
    if (!state || state.pointerId !== event.pointerId) return
    if (!state.moved) {
      if (Math.abs(event.clientY - state.startY) < DRAG_THRESHOLD) return
      state.moved = true
    }
    event.preventDefault()

    const list = listRef.current
    if (!list) return
    const rows = Array.from(
      list.querySelectorAll<HTMLElement>('[data-task-id]'),
    ).filter((row) => row.dataset.taskId !== state.id)
    let target = rows.length
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index]
      if (!row) continue
      const rect = row.getBoundingClientRect()
      if (event.clientY < rect.top + rect.height / 2) {
        target = index
        break
      }
    }

    const current = orderRef.current
    const draggedIndex = current.findIndex((item) => item.id === state.id)
    const dragged = current[draggedIndex]
    if (!dragged || target === draggedIndex) return
    const next = current.filter((item) => item.id !== state.id)
    next.splice(target, 0, dragged)
    applyOrder(next)
  }

  function finishDrag(pointerId: number, commit: boolean) {
    const state = dragRef.current
    if (!state || state.pointerId !== pointerId) return
    dragRef.current = null
    setDraggingId(null)

    const current = orderRef.current
    const originalIds = state.original.map((item) => item.id)
    if (!state.moved || !commit) {
      if (state.moved) applyOrder(state.original)
      return
    }
    const ids = current.map((item) => item.id)
    if (ids.join('|') === originalIds.join('|')) return
    reorderDefinitions.mutate(ids, {
      onError: (error) => {
        applyOrder(state.original)
        notify(describeApiError(error), 'error')
      },
    })
  }

  function endDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const pointerId = event.pointerId
    finishDrag(pointerId, true)
    try {
      if (event.currentTarget.hasPointerCapture(pointerId)) {
        event.currentTarget.releasePointerCapture(pointerId)
      }
    } catch {
      // The handle may already have lost capture.
    }
  }

  function cancelDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    finishDrag(event.pointerId, false)
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content} data-testid="task-settings-dialog">
          <div className={styles.head}>
            <div>
              <p className="eyebrow">每日</p>
              <Dialog.Title className={styles.title}>任务设置</Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <button type="button" className={styles.close} aria-label="关闭任务设置">
                <X size={20} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="visually-hidden">
            管理每日手动任务
          </Dialog.Description>

          {definitions.isError ? (
            <p className={styles.error} role="alert">
              {describeApiError(definitions.error)}
            </p>
          ) : null}

          {formOpen ? (
            <form
              className={styles.form}
              onSubmit={(event) => {
                event.preventDefault()
                save()
              }}
            >
              <label className={styles.field}>
                <span>标题</span>
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  maxLength={80}
                  placeholder="例如：速写一张"
                  autoFocus
                />
              </label>
              <label className={styles.field}>
                <span>描述</span>
                <textarea
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  maxLength={500}
                  rows={2}
                  placeholder="可选"
                />
              </label>
              <div className={styles.field}>
                <span>难度</span>
                <div className={styles.difficulty} role="group" aria-label="难度">
                  {DIFFICULTIES.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      aria-pressed={difficulty === option.value}
                      className={[
                        styles.difficultyOption,
                        difficulty === option.value
                          ? styles.difficultyActive
                          : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      onClick={() => setDifficulty(option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className={styles.formActions}>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => setFormOpen(false)}
                  disabled={saving}
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="button button--primary"
                  disabled={!title.trim() || saving}
                >
                  {saving ? '保存中…' : '保存'}
                </button>
              </div>
            </form>
          ) : (
            <>
              <div className={styles.listHead}>
                <span>每日任务</span>
                <button type="button" className={styles.add} onClick={startNew}>
                  <Plus size={15} aria-hidden="true" />
                  新增任务
                </button>
              </div>
              {definitions.isPending ? (
                <p className={styles.muted}>正在读取…</p>
              ) : (definitions.data ?? []).length === 0 ? (
                <p className={styles.muted}>还没有每日任务。</p>
              ) : (
                <ul className={styles.list} ref={listRef}>
                  {order.map((definition) => (
                    <li
                      key={definition.id}
                      className={[
                        styles.item,
                        draggingId === definition.id ? styles.itemDragging : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      data-task-id={definition.id}
                    >
                      <button
                        type="button"
                        className={styles.dragHandle}
                        aria-label={`拖动排序 ${definition.title}`}
                        data-drag-handle
                        disabled={reorderDefinitions.isPending}
                        onPointerDown={(event) => startDrag(event, definition)}
                        onPointerMove={moveDrag}
                        onPointerUp={endDrag}
                        onPointerCancel={cancelDrag}
                        onLostPointerCapture={(event) => cancelDrag(event)}
                      >
                        <GripVertical size={17} aria-hidden="true" />
                      </button>
                      <div className={styles.itemCopy}>
                        <strong>{definition.title}</strong>
                      </div>
                      <button
                        type="button"
                        className={styles.iconButton}
                        onClick={() => startEdit(definition)}
                        aria-label={`编辑 ${definition.title}`}
                      >
                        <Pencil size={16} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className={styles.iconButton}
                        onClick={() => deactivate(definition)}
                        disabled={deleteDefinition.isPending}
                        aria-label={`停用 ${definition.title}`}
                      >
                        <Trash2 size={16} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          <Dialog.Close asChild>
            <button type="button" className="button button--primary button--full">
              完成
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export default TaskSettingsDialog
