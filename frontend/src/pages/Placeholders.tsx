import { Compass } from 'lucide-react'
import { PlaceholderPage } from './PlaceholderPage'

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
