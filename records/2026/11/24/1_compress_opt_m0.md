# compress 优化 M0（2026-11-24 17:05 PT）

workfor 12h，截止 2026-11-25 05:03 PT。目标：v0027 上 vet 后词数 -25% 且丢失 case = 0；v0024 方向一致。
总预算默认 $100（用户 prompt 里 $X 未填）；每次实验 ≤ $8；5h 额度留 5%，7 天额度剩余 ≥ 30%。

## 背景（batch 8）
- compress 在 v0027（68 条、10158 词）上：3 份草稿各提 2/1/1 个 merge，多数票后剩 1 个
  （v0019c1-009 + v0023c1-003），vet 撤销：#4079 上 rule check "applies, not violated"——
  合并后的 "duplicate types" 让 reviewer 认为包装类型不算重复，丢了原条目的区分条件。

## 基线改动（e5e03c0）
- COMPRESS：先给整本书分组再逐组 merge；上限 50%→70%（SHRINK 0.75）；保留决定触发的条件和知识事实；
  undone 反馈带 rule check 的理由
- _consolidate(union=True)：不投票，取所有草稿 merge（重叠按草稿数、组大小取）
- compress_if_big：[compress] tries = 2，同一 round 再压一次
- compress_undone()：只读，供 round 和实验 harness 共用
- state: v0026/v0027（33f10a6）

## harness
scripts/compress_exp.py NAME [--base v0027] [--tries 2] [--compress-cost] [--vet-cost] [--note]
- compress() + 旧模式 vet(write=…)，结果在 lmreview/rules/<NAME>k*、data/compress_exp/<NAME>.json、results.md
- 运行前后 hash state/，变了就报错；dry-run 验证不变
- v0027：49 个不同的 proven target，平均每条 1.32 个；vet 成本随 merge 数增长，$8 上限可能不够

## 下一步
1. 19:10 PT 额度重置后：噪声测量（10 个 target × 2 次，约 $6）
2. 实验 1：基线（e5e03c0 的 compress）在 v0027 上
