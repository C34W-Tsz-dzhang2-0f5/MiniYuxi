"""将微信文章《33.6k Star！AI Agent 最强中文开源书》与结构化知识卡入库 MiniYuxi 知识库。

- 文档一：微信文章原文（正文萃取）
- 文档二：结构化知识卡（核心观点 / 方法论 / 关键知识），便于"Agent 怎么定义""Coding Agent 是什么"等检索命中

用法：python ingest_article_kb.py
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core import rag  # noqa: E402

TENANT = "default"
ARTICLE_URL = "https://mp.weixin.qq.com/s/SMZ4j7OYErYkiHcSDAsxIg"

ARTICLE_TEXT = """\
标题：33.6k Star！AI Agent 最强中文开源书，10 章从入门到工程化
作者/来源：原创 Chyris Tech Note，2026-08-10（北京）
在线阅读：https://bojieli.github.io/ai-agent-book/ （作者：李博杰 / Bojieli）

一句话总结：这本书不适合当睡前读物，适合当一张 AI Agent 学习地图。

核心公式：Agent = LLM + 上下文 + 工具。全书十章就围着这个公式打转。
前半部分解决 Agent 怎么听得懂、记得住（上下文工程、用户记忆与知识库），
后半部分上硬菜：MCP、Coding Agent、多 Agent 协作。基本覆盖从玩具到工程化的全部关卡。

书籍数据：33.6k Star、3.6k Fork、13 种语言版本。作者李博杰对 Agent 的定义即
Agent = LLM + 上下文 + 工具。它不像普通博客只讲概念，直接给了一套完整学习路线：
10 章正文 + 95 个配套实验，每章都有可运行代码。

10 章目录（全书结构）：
1. Agent 基础知识
2. 上下文工程（KV Cache、提示工程、Agent Skills、上下文压缩）
3. 用户记忆和知识库（用户记忆、RAG、结构化索引、知识图谱）
4. 工具（MCP 协议、感知/执行/协作三类工具、异步/事件驱动 Agent）
5. Coding Agent 与通用 Agent（生产级 Coding Agent 全景，"代码是能创造新工具的工具"）
6. 交互：观察与动作空间的扩展（语音 Agent、Computer Use、机器人操作）
7. Agent 的评估（评估环境、指标、统计显著性）
8. 模型后训练（SFT、强化学习）
9. Agent 的持续进化（从学习信号到知识/指令/程序/参数更新）
10. 多 Agent 协作（协作架构、失败模式、Agent 社会）

重点章节：第 4 章讲工具（MCP 协议、Coding Agent、事件驱动异步 Agent）；
第 5 章讲 Coding Agent，观点是"代码是能创造新工具的工具"——Coding Agent 最性感的地方，
就是让代码自己长出新工具。

运行方式：代码按章节组织，安装给 uv 与 pip 两条路；按章节 README 配置模型 Key 即可跑实验。
"""

KNOWLEDGE_CARD = """\
知识卡：李博杰《深入理解 AI Agent》核心方法论（MiniYuxi 知识库萃取）

【核心观点】
1. Agent = LLM + 上下文 + 工具：LLM 提供推理，上下文决定能力上限，工具让 Agent 能动手。
2. Harness 工程才是竞争力：包住模型的工程层（上下文编排、工具调度、记忆、评估）才是差异化来源。
3. 代码是「能创造新工具的工具」：Coding Agent 让 Agent 自己长出新能力（第 5 章核心论点）。
4. 把表现变成可比较信号：没有评估就没有迭代（第 7 章）。
5. 从可靠学习信号到知识/指令/程序/参数更新：Agent 的持续进化闭环（第 8、9 章）。
6. 多 Agent 协作是架构问题：协作模式、失败模式、Agent 社会治理（第 10 章）。

【方法论（10 章）】
上下文工程（Ch2）：KV Cache 友好、提示工程、Agent Skills、上下文压缩。
用户记忆与知识库（Ch3）：用户记忆、RAG、结构化索引、知识图谱。
工具（Ch4）：MCP 协议、感知/执行/协作三类工具、异步/事件驱动 Agent。
Coding Agent（Ch5）：生产级 Coding Agent 全景；代码创造新工具。
交互扩展（Ch6）：观察/动作空间扩展、语音、Computer Use。
评估（Ch7）：评估环境、指标、统计显著性。
模型后训练（Ch8）：SFT、强化学习。
持续进化（Ch9）：学习信号 → 知识/指令/程序/参数更新。
多 Agent 协作（Ch10）：协作架构与失败模式。

【关键知识 / 可落地要点】
- 工具三层分类：感知工具（读取世界）、执行工具（改变世界）、协作工具（调用其他 Agent）。
- 上下文是天花板：KV Cache 利用率、提示结构、Skills 注入、上下文压缩直接决定能力边界。
- 知识库三件套：用户记忆 + RAG 检索 + 结构化索引/知识图谱。
- MCP 是工具标准协议，统一工具接入方式，让 Agent 可插拔连接外部系统。
- Coding Agent 闭环：LLM 写代码 → 代码注册为新工具 → Agent 可调用 → 能力自增长。
- 评估先于优化：先有可比较信号与统计显著性，再做参数/提示/架构迭代。

【Coding Agent 定义】Coding Agent 不只是写代码，而是让 Agent 在运行时自我扩展工具能力：
自然语言需求 → 生成代码 → 安全校验 → 注册为可被 Agent 调用的工具。这正是 MiniYuxi
core/coding_agent.py「自生成工具工厂」所落地的能力。
"""


def main():
    a = rag.add_document(TENANT, "微信文章：33.6k Star！AI Agent 最强中文开源书", ARTICLE_TEXT, ARTICLE_URL)
    print("文章入库：", a)
    k = rag.add_document(TENANT, "知识卡：李博杰《深入理解 AI Agent》核心方法论", KNOWLEDGE_CARD,
                         "本机知识摘要《知识库_李博杰AI_Agent书_知识摘要.md》")
    print("知识卡入库：", k)

    for q in ("Agent 等于 LLM 加上下文加工具", "Coding Agent 是什么", "工具分哪三类",
              "什么是 Agent 的上下文工程"):
        hits = rag.search(TENANT, q, 3)
        print(f"\n检索「{q}」命中 {len(hits)} 条：")
        for h in hits:
            print(f"  - [{h['title']}] score={h['score']} :: {h['text'][:48].replace(chr(10),' ')}")


if __name__ == "__main__":
    main()
