const KEY="career-pilot:offline-practice:session-token:v1"
export class PracticeApiError extends Error { constructor(message,code){super(message);this.code=code} }
export function readPracticeToken(){try{const value=localStorage.getItem(KEY);return value&&/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)?value:null}catch{return null}}
export function preparePracticeToken(){try{const value=readPracticeToken()??crypto.randomUUID();localStorage.setItem(KEY,value);return value}catch{throw new PracticeApiError("浏览器无法保存练习会话身份，请检查浏览器存储后重试。","storage")}}
export function prepareNewPracticeToken(){try{const previous=readPracticeToken();const saved=JSON.parse(localStorage.getItem(KEY+":previous")??"[]");if(!Array.isArray(saved)||saved.some(value=>typeof value!=="string"))throw Error("invalid archive");if(previous&&!saved.includes(previous))saved.push(previous);localStorage.setItem(KEY+":previous",JSON.stringify(saved));const next=crypto.randomUUID();localStorage.setItem(KEY,next);return next}catch{throw new PracticeApiError("无法安全保留旧会话身份，请检查浏览器存储后重试。","storage")}}
export async function practiceRequest(path,token,body){
 try{const options={headers:{"X-CP-Local":"fixed-stub-v1","X-Practice-Token":token},cache:"no-store"};if(body!==undefined){options.method="POST";options.headers["Content-Type"]="application/json";options.body=JSON.stringify(body)}
 const response=await fetch("/api/practice/"+path,options);let payload;try{payload=await response.json()}catch{throw new PracticeApiError("本地练习服务暂不可用，请确认服务已启动。","unavailable")}
 if(!response.ok)throw new PracticeApiError(payload.error||"本地练习暂时不可用，请重试。",payload.code||"unavailable");return payload
 }catch(error){if(error instanceof PracticeApiError)throw error;throw new PracticeApiError("无法连接本地练习服务，请确认服务已启动。","unavailable")}
}
