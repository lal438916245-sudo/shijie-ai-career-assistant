"""
岗位匹配（主线一的可复用版本）
pipeline_full.py 调用它；core_pipeline.py 先保持不动，以后再接。
"""
import uuid
import pandas as pd

import paths
from job_processor import DataCleaner, JobAnalyzer
from json_utils import extract_json_from_text

DEFAULT_MUST  = ["Python", "SQL", "Pandas", "算法", "数据结构", "C++"]
DEFAULT_NICE  = ["沟通能力", "Redis", "Linux", "英语流利"]
DEFAULT_DREAM = ["腾讯", "字节跳动", "米哈游"]


def _resume_summary(my_must, my_nice, dream):
    return (f"候选人核心技能：{','.join(my_must)}。"
            f"加分技能：{','.join(my_nice)}。"
            f"目标大厂：{','.join(dream)}。")


def run_job_matching(db, hunter, trace_id,
                     data_source=paths.data_file("jobs_mock.xlsx"),
                     my_must=None, my_nice=None, dream=None,
                     top_n=1, interactive=False):
    """清洗 → 打分 → 选岗 → Agent A 剖析 → gap 落库 → A→B 交接"""
    my_must = my_must or DEFAULT_MUST
    my_nice = my_nice or DEFAULT_NICE
    dream   = dream   or DEFAULT_DREAM

    # 1) 清洗 + 打分
    cleaner  = DataCleaner(data_source)
    analyzer = JobAnalyzer(my_must, my_nice, dream, weights=(50, 10, 40))
    cleaner.clean_skills_robust()
    clean_df  = cleaner.process_basic_features()
    scored_df = analyzer.calculate_tis(clean_df)

    if scored_df.empty:
        raise ValueError(f"{data_source} 里没有可用岗位")

    # 2) 选岗
    if interactive:
        top = scored_df.head(3).reset_index(drop=True)
        for i, row in top.iterrows():
            print(f"   [{i+1}] {row['公司名']} - {row['岗位名称']} (TIS {row['TIS综合评分']})")
        while True:
            choice = input("请选择岗位编号 (1/2/3)：").strip()
            if choice in ("1", "2", "3") and int(choice) <= len(top):
                selected = top.iloc[int(choice) - 1]
                break
            print("输入无效，请重新输入！")
    else:
        selected = scored_df.head(top_n).iloc[0]

    # 3) 靶向算 Gap
    single_df = pd.DataFrame([selected])
    gap_df = analyzer.calculate_gap(single_df)
    emergency_gap = gap_df[gap_df["优先级"].fillna("").str.contains("P0|P1")]

    target_title = f"{selected['公司名']} {selected['岗位名称']}"
    print(f"[岗位匹配] 锁定：{target_title}（TIS {selected['TIS综合评分']}）")

    # 4) Agent A 深度剖析
    llm_raw = hunter.deep_audit(
        target_job_title=target_title,
        resume_text=_resume_summary(my_must, my_nice, dream),
        jd_text=selected.get("职位描述", ""),
        gap_df=emergency_gap,
    )
    audit = extract_json_from_text(llm_raw)

    # 5) 落库 + A→B 交接
    report_id = f"GAP_{uuid.uuid4().hex[:12]}"
    db.save_gap_report(
        report_id=report_id, trace_id=trace_id,
        company=selected["公司名"], title=selected["岗位名称"],
        tis_score=selected["TIS综合评分"],
        gap_df=gap_df, audit=audit,
        # 写进 tis_score 的是 job_processor 的 TIS 关键词评分（0~100 的范围里
        # 代表"关键词命中"），不是大模型判断 —— 标明尺度来源。
        scorer="tis_keyword",
    )
    db.append_message(trace_id, "Agent_A", "Agent_B", "handoff",
                      {"report_id": report_id, "title": target_title})
    print(f"[岗位匹配] gap 报告已落库：{report_id}")

    return {
        "report_id": report_id,
        "company": selected["公司名"],
        "title": selected["岗位名称"],
        "tis_score": selected["TIS综合评分"],
        "target_title": target_title,
        "clean_df": clean_df, "scored_df": scored_df,
        "selected_job": selected, "gap_df": gap_df,
        "emergency_gap": emergency_gap, "audit": audit,
    }
