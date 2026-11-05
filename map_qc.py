# -*- coding: utf-8 -*-
"""
map_qc.py — OpenDRIVE(.xodr) 解析 + 规则质检 + 报告输出（最小可运行版）

只依赖 Python 标准库，保证无网环境也能跑通：
    python map_qc.py --input data/sample_map.xodr --out out

质检规则：
    R1 重复要素：road id / lane id 重复
    R2 连通性：引用道路必须存在；双向链接按 contactPoint 校验接头位置；
       单 road 闭环（predecessor/successor 各指向自身一次且接触点互补）不报错
    R3 限速一致性：限速必须在 (0, 130] km/h 合理区间
    R4 几何断裂：planView 各段几何长度之和必须等于 road length（容差 0.1m）
    R5 交叉口拓扑：junction/connection 引用的 incomingRoad 必须存在
    R6 车道数一致性：laneSection 内 left/right 车道 id 连续；无 left/right 车道时告警
    R9 链接完整性：road→junction、connection→road、laneLink→lane 均须存在；
       laneLink 的 from/to 必须是非 0 车道；laneLink 缺失不报错（传 --no-r9 可关闭）

站点/矿区扩展规则（传 --site 时启用，见 site_rules.py）：
    R7 电子围栏闭合性与自相交
    R8 站点 POI 要素完整性（必填字段、类型合法、id 唯一）

报告产物：
    out/qc_report.csv   —— 每条问题一行
    out/qc_report.html  —— 汇总统计 + 明细表（可直接浏览器打开演示）
    out/qc_report.json  —— 机器可读结果（含规则/级别/定位）
"""
import argparse
import csv
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime

TOLERANCE_M = 0.1          # R4 几何长度容差
SPEED_MAX_KMH = 130.0      # R3 限速上限（城市场景经验值，可按需调整）


def parse_xodr(path):
    root = ET.parse(path).getroot()
    roads = {}
    for r in root.findall("road"):
        road_id = r.get("id")
        road = {
            "id": road_id,
            "name": r.get("name", ""),
            "length": float(r.get("length", "0")),
            "junction": r.get("junction", "-1"),
            "link_refs": [],
            "speeds_kmh": [],
            "geom_len_sum": 0.0,
            "lane_ids": [],
            "lane_sections": [],   # [{'s': float, 'lanes': [{'id': int, 'type': str, 'side': str}]}]
            "dup_count": 0,        # 同一 road id 在文件中重复出现的额外次数
        }

        link = r.find("link")
        if link is not None:
            for tag in ("predecessor", "successor"):
                for e in link.findall(tag):
                    road["link_refs"].append((tag, e.get("elementType"),
                                              e.get("elementId"), e.get("contactPoint")))

        for t in r.findall("type"):
            sp = t.find("speed")
            if sp is not None and sp.get("max") not in (None, ""):
                unit = sp.get("unit", "km/h")
                v = float(sp.get("max"))
                road["speeds_kmh"].append(v if "km" in unit else v * 3.6)

        pv = r.find("planView")
        if pv is not None:
            for g in pv.findall("geometry"):
                road["geom_len_sum"] += float(g.get("length", "0"))

        lanes_el = r.find("lanes")
        if lanes_el is not None:
            for sec in lanes_el.findall("laneSection"):
                section_lanes = []
                for side in ("left", "center", "right"):
                    holder = sec.find(side)
                    if holder is None:
                        continue
                    for ln in holder.findall("lane"):
                        section_lanes.append({
                            "id": int(ln.get("id")),
                            "type": ln.get("type", "none"),
                            "side": side,
                        })
                road["lane_sections"].append({
                    "s": float(sec.get("s", "0")),
                    "lanes": section_lanes,
                })
                road["lane_ids"].extend(l["id"] for l in section_lanes)

        if road_id in roads:
            road["dup_count"] = roads[road_id]["dup_count"] + 1
        roads[road_id] = road

    junctions = {}
    for j in root.findall("junction"):
        jid = j.get("id")
        connections = []
        for c in j.findall("connection"):
            connections.append({
                "id": c.get("id"),
                "incoming": c.get("incomingRoad"),
                "connecting": c.get("connectingRoad"),
                "linked": c.get("linkedRoad"),
                "lane_links": [(ll.get("from"), ll.get("to")) for ll in c.findall("laneLink")],
            })
        junctions[jid] = {
            "id": jid,
            "connections": connections,
            "incoming_roads": [c.get("incomingRoad") for c in j.findall("connection")],
            "connecting_roads": [c.get("connectingRoad") if c.get("connectingRoad") is not None
                                 else c.get("linkedRoad") for c in j.findall("connection")],
        }
    return roads, junctions

def check_rules(roads, junctions):
    """执行 R1–R6 共 6 条规则，返回问题列表 [{rule, level, object, message}]"""
    issues = []

    # R1 重复要素：road id 整文件层面；lane id 仅在同一个 laneSection 内
    for rid, road in roads.items():
        if road.get("dup_count"):
            issues.append({"rule": "R1", "level": "ERROR", "object": f"road {rid}",
                           "message": f"road id 重复出现 {road['dup_count'] + 1} 次"})
        dup = []
        for sec in road.get("lane_sections", []):
            for lid, n in Counter(l["id"] for l in sec["lanes"]).items():
                if n > 1 and lid not in dup:
                    dup.append(lid)
        if dup:
            issues.append({"rule": "R1", "level": "ERROR", "object": f"road {rid}",
                           "message": f"lane id 重复: {dup}"})

    # R2 连通性：引用存在、自引用、双向 contactPoint 与接头位置对齐
    # 先处理自引用：predecessor/successor 各一次且 contactPoint 互补（end/start）
    # 视为合法单 road 闭环（如 velodrome），其余形态按“自引用错误”报 ERROR。
    for rid, road in roads.items():
        self_refs = [x for x in road["link_refs"] if x[1] == "road" and x[2] == rid]
        if not self_refs:
            continue
        preds = [c for d, _, _, c in self_refs if d == "predecessor"]
        succs = [c for d, _, _, c in self_refs if d == "successor"]
        if len(preds) == 1 and len(succs) == 1 and {preds[0], succs[0]} == {"start", "end"}:
            # 合法闭环：两端各指向自身一次，接触点互补
            continue
        if len(preds) + len(succs) == 1:
            only = "predecessor" if preds else "successor"
            msg = f"自引用错误：仅声明 {only} 指向自身，缺少另一端"
        elif len(preds) == 1 and len(succs) == 1:
            msg = (f"自引用疑似闭环但 contactPoint 未互补："
                   f"predecessor={preds[0]}，successor={succs[0]}")
        else:
            msg = (f"自引用错误：指向自身的链接重复或形态非法"
                   f"（predecessor {len(preds)} 条 / successor {len(succs)} 条）")
        issues.append({"rule": "R2", "level": "ERROR", "object": f"road {rid}", "message": msg})

    reported_pairs = set()
    for rid, road in roads.items():
        for direction, etype, eid, contact in road["link_refs"]:
            if etype != "road":
                continue
            if eid not in roads:
                issues.append({"rule": "R2", "level": "WARN", "object": f"road {rid}",
                               "message": f"{direction} 引用的 road id={eid} 不存在"})
                continue
            if eid == rid:
                # 自引用已在上方按闭环/错误分流，这里不再逐条重复报
                continue

            # 对方指回本道路的链接（不限方向）
            rev = [x for x in roads[eid]["link_refs"]
                   if x[1] == "road" and x[2] == rid]
            if not rev:
                # 只有一侧声明链接：不做反向引用告警（真实数据中占多数）
                continue

            # 同一对道路、同一组链接属性只报一次（A->B 与 B->A 各遍历一次）
            pair_key = (min(rid, eid), max(rid, eid),
                        frozenset([(direction, contact)] + [(x[0], x[3]) for x in rev]))
            if pair_key in reported_pairs:
                continue
            reported_pairs.add(pair_key)

            # 任一侧 contactPoint 缺失：只保留存在性/自引用检查
            if contact not in ("start", "end") or any(x[3] not in ("start", "end") for x in rev):
                continue

            # 本道路的接头：successor 在 end，predecessor 在 start
            own_point = "end" if direction == "successor" else "start"
            aligned = False
            for d2, _, _, c2 in rev:
                other_point = "end" if d2 == "successor" else "start"
                # A 的 contactPoint 应指向 B 的接头；B 的 contactPoint 应指向 A 的接头
                if contact == other_point and c2 == own_point:
                    aligned = True
                    break
            if not aligned:
                d2, other_point, c2 = rev[0][0], ("end" if rev[0][0] == "successor" else "start"), rev[0][3]
                issues.append({"rule": "R2", "level": "WARN", "object": f"road {rid}",
                               "message": (f"contactPoint 与接头位置不一致：{direction} contactPoint={contact}，"
                                           f"但 road {eid} 为 {d2} contactPoint={c2}"
                                           f"（期望 {other_point}，本道路接头为 {own_point}）")})



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

    # R6 车道数一致性：每个 laneSection 内 left 应为 1..N，right 应为 -1..-N
    for rid, road in roads.items():
        for ls_idx, sec in enumerate(road.get("lane_sections", [])):
            lanes = sec["lanes"]
            left_ids  = sorted(l["id"] for l in lanes if l["side"] == "left")
            right_ids = sorted((l["id"] for l in lanes if l["side"] == "right"), reverse=True)
            if not left_ids and not right_ids:
                issues.append({"rule": "R6", "level": "WARN", "object": f"road {rid} laneSection[{ls_idx}]",
                            "message": "该 laneSection 无 left/right 车道"})
                continue
            expected_left  = list(range(1, len(left_ids) + 1))
            expected_right = [-i for i in range(1, len(right_ids) + 1)]
            if left_ids != expected_left:
                issues.append({"rule": "R6", "level": "WARN", "object": f"road {rid} laneSection[{ls_idx}]",
                            "message": f"left 车道 id 不连续：{left_ids}，期望 {expected_left}"})
            if right_ids != expected_right:
                issues.append({"rule": "R6", "level": "WARN", "object": f"road {rid} laneSection[{ls_idx}]",
                            "message": f"right 车道 id 不连续：{right_ids}，期望 {expected_right}"})

    return issues


def _lane_id_set(road):
    return {str(l["id"]) for sec in road.get("lane_sections", []) for l in sec["lanes"]}


def check_r9(roads, junctions):
    """R9 链接完整性：road→junction、connection→road、laneLink→lane。

    laneLink 缺失本身不报错，只做“有则校验”。
    """
    issues = []

    # 链接层：road 的 predecessor/successor 可指向 junction
    for rid, road in roads.items():
        for direction, etype, eid, _cp in road["link_refs"]:
            if etype == "junction" and eid not in junctions:
                issues.append({"rule": "R9", "level": "ERROR", "object": f"road {rid}",
                               "message": f"{direction} 引用的 junction id={eid} 不存在"})

    # junction 层：connection 的目标 road 与 laneLink 车道
    for jid, j in junctions.items():
        for conn in j.get("connections", []):
            cid = conn.get("id")
            target = conn["connecting"] if conn["connecting"] is not None else conn["linked"]
            tfield = "connectingRoad" if conn["connecting"] is not None else "linkedRoad"
            obj = f"junction {jid} connection {cid}"
            if target is None:
                issues.append({"rule": "R9", "level": "WARN", "object": obj,
                               "message": "既无 connectingRoad 也无 linkedRoad"})
                continue
            if target not in roads:
                issues.append({"rule": "R9", "level": "ERROR", "object": obj,
                               "message": f"{tfield} id={target} 不存在"})
                continue

            incoming = conn.get("incoming")
            incoming_lanes = _lane_id_set(roads[incoming]) if incoming in roads else set()
            target_lanes = _lane_id_set(roads[target])

            for f, t in conn.get("lane_links", []):
                if f is None or t is None:
                    issues.append({"rule": "R9", "level": "WARN", "object": obj,
                                   "message": f"laneLink 缺少 from/to（from={f}, to={t}）"})
                    continue
                if f == "0" or t == "0":
                    issues.append({"rule": "R9", "level": "WARN", "object": obj,
                                   "message": f"laneLink 使用了 center 车道 0（from={f}, to={t}）"})
                    continue

                if incoming in roads and f not in incoming_lanes:
                    issues.append({"rule": "R9", "level": "ERROR", "object": obj,
                                   "message": f"laneLink from={f} 在 incomingRoad {incoming} 中不存在"})
                if t not in target_lanes:
                    issues.append({"rule": "R9", "level": "ERROR", "object": obj,
                                   "message": f"laneLink to={t} 在 {tfield} {target} 中不存在"})

                # 注意：from/to 符号相反在真实数据中大量存在（incoming/connecting road
                # 朝向相反），属合法建模，因此不做“符号一致”校验，只保证非 0。

    return issues


def _locate(obj):
    """从 object 文本提取定位提示（road / laneSection / junction）。"""
    m = re.search(r"road (\S+) laneSection\[(\d+)\]", obj)
    if m:
        return f"road {m.group(1)} · laneSection #{m.group(2)}"
    m = re.search(r"road (\S+)", obj)
    if m:
        return f"road {m.group(1)}"
    m = re.search(r"junction (\S+) connection (\S+)", obj)
    if m:
        return f"junction {m.group(1)} · connection #{m.group(2)}"
    m = re.search(r"junction (\S+)", obj)
    if m:
        return f"junction {m.group(1)}"
    return obj


CSS = """
:root{--bg:#f5f6f8;--card:#fff;--text:#1f2933;--muted:#6b7280;--err:#c0392b;--warn:#b7791f;--line:#e2e6ea;--accent:#2b6cb0}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--text);font-family:"Microsoft YaHei",-apple-system,"Segoe UI",Arial,sans-serif;font-size:14px;line-height:1.6}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:0 0 12px}
.sub{color:var(--muted);font-size:12px;word-break:break-all}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.card.wide{grid-column:1/-1}
.card .k{color:var(--muted);font-size:12px}
.card .v.path{font-size:13px;font-weight:400;word-break:break-all}
.card .v{font-size:22px;font-weight:600;margin-top:2px}
.card .v.err{color:var(--err)}.card .v.warn{color:var(--warn)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.bars{display:grid;gap:8px}
.bar-row{display:grid;grid-template-columns:64px 1fr 48px;gap:10px;align-items:center}
.bar-track{background:#eef1f4;border-radius:4px;height:16px;overflow:hidden}
.bar{height:16px;background:var(--accent);border-radius:4px}
.bar-row a{color:var(--text);text-decoration:none}
.bar-row a:hover{color:var(--accent)}
.count{text-align:right;color:var(--muted)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.toolbar select,.toolbar input{padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;font-size:13px}
.toolbar input{min-width:240px}
table{width:100%;border-collapse:collapse;background:var(--card)}
th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f0f2f5;font-size:12px;color:var(--muted);font-weight:600}
tr.issue:last-child td{border-bottom:none}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600}
.tag.ERROR{background:#fdecea;color:var(--err)}
.tag.WARN{background:#fdf3e1;color:var(--warn)}
.rule-sec{margin-bottom:18px}
.rule-sec h3{font-size:14px;margin:0 0 8px;padding-left:8px;border-left:3px solid var(--accent)}
.empty{text-align:center;padding:48px 16px}
.empty .big{font-size:20px;font-weight:600;margin-bottom:6px}
footer{color:var(--muted);font-size:12px;margin-top:24px}
@media print{
  body{background:#fff;padding:0;font-size:12px}
  .card,.panel{box-shadow:none;border-color:#bbb}
  .toolbar{display:none}
  .bar{background:#999!important}
  .tag{background:none!important;border:1px solid #666}
  .rule-sec{break-inside:avoid}
}
"""

JS = """
<script>
(function(){
  var lv=document.getElementById('lv'), q=document.getElementById('q');
  function apply(){
    var level=lv.value, kw=q.value.trim().toLowerCase();
    var rows=document.querySelectorAll('tr.issue');
    for(var i=0;i<rows.length;i++){
      var tr=rows[i];
      var ok=(level==='ALL'||tr.getAttribute('data-level')===level) &&
             (!kw || tr.getAttribute('data-text').indexOf(kw)>=0);
      tr.style.display=ok?'':'none';
    }
    var secs=document.querySelectorAll('section.rule-sec');
    for(var j=0;j<secs.length;j++){
      var vis=0, rs=secs[j].querySelectorAll('tr.issue');
      for(var k=0;k<rs.length;k++){ if(rs[k].style.display!=='none') vis++; }
      secs[j].style.display=vis?'':'none';
    }
  }
  if(lv&&q){ lv.addEventListener('change',apply); q.addEventListener('input',apply); }
})();
</script>
"""


def write_reports(issues, roads, junctions, outdir, input_path="", elapsed_s=0.0,
                  site_status=None):
    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "qc_report.csv")
    html_path = os.path.join(outdir, "qc_report.html")
    json_path = os.path.join(outdir, "qc_report.json")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["rule", "level", "object", "message"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(issues)

    by_rule = Counter(i["rule"] for i in issues)
    levels = Counter(i["level"] for i in issues)
    lane_sections = sum(len(r.get("lane_sections", [])) for r in roads.values())
    generated_at = datetime.now().isoformat(timespec="seconds")

    located = [{**i, "location": _locate(i["object"])} for i in issues]
    payload = {
        "tool": "map_qc.py",
        "rule_version": "R1-R9",
        "input": os.path.abspath(input_path) if input_path else "",
        "generated_at": generated_at,
        "elapsed_s": round(elapsed_s, 3),
        "roads": len(roads),
        "junctions": len(junctions),
        "lane_sections": lane_sections,
        "issues_total": len(issues),
        "levels": dict(levels),
        "by_rule": dict(by_rule),
        "issues": located,
    }
    if site_status:
        payload["site_status"] = site_status
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 规则分布条（R1–R9 全显示，含 0）
    max_count = max([by_rule.get(f"R{k}", 0) for k in range(1, 10)] + [1])
    bars = []
    for k in range(1, 10):
        rule = f"R{k}"
        n = by_rule.get(rule, 0)
        width = (n / max_count * 100) if n else 0
        label = (f'<a href="#rule-{rule}">{rule}</a>'
                 if n else f'<span class="sub">{rule}</span>')
        bars.append(
            f'<div class="bar-row">{label}'
            f'<div class="bar-track"><div class="bar" style="width:{width:.1f}%"></div></div>'
            f'<div class="count">{n}</div></div>'
        )

    # 明细：按规则分组，组内 ERROR 优先
    groups = []
    for k in range(1, 10):
        rule = f"R{k}"
        rows = [i for i in located if i["rule"] == rule]
        if not rows:
            continue
        rows.sort(key=lambda i: (0 if i["level"] == "ERROR" else 1, str(i["object"])))
        trs = "".join(
            f'<tr class="issue" data-level="{html.escape(i["level"])}" '
            f'data-text="{html.escape((i["rule"]+" "+i["level"]+" "+i["object"]+" "+i["message"]).lower())}">'
            f'<td>{html.escape(i["rule"])}</td>'
            f'<td><span class="tag {html.escape(i["level"])}">{html.escape(i["level"])}</span></td>'
            f'<td>{html.escape(i["object"])}</td>'
            f'<td>{html.escape(i["message"])}</td>'
            f'<td class="sub">{html.escape(i["location"])}</td></tr>'
            for i in rows
        )
        groups.append(
            f'<section class="rule-sec" id="rule-{rule}"><h3>{rule}（{len(rows)} 条）</h3>'
            f'<table><thead><tr><th>规则</th><th>级别</th><th>对象</th>'
            f'<th>说明</th><th>定位</th></tr></thead><tbody>{trs}</tbody></table></section>'
        )

    if groups:
        detail = "".join(groups)
        toolbar = (
            '<div class="toolbar">'
            '<select id="lv"><option value="ALL">全部级别</option>'
            '<option value="ERROR">仅 ERROR</option><option value="WARN">仅 WARN</option></select>'
            '<input id="q" type="search" placeholder="输入规则号 / 对象 / 关键词过滤">'
            '</div>'
        )
    else:
        detail = ('<div class="panel empty"><div class="big">未发现问题</div>'
                  '<div class="sub">当前文件没有触发 R1–R8 中的任何规则。</div></div>')
        toolbar = ""

    page = (
        '<!doctype html><html lang="zh"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>OpenDRIVE 质检报告 - {html.escape(os.path.basename(input_path) or "report")}</title>'
        f'<style>{CSS}</style></head><body>'
        '<h1>OpenDRIVE 地图质检报告</h1>'
        '<div class="cards">'
        f'<div class="card wide"><div class="k">文件路径</div>'
        f'<div class="v path">{html.escape(os.path.abspath(input_path) if input_path else "-")}</div></div>'
        f'<div class="card"><div class="k">道路 / 交叉口</div><div class="v">{len(roads)} / {len(junctions)}</div></div>'
        f'<div class="card"><div class="k">问题总数</div><div class="v">{len(issues)}</div></div>'
        f'<div class="card"><div class="k">ERROR / WARN</div><div class="v"><span class="err">{levels.get("ERROR", 0)}</span>'
        f' / <span class="warn">{levels.get("WARN", 0)}</span></div></div>'
        f'<div class="card"><div class="k">laneSection</div><div class="v">{lane_sections}</div></div>'
        f'<div class="card"><div class="k">耗时</div><div class="v">{elapsed_s:.2f}s</div></div>'
        f'<div class="card"><div class="k">生成时间</div><div class="v" style="font-size:13px">{generated_at}</div></div>'
        '<div class="card"><div class="k">规则版本</div><div class="v" style="font-size:15px">R1–R9</div></div>'
        '</div>'
        '<div class="panel"><h2>规则分布</h2><div class="bars">'
        + "".join(bars) +
        '</div><div class="sub" style="margin-top:8px">规则版本：R1–R9 ｜ 点击规则号跳到对应明细</div></div>'
        f'<div class="panel"><h2>明细</h2>{toolbar}{detail}</div>'
        f'<footer>由 map_qc.py 生成 ｜ 单文件自包含，无外部依赖 ｜ {generated_at}</footer>'
        f'{JS}</body></html>'
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    return csv_path, html_path, json_path


def main():
    ap = argparse.ArgumentParser(description="OpenDRIVE 地图规则质检工具")
    ap.add_argument("--input", required=True, help="输入 .xodr 文件路径")
    ap.add_argument("--out", default="out", help="报告输出目录（默认 out/）")
    ap.add_argument("--site", default=None,
                    help="站点地图目录（含 site.json / geofence.geojson / poi.geojson），启用 R7/R8 站点规则")
    ap.add_argument("--no-r9", action="store_true",
                    help="关闭 R9 链接完整性校验（默认开启）")
    args = ap.parse_args()

    t0 = time.perf_counter()
    roads, junctions = parse_xodr(args.input)
    issues = check_rules(roads, junctions)
    if not args.no_r9:
        issues += check_r9(roads, junctions)
    site_status = None
    if args.site:
        from site_rules import check_site_rules, load_site, load_site_manifest
        manifest = load_site_manifest(args.site)
        input_name = os.path.basename(args.input)
        if manifest is None:
            print("[WARN] 站点目录缺少 site.json 或 base_map 字段，跳过 R7/R8")
            site_status = "skipped:no_manifest"
        elif input_name.lower() not in [n.lower() for n in manifest["base_map"]]:
            print(f"[WARN] 站点数据 base_map={'/'.join(manifest['base_map'])} "
                  f"与输入地图 {input_name} 不匹配，R7/R8 已跳过")
            site_status = "skipped:mismatch"
        else:
            fence_features, poi_features = load_site(args.site)
            issues += check_site_rules(fence_features, poi_features)
            site_status = "checked"
    elapsed = time.perf_counter() - t0
    csv_path, html_path, json_path = write_reports(
        issues, roads, junctions, args.out, args.input, elapsed,
        site_status=site_status)
    print(f"[OK] 道路 {len(roads)} 条，交叉口 {len(junctions)} 个，发现问题 {len(issues)} 条")
    print(f"[OK] CSV : {csv_path}")
    print(f"[OK] HTML: {html_path}")
    print(f"[OK] JSON: {json_path}")
    print(f"[OK] 耗时: {elapsed:.3f}s")


if __name__ == "__main__":
    main()
