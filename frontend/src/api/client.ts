/** 统一请求封装：拼后端地址、带操作者身份、把 401/403 的后端说明抛成可读错误。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

const STORAGE_KEY = 'mine-operator-id'

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const operatorId = localStorage.getItem(STORAGE_KEY) ?? ''
  return fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Operator-Id': operatorId,
      ...(init?.headers ?? {}),
    },
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/** 优先透传后端给出的拒绝原因（越权、未识别身份等），没有说明再退回状态码。 */
async function describeError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string }
    if (body?.detail) {
      return body.detail
    }
  } catch {
    // 响应体不是 JSON 时走状态码说明
  }
  return `接口返回 ${response.status}，数据未更新`
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(await describeError(response))
  }
  return (await response.json()) as T
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  if (!response.ok) {
    throw new Error(await describeError(response))
  }
  return (await response.json()) as T
}
