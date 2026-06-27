export interface Workspace {
  id: string
  name: string
  autonomy_level: string
  created_at: string
}

export interface BrandProfile {
  id: string
  workspace_id: string
  name: string
  audience: string
  tone: string
  language: string
  avoid: string[]
  extra: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type PostStatus =
  | 'draft'
  | 'pending_approval'
  | 'approved'
  | 'scheduled'
  | 'published'
  | 'rejected'

export interface Post {
  id: string
  day: number
  theme: string
  format: string
  angle: string
  content: string
  hashtags: string[]
  suggested_time: string
  status: PostStatus
  created_at: string
}

export type PlanStatus = 'generating' | 'ready' | 'failed'

export interface Plan {
  id: string
  workspace_id: string
  goal: string | null
  status: PlanStatus
  error: string | null
  posts: Post[]
  created_at: string
}

export interface Connection {
  id: string
  name: string
  identifier: string
  picture: string
  disabled: boolean
  profile: string
}
