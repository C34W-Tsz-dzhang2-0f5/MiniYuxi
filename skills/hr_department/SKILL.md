---
name: hr-department
description: 基于三维验证式技能萃取法，系统化构建可执行专业能力；支持T型知识结构定义、多维度提取、三重验证筛选、技能卡片构造、知识链接与自测验证。当用户需要创建职业专家能力库、构建领域专业视角或生成标准化可执行技能时使用此工具即可
dependency:
  python:
    - pypdf==3.17.4
    - python-docx==1.1.0
    - PyYAML==6.0.1
    - markdown==3.5.2
---

# 可执行专业能力构建器

## 核心理念

Artisan 不是生成文档，是**萃取可执行技能**。

一个好的专业能力构建器产出的是一套**可立即执行的技能卡片库**：
- 他能用什么**原子化技能**解决问题？（一个卡片一个方法）
- 他**何时**使用这个技能？（明确的Trigger触发条件）
- 他**如何**执行这个技能？（1-2-3具体步骤）
- 他**什么情况**不应该使用？（清晰的Boundary边界）
- 他如何**验证**掌握程度？（自测问题验证）

**关键区分**：萃取的是可执行的专业技能，不是知识的堆砌框架。

**三维验证式技能萃取法**：
- V1 跨域验证：至少2个独立来源佐证
- V2 预测力验证：能解决实际工作问题
- V3 独特性验证：不是常识，有独特洞见

### 职业身份 vs 人物身份

| 维度 | 人物 Skill（女娲） | 职业专家 Skill（Artisan） |
|------|------------------|------------------------|
| 蒸馏对象 | 具体个人的思维框架 | 职业身份的专业视角 |
| 知识来源 | 个人著作、访谈、演讲 | 专业文献、法规、案例、标准 |
| 思维框架 | 个人独创的心智模型 | 职业共识方法论 + 行业实践 |
| 表达风格 | 模仿个人的语言特征 | 遵循职业表达规范 |
| 可验证性 | 对比个人公开表态 | 对比行业标准和专业共识 |
| 时效性 | 需跟踪个人最新动态 | 更新专业法规和行业实践 |

---

## 任务目标
- 本 Skill 用于：系统化构建专业专家能力，蒸馏为可执行技能卡片库
- 能力包含：
  - 专家身份定义（T型知识结构）
  - 多维度并行提取（6个维度）
  - 三重验证筛选（V1跨域/V2预测力/V3独特性）
  - 知行合一技能卡片构造（R/I/A1/A2/E/B六段结构）
  - 知识链接与索引
  - 自测与验证
- 触发条件：用户请求创建职业专家能力库、构建领域专业视角或生成标准化可执行技能

## 前置准备
- 依赖说明：scripts依赖pypdf、python-docx、PyYAML、markdown
- 用户准备：
  - 明确职业身份（如"刑法律师"、"产品经理"）
  - 可选：上传私有知识文件（PDF/Word/Markdown）
  - 可选：提供应用场景偏好（如"合同审查"、"需求分析"）

## 操作步骤

### 阶段0: 专家身份定义（T型知识结构）
- 主领域定义：核心领域、核心概念、理论框架、行业标准
- 辅助领域定义：辅助领域、权重分配、融合点
- 知识融合策略：融合方法、冲突处理、跨领域框架
- 输出：EXPERT_OVERVIEW.md
- 【用户确认节点1】确认专家身份定义

### 阶段1: 多维度并行提取
并行提取6个维度：
- 维度1: 学科基础（核心概念、理论框架、基本原理）
- 维度2: 法规规范（法律法规、行业标准、政策文件）
- 维度3: 方法论（分析框架、决策流程、思维模型）
- 维度4: 典型案例（成功案例、失败案例、行业数据）
- 维度5: 行业实践（实务技巧、行业惯例、最佳实践）
- 维度6: 表达规范（专业术语、文书格式、沟通风格）

用户私有知识处理：
- 调用 `python scripts/parse_document.py --file_path <路径>` 解析文件
- 将内容归入对应维度

提取标准：
- 必须标注来源（文献、法规、案例等）
- 必须用自己的话重写（避免照搬）
- 必须保留原文引用（≤150字/段）

输出：candidates/*.md

### 阶段1.5: 三重验证筛选（核心）
对每个提取的内容单元执行三重验证：

**V1 跨域验证**：
- ✅ 通过：2个及以上独立来源提及或佐证
- ⚠️ 待确认：只有1个来源提及
- ❌ 不通过：无明确出处或仅提及一次

**V2 预测力验证**：
- ✅ 通过：能解决至少1个实际工作问题
- ⚠️ 待确认：只能解释理论，无法解决实际问题
- ❌ 不通过：无法迁移到实际场景

**V3 独特性验证**：
- ✅ 通过：有独特洞见或反常识观点
- ⚠️ 待确认：有一定深度但不够独特
- ❌ 不通过：纯属常识或陈词滥调

验证结果处理：
- 3个✅ → 进入阶段2，标记为"核心技能"
- 2个✅ + 1个⚠️ → 进入阶段2，标记为"辅助技能"
- 其他组合 → 写入rejected/，附原因

输出：skills/pending/ + rejected/

【用户确认节点2】确认重点方向

### 阶段2: 知行合一技能卡片构造
对通过验证的内容，构造独立技能卡片：

**六段结构**：
- **R (Reading) 核心原理**：原文引用（≤150字）+ 来源
- **I (Interpretation) 方法论解读**：用自己的话重写
- **A1 (Past Application) 行业案例**：实际应用案例
- **A2 (Future Trigger) 触发条件**：何时使用（至少2个情境）
- **E (Execution) 执行步骤**：1-2-3具体可执行步骤
- **B (Boundary) 边界条件**：不适用场景（至少2个）

输出：skills/skill-XXX.md

【用户确认节点3】确认可执行性

### 阶段3: 知识链接与索引
建立技能卡片之间的链接关系：
- 依赖关系：A技能需要先掌握B技能
- 对比关系：A技能与B技能适用场景不同
- 组合关系：A技能 + B技能产生协同
- 递进关系：A技能是B技能的高级版

输出：INDEX.md

### 阶段4: 自测与验证
为每个技能卡片设计自测问题：
- 应该使用此方法的场景（2题）
- 不应该使用此方法的场景（2题）
- 边界场景（1题）

输出：tests/*.md

## 输出结构

```
expert-skills/
├── EXPERT_OVERVIEW.md      # 阶段0：专家概览
├── INDEX.md                 # 阶段3：技能索引
├── CHANGELOG.md            # 版本变更记录
├── candidates/             # 阶段1：原始提取池
│   ├── discipline-foundation.md
│   ├── regulations.md
│   ├── methodologies.md
│   ├── cases.md
│   ├── industry-practices.md
│   └── expression-norms.md
├── rejected/               # 阶段1.5：未通过验证
│   ├── rejected-items.md
│   └── reasons.md
├── skills/                 # 阶段2：技能卡片库
│   ├── skill-001-[名称].md
│   ├── skill-002-[名称].md
│   └── ...
└── tests/                  # 阶段4：自测题库
    ├── self-tests.md
    └── scenarios.md
```

## 质量红线

违反以下任一红线将阻止输出：

| 红线 | 标准 | 违反处理 |
|------|------|----------|
| 原文引用超限 | >150字/段 | 阻止输出，要求精简 |
| 缺少Trigger | A2字段为空 | 阻止输出，要求补充 |
| 缺少Boundary | B字段为空 | 阻止输出，要求补充 |
| 执行步骤空泛 | 不是1-2-3具体步骤 | 阻止输出，要求细化 |
| 未通过验证 | 三重验证<2个✅ | 降级为辅助技能或淘汰 |
| 缺少自测问题 | 无自测问题 | 阻止输出，要求补充 |
| 缺少原文引用 | 无出处标注 | 阻止输出，要求补充 |
| 跳过用户确认 | 未获得确认继续 | 阻止输出，要求确认 |

## 使用示例

### 示例1: 创建完整专家能力库
- 场景/输入: "创建一个刑法律师的专业能力库"
- 预期产出: 生成专家概览 + 技能卡片库 + 自测题库
- 关键要点:
  - 阶段0: 定义主领域（刑法）+ 辅助领域（刑诉法、证据法）
  - 阶段1: 并行提取6个维度
  - 阶段1.5: 三重验证筛选，保留核心技能
  - 阶段2: 构造知行合一技能卡片（每个卡片都有Trigger和Boundary）
  - 阶段3: 建立技能链接索引
  - 阶段4: 生成自测问题

### 示例2: 互联网领域专家
- 场景/输入: "创建一个B端产品经理的专业能力库"
- 预期产出: 生成包含需求分析、业务架构、产品规划的技能卡片库
- 关键要点:
  - 参考[互联网行业专项指南](references/internet-industry-guide.md)
  - 重点提取：需求分析方法论、PRD规范、产品规划流程
  - 每个技能卡片都有明确的Trigger（何时使用）和Boundary（不适用场景）
  - 提供1-2-3可执行步骤

### 示例3: 跨学科专家（T型知识结构）
- 场景/输入: "创建一个智慧城市解决方案专家的能力库"
- 预期产出: 生成融合城市规划、技术和人文视角的技能卡片库
- 关键要点:
  - T型知识结构：城市规划（70%）+ 计算机科学（15%）+ 数据科学（10%）+ 社会学（5%）
  - 识别融合点：城市数据、智能交通、社会公平
  - 为跨领域技能卡片设计自测问题

### 示例4: 快速模式（跳过验证）
- 场景/输入: "快速生成一个数据分析师的能力库"
- 预期产出: 生成基础的技能卡片库
- 关键要点:
  - 跳过阶段1（多维度提取）
  - 跳过阶段1.5（三重验证）
  - 直接构造技能卡片
  - 适用于时间紧迫或内容简单的场景

## 脚本调用说明

### 执行三重验证
```bash
python scripts/verify_content.py \
  --input_dir "/workspace/projects/expert-skills/candidates" \
  --output_dir "/workspace/projects/expert-skills/skills/pending" \
  --rejected_dir "/workspace/projects/expert-skills/rejected"
```

### 生成技能卡片
```bash
python scripts/generate_skill.py \
  --expert_name "刑法律师" \
  --expert_overview "/workspace/projects/expert-skills/EXPERT_OVERVIEW.md" \
  --verified_skills "/workspace/projects/expert-skills/skills/pending" \
  --output_dir "/workspace/projects/expert-skills/skills"
```

### 生成自测问题
```bash
python scripts/generate_self_tests.py \
  --skills_dir "/workspace/projects/expert-skills/skills" \
  --output_dir "/workspace/projects/expert-skills/tests"
```

### 质量验证
```bash
python scripts/validate_structure.py \
  --skill_path "/workspace/projects/expert-skills"
```

## 用户确认节点话术

### 节点1: 专家身份定义确认
```
总裁，专家身份定义已完成！

【核心内容】
- 主领域：刑法
- 辅助领域：刑事诉讼法（权重20%）、证据法（权重15%）
- 知识融合策略：以刑法为核心，辅以程序法视角

请确认：
[ ] 定义准确，继续下一步
[ ] 需要修改（请指出）
```

### 节点2: 重点方向确认
```
总裁，内容提取和验证完成！

【提取结果】
- 通过验证：15个技能点
- 未通过：3个（已存档rejected/）

【重点方向】
- 核心技能：犯罪构成分析（3个✅）、量刑方法（3个✅）
- 辅助技能：证据规则审查（2个✅+1个⚠️）

请确认：
[ ] 方向正确，继续制作技能卡片
[ ] 需要调整（请说明）
```

### 节点3: 可执行性确认
```
总裁，技能卡片已完成！

【完成情况】
- 技能卡片：15个
- 自测问题：45道

【示例卡片】
[展示一个完整的技能卡片]

请确认：
[ ] 可执行性强，可以输出
[ ] 需要改进（请说明）
```

## 资源索引

### 脚本
- [scripts/verify_content.py](scripts/verify_content.py)（用途：执行三重验证（V1跨域/V2预测力/V3独特性），支持自动验证和交互式验证）
- [scripts/generate_self_tests.py](scripts/generate_self_tests.py)（用途：为技能卡片生成针对性自测问题，评估掌握程度和盲点）
- [scripts/generate_skill.py](scripts/generate_skill.py)（用途：生成技能卡片库，包括专家概览、技能卡片和自测题库）
- [scripts/parse_document.py](scripts/parse_document.py)（用途：解析用户上传的PDF/Word/Markdown文件）
- [scripts/validate_structure.py](scripts/validate_structure.py)（用途：验证Skill结构完整性）
- [scripts/refine_skill.py](scripts/refine_skill.py)（用途：生成评审模板和优化建议）
- [scripts/validate_skill_quality.py](scripts/validate_skill_quality.py)（用途：验证专家Skill质量指标）

### 参考
- [references/extraction-methodology.md](references/extraction-methodology.md)（何时读取：阶段1-3执行三维验证式技能萃取时）
- [references/profession-taxonomy.md](references/profession-taxonomy.md)（何时读取：阶段0识别职业身份层级时）
- [references/cross-disciplinary-guide.md](references/cross-disciplinary-guide.md)（何时读取：创建跨学科专家时）
- [references/knowledge-fusion-methods.md](references/knowledge-fusion-methods.md)（何时读取：阶段2知识融合时）
- [references/internet-industry-guide.md](references/internet-industry-guide.md)（何时读取：创建互联网领域专家时）
- [references/skill-template.md](references/skill-template.md)（何时读取：阶段2提炼框架结构时）
- [references/collection-dimensions.md](references/collection-dimensions.md)（何时读取：阶段1执行六维度采集时）
- [references/refinement-workflow.md](references/refinement-workflow.md)（何时读取：阶段4执行双Agent精炼时）

### 资产（模板）
- [templates/skill-card-template.md](templates/skill-card-template.md)（用途：生成知行合一技能卡片，包含R/I/A1/A2/E/B六段结构）
- [templates/self-test-template.md](templates/self-test-template.md)（用途：生成自测问题，评估技能掌握程度）
- [templates/verification-record-template.md](templates/verification-record-template.md)（用途：记录三重验证过程和结果）

## 注意事项
- 仅在需要时读取参考文档，保持上下文简洁
- 3个用户确认节点（阶段0之后、阶段1.5、阶段2.5）必须等待用户确认后才能继续
- 质量红线必须严格遵守：原文引用≤150字、必须有Trigger和Boundary、必须有自测问题
- 用户私有知识优先级最高，应覆盖公开知识
- 充分利用智能体的网络搜索和内容理解能力，避免为简单任务编写脚本
- 三重验证通过率应≥60%，低于此标准需重新萃取
- 保留candidates/和rejected/目录，形成审计轨迹，便于追溯决策过程
