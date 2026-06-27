import type { BrandProfile, Connection, Plan, Post, Workspace } from './types'

const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8001'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status}: ${body}`)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// Workspaces
export const listWorkspaces = () => req<Workspace[]>('/api/workspaces')
export const createWorkspace = (name: string) =>
  req<Workspace>('/api/workspaces', { method: 'POST', body: JSON.stringify({ name }) })

// Brand
export const getBrand = (wsId: string) =>
  req<BrandProfile>(`/api/workspaces/${wsId}/brand`).catch(() => null)
export const upsertBrand = (wsId: string, data: Partial<BrandProfile>) =>
  req<BrandProfile>(`/api/workspaces/${wsId}/brand`, { method: 'PUT', body: JSON.stringify(data) })

// Plans
export const listPlans = (wsId: string) => req<Plan[]>(`/api/workspaces/${wsId}/plans`)
export const getPlan = (wsId: string, planId: string) =>
  req<Plan>(`/api/workspaces/${wsId}/plans/${planId}`)
export const generatePlan = (wsId: string, goal?: string) =>
  req<Plan>(`/api/workspaces/${wsId}/plans:generate`, {
    method: 'POST',
    body: JSON.stringify({ goal: goal || null }),
  })

// Connections
export const getConnections = (wsId: string) =>
  req<{ workspace_id: string; connections: Connection[] }>(`/api/workspaces/${wsId}/connections`)

// Posts
export const approvePost = (postId: string) =>
  req<Post>(`/api/posts/${postId}:approve`, { method: 'POST' })
export const rejectPost = (postId: string, reason?: string) =>
  req<Post>(`/api/posts/${postId}:reject`, { method: 'POST', body: JSON.stringify({ reason }) })
export const editPost = (postId: string, data: { content?: string; hashtags?: string[]; suggested_time?: string }) =>
  req<Post>(`/api/posts/${postId}`, { method: 'PATCH', body: JSON.stringify(data) })
export const regeneratePost = (postId: string, note?: string) =>
  req<void>(`/api/posts/${postId}:regenerate`, { method: 'POST', body: JSON.stringify({ note }) })
export const schedulePost = (postId: string, integrationId: string, provider: string, when: string) =>
  req<Post>(`/api/posts/${postId}:schedule`, {
    method: 'POST',
    body: JSON.stringify({ integration_id: integrationId, provider, when }),
  })

// Admin
export interface AdminStats {
  workspaces: number
  plans_generating: number; plans_ready: number; plans_failed: number
  posts_pending: number; posts_approved: number; posts_scheduled: number
  posts_published: number; posts_rejected: number
  action_logs: number
}
export interface AdminPlan {
  id: string; workspace_id: string; workspace_name: string
  goal: string | null; status: string; error: string | null
  post_count: number; created_at: string
}
export interface AdminPost {
  id: string; plan_id: string; workspace_id: string; workspace_name: string
  day: number; theme: string; format: string; content: string
  hashtags: string[]; suggested_time: string; status: string
  postiz_post_id: string | null; created_at: string
}
export interface AdminLog {
  id: string; workspace_id: string; actor: string; action: string
  payload: Record<string, unknown>; result: Record<string, unknown> | null; created_at: string
}

export const adminStats = () => req<AdminStats>('/api/admin/stats')
export const adminWorkspaces = () => req<{ id: string; name: string; autonomy_level: string; created_at: string }[]>('/api/admin/workspaces')
export const adminDeleteWorkspace = (id: string) => req<void>(`/api/admin/workspaces/${id}`, { method: 'DELETE' })
export const adminPlans = () => req<AdminPlan[]>('/api/admin/plans')
export const adminDeletePlan = (id: string) => req<void>(`/api/admin/plans/${id}`, { method: 'DELETE' })
export const adminPosts = (status?: string) => req<AdminPost[]>(`/api/admin/posts${status ? `?status=${status}` : ''}`)
export const adminDeletePost = (id: string) => req<void>(`/api/admin/posts/${id}`, { method: 'DELETE' })
export const adminLogs = (limit = 100, offset = 0) => req<AdminLog[]>(`/api/admin/logs?limit=${limit}&offset=${offset}`)
