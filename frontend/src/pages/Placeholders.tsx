import { Compass, Flame, History, Trophy, User } from 'lucide-react'
import { PlaceholderPage } from './PlaceholderPage'

export function LeaguePage() {
  return (
    <PlaceholderPage
      eyebrow="小组"
      title="小组榜"
      description="完整小组榜、升降级区和成员资料会在下一步接入。"
      icon={Trophy}
    />
  )
}

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

export function MePage() {
  return (
    <PlaceholderPage
      eyebrow="我的"
      title="个人页"
      description="资料、装备和收藏会在后续迭代接入。"
      icon={User}
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
