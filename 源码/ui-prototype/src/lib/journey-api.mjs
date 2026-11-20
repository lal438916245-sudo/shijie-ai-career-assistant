import { practiceRequest, PracticeApiError } from "./practice-api.mjs"
const KEY="career-pilot:journey:session-token:v1"
export function readJourneyToken(){
 try { const token=localStorage.getItem(KEY); if(token===null)return null; if(!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(token))throw new Error("invalid"); return token }
 catch { throw new PracticeApiError("无法读取本机练习身份，请检查浏览器存储；原数据未被覆盖。","storage") }
}
export function prepareJourneyToken(){
 try { const token=readJourneyToken()??crypto.randomUUID();localStorage.setItem(KEY,token);return token }
 catch(error) { if(error instanceof PracticeApiError)throw error;throw new PracticeApiError("无法保存练习身份，请检查浏览器存储后重试。","storage") }
}
export function prepareNewJourneyToken(){
 try { const previous=readJourneyToken();const saved=JSON.parse(localStorage.getItem(KEY+":previous")??"[]");if(!Array.isArray(saved)||saved.some(value=>typeof value!=="string"))throw Error("invalid archive");if(previous&&!saved.includes(previous))saved.push(previous);localStorage.setItem(KEY+":previous",JSON.stringify(saved));const next=crypto.randomUUID();localStorage.setItem(KEY,next);return next }
 catch(error){if(error instanceof PracticeApiError)throw error;throw new PracticeApiError("无法保留旧会话身份，请检查浏览器存储。","storage")}
}
export function readLastRun(token,view){try{return localStorage.getItem(KEY+":"+token+":"+view)}catch{return null}}
export function saveLastRun(token,view,runId){try{localStorage.setItem(KEY+":"+token+":"+view,runId);return true}catch{return false}}
export async function journeyRequest(path,token,body){const response=await practiceRequest("journey/"+path,token,body);return response.data}
export function requestForRetry(previous,action,body){const signature=JSON.stringify([action,body]);return previous?.signature===signature?previous:{signature,requestId:crypto.randomUUID()}}
