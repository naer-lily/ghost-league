import { Compass, Flame, History } from 'lucide-react'
import { PlaceholderPage } from './PlaceholderPage'

export function EmbersPage() {
  return (
    <PlaceholderPage
      eyebrow="余烬"
      title="余烬"
      description="余烬余额、获取记录和补签会在后续迭代接入。"
      icon={Flame}
    />
  )
}

export function HistoryPage() {
  return (
    <PlaceholderPage
      eyebrow="历史"
      title="历史"
      description="每周结算、段位变化和历史名次会在后续迭代接入。"
      icon={History}
    />
  )
}

export function NotFoundPage() {
  return (
    <PlaceholderPage
      eyebrow="导航"
      title="没有这个页面"
      description="这个地址还没有对应内容，回到首页继续查看本周联赛。"
      icon={Compass}
    />
  )
}
