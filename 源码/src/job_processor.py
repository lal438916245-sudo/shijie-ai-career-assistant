import pandas as pd
import ast

# ==========================================
#  模块 1：数据清洗专家 (DataCleaner)
# 职责：只负责读取文件、处理空值、打基础标签。绝对不碰评分算法！
# ==========================================
class DataCleaner:
    def __init__(self, file_path):
        print(f" [DataCleaner] 正在加载数据文件: {file_path}")
        self.df = pd.read_excel(file_path)

    def clean_skills_robust(self):
        """ 鲁棒的清洗逻辑：只在需要时清洗脏数据 """
        print(" [DataCleaner] 正在检测并清洗可能存在的脏数据...")
        
        # 1. 如果数据里有“核心技能”这种老式脏数据列，咱们就执行清洗！
        if "核心技能" in self.df.columns:
            self.df["核心技能"] = self.df["核心技能"].fillna("")
            self.df["核心技能"] = self.df["核心技能"].str.replace("\n", "").str.strip()
            self.df["核心技能"] = self.df["核心技能"].str.replace("，", ",")
            self.df["技能列表"] = self.df["核心技能"].str.split(',')
            print(" 探测到原始格式数据，已执行深度清洗与分词！")
            
        # 2. 如果数据里直接是 AI 拆分好的 "JD核心技能" 和 "JD加分技能"
        elif "JD核心技能" in self.df.columns and "JD加分技能" in self.df.columns:
            # 对于这种数据，可能也有换行符，我们可以简单做个兜底清洗
            for col in ["JD核心技能", "JD加分技能"]:
                self.df[col] = self.df[col].fillna("[]")
                # 如果是字符串形式，清洗一下可能存在的奇怪空白
                if self.df[col].dtype == object:
                   self.df[col] = self.df[col].str.replace("\n", "").str.strip()
            print(" 探测到已拆分结构数据，已执行兜底清洗！")
            
        else:
            print("未发现可识别的技能列，跳过特征清洗！")

    def process_basic_features(self):
        print(" [DataCleaner] 正在进行基础特征工程 (打粗略标签)...")
        
        def check_logic(text):
            if pd.isna(text):
                return "普通"
            if "Python" in text or "数据分析" in text or "算法" in text:
                return "高相关" 
            return "普通"
            
        self.df["岗位相关度"] = self.df["岗位名称"].apply(check_logic)          
        print(" [DataCleaner] 基础清洗与标签添加完毕。")
        
        # 洗完菜后，把干净的菜 (DataFrame) 交出去
        return self.df


# ==========================================
#  模块 2：算法分析专家 (JobAnalyzer)
# 职责：不关心数据怎么来的，只要给我 DataFrame，我就负责算出 TIS 分数！
# ==========================================
class JobAnalyzer:
    def __init__(self, my_must, my_nice, target_companies, weights=(60, 20, 20)):
        # 算法引擎在启动时，只需要知道“候选人的画像”和“权重参数”
        self.my_must_set = {s.lower() for s in my_must}
        self.my_nice_set = {s.lower() for s in my_nice}
        self.target_companies = target_companies
        self.weights = weights

        w_must, w_nice, w_company = weights
        if w_must + w_nice + w_company != 100:
            print(f" 警告：您设置的权重总和({w_must+w_nice+w_company})不等于100分！")
            
        print(f" [JobAnalyzer] TIS 引擎初始化完成！")
        print(f" 当前权重 -> 硬技能:{w_must}%, 软技能:{w_nice}%, 心仪公司:{w_company}%")

    def calculate_tis(self, df):
        """ 接收外部传来的 DataFrame，执行惩罚矩阵打分 """
        w_must, w_nice, w_company = self.weights
        print("\n [JobAnalyzer] 正在执行交叉评分...")
        
        def _score_algorithm(row):
            try:
                jd_must = {s.lower() for s in ast.literal_eval(row.get("JD核心技能", "[]"))}
                jd_nice = {s.lower() for s in ast.literal_eval(row.get("JD加分技能", "[]"))}
            except:
                jd_must, jd_nice = set(), set()
                
            company = row.get("公司名", "")
            
            
            """
            --- TIS惩罚矩阵算法 ---
            解决“特征粒度错配 (Feature Granularity Mismatch)”。
            问：“如果我的硬技能是 JD 的软技能，我的软技能是 JD 的硬技能，怎么解决？”
            这恰恰指出了“技能掌握熟练度”与“岗位要求严格度”之间的矛盾！
            """

            if not jd_must: 
                must_score = 0
            else:
                perfect_match = self.my_must_set & jd_must
                weak_match = self.my_nice_set & jd_must
                must_match_count = len(perfect_match) * 1.0 + len(weak_match) * 0.5
                must_score = (must_match_count / len(jd_must)) * w_must
            
            if not jd_nice:
                nice_score = 0
            else:
                my_all_skills = self.my_must_set.union(self.my_nice_set)
                nice_match = my_all_skills & jd_nice
                nice_score = (len(nice_match) / len(jd_nice)) * w_nice

            company_score = w_company if company in self.target_companies else 0
            total_score = min(float(w_must + w_nice + w_company), must_score + nice_score + company_score)
            return round(total_score, 1)

        df["TIS综合评分"] = df.apply(_score_algorithm, axis=1)
        df = df.sort_values(by="TIS综合评分", ascending=False)
        print(" [JobAnalyzer] 评分计算完成，已降序排列！")
        
        # 算完分后，把结果交还给流水线
        return df

    def calculate_gap(self, df):
        """ 动态计算 Gap 优先级，直接返回一个字典列表给 Word 用 """
        all_jd_skills = df["JD核心技能"].apply(lambda x: ast.literal_eval(x) if pd.notna(x) else []).explode()
        skill_counts = all_jd_skills.value_counts().reset_index()
        skill_counts.columns = ["核心技能", "市场需求频次"]

        my_all_skills = self.my_must_set.union(self.my_nice_set)
        total_jobs = len(df)
        gap_records = []

        for _, row in skill_counts.iterrows():
            skill = row["核心技能"]
            if pd.isna(skill) or skill.strip() == "": continue
            
            market_hotness = row["市场需求频次"] / total_jobs
            mastery = "已掌握" if skill.lower() in my_all_skills else " 未掌握 (Gap)"
            
            if mastery == "已掌握":
                priority = "P3 - 巩固即可"
            elif market_hotness >= 0.3: 
                priority = "P0 - 极其紧急"
            elif market_hotness >= 0.1:
                priority = "P1 - 高优补充"
            else:
                priority = "P2 - 战略放弃"
                
            gap_records.append({"技能": skill, "状态": mastery, "优先级": priority})
            
        
        gap_df = pd.DataFrame(gap_records)


         # P0 → P1 → P2 → P3
        priority_order = {
        "P0 - 极其紧急": 0,
        "P1 - 高优补充": 1,
        "P2 - 战略放弃": 2,
        "P3 - 巩固即可": 3
    }

        gap_df["_priority_order"] = (
        gap_df["优先级"]
        .map(priority_order)
        )

        gap_df = (
        gap_df
        .sort_values("_priority_order")
        .drop(columns="_priority_order")
        .reset_index(drop=True)
    )

        return gap_df