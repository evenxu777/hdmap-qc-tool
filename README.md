# project2_map_qc — OpenDRIVE / NDS 地图质检工具

## 30 秒跑起来

```bash
cd project2_map_qc
python map_qc.py --input data/sample_map.xodr --out out
# Windows 提示：本项目零第三方依赖，无需 pip；装可选包若遇 GBK 解码错误，先 $env:PYTHONUTF8="1"，推荐在 venv 中安装
```

产物：`out/qc_report.csv` + `out/qc_report.html`（浏览器打开演示）。
内置示例故意埋了 3 处问题（road 2 几何断裂、后继引用不存在的 road 99、junction 引用不存在的 incomingRoad 999），用于演示质检命中。

## 矿区站点扩展（卡特彼勒岗位口径，R7/R8）

```bash
# 基础 5 条规则 + 站点 2 条规则（围栏闭合/自相交、POI 必填/类型/唯一）
python map_qc.py --input data/sample_map.xodr --out out_site --site data/site
# 站点静态地图样例（PNG + 合并 GeoJSON）
python site_map_preview.py --site data/site --out out_site
```

站点输入均为 GeoJSON：`data/site/roads.geojson`（含 slope_pct / height_limit_m）、
`data/site/poi.geojson`（load / unload / fuel / parking / dump）、`data/site/geofence.geojson`。
规则实现在 `site_rules.py`，`--site` 不传时不影响原有城市地图质检。

## 换成真实数据

1. 下载公开 xodr：esmini 仓库 `resources/xodr/` 下有多个样例（https://github.com/esmini/esmini ）。
2. `python map_qc.py --input <你的文件.xodr> --out out`。
3. 规则阈值在 `map_qc.py` 顶部常量区调整（容差、限速上限）。

## Docker（可选，Day 4 做）

```bash
docker build -t map-qc .
docker run --rm -v %cd%/data:/app/data -v %cd%/out:/app/out map-qc --input data/sample_map.xodr --out out
```

## 下一步 TODO

- [ ] 接入 3–5 个公开 xodr 样例，整理《命中问题统计表》
- [ ] 增加 lane 级规则：车道宽 a+b·s 连续性、车道数突变检查
- [ ] 增加 junction laneLink from/to 合法性检查
- [ ] 用 matplotlib 出 1 张"规则命中分布"柱状图嵌进 HTML
- [ ] （进阶）用 pyodrx 替换手写解析，对比解析结果一致性
- [ ] 输出《OpenDRIVE vs NDS 数据模型对比》一页笔记（对应面试讲解）
- [ ] R9：POI 是否落在任一围栏内（`site_rules.point_in_ring` 已实现，只差调用）
- [ ] R10：道路连通性与单向环路（road→successor 邻接表，无出口的单向闭环报错）
- [ ] R11：坡度 / 限高字段范围校验（slope_pct ∈ [-15,15]，height_limit_m ≥ 0）
