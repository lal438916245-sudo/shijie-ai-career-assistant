import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdir, mkdtemp, readFile, rm, writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {fileURLToPath, pathToFileURL} from 'node:url'
import {build} from 'vite'
import React from 'react'
import {renderToStaticMarkup} from 'react-dom/server'

const root = fileURLToPath(new URL('..', import.meta.url))

test('diagnosis uses saved source identities and counts evidence without scoring context', async () => {
  const cache = join(root, 'node_modules', '.cache')
  await mkdir(cache, {recursive: true})
  const temp = await mkdtemp(join(cache, 'workbench-diagnosis-'))
  try {
    const result = await build({root, logLevel: 'silent', build: {
      ssr: join(root, 'src/components/WorkbenchDiagnosis.tsx'), write: false, minify: false,
    }})
    const entry = join(temp, 'view.mjs')
    await writeFile(entry, result.output.find(chunk => chunk.type === 'chunk' && chunk.isEntry).code)
    const {default: Diagnosis} = await import(pathToFileURL(entry))
    const {candidate, position} = JSON.parse(await readFile(join(root, '../examples/competition_case/v1/case.json'), 'utf8'))
    const sqlQuote = '1、开发订单报表，核对多表连接、分组和金额口径。'
    const resumeQuote = '做过基础SQL聚合和离线订单报表课程练习'
    const requirements = [
      {requirement_id: 'JD-02', label: '连接口径', evidence_status: 'partial', resume_quotes: [resumeQuote],
        rationale: '尚需验证连接后的金额。', follow_up: '用小样本复算。', priority: 'P1'},
      {requirement_id: 'JD-08', label: '流处理练习', evidence_status: 'not_provided', resume_quotes: [],
        rationale: '证据不足。', follow_up: '补充复现记录。', priority: 'P2'},
      {requirement_id: 'JD-09', label: '面试安排上下文', evidence_status: 'not_applicable',
        resume_quotes: [], rationale: '岗位背景。', follow_up: ''},
    ]
    const props = {candidate, position, busy: false, recover: false, hasPlan: false}
    const audit = {match_score: 55, score_reason: '固定案例', score_label: '固定参考',
      jd_items: [
        {requirement_id: 'JD-09', category: 'context', jd_quote: '远程技术交流'},
        {requirement_id: 'JD-08', category: 'bonus', jd_quote: '1、有可复现的流处理或自动化测试练习。'},
        {requirement_id: 'JD-02', category: 'responsibility', jd_quote: sqlQuote},
      ], evidence_assessment: {requirements}}
    const render = input => renderToStaticMarkup(React.createElement(Diagnosis, {...props, ...input})).replace(/\n/g, ' ')
    const pending = render({})
    assert.match(pending, /简历概况.*岗位描述（JD）.*诊断待完成.*完成示例岗位诊断/)
    assert.doesNotMatch(pending, /证据覆盖图|固定匹配参考/)
    assert.match(render({recover: true}), /恢复中断步骤/)
    const saved = render({audit, hasPlan: true})
    assert.match(saved, /简历与岗位对照.*诊断结论.*能力图 · 岗位证据覆盖.*逐项证据/)
    assert.match(saved, /岗位职责<\/strong><span>1 项.*部分支持 1 项/)
    assert.match(saved, /加分项<\/strong><span>1 项.*待补充证据 1 项/)
    assert.match(saved, new RegExp('JD 原句.*'+sqlQuote+'.*简历引用.*'+resumeQuote))
    assert.match(saved, /本项暂无对应的简历引用/)
    assert.match(saved, /查看本会话学习计划/)
    assert.doesNotMatch(saved, /面试安排上下文/)
    const older = render({audit: {...audit, jd_items: undefined}})
    assert.match(older, /该条原句未随结果保存/)
    assert.match(older, /待分类要求<\/strong><span>2 项/)
  } finally {
    await rm(temp, {recursive: true, force: true})
  }
})
