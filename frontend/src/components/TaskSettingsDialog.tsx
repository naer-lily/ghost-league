import * as Dialog from '@radix-ui/react-dialog'
import { Pencil, Plus, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  useCreateTaskDefinition,
  useDeleteTaskDefinition,
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
  const notify = useUiStore((state) => state.notify)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [difficulty, setDifficulty] = useState<number>(1)

  useEffect(() => {
    if (!open) {
      setEditingId(null)
      setFormOpen(false)
      setTitle('')
      setDescription('')
      setDifficulty(1)
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
                <ul className={styles.list}>
                  {(definitions.data ?? []).map((definition) => (
                    <li key={definition.id} className={styles.item}>
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
