import os

import docx
from docx.shared import Inches, RGBColor#inches 用于设置图片宽度，RGBColor 用于设置字体颜色
from docx.oxml.ns import qn

class ReportGenerator:
    """ 报告生成中台：负责将各种数据和内存流图片，组合成最终的商业 Word 研报。"""
    
    def __init__(self, template_path=None):
        print(" [ReportGenerator] 正在初始化报告引擎...")
        # 如果有现成的 Word 模版就用模版，没有就建个空白的
        self.doc = docx.Document(template_path) if template_path else docx.Document()#self.doc 是当前正在操作的对象
        # 设置 Word 的默认中文字体为黑体 (防止宋体太丑)
        self.doc.styles['Normal'].font.name = '微软雅黑'
        self.doc.styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')

    def add_title_and_intro(self, job_title, company, score, scorer="综合评分"):
        """
        动态插入：根据分数选择鼓励话术还是警告话术。

        `scorer` 必须如实传："TIS 引擎" 与 "AI 猎头" 是两套完全不同的口径，
        写错了会让读者以为分数可比（实测库里 88.5 与 52.0 就来自两个不同来源）。
        """
        self.doc.add_heading(f"《{company} - {job_title}》 岗位对齐分析报告", level=0)
        
        p = self.doc.add_paragraph(f"经 {scorer} 评测，您与该岗位的匹配度为：")
        run = p.add_run(f"{score}分")
        run.bold = True#加粗分数
        run.font.color.rgb = RGBColor(255, 0, 0) if score < 60 else RGBColor(0, 128, 0) # 不及格红色，及格绿色
        
        if score >= 80:
            self.doc.add_paragraph(" 结论：高度匹配，建议优先投递")
        elif score >= 60:
            self.doc.add_paragraph(" 结论：中等匹配，建议针对 Gap 进行补强")
        else:
            self.doc.add_paragraph(" 结论：当前匹配度较低，建议优先提升关键能力")

    def add_radar_chart(self, image_stream, categories=None):
        """ 接收内存流对象，并直接插入 Word！ """
        n = len(categories) if categories else None
        heading = f"一、 能力画像雷达图（{n} 个维度）" if n else "一、 能力画像雷达图"
        self.doc.add_heading(heading, level=1)
        self.doc.add_paragraph(
            "以下维度全部由真实数据计算："
            "AI 猎头打分来自对简历与 JD 的语义分析，"
            "覆盖率来自 Gap 表的确定性统计。具体来源见随后的明细表。")
        
        #  核心：直接把刚才的 img_stream 丢进 Word 里，不需要读取硬盘文件
        self.doc.add_picture(image_stream, width=Inches(4.5))

    def add_score_breakdown(self, details):
        """
        插入能力画像明细表：维度 / 分数 / 数据来源 / 依据。

        这张表的作用是让雷达图**可核对** —— 否则读者只能看到一张形状，
        却不知道每个角是从哪来的。
        """
        if not details:
            return
        self.doc.add_heading("能力画像明细（含数据来源）", level=2)

        table = self.doc.add_table(rows=1, cols=4)
        table.style = 'Light Shading Accent 1'
        hdr = table.rows[0].cells
        hdr[0].text = '维度'
        hdr[1].text = '分数'
        hdr[2].text = '数据来源'
        hdr[3].text = '依据'

        for d in details:
            cells = table.add_row().cells
            cells[0].text = str(d.get("label", ""))
            cells[1].text = str(d.get("score", ""))
            cells[2].text = str(d.get("source", ""))
            cells[3].text = str(d.get("reason", "") or "—")

    def export_report(self, filename="最终研报.docx"):
        parent = os.path.dirname(filename)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.doc.save(filename)
        print(f" 报告已自动排版并生成！请查看: {filename}")

    def add_header_footer(self):
        """ 为报告添加页眉和页脚 """
        # 获取第一节
        section = self.doc.sections[0]
        
        # 1. 设置页眉
        header = section.header
        header_para = header.paragraphs[0]
        header_para.text = " Career-Pilot 智能求职研报  | 内部机密资料"
        # 把页眉变成灰色，显得专业
        header_para.runs[0].font.color.rgb = RGBColor(128, 128, 128)
        
        # 2. 设置页脚
        footer = section.footer
        footer_para = footer.paragraphs[0]
        footer_para.text = "版权所有 © Career-Pilot - 严禁外传"

    def add_gap_table(self, gap_data_list):
        """ 
        插入技能比对表格 
        gap_data_list 的格式例如: [{"技能": "C++", "状态": "未掌握", "优先级": "P0"}]
        """
        self.doc.add_heading("二、 基础硬技能匹配清单 (模拟 HR 关键词初筛)", level=1)
        
        # 1. 创建表格 (行数 = 数据行数 + 1行表头，列数 = 3)
        table = self.doc.add_table(rows=1, cols=3)
        #  应用 Word 自带的精美表格样式 (带边框和斑马纹背景)
        table.style = 'Light Shading Accent 1'
        
        # 2. 填写表头
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = '核心技能'
        hdr_cells[1].text = '当前状态'
        hdr_cells[2].text = '补位优先级'
        
        # 3. 遍历数据，动态新增行并填入表格
        for item in gap_data_list:
            row_cells = table.add_row().cells
            row_cells[0].text = item.get("技能", "")
            row_cells[1].text = item.get("状态", "")
            row_cells[2].text = item.get("优先级", "")

    def add_market_analysis(self, bar_stream, hist_stream):
        """ 接收柱状图和直方图的内存流，插入到 Word 中 """
        self.doc.add_heading("三、 岗位库统计分析", level=1)
        # 原来的文案写的是"根据最新爬取的数据" —— 实际上这份数据来自本地
        # `data/jobs_mock.xlsx`（模拟生成），如实标注比看起来专业更重要。
        self.doc.add_paragraph(
            "以下统计基于本地岗位库（当前为模拟数据，尚未接入真实招聘源）：")
        
        # 插入 Top技能 柱状图
        self.doc.add_paragraph("【市场核心技能需求 Top 10】")
        self.doc.add_picture(bar_stream, width=Inches(5.0))
        
        # 插入 匹配度 直方图
        self.doc.add_paragraph("【本次检索岗位的整体匹配度分布】")
        self.doc.add_picture(hist_stream, width=Inches(5.0))


    
    def add_agent_analysis(self, agent_data: dict,has_hard_gaps:bool=False):
        """
        专门用于将 Agent A 的 JSON 数据排版进 Word
        """
        if not agent_data:
            return
            
        # 1. 添加大标题
        heading = self.doc.add_heading(' AI 猎头深度剖析', level=2)

         # 【核心逻辑】：根据底层 Pandas 的计算结果，动态输出承上启下的文案
        if has_hard_gaps:
            # 场景A：连基础工具都没对齐
            transition_text = " 提示：除了下列表格中暴露的【基础硬技能缺失】外，经 AI 猎头对岗位底层业务逻辑的深度推理，您在业务实操层面还面临以下降维打击："
        else:
            # 场景B：基础工具全覆盖，但缺乏深度（也就是你这次测试遇到的情况）
            transition_text = " 提示：虽然您的【基础硬技能】在字面上已基本覆盖 JD 要求，但经 AI 猎头深度推理，发现您仍存在以下致命的隐形业务盲区："
            
        self.doc.add_paragraph(transition_text, style='Intense Quote')
        
        # 2. 致命弱点 (红色高亮显示)
        self.doc.add_heading(' 致命弱点', level=3)
        p1 = self.doc.add_paragraph(agent_data.get('fatal_weakness', '无'))
        # 如果你懂一点 docx 的样式，可以在这里设置颜色，不懂直接默认就行
        
        # 3. 隐形 Gap 列表
        self.doc.add_heading(' 隐形 Gap 挖掘', level=3)
        invisible_gaps = agent_data.get('invisible_gaps', [])
        for gap in invisible_gaps:
            text = f"【{gap.get('skill')}】\nJD要求: {gap.get('industry_requirement')}\n现状: {gap.get('candidate_current')}\n差距: {gap.get('gap_reason')}"
            self.doc.add_paragraph(text, style='List Bullet')
            
        # 4. 行动建议
        self.doc.add_heading(' 猎头突击建议', level=3)
        advice_list = agent_data.get('actionable_advice', [])
        for advice in advice_list:
            self.doc.add_paragraph(advice, style='List Number')