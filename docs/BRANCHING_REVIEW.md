# 语义分支逐题人工核对表

本表用于解释 `docs/BRANCHING_AUDIT.md` 中 15 个样本的分支质量。它区分三类内容：代码可复现事实、需要人工判断的分支质量、后续计划。BIRD dev 只用于开发审查，不作为训练集、最终测试集或模型准确率结果。

## 指标含义

- `old_fixed=15`：表示旧的硬编码拆分器在这 15 个样本中，每题至少遗漏一种由审查脚本标出的粗粒度需求类型，例如输出目标、过滤条件、聚合口径、排序/极值或时间条件。它只说明旧实现太窄，不代表当前 15 道题的分支都正确。
- `needs_review=0`：表示当前规则没有遗漏审查脚本能自动识别的粗粒度需求类型。它不代表语义拆分已经经人工标注验证。
- `gold_reference_only=1`：表示离线审查代码用 gold SQL 表面标识符发现一个人工核对线索。gold SQL 不进入拆分器、检索器或 SQL Agent 输入，也不能被当作唯一正确分支标注。

本轮明确修复了两个可复现错误：

1. Q39 的 `from Fresno schools` 没被识别为过滤条件，已补充 `filter_conditions` 规则和回归测试。
2. Q340 的 `powerful` 曾误匹配 schema 字段 `power`，已改为字段词边界匹配，并用 `cardKingdomFoilId` / `cardKingdomId` 回归测试覆盖。

## 逐题核对表

| question_id | db_id | 题目摘要 | 生成分支 | 判断依据 | 发现的问题 | 结论 |
|---|---|---|---|---|---|---|
| `task_v1_learn_refund_rule` | `retail_v1` | highest net sales after refunds | `refund_semantics`; `requested_output`; `ranking_or_extreme` | 问题明确要求扣除 refunds 并取最高城市；toy schema 描述包含 `refunds.refund_amount`。 | toy schema 是短文本，不足以自动证明城市表和订单表连接；但该 toy 任务的检索目标主要是退款口径。 | 可用，但真实任务需更完整 schema/外键证据。 |
| `task_v1_reuse_refund_rule` | `retail_v1` | same db version, city wins after deducting refunds | `refund_semantics`; `requested_output` | 问题明确含 `deducting refunds` 和返回 city。 | 没有显式排序分支，因为 `wins` 当前只体现在 requested output 中；toy 可接受，真实任务建议人工标注是否应建极值分支。 | 可用，粒度偏保守。 |
| `task_v2_refund_schema_changed` | `retail_v2` | schema update, city wins after approved returned amounts | `refund_semantics`; `requested_output` | 问题和 schema 描述含 `returned_amount` / approved returned amounts。 | `approved` 当前进入退款分支文本，但没有独立过滤分支；真实数据中应核对是否需要单独业务过滤。 | 可用，approved 口径需人工核对。 |
| `0` | `california_schools` | highest eligible free rate for K-12 in Alameda County | `requested_output`; `metric_or_aggregation`; `filter_conditions`; `ranking_or_extreme` | evidence 给出 eligible free rate 公式；问题包含 Alameda County 和 highest。 | `gold_reference_only` 仍提示字段/别名可能未完全对齐；SQL 表面结构不能直接证明分支错误。 | 无法完全判断；需人工核对公式字段与连接路径。 |
| `4` | `california_schools` | direct charter-funded schools opened after 2000/1/1, list phones | `requested_output`; `filter_conditions`; `time_conditions` | 问题有 phone 输出、direct charter-funded 过滤、opened after date；evidence 给 charter 口径。 | `direct charter-funded` 同时涉及 funding 与 charter，当前合并在过滤分支中；是否需要拆成两个过滤子分支需人工标注。 | 可用，业务过滤可进一步细分。 |
| `5` | `california_schools` | count virtual schools with average Math > 400 | `metric_or_aggregation`; `filter_conditions` | `How many` 对应计数；问题包含 Math > 400 和 virtual，evidence 给 virtual 口径。 | SAT 表和 schools 表连接路径未显式成分支；当前审查只记录表/字段线索。 | 可用，但多表连接需人工核对。 |
| `13` | `california_schools` | phone numbers of top 3 SAT excellence rate schools | `requested_output`; `metric_or_aggregation`; `filter_conditions`; `ranking_or_extreme` | evidence 给 excellence rate 公式；问题要求 top 3 和 phone 输出。 | `filter_conditions` 中的 “with top 3” 与 ranking 有重复，属于可接受的轻微重叠；不应为了扩大候选重复拆分。 | 可用，存在轻微重复。 |
| `39` | `california_schools` | average test takers from Fresno schools opened in 1980 | `requested_output`; `metric_or_aggregation`; `filter_conditions`; `time_conditions` | 问题包含 average、Fresno schools、opened between dates；evidence 将日期解释为 year=1980。 | 本轮修复前漏掉 `from Fresno schools` 过滤条件；已补测试。 | 可用。 |
| `62` | `california_schools` | total non-chartered LA schools with eligible free meal percent < 0.18% | `requested_output`; `metric_or_aggregation`; `filter_conditions` | 问题和 evidence 给 non-chartered、County、percent formula、threshold。 | 多个过滤条件被合并为一个分支；如果未来要训练细粒度管理策略，建议标注 non-charter、county、threshold 三类子条件。 | 可用，粒度偏粗。 |
| `66` | `california_schools` | count directly funded schools opened 2000-2005 in Stanislaus | `metric_or_aggregation`; `filter_conditions`; `time_conditions` | 问题包含 how many、directly funded、county、opened date range；evidence 给 FundingType。 | 输出是计数，无 requested_output 分支也可接受；直接资助和 county 合并为过滤分支。 | 可用。 |
| `89` | `financial` | count accounts with issuance after transaction in East Bohemia | `metric_or_aggregation`; `filter_conditions` | 问题是 how many accounts；evidence 给 region 字段和 issuance phrase。 | 当前分支能定位 `account` / `district.A3`，但 `POPLATEK PO OBRATU` 与具体字段值的映射仍需人工或数据字典确认。 | 无法完全判断；业务值映射需人工核对。 |
| `340` | `card_games` | cards with incredibly powerful foils | `requested_output`; `filter_conditions` | evidence 明确 `cardKingdomFoilId is not null AND cardKingdomId is not null`。 | 本轮修复了 `powerful` 误匹配 `power` 字段；现在过滤分支关联 `cardKingdomFoilId` / `cardKingdomId`。 | 可用。 |
| `531` | `codebase_community` | higher reputation, Harlan vs Jarrod Dixon | `requested_output`; `ranking_or_extreme` | evidence 指明 DisplayName 和 Max(Reputation)。 | 两个候选人过滤条件没有单独分支；当前 requested output + ranking 可用于检索，但真实执行需要候选人过滤。 | 需人工核对是否补 filter 分支。 |
| `717` | `superhero` | list all superpowers of 3-D Man | `requested_output` | evidence 指出 `3-D Man` 是 superhero_name，superpowers 是 power_name。 | 当前没有 filter 分支表示 `3-D Man`，也没有显式 entity linking；这是业务实体过滤，需后续规则或标注。 | 需修改或人工标注后再用于训练。 |
| `1020` | `european_football_2` | player with highest overall rating, output api id | `requested_output`; `ranking_or_extreme` | evidence 给 `MAX(overall_rating)`；问题要求 player api id。 | Player 与 Player_Attributes 的连接路径未显式记录；真实多表题需人工核对 entity linking。 | 可用作粗分支；连接关系无法自动确认。 |

## 结论

当前分支拆分比旧硬编码实现更适合做记忆检索审查：它能显式记录输出、过滤、聚合、排序/极值和时间条件，并能在无法确认字段或连接关系时保留不确定性。但这仍不是人工标注过的语义分支器。

下一步建议：制作一个小规模分支标注集，至少覆盖输出目标、过滤条件、聚合口径、时间条件、排序/极值、实体连接和业务值映射。之后再决定是否训练拆分模型或引入 LLM 生成分支，并用标注集评估。