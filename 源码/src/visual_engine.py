import matplotlib
# 必须在 import pyplot 之前指定后端。
# 报告是从命令行后台生成的，不需要 GUI；不指定的话 matplotlib 可能选 TkAgg，
# 而某些环境里 tkinter 是坏的（实测在 conda 环境下报 _tkinter.TclError）。
# 显式用 Agg 让"能出图"这件事不依赖桌面环境，结果也可复现。
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import io  # 核心：Python 的内存输入输出库
import platform
import warnings

warnings.filterwarnings("ignore")

class VisualEngine:
    """
    视觉中台：负责生成所有的统计图表，并以内存流（BytesIO）形式返回，全程不落盘。
    """
    def __init__(self):
        print(" [VisualEngine] 正在初始化视觉渲染引擎...")
        # 配置中文字体防方块
        system = platform.system()
        if system == 'Windows':
            self.font_name = 'SimHei'
        elif system == 'Darwin':
            self.font_name = 'Arial Unicode MS'
        else:
            self.font_name = 'sans-serif'
            
        plt.rcParams['font.sans-serif'] = [self.font_name]
        plt.rcParams['axes.unicode_minus'] = False
        sns.set_theme(style="whitegrid")
        sns.set(font=self.font_name)

    def generate_radar_chart_stream(self, categories, scores, title=None):
        """
        生成能力雷达图，返回内存流。

        categories / scores 必须由调用方从**真实数据**算好传入
        （见 `ability_profile.build()`）—— 这里不再提供任何默认值，
        免得又出现"分数是写死的"这种情况。

        title 不给时按维度数自动生成（原来固定写"五维"，维度一变标题就错了）。
        """
        if len(categories) != len(scores):
            raise ValueError(
                f"维度与分数数量不一致：{len(categories)} vs {len(scores)}")
        if len(categories) < 3:
            raise ValueError(f"雷达图至少需要 3 个维度，收到 {len(categories)} 个")

        cats = [*categories, categories[0]]#雷达图需要闭合
        vals = [*scores, scores[0]]#实现首尾连接
        angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()#将圆平均切割成len(categories)份
        angles += angles[:1]

        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))#创建雷达图，polar=Treu表示需要极坐标
        ax.plot(angles, vals, color='#1f77b4', linewidth=2)#画图，angels是每个维度应该放在哪个方向，vals是每个维度应该延申多远
        ax.fill(angles, vals, color='#1f77b4', alpha=0.25)
        
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=10, fontweight='bold')
        ax.set_yticks([20, 40, 60, 80, 100])
        ax.set_ylim(0, 100)
        plt.title(title or f"能力画像（{len(categories)} 个维度）",
                  fontsize=14, fontweight='bold', pad=20)

        # -----------------------------------------
        #  核心黑魔法：内存流保存法
        # -----------------------------------------
        img_stream = io.BytesIO() # 1. 凭空在内存里捏出一个空文件
        plt.savefig(img_stream, format='png', dpi=150, bbox_inches='tight') # 2. 把图画进这个内存文件里，img_stream 就是一个“虚拟的 .png 文件”
        plt.close() # 3. 关闭画笔，释放系统资源
        
        img_stream.seek(0) # 4. 把读取指针移回文件开头（极其重要，否则后面读取是空的）
        return img_stream  # 5. 返回这坨内存数据！

    def generate_skills_bar_stream(self, df_skills):
        """ 生成 Top 技能条形图，返回内存流 """
        plt.figure(figsize=(8, 5))
        sns.barplot(x="出现次数", y="技能名称", data=df_skills, palette="viridis")
        
        plt.title("市场 Top 核心技能需求", fontsize=14, fontweight='bold')
        plt.xlabel("需求频次", fontsize=10)
        plt.ylabel("")

        img_stream = io.BytesIO()#凭空在内存里捏出一个空文件
        plt.savefig(img_stream, format='png', dpi=150, bbox_inches='tight')#画进去
        plt.close()#释放系统资源
        
        img_stream.seek(0)#游标归零
        return img_stream

    def generate_score_histogram_stream(self, df_scores):
        """ 生成分数分布直方图，返回内存流 """
        plt.figure(figsize=(8, 5))
        sns.histplot(data=df_scores,x="TIS综合评分", bins=20, kde=True, color='skyblue')
        
        plt.title("岗位匹配度分布直方图", fontsize=14, fontweight='bold')
        plt.xlabel("岗位匹配度 (TIS)", fontsize=10)
        plt.ylabel("岗位数量")

        img_stream = io.BytesIO()#凭空在内存里捏出一个空文件
        plt.savefig(img_stream, format='png', dpi=150, bbox_inches='tight')#画进去
        plt.close()#释放系统资源
        
        img_stream.seek(0)#游标归零
        return img_stream

# ==================================
#  测试区 (确保引擎正常工作)
# ==================================
# if __name__ == "__main__":
#     engine = VisualEngine()

#     # ==================================
#     # 1. 测试雷达图
#     # ==================================
#     cats = ['代码力', '产品力', '业务感', 'AI工具应用', '文档力']
#     scores = [85, 70, 60, 95, 75]

#     print("\n⏳ 正在测试雷达图...")

#     radar_stream = engine.generate_radar_chart_stream(cats, scores)

#     print(f"✅ 雷达图生成成功")
#     print(f"📦 内存占用大小: {radar_stream.getbuffer().nbytes} 字节")


#     # ==================================
#     # 2. 测试技能柱状图
#     # ==================================
#     import pandas as pd

#     df_skills = pd.DataFrame({
#         "技能名称": ["Python", "SQL", "C++", "算法", "Linux"],
#         "出现次数": [120, 95, 80, 75, 60]
#     })

#     print("\n⏳ 正在测试技能柱状图...")

#     skills_stream = engine.generate_skills_bar_stream(df_skills)

#     print(f"✅ 技能柱状图生成成功")
#     print(f"📦 内存占用大小: {skills_stream.getbuffer().nbytes} 字节")


#     # ==================================
#     # 3. 测试 TIS 匹配度分布图
#     # ==================================
#     df_scores = pd.DataFrame({
#         "TIS": [
#             55, 60, 62, 65, 68,
#             70, 72, 73, 75, 76,
#             78, 80, 81, 82, 84,
#             85, 86, 88, 90, 92
#         ]
#     })

#     print("\n⏳ 正在测试 TIS 匹配度分布图...")

#     score_stream = engine.generate_score_histogram_stream(df_scores)

#     print(f"✅ TIS 匹配度分布图生成成功")
#     print(f"📦 内存占用大小: {score_stream.getbuffer().nbytes} 字节")


#     print("\n🎉 所有图表测试完成！")