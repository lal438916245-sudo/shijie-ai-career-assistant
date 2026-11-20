// Keep input strings while editing; normalize only at the save boundary.
const rules = [
 ['max_input_chars', '输入字符预检阈值', 1000, 200000, true, false],
 ['max_output_tokens', '输出 token 上限', 256, 16000, true, false],
 ['timeout_seconds', '请求超时', 5, 180, true, false],
 ['temperature', 'temperature', 0, 2, false, true],
 ['input_price_per_million', '输入单价', 0, Infinity, false, true],
 ['output_price_per_million', '输出单价', 0, Infinity, false, true],
]

export function normalizePreparationNumbers(config) {
 const next = {...config}
 for (const [field, label, low, high, integer, optional] of rules) {
  const raw = config[field]
  const empty = raw === null || raw === undefined || (typeof raw === 'string' && raw.trim() === '')
  if (empty) {
   if (!optional) throw new Error(`请填写${label}`)
   next[field] = null
   continue
  }
  const number = typeof raw === 'number' || typeof raw === 'string' ? Number(raw) : NaN
  if (!Number.isFinite(number) || (integer && !Number.isInteger(number)) || number < low || number > high) {
   const range = high === Infinity ? `不小于 ${low} 的数值` : `${low} 到 ${high} 之间的${integer ? '整数' : '数值'}`
   throw new Error(`${label}须为${range}`)
  }
  next[field] = number
 }
 return next
}

export function normalizePreparationConfig(config) {
 const next = {...config}
 for (const field of ['provider','base_url','model']) {
  if (typeof next[field] === 'string') next[field] = next[field].trim()
 }
 if (!next.provider) throw new Error('请填写服务商名称')
 if (typeof next.model !== 'string' || !/^[A-Za-z0-9_./:\\-]{1,160}$/.test(next.model)) {
  throw new Error('模型标识请填写接口名称，例如 deepseek-flash；不要包含中文、空格或反引号。')
 }
 return normalizePreparationNumbers(next)
}
