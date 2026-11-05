# project2_map_qc — OpenDRIVE / NDS 地图质检工具

## 项目状态

- 冻结日期：2026-11-05。
- 冻结范围：规则 R1–R6 + R9，以及站点扩展 R7/R8；解析器、报告和 HTML 不再新增功能。
- 2026-11-05 缺陷修复：`--site` 增加 `site.json` 绑定校验，缺失或不匹配时跳过 R7/R8 并告警；规则编号与判定逻辑不变。
- 未完成的非代码事项：① 3 分钟演示录屏（已有 4 张截图，录屏缺失）；② Docker 构建验证未在本机实测（当前环境无 Docker CLI）。
- 后续只接受缺陷修复与文档修订；新增规则或字段进入 Future work，需先满足各自的恢复条件。

## 30 秒跑起来

```bash
cd project2_map_qc
python map_qc.py --input data/sample_map.xodr --out out
# Windows 提示：本项目零第三方依赖，无需 pip；装可选包若遇 GBK 解码错误，先 $env:PYTHONUTF8="1"，推荐在 venv 中安装
```

产物：`out/qc_report.csv` + `out/qc_report.html`（浏览器打开演示）+ `out/qc_report.json`（机器可读）。

内置样例为 3 条道路 + 1 个交叉口的多 road 版本，与 `data/real/` 的 esmini 真实样例并列。基础模式刻意埋了 5 处问题，用于演示质检命中；`--site` 另触发 5 条站点问题。

### 样例刻意埋错清单

| 规则 | 模式 | 对象 | 期望消息摘要 |
|---|---|---|---|
| R2 | 基础 | road 1 | `predecessor 引用的 road id=0 不存在` |
| R2 | 基础 | road 2 | `successor 引用的 road id=99 不存在` |
| R4 | 基础 | road 2 | `几何总长 60.00m 与 length=80.00m 不一致` |
| R4 | 基础 | road 3 | `几何总长 60.00m 与 length=80.00m 不一致` |
| R5 | 基础 | junction 10 | `incomingRoad id=999 不存在` |
| R7 | `--site` | fence F2 | `围栏未闭合（首点 ≠ 末点）` |
| R7 | `--site` | fence F3 | `围栏边界自相交` |
| R8 | `--site` | poi P1 | `poi_id 重复 2 次` |
| R8 | `--site` | poi P3 | `缺少必填字段: ['name']` |
| R8 | `--site` | poi P4 | `type=weigh 不在允许集合` |

对应基线条数：基础 **5 条**，带 `--site` **10 条**（5 基础 + 2 R7 + 3 R8）。road 3 的 `successor` 指向存在的 road 1 且 contactPoint 对齐，不产生额外告警。

### 规则清单

| 规则 | 检查内容 | 级别 | 说明 |
|---|---|---|---|
| R1 | road id 重复；同一 laneSection 内 lane id 重复 | ERROR | 按 laneSection 分组，避免跨段误报 |
| R2 | 引用 road 存在性；双向 contactPoint 与接头位置对齐；自引用形态 | ERROR/WARN | **单 road 闭环例外**：`predecessor`/`successor` 各指向自身一次且 contactPoint 互补（end/start 或 start/end）视为合法闭环，不报错；仅声明一端、两端 contactPoint 相同、重复声明仍报 ERROR |
| R3 | 限速在 (0, 130] km/h | WARN | 阈值见 `SPEED_MAX_KMH` |
| R4 | planView 几何长度之和与 road length 一致 | ERROR | 容差 `TOLERANCE_M = 0.1` |
| R5 | junction/connection 的 `incomingRoad` 存在 | ERROR | 与 R9 有重叠，后续可合并 |
| R6 | laneSection 内 left/right 车道 id 连续 | WARN | center 车道不参与；laneSection 无 left/right 车道时也告警 |
| R7 | 电子围栏闭合性、最小点数与自相交 | ERROR | 环点数 < 4、首尾不闭合、非相邻边相交均报错；仅 `--site` |
| R8 | 站点 POI 必填字段、类型、id 唯一 | ERROR/WARN | 仅 `--site` |
| R9 | road→junction、connection→road（`connectingRoad`/`linkedRoad`）、laneLink 的 from/to 车道存在；from/to 非 0 | ERROR/WARN | 默认开启；目标缺失 ERROR，center 车道 0 或缺失 from/to 为 WARN；**laneLink 缺失本身不报错**；传 `--no-r9` 关闭 |

R9 未做 from/to 符号一致性校验：真实数据中 `from=2, to=-1` 这类反向符号大量存在，incoming/connecting road 朝向相反属合法建模。

## 矿区站点扩展（R7/R8）

```bash
# 基础 7 条规则（R1–R6、R9）+ 站点 2 条规则（R7 围栏、R8 POI）
python map_qc.py --input data/sample_map.xodr --out out_site --site data/site
# 站点静态地图样例（PNG + 合并 GeoJSON）
python site_map_preview.py --site data/site --out out_site
# 渲染结果示例见 docs/site_map.png（由上面这条命令生成后另存）
```

站点输入均为 GeoJSON：`data/site/roads.geojson`（含 slope_pct / height_limit_m）、
`data/site/poi.geojson`（load / unload / fuel / parking / dump）、`data/site/geofence.geojson`。
规则实现在 `site_rules.py`，`--site` 不传时不影响原有城市地图质检。

站点目录还需带 `site.json`，声明这组站点数据绑定哪份基准地图：

```json
{"name": "demo_site", "base_map": "sample_map.xodr", "description": "演示站点"}
```

- `base_map` 只写文件名（可写字符串数组），与 `--input` 的 basename 做大小写不敏感比对。
- 匹配时正常执行 R7/R8；不匹配时打印 `[WARN] 站点数据 base_map=... 与输入地图 ... 不匹配，R7/R8 已跳过`，退出码仍为 0，JSON 的 `site_status` 记为 `skipped:mismatch`。
- `site.json` 缺失或 `base_map` 字段为空时打印 `[WARN] 站点目录缺少 site.json 或 base_map 字段，跳过 R7/R8`，JSON 记为 `skipped:no_manifest`；不会默认放行站点数据。

## 换成真实数据

`data/real/` 已内置 10 份 esmini 真实样例（MPL-2.0，来源、版本与许可见 `data/real/NOTICE.md`）：

| 文件 | 版本 | road | junction | laneSection | 当前问题数 |
|---|---|---|---|---|---|
| `multi_intersections.xodr` | 1.4 | 63 | 5 | 63 | 0 |
| `fabriksgatan.xodr` | 1.4 | 16 | 1 | 16 | 0 |
| `fabriksgatan_traffic_lights.xodr` | 1.4 | 16 | 1 | 16 | 0 |
| `soderleden.xodr` | 1.7 | 5 | 1 | 7 | 0 |
| `parking_demo.xodr` | 1.7 | 7 | 1 | 7 | 0 |
| `tunnels.xodr` | 1.6 | 2 | 0 | 2 | 0 |
| `two_plus_one.xodr` | 1.5 | 1 | 0 | 5 | 0 |
| `velodrome.xodr` | 1.5 | 1 | 0 | 1 | 0（单 road 闭环，R2 已豁免） |
| `curves.xodr` | 1.4 | 1 | 0 | 1 | 0 |
| `curves_elevation.xodr` | 1.4 | 1 | 0 | 1 | 0 |

```bash
python map_qc.py --input data/real/multi_intersections.xodr --out out_real
# 机器可读结果：out_real/qc_report.json
# 重新生成统计表：python tools/build_stats.py --json-dir <含 qc_report.json 的目录> --out docs/命中问题统计表.md
```

逐文件命中、规则维度汇总与真实数据特征见 [docs/命中问题统计表.md](docs/命中问题统计表.md)。

自行补充数据时：从 esmini 仓库 `resources/xodr/` 下载（https://github.com/esmini/esmini ），
或其它许可清晰的公开 xodr；单文件建议不超过 15 MB。规则阈值在 `map_qc.py` 顶部常量区调整（容差、限速上限）。

## 解析器覆盖范围与已知限制

### 支持的字段与结构

- **road**：`id`、`name`、`length`、`junction`、`type/speed`（限速，`km/h` 与 `m/s` 自动换算）。
- **planView geometry**：当前只读取每段 `length` 用于 R4；文件中的 `s`、`x`、`y`、`hdg` 与类型（`line` / `arc` / `spiral` / `poly3` / `paramPoly3`）不参与判定。
- **lanes → laneSection → lane**：车道 `id`、`type` 参与规则；`level`、`width` 与 lane 内 `laneLink` 可存在于输入中并被安全跳过，不参与判定。
- **road link**：`predecessor` / `successor` 的 `elementType`、`elementId`、`contactPoint`。
- **junction**：`connection` 的 `incomingRoad`、`connectingRoad`、`linkedRoad`，以及 connection 下 `laneLink` 的 `from` / `to`。

### 明确不支持 / 不做的部分

- `objects` / `signals` 的语义校验：元素存在时不影响解析，但工具不做判定。
- `arc` / `spiral` / `paramPoly3` 的精确轨迹推算：不做轨迹计算，R4 仅比对各段 `length` 之和。
- 高程 `elevationProfile`、超高（superelevation）的几何连续性：不读取、不校验。
- OpenDRIVE 1.8 新增元素，以及 1.7 之后未覆盖的新写法：不在冻结范围内。
- lane 级宽度突变、车道数突变的连续性校验：不实现。
- 多文件 / 多图幅拼接与跨文件引用：只处理单个 `.xodr`，不解析外部引用。

### 实现方式

标准库 `xml.etree.ElementTree` 手写解析，核心解析与规则零第三方依赖、离线可跑。选择理由：现有规则只需要上述字段子集，解析结果确定，不引入 pip 依赖即可在无网环境复现。

### 实测覆盖证据

10 份真实 `.xodr`（版本 1.4 / 1.5 / 1.6 / 1.7）：312 段 geometry（`arc` 64 / `line` 112 / `paramPoly3` 48 / `spiral` 88）、135 条 `laneLink`、2 条 `linkedRoad`、31 条 road→junction 引用，R1–R6 与 R9 零命中（零误报）。逐文件明细与口径见 [docs/命中问题统计表.md](docs/命中问题统计表.md)。

### 已知风险

- 遇到未覆盖的写法时倾向于**漏检而非误报**：解析器会跳过无法识别的元素，不会因此编造问题。
- 需要更强几何校验时，可引入 `pyodrx` 或 `esmini` 库做解析对拍；这属于可选扩展，不在当前冻结范围，也不作为待办。

## Docker（可选）

```bash
docker build -t map-qc .
docker run --rm -v %cd%/data:/app/data -v %cd%/out:/app/out map-qc --input data/sample_map.xodr --out out
```

## 下一步 TODO（仅交付事项）

- [ ] **3 分钟演示录屏**：按现有演示脚本录制完整流程，放到 `docs/` 或指定交付位置。状态：未完成——录屏缺失；当前可展示素材为 HTML 报告与 `docs/site_map.png`（站点静态图），项目内没有界面截图。
- [ ] **Docker 构建验证**：在具备 Docker 的环境执行 `docker build -t map-qc .`，并用样例跑一次容器内质检。状态：未验证——当前机器无 Docker CLI。

## Future work

以下条目设计已明确，但不在当前冻结范围内实现。

- **lane 级规则（宽度 / 车道数连续性）**：校验车道宽 `a+b·s` 在 laneSection 边界连续、车道数突变是否合理。暂缓原因：现有 10 份真实数据 0 命中，缺少正样本，阈值也未经业务确认。恢复条件：接入对象级 / 车道级地图验收需求，并拿到宽度突变的真实问题样本。
- **R10：POI 落围栏校验**：判断每个 POI 是否落在至少一个电子围栏内，`site_rules.point_in_ring` 已实现解析与几何判断。暂缓原因：库存 POI 与围栏尚未形成稳定正负样本，直接开启容易产生站点布局口径争议。恢复条件：站点业务确认“POI 必须在围栏内”的验收口径，并提供标注样本。
- **R11：单向闭环 / 回环判定**：构造 road→successor 邻接表，检出无出口的单向闭环。暂缓原因：velodrome 合法闭环刚通过 R2 例外，环路是否合法依赖通行方向与业务语义，容易误报。恢复条件：明确矿区 / 园区单向环路的允许形态，并补充正负样本。
- **R12：坡度 / 限高范围校验**：校验 `slope_pct ∈ [-15, 15]`、`height_limit_m ≥ 0`。暂缓原因：阈值随车型与场地变化，当前没有业务方确认的上下限。恢复条件：拿到矿区道路设计规范或业务给定的阈值。
- **R5 与 R9 合并**：把 R5 只校验 `incomingRoad` 的分支并入 R9，避免同一 junction 连接重复扫描。暂缓原因：合并会改变规则编号与历史报告口径，冻结期内不调整规则边界。恢复条件：下一次规则版本升级（引入 R10 及以后）时统一重排编号。
- **pyodrx / esmini 解析对拍**：用成熟库解析同一批 `.xodr`，与原手写解析逐字段对比。暂缓原因：会引入第三方依赖，破坏离线零依赖的可复现性。恢复条件：允许安装外部依赖，且确实需要验证解析器边界时。
- **OpenDRIVE vs NDS 数据模型对比笔记**：整理一页字段与结构差异对照。暂缓原因：属于知识整理，不影响当前演示与交付。恢复条件：准备做数据模型选型或对外分享材料时。
