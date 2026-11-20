/** @returns {{daily_minutes:number,starting_level:"beginner"}} */
export const defaultLearningPreferences=()=>({daily_minutes:60,starting_level:'beginner'})
export function normalizeLearningPreferences(value){
 if(value===undefined)return undefined
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!['daily_minutes','starting_level'].includes(k)))throw Error('每日学习配置无效')
 if(!['beginner','foundation'].includes(value.starting_level))throw Error('请选择学习起点')
 return {daily_minutes:60,starting_level:value.starting_level}
}

// Historical pending requests retain their original payload for safe recovery.
export function readSavedLearningPreferences(value){
 if(value===undefined)return undefined
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!['daily_minutes','starting_level'].includes(k)))throw Error('每日学习配置无效')
 const raw=value.daily_minutes
 if(raw===null||raw===undefined||String(raw).trim()==='')throw Error('请填写每日可用分钟数')
 const minutes=typeof raw==='number'||typeof raw==='string'?Number(raw):NaN
 if(!Number.isInteger(minutes)||minutes<15||minutes>240)throw Error('每日时间须为15到240之间的整数分钟')
 if(!['beginner','foundation'].includes(value.starting_level))throw Error('请选择学习起点')
 return {daily_minutes:minutes,starting_level:value.starting_level}
}
