import {lazy,Suspense,useEffect,useCallback,useRef,useState} from 'react'
import {ArrowRight,ArrowUpRight,BookOpen,ChevronRight,Compass,FileCheck2,FlaskConical,HelpCircle,History,LayoutDashboard,Menu,MessageSquareText,Plus,ShieldCheck,Sparkles,Target,TrendingUp} from 'lucide-react'
import {Button} from '@/components/ui/button'
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from '@/components/ui/dialog'
import {Sheet,SheetContent,SheetDescription,SheetHeader,SheetTitle} from '@/components/ui/sheet'
import {TooltipProvider} from '@/components/ui/tooltip'
import {Toaster} from '@/components/ui/sonner'
import {Welcome} from '@/components/Welcome'
import {ExperienceModeBadge,type ExperienceMode} from '@/components/ExperienceMode'
import {PageBoundary,PendingEditsContext} from '@/components/WorkspaceQuality'
import {readEntryRegistry} from '@/lib/workbench-sessions.mjs'
import {VIEW_TITLES,type View} from '@/lib/routes.mjs'
import {showcaseRoute,showcaseHash} from '@/lib/showcase-route.mjs'
import '@/components/career-pages.css'
import '@/components/quality.css'
import '@/components/competition-workbench.css'
import '@/components/multi.css'

const CompetitionWorkspace=lazy(()=>import('@/components/CompetitionWorkspace'))
const steps:[View,string,typeof Target][]=[['diagnosis','岗位诊断',Target],['plan','学习计划',BookOpen],['exam','学习考核',FileCheck2],['retest','专题复测',FlaskConical],['growth','成长状态',TrendingUp],['scenario','模拟面试',MessageSquareText],['records','成长记录',History],['resume','简历修改',FileCheck2]]

export default function App(){
 const [route,setRoute]=useState(()=>showcaseRoute(window.location.hash))
 const view=route.view as View
 const [sessionMode,setSessionMode]=useState<{key:string;mode:ExperienceMode}|null>(null)
 const onModeChange=useCallback((mode:ExperienceMode)=>setSessionMode(previous=>previous?.key===route.hash&&previous.mode===mode?previous:{key:route.hash,mode}),[route.hash])
 const visibleMode=route.entry==='demo'?'case':sessionMode?.key===route.hash?sessionMode.mode:'loading'
 const [about,setAbout]=useState(false),[mobile,setMobile]=useState(false)
 const [pending,setPending]=useState<string|null>(null)
 const edits=useRef<Record<string,boolean>>({}),accepted=useRef(route.hash)
 const register=useRef((key:string,dirty:boolean)=>{edits.current={...edits.current,[key]:dirty}}).current
 const apply=(hash:string)=>{
  const next=showcaseRoute(hash);accepted.current=next.hash;setRoute(next);setMobile(false);setAbout(false);setPending(null)
  if(window.location.hash!==next.hash)window.history.replaceState(null,'',next.hash)
  window.scrollTo({top:0,behavior:'instant'})
 }
 const navigate=(next:View,params:Record<string,string>={})=>{
  const hash=showcaseHash(next,next==='welcome'?params:{entry:next==='new'?'personal':route.entry,...params})
  if(hash!==accepted.current&&Object.values(edits.current).some(Boolean)){setPending(hash);setMobile(false);return}
  if(window.location.hash!==hash)window.history.pushState(null,'',hash)
  apply(hash)
 }
 useEffect(()=>{
  if(window.location.hash!==accepted.current)window.history.replaceState(null,'',accepted.current)
  const sync=()=>{const hash=window.location.hash;if(hash===accepted.current)return
   if(Object.values(edits.current).some(Boolean)){setPending(hash);return}apply(hash)}
  const guard=(event:BeforeUnloadEvent)=>{if(Object.values(edits.current).some(Boolean)){event.preventDefault();event.returnValue=''}}
  window.addEventListener('hashchange',sync);window.addEventListener('beforeunload',guard)
  return()=>{window.removeEventListener('hashchange',sync);window.removeEventListener('beforeunload',guard)}
 },[])
 useEffect(()=>{document.title=`拾阶——AI 求职准备助手 · ${VIEW_TITLES[view]}`;if(view!=='welcome')document.getElementById('main-content')?.focus({preventScroll:true})},[view])
 const stay=()=>{window.history.replaceState(null,'',accepted.current);setPending(null)}
 const navigation=<>
  <a className="brand" href="#welcome" onClick={e=>{e.preventDefault();navigate('welcome')}} aria-label="拾阶 返回欢迎页"><span className="brand-mark"><Compass size={26} strokeWidth={1.7}/></span><span><strong>拾阶<span className="brand-period">.</span></strong><small>AI 求职准备助手</small></span></a>
  <div className="workspace-label">选择入口 <span>AI 求职准备助手</span></div>
  <nav aria-label="体验入口"><button className={'nav-item '+(route.entry==='demo'?'active':'')} onClick={()=>navigate('overview',{entry:'demo'})}><FileCheck2 size={18}/>查看完整案例</button><button className={'nav-item '+(route.entry==='personal'?'active':'')} onClick={()=>navigate('overview',{entry:'personal'})}><Plus size={18}/>我的求职准备</button></nav>
  <nav aria-label="主要导航"><button className={'nav-item '+(view==='overview'?'active':'')} aria-current={view==='overview'?'page':undefined} onClick={()=>navigate('overview')}><LayoutDashboard size={18}/>成长概览</button></nav>
  <div className="nav-section-title">成长路径 <span>来源分项标注</span></div><nav aria-label="成长路径导航">{steps.filter(([target])=>route.entry==='demo'||['diagnosis','resume','scenario','records'].includes(target)).map(([target,label,Icon])=><button key={target} className={'nav-item '+(view===target?'active':'')} aria-current={view===target?'page':undefined} onClick={()=>navigate(target)}><Icon size={18}/>{label}</button>)}</nav>
  <div className="sidebar-bottom"><div className="sidebar-note"><span className="note-spark"><Sparkles size={18}/></span><h3>每一步，都有证据。</h3><p>同一份简历与岗位，<br/>贯穿学习、验证和表达。</p><button onClick={()=>{setAbout(true);setMobile(false)}}>案例与数据说明<ArrowUpRight size={13}/></button></div><div className="local-profile"><span className="profile-avatar">CP</span><div><strong>{route.entry==='demo'?'查看完整案例':'开始动手体验'}</strong><p>{route.entry==='demo'?'固定回放 · 不调用模型':'个人资料 · AI辅助准备'}</p></div><span className="online-dot"/></div></div>
 </>
 if(view==='welcome')return <Welcome onEnter={next=>{if(next==='new'){let saved=false;try{saved=Boolean(readEntryRegistry(localStorage,'personal').active)}catch{}navigate(saved?'overview':'new',{entry:'personal'})}else navigate(next,{entry:'demo'})}} hasDraft={false}/>
 return <PendingEditsContext.Provider value={register}><TooltipProvider>
  <a href="#main-content" className="skip-content" onClick={e=>{e.preventDefault();document.getElementById('main-content')?.focus()}}>跳到页面内容</a>
  <div className="app-shell"><aside className="desktop-sidebar">{navigation}</aside><div className="app-content">
   <header className="topbar"><div className="topbar-left"><Button className="mobile-menu-button" variant="ghost" size="icon" aria-label="打开导航菜单" onClick={()=>setMobile(true)}><Menu size={21}/></Button><span className="breadcrumb-root">拾阶</span><ChevronRight size={14}/><span>{VIEW_TITLES[view]}</span></div><div className="topbar-right"><ExperienceModeBadge mode={visibleMode}/><button className="help-button" aria-label="查看案例与数据说明" onClick={()=>setAbout(true)}><HelpCircle size={18}/></button></div></header>
   <main id="main-content" tabIndex={-1} className="main-content">
    {route.archived&&<p className="workspace-notice" role="status">该历史演示已归档，已返回新的统一比赛案例。原记录没有删除。</p>}
    {route.invalid&&<p className="workspace-notice" role="status">链接暂不可用，已返回成长概览。</p>}
    <PageBoundary key={route.hash} onHome={()=>navigate('overview')}><Suspense fallback={<p role="status" className="quality-loading">正在打开当前工作台…</p>}><CompetitionWorkspace key={route.hash} entryMode={route.entry as 'demo'|'personal'} onModeChange={onModeChange} view={view} routeHash={route.hash} onNavigate={navigate}/></Suspense></PageBoundary>
   </main>
  </div></div>
  <Sheet open={mobile} onOpenChange={setMobile}><SheetContent side="left" className="mobile-navigation"><SheetHeader className="sr-only"><SheetTitle>比赛案例导航</SheetTitle><SheetDescription>查看当前案例的学习、考核、面试、简历及记录</SheetDescription></SheetHeader>{navigation}</SheetContent></Sheet>
  <Dialog open={about} onOpenChange={setAbout}><DialogContent className="about-dialog"><DialogHeader><span className="dialog-hero-icon"><Compass size={27}/></span><DialogTitle>一份资料，一条完整成长路径。</DialogTitle><DialogDescription>查看完整案例与独立动手体验分别进入，资料与成绩不混用。</DialogDescription></DialogHeader>
   <div className="about-row"><span>01</span><div><h3>查看完整案例与开始动手体验</h3><p>完整演示为只读体验：学习、日周考核、专题复测和岗位面试使用固定回放；案例中的学习、考核、对话和简历均为同一套预存示例。开始动手体验填写自己的简历和JD，创建独立会话；点击生成后由AI处理本次资料，结果保存在个人准备记录中，不借用案例成绩。</p></div></div>
   <div className="about-row"><span>02</span><div><h3>如实说明数据来源</h3><p>原简历、JD、学习、作答、分数与面试反馈是人工准备的固定演示。完整案例用于展示流程，不代表真实用户完成了长期学习或取得了相应能力；个人体验使用真实模型生成的内容独立保存。资料链接沿用已核对目录，参考资料不作为能力证据。</p></div></div>
   <div className="about-row"><span>03</span><div><h3>旧演示已归档</h3><p>历史四模式与旧比赛会话不再从正常入口进入，原数据和调用凭据保留归档。当前案例采用新的会话目录和浏览器列表，不迁入旧成绩。</p></div></div>
   <div className="about-footer"><ShieldCheck size={16}/>查看历史结果不发出新模型请求、不增加费用；历史用量在真实D结果中单独展示。</div>
  </DialogContent></Dialog>
  <Dialog open={pending!==null} onOpenChange={open=>{if(!open)stay()}}><DialogContent className="guard-dialog"><DialogHeader><DialogTitle>还有内容没有保存。</DialogTitle><DialogDescription>先保存当前学习记录或作答草稿，再切换页面；确认离开后，未提交内容可能需要重新填写。</DialogDescription></DialogHeader><div className="guard-dialog-actions"><Button variant="outline" onClick={stay}>留在此页</Button><Button onClick={()=>{if(pending)apply(pending)}}>仍然离开<ArrowRight size={14}/></Button></div></DialogContent></Dialog>
  <Toaster theme="light" position="bottom-right" richColors closeButton/>
 </TooltipProvider></PendingEditsContext.Provider>
}
