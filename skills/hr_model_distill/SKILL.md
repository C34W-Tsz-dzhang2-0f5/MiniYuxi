---
name: hr-model-distill
description: 为 HR / 北森（Beisen）等人力资源业务场景编写知识蒸馏（Knowledge Distillation）代码，将大型教师模型能力迁移到轻量学生模型，支持边缘 / 本地轻量化部署。当用户需要模型压缩、蒸馏损失实现、teacher-student 训练流程、北森模型轻量化时使用。
---

# HR / 北森场景 · 模型轻量化知识蒸馏

## 触发场景
- 用户要求为北森 / HR SaaS / 招聘 / 人才测评场景做「模型轻量化」「知识蒸馏」「teacher-student 蒸馏」「压缩部署」。
- 需要把云端大模型（教师）能力迁移到边缘 / 本地小模型（学生）。

## 业务映射
- **教师来源**：北森 iTalentX 云端大模型（岗位匹配 / 人才测评 / 招聘意图识别）。演示中用一个较大的 MLP 预训练得到高精度教师；生产可直接 `teacher.load_state_dict(torch.load("beisen_teacher.pt"))`。
- **学生结构**：轻量 MLP（2 层隐藏），用于本地 / 移动端低延迟部署。
- **任务示例**：候选人-岗位匹配意图分类（研发 / 销售 / 产品 / 职能 / 运营）。

## 核心实现要点
1. **蒸馏损失（Hinton 经典形式，含温度 T）**：
   ```
   L = alpha * T^2 * KL( softmax(z_s/T) || softmax(z_t/T) )   # 软标签
     + (1 - alpha) * CE( softmax(z_s), y )                     # 硬标签
   ```
   - 实现：`F.kl_div(F.log_softmax(z_s/T,1), F.softmax(z_t/T,1), reduction="batchmean") * T*T`
   - 软标签乘 T² 抵消温度对梯度的缩放（Hinton 建议）。
2. **训练流程**：DataLoader 加载 → 教师前向（torch.no_grad 冻结）产软标签 → 学生前向 → 蒸馏损失 → backward → 优化器更新。教师参数全程冻结。
3. **超参默认值（可直接改）**：`T=4.0`, `alpha=0.7`（软标签权重）, `lr_teacher=1e-3`, `lr_student=2e-3`, `teacher_epochs=30`, `student_epochs=50`, `batch_size=64`。
4. **体现蒸馏增益**：务必设置「学生仅硬标签从零训练」的基线，对比蒸馏学生；在「数据稀缺 / 学生小容量」设定下增益最明显。

## 数据构造陷阱（已踩坑）
- 高维高斯聚簇 + 类中心同分布 → 标签近似随机，准确率 ~20%（=随机），演示失真。
- 修复：各类用不同方向中心（`centers = torch.randn(C, D)*scale`），train/test 共享中心保证同分布；注入 label_noise 模拟标注误差；缩小学生容量或训练样本量让硬标签基线欠拟合，蒸馏增益才可见。

## 参考实现
项目 `E:\HR有关AI\车务通招聘AI助手\beisen_kd_demo.py`（自包含、仅依赖 torch，可直接运行，输出教师/学生准确率、模型压缩比、蒸馏增益并保存学生权重）。

## 依赖与运行
- Python 3.13 + torch（本项目 venv2 已随 sentence_transformers 安装）。运行：
  `cd E:\HR有关AI\车务通招聘AI助手 && venv2\Scripts\python.exe beisen_kd_demo.py`

## 注意事项
- 温度 T 越大软标签越平滑、类间信息越丰富；T 过小则退化为硬标签。
- alpha 控制软/硬权重；教师标注有噪声时适当降低 alpha。
- 生产替换：TeacherModel 载入真实教师权重，StudentModel 替换为目标部署结构即可。
