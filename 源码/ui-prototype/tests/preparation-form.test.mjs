import test from 'node:test'
import assert from 'node:assert/strict'
import {normalizePreparationNumbers,normalizePreparationConfig} from '../src/lib/preparation-form.mjs'

const base = {max_input_chars:12000,max_output_tokens:16000,timeout_seconds:180,temperature:null,input_price_per_million:2,output_price_per_million:8}

test('清空必填数字时不将空白转换为零，重新输入后发送数字',()=>{
 const draft = {...base,max_output_tokens:''}
 assert.throws(()=>normalizePreparationNumbers(draft),/请填写输出 token 上限/)
 assert.equal(draft.max_output_tokens,'')
 draft.max_output_tokens='1'
 assert.throws(()=>normalizePreparationNumbers(draft),/256 到 16000/)
 draft.max_output_tokens='16000'
 assert.equal(normalizePreparationNumbers(draft).max_output_tokens,16000)
 assert.equal(draft.max_output_tokens,'16000')
 assert.equal(normalizePreparationNumbers({...base,max_output_tokens:'016000'}).max_output_tokens,16000)
})

test('可选小数可留空，零单价与零温度不丢失',()=>{
 const result=normalizePreparationNumbers({...base,temperature:'',input_price_per_million:'0',output_price_per_million:'0.04'})
 assert.equal(result.temperature,null)
 assert.equal(result.input_price_per_million,0)
 assert.equal(result.output_price_per_million,0.04)
 assert.equal(normalizePreparationNumbers({...base,temperature:'0'}).temperature,0)
})

test('保存前拒绝非整数、越界和非有限值，保留其他配置',()=>{
 for(const patch of [{timeout_seconds:'4'},{timeout_seconds:'181'},{timeout_seconds:'5.5'},{max_input_chars:''},{max_input_chars:'200001'},{max_output_tokens:'16001'},{temperature:'2.1'},{input_price_per_million:'-1'},{output_price_per_million:'Infinity'},{output_price_per_million:'NaN'}]) {
  assert.throws(()=>normalizePreparationNumbers({...base,...patch}))
 }
 const config={...base,provider:'DeepSeek',model:'deepseek-flash'}
 assert.deepEqual(normalizePreparationNumbers(config),config)
})

test('模型配置接受复制时的首尾空白，拦住中文名和反引号，不回显输入',()=>{
 const config={...base,provider:' DeepSeek ',base_url:' https://api.deepseek.com ',model:' deepseek-flash\n'}
 const result=normalizePreparationConfig(config)
 assert.equal(result.provider,'DeepSeek')
 assert.equal(result.base_url,'https://api.deepseek.com')
 assert.equal(result.model,'deepseek-flash')
 assert.equal(config.model,' deepseek-flash\n')
 for(const model of ['', 'DeepSeek 闪电模型', '`deepseek-flash`', 'deepseek flash']) {
  assert.throws(()=>normalizePreparationConfig({...config,model}),e=>e.message.includes('模型标识请填写接口名称')&&!e.message.includes('DeepSeek 闪电模型'))
 }
})
