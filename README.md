# 跨国中文教师实践安排与在岗支持服务

服务于国际中文教育学院学员分赴东盟合作学校的实践安排与在岗支持，覆盖：
合作点/导师/课程场景/能力要求/不可用时段的统一维护、可解释候选安排生成、
学校/导师/学院三方确认、变更触发的重新评估、分级事件案件管理，以及每日汇总。

## 领域规则

- **硬约束（不可作为候选）**：窗口不在校历内；学员语言达不到场景或导师要求；
  导师/学员在窗口内有不可用时段；导师容量在重叠窗口内将被重复占用；
  同一学员同时落入两个重叠窗口。
- **可解释打分**：能力补齐权重最高（培养目标），导师负荷率与重复同导师/同学校
  扣分（公平轮换）；每个候选附逐条算分说明与全部不可行原因。
- **三方确认**：合作学校、导师、学院实践办公室逐一确认后安排才成立，方可出发。
- **变更重评估**：任何一方修订资料（版本号递增）都会重评受影响人员；
  未开始且出现冲突的安排转入“待重新评估”，冲突消除自动回到待确认。
- **已开始不静默改派**：进行中的实践遇变更只追加变更提示；改派必须显式
  “立新替旧”，旧安排保留 `已被新方案替代` 与关联编号。
- **事件案件**：请假/教学事故/安全事件按级别限定可见范围；合作学校可用
  `ReportScope` 自行扩大某级别以上事件的上报对象。同人同类同期重复上报只留
  一个案件（并案、计数、可提级）。教学事故与安全事件必须处置 + 复盘才能办结。
- **可控时钟**：逾期升级只由时钟推进触发（请假 3 天、MEDIUM 2 天、HIGH 1 天、
  安全 12 小时），升级扩大可见范围；待复盘案件不再按受理时限升级。
- **每日汇总**：仍有冲突的安排、等待哪一方确认、每名学员的能力覆盖、
  中断恢复后尚未办结的事件。

## 代码结构

```
src/teacher_practicum/
  contracts.py    基础版本化契约（既有）
  clock.py        可控时钟
  domain.py       合作点/导师/学员/场景/能力/窗口/上报范围
  scheduler.py    硬约束、候选评分、安排状态机、全量冲突扫描、重评估
  service.py      应用服务：注册修订、生成安排、确认、改派、重评估
  incidents.py    事件案件：分级可见、并案、升级、处置复盘
  reporting.py    每日汇总
  storage.py      JSON 快照（含时钟），支持中断恢复
  fixtures.py     曼谷/河内情景数据
```

## 运行

```bash
python -m unittest discover -s tests -v     # 38 项测试
python -m compileall -q src tests run_cli.py
python run_cli.py smoke                     # 基础契约冒烟
python run_cli.py demo                      # 端到端情景演示

python run_cli.py --data state.json init
python run_cli.py --data state.json plan --trainee T03
python run_cli.py --data state.json propose --trainee T03
python run_cli.py --data state.json confirm AS-0005 --party 合作学校
python run_cli.py --data state.json incident --trainee T03 \
    --kind 安全事件 --level SAFETY --title 通勤意外 --date 2026-11-20 --site HAN
python run_cli.py --data state.json tick --days 3
python run_cli.py --data state.json daily
```
