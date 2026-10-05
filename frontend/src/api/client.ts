/** 统一请求封装：拼后端地址、带身份头、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** 每次请求带上当前身份；中文姓名按 percent-encode 编码，后端负责解码。 */
function identityHeaders(): Record<string, string> {
  const session = useSessionStore()
  return {
    'X-Operator-Id': encodeURIComponent(session.operator),
    'X-Role': session.role,
    'X-Unit-Id': session.unitId,
  }
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...identityHeaders(), ...init?.headers },
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/** 从错误响应里取出后端给的 detail，越权拒绝时能看到具体原因。 */
async function errorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (body && typeof body.detail === 'string') {
      return body.detail
    }
  } catch {
    // 响应不是 JSON 时走默认说明
  }
  return `接口返回 ${response.status}，数据未更新`
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(await errorDetail(response))
  }
  return (await response.json()) as T
}

export async function postJson<T>(path: string, values: Record<string, unknown> = {}): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify({ values }) })
  if (!response.ok) {
    throw new Error(await errorDetail(response))
  }
  return (await response.json()) as T
}
