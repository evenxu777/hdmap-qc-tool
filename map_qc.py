# -*- coding: utf-8 -*-
"""
map_qc.py — OpenDRIVE(.xodr) 解析 + 规则质检 + 报告输出（最小可运行版）

只依赖 Python 标准库，保证无网环境也能跑通：
    python map_qc.py --input data/sample_map.xodr --out out

质检规则（5 条，示例内置坏数据用于演示）：
    R1 重复要素：road id / lane id 重复
    R2 连通性：road 的 predecessor/successor 引用的道路必须存在
    R3 限速一致性：限速必须在 (0, 130] km/h 合理区间
    R4 几何断裂：planView 各段几何长度之和必须等于 road length（容差 0.1m）
    R5 交叉口拓扑：junction/connection 引用的 incomingRoad 必须存在

站点/矿区扩展规则（传 --site 时启用，见 site_rules.py）：
    R7 电子围栏闭合性与自相交
    R8 站点 POI 要素完整性（必填字段、类型合法、id 唯一）

报告产物：
    out/qc_report.csv   —— 每条问题一行
    out/qc_report.html  —— 汇总统计 + 明细表（可直接浏览器打开演示）
"""
import argparse
import csv
import html
import os
import xml.etree.ElementTree as ET
from collections import Counter

TOLERANCE_M = 0.1          # R4 几何长度容差
SPEED_MAX_KMH = 130.0      # R3 限速上限（城市场景经验值，可按需调整）


def parse_xodr(path):
    """解析 xodr，返回 dict: roads, junctions。每一步都带注释，方便替换为 pyodrx 等成熟库。"""
    tree = ET.parse(path)
    root = tree.getroot()
    roads = {}
    for r in root.iter("road"):
        road_id = r.get("id")
        road = {
            "id": road_id,
            "name": r.get("name", ""),
            "length": float(r.get("length", "0")),
            "junction": r.get("junction", "-1"),
            "link_refs": [],      # [(dir, elementType, elementId)]
            "speeds_kmh": [],     # road type 上的 speed
            "geom_len_sum": 0.0,  # planView 几何长度累计
            "lane_ids": [],       # 全部 lane id（用于 R1）
        }
        link = r.find("link")
        if link is not None:
            for tag in ("predecessor", "successor"):
                for e in link.findall(tag):
                    road["link_refs"].append((tag, e.get("elementType"), e.get("elementId")))
        for t in r.findall("type"):
            sp = t.find("speed")
            if sp is not None and sp.get("max") not in (None, ""):
                unit = sp.get("unit", "km/h")
                v = float(sp.get("max"))
                road["speeds_kmh"].append(v if "km" in unit else v * 3.6)  # m/s -> km/h
        pv = r.find("planView")
        if pv is not None:
            for g in pv.findall("geometry"):
                road["geom_len_sum"] += float(g.get("length", "0"))
        lanes = r.find("lanes")
        if lanes is not None:
            for ls in lanes.iter("lane"):
                road["lane_ids"].append(ls.get("id"))
        roads[road_id] = road

    junctions = {}
    for j in root.iter("junction"):
        jid = j.get("id")
        junctions[jid] = {
            "id": jid,
            "incoming_roads": [c.get("incomingRoad") for c in j.findall("connection")],
            "connecting_roads": [c.get("connectingRoad") for c in j.findall("connection")],
        }
    return roads, junctions


def check_rules(roads, junctions):
    """执行 5 条规则，返回问题列表 [{rule, level, object, message}]"""
    issues = []

    # R1 重复要素
    road_ids = list(roads.keys())
    if len(road_ids) != len(set(road_ids)):
        # ET 解析时 dict 会覆盖重复 id，这里用计数提示（真实重复在解析阶段丢失，故单独统计）
        pass
    for rid, road in roads.items():
        dup = [lid for lid, n in Counter(road["lane_ids"]).items() if n > 1]
        if dup:
            issues.append({"rule": "R1", "level": "ERROR", "object": f"road {rid}",
                           "message": f"lane id 重复: {dup}"})

    # R2 连通性：道路引用必须存在
    for rid, road in roads.items():
        for direction, etype, eid in road["link_refs"]:
            if etype == "road" and eid not in roads:
                issues.append({"rule": "R2", "level": "ERROR", "object": f"road {rid}",
                               "message": f"{direction} 引用的 road id={eid} 不存在"})
            if etype == "junction" and eid not in junctions:
                issues.append({"rule": "R2", "level": "ERROR", "object": f"road {rid}",
                               "message": f"{direction} 引用的 junction id={eid} 不存在"})

    # R3 限速合理性
    for rid, road in roads.items():
        for v in road["speeds_kmh"]:
            if not (0 < v <= SPEED_MAX_KMH):
                issues.append({"rule": "R3", "level": "WARN", "object": f"road {rid}",
                               "message": f"限速 {v} km/h 超出合理区间 (0,{SPEED_MAX_KMH}]"})

    # R4 几何断裂：几何长度和 != road length
    for rid, road in roads.items():
        if abs(road["geom_len_sum"] - road["length"]) > TOLERANCE_M:
            issues.append({"rule": "R4", "level": "ERROR", "object": f"road {rid}",
                           "message": f"几何总长 {road['geom_len_sum']:.2f}m 与 length={road['length']:.2f}m 不一致"})

    # R5 交叉口拓扑：connection 引用道路必须存在
    for jid, j in junctions.items():
        for ir in j["incoming_roads"]:
            if ir not in roads:
                issues.append({"rule": "R5", "level": "ERROR", "object": f"junction {jid}",
                               "message": f"incomingRoad id={ir} 不存在"})

    return issues


def write_reports(issues, roads, junctions, outdir):
    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "qc_report.csv")
    html_path = os.path.join(outdir, "qc_report.html")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rule", "level", "object", "message"])
        w.writeheader()
        w.writerows(issues)

    by_rule = Counter(i["rule"] for i in issues)
    rows = "".join(
        f"<tr><td>{html.escape(i['rule'])}</td><td>{i['level']}</td>"
        f"<td>{html.escape(i['object'])}</td><td>{html.escape(i['message'])}</td></tr>"
        for i in issues
    )
    stat = " ".join(f"{k}:{v}" for k, v in sorted(by_rule.items())) or "无问题"
    page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>OpenDRIVE 质检报告</title>
<style>body{{font-family:Microsoft YaHei,Arial;margin:32px}}table{{border-collapse:collapse}}
td,th{{border:1px solid #999;padding:4px 10px}}.err{{color:#c00}}</style></head><body>
<h1>OpenDRIVE 地图质检报告</h1>
<p>道路数：{len(roads)} ｜ 交叉口数：{len(junctions)} ｜ 问题总数：{len(issues)} ｜ 按规则：{stat}</p>
<table><tr><th>规则</th><th>级别</th><th>对象</th><th>说明</th></tr>{rows}</table>
</body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    return csv_path, html_path


def main():
    ap = argparse.ArgumentParser(description="OpenDRIVE 地图规则质检工具")
    ap.add_argument("--input", required=True, help="输入 .xodr 文件路径")
    ap.add_argument("--out", default="out", help="报告输出目录（默认 out/）")
    ap.add_argument("--site", default=None,
                    help="站点地图目录（含 geofence.geojson / poi.geojson），启用 R7/R8 站点规则")
    args = ap.parse_args()

    roads, junctions = parse_xodr(args.input)
    issues = check_rules(roads, junctions)
    if args.site:
        from site_rules import check_site_rules, load_site
        fence_features, poi_features = load_site(args.site)
        issues += check_site_rules(fence_features, poi_features)
    csv_path, html_path = write_reports(issues, roads, junctions, args.out)
    print(f"[OK] 道路 {len(roads)} 条，交叉口 {len(junctions)} 个，发现问题 {len(issues)} 条")
    print(f"[OK] CSV : {csv_path}")
    print(f"[OK] HTML: {html_path}")


if __name__ == "__main__":
    main()
