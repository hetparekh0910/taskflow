import { createContext, useContext } from 'react'
import type { Project, Role, Workspace } from '../api/types'
import { ROLE_RANK } from '../api/types'

export interface WsCtx {
  ws: Workspace
  role: Role
  slug: string
  projects: Project[]
  can: (min: Role) => boolean
  /** Build an API path inside this workspace, e.g. p('/issues/') -> /w/acme/issues/ */
  p: (path: string) => string
}
export const WorkspaceContext = createContext<WsCtx>(null as never)
export const useWs = () => useContext(WorkspaceContext)
export const makeCan = (role: Role) => (min: Role) => ROLE_RANK[role] >= ROLE_RANK[min]
