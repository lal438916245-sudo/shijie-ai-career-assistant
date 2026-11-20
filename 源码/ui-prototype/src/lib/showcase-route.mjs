import {viewFromHash,unknownHash} from './routes.mjs'
/** @param {string} view @param {Record<string,string>} [params] */
export function showcaseHash(view,params={}){const q=new URLSearchParams({case:'workflow',topic:'sql',...params});q.set('case','workflow');return `#${view}?${q}`}
/** Old cases are archived, never rendered by the current application. @param {string} hash */
export function showcaseRoute(hash){
 const q=new URLSearchParams(hash.split('?')[1]??''),archived=['classic','multi','journey'].includes(q.get('case')??'')
 const invalid=unknownHash(hash),view=archived||invalid?'overview':viewFromHash(hash)
 const params={}
 if(!archived&&!invalid)for(const key of ['entry','task','focus','week','record','kind','subject','date','run','interview','resume'])if(q.has(key))params[key]=q.get(key)
 if(params.entry&&!['demo','personal'].includes(params.entry))delete params.entry
 const entry=params.entry??(view==='new'?'personal':'demo')
 return {view,hash:showcaseHash(view,params),entry,archived,invalid}
}
