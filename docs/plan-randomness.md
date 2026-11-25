# Plan：开发迭代中的随机性（单次结果当事实）

## 目标

lmreview 的迭代流程里，有几处凭一次运行做决定。把这几处改成"边界情况才多跑"。额外成本按样本算（一次审阅约 $0.5–0.8）；参考：round 6212（2 个样本）$8.24，一次 compress vet $11–25。

**范围（2026-11-25 决定）：只做 D → B → C。A、E 先不做**（用户决定不专门测泛化性；E 还会改动 split）。

```
round:  review(train) ─► judge ─► [C 确认 miss] ─► distill ─► vet ─► [B 序贯检验] ─► promote
                                                                         │
A/B:    review(test) vN vs vN+1 ─► compare ─► [A 翻转复核] ─► 接受/回滚   │
上线:   [E holdout，只用一次]                                              │
底座:   [D 运行记录：rep 编号 + 模型版本 + 命中统计]  ◄────────────────────┘ 所有步骤都写入/复用
```

原则：
- 只在决策点加跑。两次结果一致就停，不一致才补跑。
- 所有运行都缓存、都复用，绝不为同一个（reviewer, sample, rep）付两次钱。
- 每个新步骤都受 `--max-cost` 约束，`--max-cost 0` 只打印计划。

实施顺序：D → B → C。D 是其余几项的基础。

---

## D. 运行记录（底座，不花钱）

现状：runs 缓存在 `data/runs/<reviewer>[#rK]/`（见 `vet.py:run_dir`），按 reviewer 名字缓存。`llm.py` 里 model 默认是 `"default"`，Claude Code 升级后底层模型可能悄悄换掉，但缓存仍会命中。

要做：
1. **把 rep 编号做成通用功能**：从 `vet.py` 抽一个公用的 `run_dir(reviewer, k)`。`replay.py:run_path` / `replay()` 支持 `rep=k`，`score.judge_runs` 能判分 `#rK` 的运行。
2. **记录真实模型**：把 `claude -p` 结果里实际用到的模型 id（`modelUsage` 的 key）写进每个 run json 的 `model` 字段。读缓存时，如果和当前模型不一致，视为未缓存，并打一行 warn。旧 run 没有这个字段的，按"未知"处理，照常命中，但在报告里标出来。
3. **命中统计**：新增函数 `hits(reviewer_base, sample, comment) -> (hit, n)`，汇总该 reviewer 所有 rep 的判分结果，不花钱。B、C、A 都通过它取数。
4. 新增 CLI `lmreview stability --reviewer R`：列出 n≥2 的评论，以及 hit/n 的分布（0、0<p<1、1 各有多少）。这是"p 分布"的免费测量，随轮次自然积累。

验收：同一个 sample 跑 `#r2` 能判分并进入 hits；手动改 run json 的 `model` 后不再命中缓存。

## C. distill 前确认 miss（约 $8/轮）

位置：`state.round_`，在 `judge(...)` 之后、distill 循环之前。

要做：
1. 本轮新出现的 `to_distill` 评论按 sample 分组，对这些 sample 用同一个 reviewer 跑 `#r2`，再判分（复用 D）。
2. 某条评论在 r2 里被抓到：记 `hits="1/2"` 并标 `flaky`，**照样送 distill**（时有时无正是规则能稳定住的地方），
   排在两次都漏的评论后面。两次都漏的保持 `to_distill`、不标。C 的主要产出是 flaky 的比例。
4. 加一个预算项 `[budget.round] confirm`（默认 10），受 `--max-cost` 约束。超出预算时，没确认的 miss 照常送 distill，并在输出里标出"未确认"。
5. 在 round 输出和 log 里记一行：`confirm: N misses, K flaky, $X`。

验收：在一个已有的 round 样本上 dry-run，计划里显示需要复跑的 sample 数和估价；真跑一次后，ledger 里有评论带 `flaky` 标记、仍是 `to_distill`。

## B. vet 的序贯检验（约 $2–3/轮）

现状（`vet.py`）：失败的 case 用 NEW 再跑一次（`retry`），两边都漏的 case 再跑一次 BASE。但 effect case 跑一次 "fires" 就算有效，这正是会把运气好的规则收进来的地方。

要做：
1. effect case 第一次通过后，用 NEW 再跑 `#r2`。2/2 算有效；1/2 再补 2 次，累计 ≥3/4 才算有效；否则算 not working，原因写进 tries。
2. side effect 也用同一套逻辑（compress 的决定全出在这里：2026-11-25 trim 退回 5 条、merge 撤销 7 组）：
   LOST 要求 NEW 0/2 且 BASE ≥1/2；NEW 1/2 再补跑，累计 ≥2/3 算 kept。"kept" 和 "lost" 都读 `hits()`，
   多次 rep 的结果都算进去。注意：merge 的丢失重跑后没减少（13→13），B 减少误判，但不会让 merge 通过。
3. effect 的 base 对照：报告里 `base not run` 的地方，改为引用 C 的结果（这条评论在 baseline 上 0/2）。不额外花钱跑 base。
4. 报告第 2 节每条显示 `NEW 2/2`、`NEW 3/4` 这样的计数，不再只写 fires。
5. 估价 `est` 把这些额外 rep 算进去，`--max-cost` 照常封顶，不够就 INCOMPLETE。

验收：在一次已有的 vet 候选上（比如 v0031c1）重跑，第 2 节出现计数；之前 1/1 的 case 有一部分变成 1/2 → 补跑。

## A. A/B 翻转复核（约 $3–5/轮）——暂不做

位置：`compare.py`（现在完全免费，只读判分结果），以及 `lmreview eval --vs`。

要做：
1. 新增 `confirm_flips(a, b, max_cost)`：对每个 `fixed` / `broken` 翻转所在的 sample，A 和 B 各补跑一次 `#r2` 并判分（已缓存就跳过）。
2. 用 `hits()` 合并两次运行的结果重新分类：B 2/2、A 0/2 才算 confirmed fixed；B 2/2、A 1/2 或 B 1/2、A 0/2 算 weak；其余归为 `noise`。broken 对称处理。
3. 报告新增一节：`confirmed net = confirmed fixed − confirmed broken`，并列出 noise。**接受新版本改为看 confirmed net > 0**。同步修改 `docs/mechanism.md` 第 5 步的措辞。
4. CLI：`lmreview eval --reviewer B --vs A --confirm-flips [--max-cost N]`，默认开启，`--no-confirm-flips` 关掉。

验收：在一对已有的 A/B 上（找一个现成的 `compare_*_vs_*.md`）跑，报告里有 confirmed / noise 两节，花费和翻转数量对得上。

## E. holdout split（不花钱）——暂不做

现状：mechanism.md 说 holdout 只在上线门槛用一次，但 `sync.py` 只有 train / test / new 三个 split，代码里没有 holdout。

要做：
1. `sync.py` 从 test 中按 PR 号哈希稳定地划出约 1/3 作为 `holdout`，跨 sync 保持不变，新 PR 进入时也按同样规则划分。注意：划走的这部分以后不再出现在 test 里，test 历史报告的样本集会变，在报告里注明。
2. 加守卫：`distill`、`judge`（已经只允许 train）、`vet`、`compare`、`eval --rules` 在 holdout 上一律报错。只有新命令 `lmreview gate --reviewer R` 能用 holdout，并且每次使用都写进 `log.jsonl`。重复使用时 warn："holdout 已被看过 N 次"。
3. `lmreview gate` 输出 holdout 上可学的 human 独有率，同样带 A 的翻转复核逻辑。

验收：对 holdout 调 distill/vet 时报错；`gate` 能跑，并写一条 log。

---

## 约束

- 测试时用 `--max-cost 0`（只看计划）或很小的上限。真花钱的端到端验证只跑一轮，总上限 $20，跑之前先报告估价。
- 不往 GitHub 发任何东西，不开 PR，不 push。commit 不加 Claude 署名（不要 Co-Authored-By）。
- 每一项单独 commit，附带单测（不花钱的部分：hits 汇总、状态机、翻转分类、split 稳定性、守卫）。
- 改动 `LEDGER`、`STATUSES`、报告格式时，同步更新 `docs/mechanism.md`。文档保持简短。

## 完成后要汇报的

1. 一轮真实运行中，C / B / A 各自额外花了多少，和这里的估计（$8 / $2–3 / $3–5）对比。
2. 实测数据：多少 miss 被判为 flaky，多少 effect 从 1/1 变成没通过，多少 LOST 重跑后变成 kept。这三个数说明了"单次结果当事实"在我们这里到底有多严重。
3. `lmreview stability` 的 p 分布。
