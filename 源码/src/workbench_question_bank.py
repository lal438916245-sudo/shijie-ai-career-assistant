"""Original, fixed competition exercises. No network, model, or keyword grading."""
from copy import deepcopy
import hashlib
import re

RULE_VERSION='competition-demo-mastery-v1'
GRADING_VERSION='competition-fixed-rubric-v1'
PATHS={'repair':'先补强再通过','pass':'连续通过','weak':'持续困难','review':'评分待复核'}

# Each prompt is deliberately small enough for the stated beginner task.
ITEMS={
 'CP-T01':[
  ('sql','订单A=60元、B=40元，A有两条明细，B有一条。按订单ID连接后，直接累加订单金额是多少？真实订单总额是多少？写出修正办法。','连接行上60+60+40=160；真实订单总额60+40=100。若只要订单总额直接查订单表；需要明细指标时先按订单ID汇总明细再连接，不能按金额去重。'),
  ('model','同一订单有两条商品明细。订单表、明细表和连接结果分别一行代表什么？为什么不能把订单总额在每条明细上相加？','订单表一行一订单，明细表一行一商品明细，连接后通常是一行一配对明细。订单总额属于订单粒度，应先统一粒度再汇总。')],
 'CP-T02': [('stream','订单10:00发生、10:03被程序收到。事件时间和处理时间各是什么？按事件时间的10:00窗口统计时，10:03收到就一定丢弃吗？','事件时间10:00，处理时间10:03。是否接受迟到取决于水位线、窗口关闭及允许迟到策略，不能只凭收到时间决定。')],
 'CP-T03': [('model','一张表一行一订单，另一张一行一订单商品。要做每日订单金额报表，先说明事实粒度、关联键及一条防止重复金额的质量检查。','确定订单粒度，以订单ID关联；先将商品表聚合到一行一订单或直接从订单事实统计，并核对连接前后订单数/金额及订单ID唯一性。')],
 'CP-T04': [('sql','给订单金额统计加索引后跑得更快，但结果多了一倍。先查正确性还是看执行计划？说明两个验证步骤，以及单次耗时能否证明优化成功。','先核对结果口径/连接基数，再查看EXPLAIN与实际执行指标；用同一数据、统计信息和可重复测量对照，单次耗时不能证明收益，不能牺牲正确性。')],
 'CP-T05': [('stream','计算计数时程序在检查点之后故障。恢复状态一定代表外部下游永不重复吗？说明状态、源重放与下游提交三个边界。','状态恢复到检查点，源可能重放之后的数据；端到端结果还依赖源一致性和下游事务/幂等提交。仅有检查点不能承诺所有外部系统绝不重复。')],
 'CP-T06': [('engineering','给订单金额核对写测试：提供一个正常样本和一个会重复求和的反例，分别写预期结果；如何让测试可重复？','正常：A=60、B=40各一明细应100；反例A两明细时直接连接求和160，订单口径仍应100。固定输入与断言，在隔离环境重复运行，并保留失败信息。')],
 'CP-T07': [('stream','10:01发生的事件10:06才收到。水位线已越过10:05。是否仍能更新窗口？需要先确认哪些策略？','先确认窗口边界、允许迟到、水位线策略和侧输出/更新策略；水位线代表事件时间推进假设，不保证世界上再无迟到。按配置接受更新或旁路处理，不能凭常识一律丢弃。')],
 'CP-T08': [('sql','按用户取最近订单：两个订单时间相同，ROW_NUMBER只按时间倒序是否稳定？补充排序条件，并说明如何核对结果。','增加唯一订单ID等确定性次序；明确并列是否只取一个或保留全部。构造时间相同和用户边界样本核对结果，再做性能验证。')],
 'CP-T09': [('model','订单ID出现重复、金额出现NULL。为订单事实表写两条质量检查，说明NULL不能直接当0的原因以及模型变更后如何核对。','检查订单ID唯一和金额空值/取值规则；NULL可能是未知或缺数据，不能无依据当0。模型变更前后对同一订单集合核对数量、粒度、金额及异常明细。')],
 'CP-T10': [('engineering','订单任务偶发失败。日志里应记录哪些信息帮助串联处理过程？哪些内容不应原样写日志？说明一次排查顺序。','记录关联ID、任务/阶段、时间、错误类别和必要计数；不记录Key、完整个人资料或无关原始数据。先按关联ID查阶段，再用输入范围和错误定位小样本复现，避免只堆日志。')]
}

RETEST={
 'sql':[
 ('基础换数','退款单R1=90、R2=30，R1关联两条明细。连接后直接加退款总额是多少？正确退款总额是多少？','直接加90+90+30=210；真实退款120。保持退款单粒度，先汇总明细再连接或直接从退款单统计。'),
 ('边界迁移','两个不同退款单金额都是90，其中一个有两条明细。SUM(DISTINCT 退款金额)能修复重复吗？给出正确总额和依据。','不能，金额相同不是同一个退款单。不同金额只加一次得90但真实是180；应按退款单ID及目标粒度核对。'),
 ('保留缺失','一笔无明细退款单也要计入总额，应选INNER还是LEFT JOIN？LEFT JOIN是否自动防重复？','选保留左表的LEFT JOIN以保留无明细单；LEFT JOIN不自动防止一对多重复，仍需按退款单粒度处理。')],
 'model':[
 ('基础换景','退款事实一行一退款单、商品事实一行一退款商品。要按天统计退款总额，说明粒度与关联前检查。','目标一行一退款单参与求和，再按天汇总；先确认退款单ID唯一、商品表基数与缺失，不混用商品粒度。'),
 ('边界迁移','两笔退款金额相同，但退款ID不同。金额去重是否保持退款事实粒度？给出检查方法。','不保持。按退款ID区分事实；用相同金额不同ID的小样本对照总额、行数和唯一键，不能按金额合并事实。'),
 ('质量边界','模型新增退款状态维度后金额变大，应如何验证维度关联和历史口径？','检查维度键是否一对多、版本生效区间是否重叠；同一事实ID只能匹配适用版本，核对变更前后金额及未匹配/多匹配明细。')],
 'stream':[
 ('基础换景','支付事件10:00发生、10:04收到。按事件时间窗口计算时，应如何说明这两个时间及迟到处理依据？','事件时间10:00、处理时间10:04；需依据水位线、窗口边界及允许迟到/侧输出策略决定，不只看收到时刻。'),
 ('边界迁移','支付流恢复检查点后，下游账单出现重复。为什么检查点不能单独保证外部账单恰好一次？','源可能重放；状态快照、源位置和下游事务/幂等边界必须一致。需要幂等键或事务提交，并验证故障点和重放结果。'),
 ('恢复验证','如何用小样本验证迟到与故障恢复，不声称已经证明生产稳定性？','设置正常、迟到及重复事件与明确预期；在提交前后注入故障并对照状态/输出，说明源、下游和配置限制，小样本不能证明生产SLA。')],
 'engineering':[
 ('基础换景','为退款金额核对提供正常、重复明细两个测试样本，并说出断言。','正常两单90+30应120；一单两明细不能把正确订单口径从120变210。固定输入、唯一键/金额断言并隔离环境。'),
 ('边界迁移','失败重试后日志重复，怎样区分重复执行和两笔不同业务？哪些标识有用？','结合业务ID、请求/关联ID、运行/重试序号和阶段，不按相同日志文字判断同一业务；排查可重复输入且不记录敏感Key。'),
 ('反例验证','测试全通过是否足以承诺生产可靠？补充一个遗漏边界和可验证措施。','不够。补充空值、重复键或重试边界样本，明确预期并自动断言，说明数据规模、外部依赖和故障假设未覆盖的限制。')]
}

def fingerprint(text):
    return hashlib.sha256(re.sub(r'\s+',' ',text).strip().encode()).hexdigest()

def definition(topic):
    return {'topic_key':topic,'version':GRADING_VERSION,'dimensions':[
        {'key':'result','label':'结论与结果','weight':5000},
        {'key':'basis','label':'依据与边界','weight':5000}]}

def assessment_questions(tasks,kind):
    """Cover selected topic scope with per-topic independent rubric components."""
    count=2 if kind=='day' else 3
    keys=list(dict.fromkeys(k for t in tasks for k in t['topic_keys']))
    groups=[keys[i::count] for i in range(count)]
    result=[]
    for index,group in enumerate(groups):
        if not group:group=[keys[index%len(keys)]]
        parts=[]
        for key in group:
            task=next(t for t in tasks if key in t['topic_keys'])
            item=next((v for v in ITEMS[task['task_template_id']] if v[0]==key),None)
            if item is None:raise ValueError('fixed task question missing')
            prompt=item[1]
            if index>=len(keys):
                prompt+='\n补充：写出一个会使上述结论不成立的反例及核对办法。'
            parts.append({'topic_key':key,'task_id':task['task_id'],'prompt':prompt,'reference':item[2],
                          'rubric':definition(key)})
        result.append({'prompt':'\n\n'.join(p['prompt'] for p in parts),'parts':parts,'bank_key':f'{kind}:{index}',
                       'branch':'confirmed_scope','basis':'题目只取本次确认范围中的任务目标；日2题、周3题，不按专题各生成一套。'})
    return result

# Each extra item checks a different decision within its source task.
EXTRA_ITEMS={
 'CP-T01':[
  ('sql','订单 A=60、B=40。B 没有明细，也要计入总额。用 INNER JOIN 还是 LEFT JOIN？还需防什么？','LEFT JOIN 保留 B。若 A 有多行明细，仍需先按订单 ID 汇总明细，或从订单表直接统计。'),
  ('model','两笔不同订单恰好都是 60 元，按金额去重得到多少？应使用什么键区分事实？','金额去重得到 60，实际订单总额是 120。用订单 ID 区分不同订单。'),
  ('sql','报表还要显示每单的商品件数。A 有两条明细，件数 1 和 3。如何同时保持每单一行？','按订单 ID 聚合件数得到 A=4，再连接到订单表。订单金额只保留一次。')],
 'CP-T02':[
  ('stream','A 10:00 发生、10:04 到达，B 10:01 发生、10:02 到达。按事件发生和到达排序分别是什么？','发生顺序 A、B，到达顺序 B、A。以事件时间排序才能表达业务发生先后。'),
  ('stream','商家想查看每分钟产生了几笔订单，另想观察程序每分钟收到多少。两个图分别按什么时间归组？','订单产生量按事件时间，程序接收量按处理时所观察到的接收时间。'),
  ('stream','订单消息只有接收时间，能准确重建真实发生分钟吗？怎么记录这个限制？','无法准确重建。标记事件时间缺失或明确使用接收时间近似，保留字段来源并补齐上游时间戳。'),
  ('stream','同一事件重放，首次 10:03 收到，重放时 10:08 收到，原始发生时间为 10:00。哪一个时间决定业务窗口？','事件时间窗口仍取 10:00；接收时间会随运行变化。是否纳入窗口还取决于迟到处理策略。')],
 'CP-T03':[
  ('model','状态表里 A 同时有“已付款”和“已发货”两条记录，订单事实 join 后金额翻倍。如何先确定该关联哪一条？','确定需要最新状态还是截至某时刻的状态，再按订单和时间选唯一记录，检查每个订单最多匹配一条。'),
  ('model','业务希望同时看到每日订单数和商品件数。两种指标各从什么粒度统计？','订单数来自订单事实或订单 ID 去重，件数来自商品明细数量求和；分别按日汇总后再合并。'),
  ('model','检查发现某条商品明细的订单 ID 在订单表找不到。记录什么结果，为什么别直接忽略？','记录未匹配行数和样例，核对延迟或无效键。直接忽略会掩盖数据缺口或改变统计覆盖。'),
  ('model','来自两个店铺的数据都出现订单 ID 001。怎样判定是否同一订单？','依据业务定义核对订单 ID 的唯一范围；若仅店内唯一，用店铺 ID 与订单 ID 组成键。')],
 'CP-T04':[
  ('sql','对比两版查询时，一版跑昨天小样本，另一版跑最近一月。能用耗时判断哪个更快吗？','不能。用相同日期、数据、参数与可比环境重复测量，再看行数及执行指标。'),
  ('sql','执行计划估计输出 10 行，实际输出 1 万行。你先检查哪些输入条件？','检查过滤条件、连接基数和统计信息是否过期；先定位行数偏差再决定改写或建索引。'),
  ('sql','两版查询结果行数相同，但个别订单金额不同。什么样的对照能发现这个问题？','按业务唯一键逐项对照金额和缺失键，加入边界样本，单看总行数不足。'),
  ('sql','查询读得更快，但导入任务写入变慢。新增索引的影响怎么取证？','分别在相同负荷下量测读延迟、写入吞吐与索引空间，比较收益和成本。')],
 'CP-T05':[
  ('stream','检查点保存前处理了事件 X，但外部表已写入 X 就故障。恢复后再处理 X 会发生什么？','可能重放并再次写入。以业务事件 ID 实施幂等写入，或确保外部提交与检查点协调。'),
  ('stream','源端保留期短于停机时长，快照还在。恢复时为什么可能无法补齐数据？','快照只保存状态和恢复位置，源端过期数据可能无法重放；需要更长保留或独立补数来源。'),
  ('stream','要验证恢复时不漏计，如何设计一个包含故障的最小对照？','固定输入事件和期望累计值，在已知位置中断恢复，检查输出每个事件及最终聚合是否匹配。'),
  ('stream','只恢复源偏移，聚合状态却清空了。总计会怎样，需检查哪两者？','偏移之前的贡献可能丢失。检查状态快照和源位置是否来自一致的恢复点。')],
 'CP-T06':[
  ('engineering','测试只断言返回一行，但返回金额错了仍通过。补哪条断言？','断言小样本的精确期望金额，如两笔订单总额 100，另核对异常是否可读。'),
  ('engineering','测试读取数据库里每天变化的真实订单。怎样让失败能在另一台机器复现？','使用固定、最小化的脱敏测试样本和隔离环境，控制依赖与时钟并保存重现步骤。'),
  ('engineering','两笔不同订单金额相同。给去重逻辑设计一条能暴露错按金额去重的断言。','例如 A=60、B=60，断言两条订单及总额 120，不能被当成一笔。'),
  ('engineering','无明细订单也要出现在报表。给出最小输入及预期行数与金额。','一笔 40 元订单、明细为空，断言报表有 1 笔订单、总额 40。')],
 'CP-T07':[
  ('stream','窗口是 [10:00,10:05)，事件时间恰好 10:05。它归哪个窗口？','右端不包含，归从 10:05 开始的下一窗口。'),
  ('stream','窗口允许迟到两分钟，水位线已到 10:08。10:04 的事件可更新 10:05 关闭的窗口吗？','已超过窗口结束加两分钟的界限，通常不再更新，按配置送侧输出或记录。'),
  ('stream','一部分迟到事件被送侧输出。怎么验证它们没有同时计入主结果？','构造边界前后事件，按事件 ID 对照主结果与侧输出，并核对数量及总值。'),
  ('stream','两个分区中一个暂时无事件，整体水位线迟迟不动。该观察和验证什么？','检查各分区水位线及空闲检测设置；用空闲与重新来数的样本验证窗口推进和迟到行为。')],
 'CP-T08':[
  ('sql','需求是同一用户并列最近的订单全部保留。应选 ROW_NUMBER=1 还是按时间 DENSE_RANK=1？','按用户分区、时间降序用 DENSE_RANK=1 保留并列；ROW_NUMBER=1 只保留一个。'),
  ('sql','ROW_NUMBER 只有 ORDER BY 时间，没写 PARTITION BY 用户。两个用户各有一笔订单时会选出几笔？','全表只有一个序号 1，故只选一笔。按用户分区才能每用户各选一笔。'),
  ('sql','两个同用户订单时刻一致，约定 ID 大者胜出。写出确定的排序，并给出 ID 7 和 9 的预期。','在用户分区内 ORDER BY 时间 DESC、订单 ID DESC，结果应为 ID 9。'),
  ('sql','时间为空的订单不应当作最近。窗口计算前可如何处理？','明确口径后先过滤空时间或显式排到最后，同时记录空时间异常，避免默认排序误选。')],
 'CP-T09':[
  ('model','校验前总额 100，修复后仍为 100，但 A 少 20、B 多 20。还需加什么检查？','按订单 ID 对照逐笔金额与缺失键，整表总额相同可能掩盖抵消错误。'),
  ('model','金额列有真实零元单也有 NULL。质量报告如何让两种记录分开？','分开统计零值和缺失值，NULL 走缺失规则，零值按业务规则解释。'),
  ('model','重复键对应两条不一致的状态记录，可直接选金额较大的一条吗？','先定位重复来源，按有依据的更新时间或业务有效规则判定，保留冲突样本。'),
  ('model','日切后发现日期缺少一天，单行唯一性仍全通过。该补哪类检查？','补日期覆盖和数据新鲜度检查，与预期批次或日历逐日对照。')],
 'CP-T10':[
  ('engineering','同一任务重试三次。日志用什么字段同时找到整条链路并区分三次尝试？','用关联或业务 ID 串联，另记运行 ID 或重试序号、阶段和时间。'),
  ('engineering','异常文本包含连接字符串。记录日志前怎么处理，同时保留诊断价值？','移除凭证和连接细节，记录错误类型、阶段、关联 ID 与可公开的简短错误信息。'),
  ('engineering','看到“导入失败”但无法复现。加哪些最小上下文方便重放？','加批次与输入范围、处理阶段、错误类别和版本，必要时保留脱敏小样本。'),
  ('engineering','某次失败发生在写出之前，另一次在提交之后。如何通过日志区分并决定检查什么？','记录写出、提交的阶段与成功标记；前者查输入/处理，后者核对落库与重试幂等性。')]
}

def scoped_assessment_questions(tasks,kind,count):
    """Round-robin the selected tasks before drawing additional items per task."""
    banks=[(task, ITEMS[task['task_template_id']]+EXTRA_ITEMS[task['task_template_id']]) for task in tasks]
    questions=[]
    for index in range(5):
        for task,items in banks:
            key,prompt,reference=items[index]
            part={'topic_key':key,'task_id':task['task_id'],'prompt':prompt,'reference':reference,'rubric':definition(key)}
            questions.append({'prompt':prompt,'parts':[part],'bank_key':f"{kind}:{task['task_template_id']}:{index}",
                'branch':'confirmed_scope','basis':f"来自所选任务「{task['title']}」的固定题库；每题核对一个专题分项。"})
            if len(questions)==count:
                return questions
    raise ValueError('confirmed scope has too few fixed questions')

def retest_question(topic,index,previous_score,task_ids,progress):
    # Only this single branch is produced. No later question is exposed/stored.
    slot=index
    if index>0 and previous_score is not None and previous_score<60:slot=0
    title,prompt,reference=RETEST[topic][slot]
    if index>0 and slot==0:
        prompt+='\n请先列出一项核对步骤，再给结论。'
    return {'prompt':prompt,'parts':[{'topic_key':topic,'task_id':task_ids[0],
        'prompt':prompt,'reference':reference,'rubric':definition(topic)}],
        'bank_key':f'retest:{topic}:{slot}:{index if slot==0 else 0}','branch':title,
        'basis':('上题未通过，改用基础核对分支；' if index and previous_score<60 else '上题通过，换边界验证；' if index else '从本专题最新有效答卷开始；')+
                '同时冻结当前学习状态供核对。固定分支，不读取笔记推理，不声称模型动态出题。',
        'learning_snapshot':deepcopy(progress)}

def fixed_grade(question,kind,path,ordinal):
    """Explicit scenario, NEVER judge typed answer. Separate topic components."""
    if path=='review':return {'status':'review_required','version':GRADING_VERSION,'scores':[],
        'feedback':'此分支固定模拟评分信息不足，保留答卷但不作为通过或失败。'}
    base=45 if path=='weak' else 80 if path=='pass' else (55 if ordinal==0 else 75) if kind=='day' else 72 if kind=='week' else (72 if ordinal==0 else 82)
    scores=[]
    for part in question['parts']:
        score=base+{'sql':0,'model':1,'stream':2,'engineering':3}[part['topic_key']]
        scores.append({'topic_key':part['topic_key'],'dimensions':{'result':score,'basis':score},'score':score})
    return {'status':'scored','version':GRADING_VERSION,'scores':scores,
        'feedback':'固定示例：先核对结果，再补依据和边界。分数由所选演示路线决定，与输入答案内容无关。'}
