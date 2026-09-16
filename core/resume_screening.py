"""模块一补充 · 简历规则初筛引擎：硬条件过滤 + 软条件加权评分 + 三档归类。

移植自 hr-ai-workbench/app/services/screening.py，纯规则、可解释、可审计，
不依赖外部 LLM 即可跑通（作为 DeepSeek 提取的离线降级与双轨交叉校验）。

流程：screen_resume(text, role, hard_cond, weights)
  1. 解析简历文本 → 候选字段（学历/年限/城市/期望薪资/技能/院校/管理经验/稳定性）；
  2. 硬条件(_check_hard) 任一不满足 → 直接 reject（保留分数与理由）；
  3. 软加权(_score_soft) 归一化到 100 分制；
  4. 三档：pass(>=pass_threshold) / maybe(>=maybe_threshold) / reject。
全部为确定性输出，便于出庭/复核与离线环境兜底。
"""
import json
import re


EDU_RANK = {"博士": 6, "硕士": 5, "硕士研究生": 5, "研究生": 5, "本科": 4, "双学位": 4,
            "大专": 3, "专科": 3, "高中": 2, "中专": 2, "中技": 2, None: 0}

# 通用技能词表（命中即计入技能分；可与岗位词典合并）
SKILL_LEXICON = {
    "软件工程师": ["python", "java", "go", "c++", "react", "vue", "linux", "mysql", "redis", "docker", "k8s", "算法", "数据结构"],
    "销售代表": ["bd", "大客户", "渠道", "签单", "陌拜", "crm", "谈判", "回款"],
    "HR专员": ["招聘", "绩效", "薪酬", "员工关系", "劳动争议", "社保", "劳动合同法", "培训", "组织发展"],
    "产品经理": ["需求分析", "原型", "prd", "axure", "用户研究", "数据分析", "项目管理", "埋点", "增长"],
}

TOP_SCHOOLS = ["985", "211", "双一流", "清华", "北大", "复旦", "上海交大", "浙大", "中科院"]


def _edu_rank(edu):
    return EDU_RANK.get(edu, 0)


def _norm_edu(text):
    t = text or ""
    for k in ["博士研究生", "硕士", "研究生", "本科", "双学位", "大专", "专科", "高中", "中专", "中技"]:
        if k in t:
            return k
    return None


def parse_resume_text(text: str) -> dict:
    """轻量解析：从简历文本抽取候选字段。规则可解释，便于复核。"""
    t = (text or "").lower()

    # 学历
    edu = _norm_edu(text)

    # 工作年限：取最大 "X年"
    years = 0
    for m in re.finditer(r"(\d{1,2})\s*年", t):
        years = max(years, int(m.group(1)))

    # 城市（常见一二线城市）
    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "南京", "武汉", "西安", "苏州", "重庆", "天津", "东莞", "佛山"]
    city = next((c for c in cities if c in text), "")

    # 期望薪资：期望 10k-15k / 期望薪资：12000
    sal = 0
    m = re.search(r"期望\s*(?:薪资|工资)?\s*[:：]?\s*(\d{1,3})\s*(?:k|千|w|万)?\s*[-~—]?\s*(\d{1,3})?\s*(?:k|千|万)?", t)
    if m:
        try:
            v = int(m.group(1))
            # 粗略：k/千→千元；w/万→万元转千
            unit = m.group(0)
            if "w" in unit or "万" in unit:
                sal = v * 10000
            else:
                sal = v * 1000
        except Exception:
            sal = 0

    # 技能命中（合并通用词典）
    skills = []
    for word in sum(SKILL_LEXICON.values(), []):
        if word.lower() in t:
            skills.append(word)

    # 院校层次
    top_school = any(s.lower() in t for s in TOP_SCHOOLS)
    school = ""
    sm = re.search(r"(?:毕业[院学]|[院学]校)[：: ]*([\u4e00-\u9fa5a-zA-Z0-9]{2,20})", text)
    if sm:
        school = sm.group(1)

    # 管理经验
    has_management = (any(k in t for k in ["管理", "带团队", "团队负责人", "leader", "总监", "经理", "主管"])
                      or bool(re.search(r"带\s*\d+\s*人", t)))

    # 稳定性：工作经历段数（粗略：数「公司」出现次数或日期区间段）
    job_changes = len(re.findall(r"(?:公司|企业|集团)", t))

    return {
        "education": edu or "",
        "work_years": years,
        "city": city,
        "expect_salary": sal,
        "skills": skills,
        "top_school": top_school,
        "school": school,
        "has_management": has_management,
        "job_changes": job_changes,
    }


def _check_hard(c, cond):
    """返回 (pass_all, details)。details: [{key, label, ok, expect, actual}]"""
    details = []
    all_ok = True

    edu_req = cond.get("education") or "不限"
    if edu_req != "不限":
        ok = _edu_rank((c.get("education") or "").replace("硕士研究生", "硕士").replace("研究生", "硕士")) >= _edu_rank(edu_req)
        details.append({"key": "education", "label": "学历", "ok": ok,
                        "expect": f"{edu_req}及以上", "actual": c.get("education") or "未识别"})
        all_ok = all_ok and ok

    min_years = int(cond.get("min_years") or 0)
    if min_years > 0:
        y = c.get("work_years") or 0
        ok = y >= min_years
        details.append({"key": "years", "label": "工作年限", "ok": ok,
                        "expect": f"{min_years}年以上", "actual": f"{y}年" if y else "未识别"})
        all_ok = all_ok and ok

    city = cond.get("city") or "不限"
    if city != "不限":
        ok = c.get("city") == city
        details.append({"key": "city", "label": "现居/期望城市", "ok": ok,
                        "expect": city, "actual": c.get("city") or "未识别"})
        all_ok = all_ok and ok

    salary_max = int(cond.get("salary_max") or 0)
    if salary_max > 0:
        s = c.get("expect_salary") or 0
        ok = s <= salary_max
        details.append({"key": "salary", "label": "期望薪资上限", "ok": ok,
                        "expect": f"{salary_max}元内", "actual": f"{s}元" if s else "未识别"})
        all_ok = all_ok and ok

    skills_req = [s for s in (cond.get("skills") or "").split(",") if s.strip()]
    if skills_req:
        mode = cond.get("skills_mode") or "any"
        matched = [s for s in skills_req if s.strip().lower() in [x.lower() for x in (c.get("skills") or [])]]
        ok = (len(matched) == len(skills_req)) if mode == "all" else (len(matched) > 0)
        details.append({"key": "skills", "label": "技能关键词", "ok": ok,
                        "expect": ("全部满足" if mode == "all" else "任一满足") + "：" + ",".join(skills_req),
                        "actual": ("命中：" + ",".join(matched)) if matched else "未命中"})
        all_ok = all_ok and ok

    return all_ok, details


def _score_soft(c, cond, weights, strict=False):
    """返回 (score, score_detail)，归一化到 100 分制。

    归一化口径（关键，勿改回全量分母）：
      - 只对「实际识别到信息的维度」做归一化，未识别的维度不计入分母，
        避免"简历没写院校/没写公司"被当成"院校差/不稳定"而把总分稀释到 reject。
      - strict=True 时退回全量分母（未识别=0分），用于需要保守打分的场景。
    """
    items = []  # (key, label, pts, base, reason, recognized)

    def add(key, label, pts, base, reason, recognized=True):
        items.append((key, label, pts, base, reason, recognized))

    min_years = int(cond.get("min_years") or 0)
    y = c.get("work_years") or 0
    if min_years:
        if y:
            ratio = min(1.0, y / (min_years + 2))
            add("years", "工作年限", 1, ratio * 50, f"{y}年 / 要求{min_years}年")
        else:
            add("years", "工作年限", 0, 0, "未识别年限", False)

    if c.get("top_school"):
        add("school", "985/211 院校", 1, 45, c.get("school", "") or "顶尖院校")
    elif c.get("school"):
        add("school", "院校层次", 0, 30, c.get("school", ""))

    if c.get("has_management"):
        add("management", "团队管理经验", 1, 40, "有管理/带团队描述")

    changes = c.get("job_changes") or 0
    if changes == 0:
        # 未识别到工作经历段数：信息缺失，不奖不罚（strict 模式下才计 0 分）
        add("stability", "稳定性", 0, 0, "未识别工作经历", False)
    elif changes <= 2:
        add("stability", "稳定性", 1, 45, f"{changes}段经历，较稳定")
    else:
        add("stability", "稳定性", 0, 15, f"{changes}段经历，跳槽较频繁")

    req = [s for s in (cond.get("skills") or "").split(",") if s.strip()]
    skills = c.get("skills") or []
    if req:
        hit = sum(1 for s in req if s.strip().lower() in [x.lower() for x in skills])
        # 满分线取 min(要求数, 3)：词典越长不应越难拿分（技能是"或"关系而非"全都要会"）
        expect = min(len(req), 3) or 1
        ratio = min(1.0, hit / expect)
        add("skills", "技能命中", 1, round(50 * ratio),
            f"命中 {hit}/{len(req)}（满分线 {expect}）")

    participated = [it for it in items if it[5] or strict]
    total_w = sum(weights.get(it[0], 0) for it in participated) or 1
    score, detail = 0.0, []
    for key, label, pts, base, reason, recognized in items:
        w = weights.get(key, 0)
        active = recognized or strict
        part = round(base * w / 50 / total_w * 100, 1) if active else 0.0
        score += part
        detail.append({"key": key, "label": label, "points": pts, "weight": w,
                       "part": part, "reason": reason,
                       "recognized": recognized})
    score = round(min(100, score))
    return score, detail


def screen_resume(text: str, role: str = "", hard_cond: dict = None,
                  weights: dict = None, pass_threshold: int = 80,
                  maybe_threshold: int = 60, strict: bool = False) -> dict:
    """端到端规则初筛。返回 {bucket, score, hard_pass, hard_detail, score_detail, fields}。

    strict=False（默认）：未识别维度不计入分母——信息缺失不惩罚，需人工看 fields 完整度。
    strict=True：未识别按 0 分计入全量分母——保守口径，信息不全者得分偏低。
    """
    fields = parse_resume_text(text)
    cond = hard_cond or {}
    if role and role in SKILL_LEXICON:
        # 用岗位词典补充技能要求（若硬条件未显式给）
        if not cond.get("skills"):
            cond = dict(cond)
            cond["skills"] = ",".join(SKILL_LEXICON[role])
    weights = weights or {"years": 20, "school": 12, "management": 14,
                          "stability": 12, "skills": 20}
    hard_ok, hard_detail = _check_hard(fields, cond)
    score, score_detail = _score_soft(fields, cond, weights, strict=strict)
    if not hard_ok:
        bucket = "reject"
    elif score >= pass_threshold:
        bucket = "pass"
    elif score >= maybe_threshold:
        bucket = "maybe"
    else:
        bucket = "reject"
    return {"bucket": bucket, "score": score, "hard_pass": hard_ok,
            "hard_detail": hard_detail, "score_detail": score_detail, "fields": fields}


def serialize(d):
    return json.dumps(d, ensure_ascii=False)
