# 跨国中文教师实践安排与在岗支持服务

面向国际中文教育学院实践办公室，统一维护合作点、导师、课程场景、能力要求与不可用时段，生成可解释的候选安排，驱动学校/导师/学院三方确认，并对请假、教学事故、安全事件做分级处置。

## 领域能力

- **主数据**：合作点（含校历窗口与敏感事件上报政策）、导师容量、课程场景（授课对象语言要求、覆盖能力）、学员画像（语言水平、培养目标、轮换历史）、不可用时段。
- **候选安排**：按培养目标增益与公平轮换打分，逐条给出理由；自动检测导师容量重复占用、语言水平不匹配、同一人落入重叠校历窗口、不可用时段冲突；未安排场景保留拒绝原因。
- **三方确认**：学校、导师、学院分别确认；任何一方数据变更仅触发受影响人员的重新评估，确认状态随之重置；已开始的实践禁止静默改派，显式改派须留痕并重新确认。
- **事件管理**：请假/教学事故/安全事件按级别限制可见范围，合作点可自定义上报范围；同学员同日同类重复上报归并为同一案件；处置-复盘-归档流转；逾期由可控制时钟触发自动升级。
- **每日汇总**：仍有冲突的安排、等待哪一方确认、每名学员能力覆盖、中断恢复后仍未办结的事件。

## 运行测试

    python3 -m unittest discover -s tests -v

## 编译检查

    python3 -m compileall -q src tests run_cli.py

## 命令行

    python3 run_cli.py                      # 内存演示全流程
    python3 run_cli.py seed                 # 演示数据写入状态文件
    python3 run_cli.py generate             # 生成候选安排（附理由）
    python3 run_cli.py confirm A-0001 school
    python3 run_cli.py start A-0001 && python3 run_cli.py complete A-0001
    python3 run_cli.py report --type safety --level high --trainee T-01 --by 导师 --desc "..."
    python3 run_cli.py tick --hours 30      # 推进可控制时钟，触发逾期升级
    python3 run_cli.py capacity M-BKK-2 1   # 调整导师容量（触发重新评估）
    python3 run_cli.py blackout mentor M-BKK-1 2026-11-10 2026-11-15 "外出培训"
    python3 run_cli.py summary              # 实践办公室每日汇总

状态默认保存在 `practicum_state.json`（可用 `--state` 指定），中断后重新运行命令即可恢复，未办结事件继续出现在汇总中。

## 代码结构

    src/teacher_practicum/
      models.py        合作点、导师、课程场景、学员、不可用时段
      scheduling.py    冲突检测与可解释候选生成
      arrangements.py  安排生命周期与三方确认
      incidents.py     事件分级、可见范围、案件流转
      service.py       服务门面：重新评估、改派保护、快照恢复
      reporting.py     每日汇总
      clock.py         可控制时钟
      demo.py          演示数据
