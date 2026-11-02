import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PullToRefresh } from './PullToRefresh'

function touch(y: number, type: 'start' | 'move' | 'end') {
  const map = {
    start: { touches: [{ clientY: y }] },
    move: { touches: [{ clientY: y }] },
    end: { touches: [] },
  }
  return map[type]
}

describe('PullToRefresh', () => {
  it('calls the real refresh callback after a full touch pull', async () => {
    const onRefresh = vi.fn(async () => undefined)
    render(
      <PullToRefresh onRefresh={onRefresh}>
        <p>内容</p>
      </PullToRefresh>,
    )

    const wrap = screen.getByTestId('pull-to-refresh')
    fireEvent.touchStart(wrap, touch(10, 'start'))
    fireEvent.touchMove(wrap, touch(180, 'move'))
    fireEvent.touchEnd(wrap, touch(180, 'end'))

    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('内容')).toBeVisible()
  })

  it('does not refresh on a tiny pull', () => {
    const onRefresh = vi.fn(async () => undefined)
    render(
      <PullToRefresh onRefresh={onRefresh}>
        <p>内容</p>
      </PullToRefresh>,
    )

    const wrap = screen.getByTestId('pull-to-refresh')
    fireEvent.touchStart(wrap, touch(10, 'start'))
    fireEvent.touchMove(wrap, touch(30, 'move'))
    fireEvent.touchEnd(wrap, touch(30, 'end'))

    expect(onRefresh).not.toHaveBeenCalled()
  })
})
