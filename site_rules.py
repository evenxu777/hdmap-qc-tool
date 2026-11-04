# -*- coding: utf-8 -*-
"""
site_rules.py — 站点/矿区地图语境规则（项目②的项目③改造扩展）

在城市 OpenDRIVE 质检之外，增加矿区站点静态地图的两类检查：
    R7 电子围栏闭合性与自相交：环首尾必须闭合；非相邻边不得相交
    R8 站点 POI 要素完整性：必填字段、类型合法、id 唯一

只依赖标准库。输入为 GeoJSON：
    geofence.geojson  Polygon，properties: fence_id, name
    poi.geojson       Point，  properties: poi_id, type(load/unload/fuel), name

用法（由 map_qc.py 调用）：
    python map_qc.py --input data/sample_map.xodr --out out --site data/site
"""
import json
import os
from collections import Counter

POI_TYPES = {"load", "unload", "fuel", "parking", "dump"}  # 矿区站点常见要素类型
REQUIRED_POI_FIELDS = ["poi_id", "type", "name"]


def load_site(site_dir):
    """读取站点围栏与 POI，缺文件时返回空列表（规则自然不触发）"""
    def _load(name):
        p = os.path.join(site_dir, name)
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("features", [])

    return _load("geofence.geojson"), _load("poi.geojson")


# ---------------- 几何基础函数（纯 Python，避免引入 shapely） ----------------
def _ring_coords(feature):
    """取 Polygon 外环坐标；兼容 MultiPolygon 的第一个面"""
    geom = feature.get("geometry", {})
    if geom.get("type") == "Polygon":
        rings = geom.get("coordinates", [])
        return rings[0] if rings else []
    if geom.get("type") == "MultiPolygon":
        polys = geom.get("coordinates", [])
        return polys[0][0] if polys and polys[0] else []
    return []


def _orient(a, b, c):
    """叉积符号：>0 逆时针，<0 顺时针，=0 共线"""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p):
    """共线情况下判断 p 是否落在线段 ab 上"""
    return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def segments_intersect(p1, p2, p3, p4):
    """两条线段是否相交（含端点接触）"""
    d1, d2 = _orient(p3, p4, p1), _orient(p3, p4, p2)
    d3, d4 = _orient(p1, p2, p3), _orient(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0:
        return True
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True
    return False


def ring_self_intersects(ring):
    """检测环是否自相交；相邻边共享端点不算自交"""
    pts = ring[:-1] if ring and ring[0] == ring[-1] else ring  # 去掉闭合重复点，避免零长度边误报
    n = len(pts)
    if n < 3:
        return False
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(len(edges)):
        for j in range(i + 2, len(edges)):
            if i == 0 and j == len(edges) - 1:
                continue  # 首尾相邻，跳过
            if segments_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return True
    return False


def point_in_ring(pt, ring):
    """射线法判断点是否在环内（边界视为在内）"""
    x, y = pt[0], pt[1]
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if _orient((x1, y1), (x2, y2), (x, y)) == 0 and _on_segment((x1, y1), (x2, y2), (x, y)):
            return True  # 点落在边上
        if ((y1 > y) != (y2 > y)):
            xi = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xi:
                inside = not inside
    return inside


# ---------------- 规则实现 ----------------
def check_site_rules(fence_features, poi_features):
    """返回站点规则问题列表，格式与 map_qc.py 的 issues 一致"""
    issues = []

    # R7 电子围栏：闭合性、最小点数、自相交
    for feat in fence_features:
        props = feat.get("properties", {})
        fid = props.get("fence_id") or props.get("name") or "unknown"
        ring = _ring_coords(feat)
        if len(ring) < 4:
            issues.append({"rule": "R7", "level": "ERROR", "object": f"fence {fid}",
                           "message": f"围栏环点数 {len(ring)} < 4，无法构成有效多边形"})
            continue
        first, last = ring[0], ring[-1]
        if first != last:
            issues.append({"rule": "R7", "level": "ERROR", "object": f"fence {fid}",
                           "message": f"围栏未闭合（首点 {first} ≠ 末点 {last}），不可通行性判定会失效"})
        if ring_self_intersects(ring):
            issues.append({"rule": "R7", "level": "ERROR", "object": f"fence {fid}",
                           "message": "围栏边界自相交，围栏内外关系不确定"})

    # R8 POI 要素完整性：必填字段、类型合法、id 唯一
    poi_ids = [f.get("properties", {}).get("poi_id") for f in poi_features]
    for pid, n in Counter(poi_ids).items():
        if pid and n > 1:
            issues.append({"rule": "R8", "level": "ERROR", "object": f"poi {pid}",
                           "message": f"poi_id 重复 {n} 次"})
    for feat in poi_features:
        props = feat.get("properties", {})
        pid = props.get("poi_id") or "unknown"
        missing = [k for k in REQUIRED_POI_FIELDS if not props.get(k)]
        if missing:
            issues.append({"rule": "R8", "level": "ERROR", "object": f"poi {pid}",
                           "message": f"缺少必填字段: {missing}"})
        if props.get("type") and props["type"] not in POI_TYPES:
            issues.append({"rule": "R8", "level": "WARN", "object": f"poi {pid}",
                           "message": f"type={props['type']} 不在允许集合 {sorted(POI_TYPES)}"})

    return issues
