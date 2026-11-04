# -*- coding: utf-8 -*-
"""
site_map_preview.py — 矿区站点静态地图样例渲染（第四个个人项目的最小产出）

读取 data/site 下的 roads/poi/geofence GeoJSON，渲染一张静态 PNG：
    道路（按单向/双向区分线型）+ 坡度标注 + 装载/卸载/加油 POI + 电子围栏
同时导出合并后的 out/site_static_map.geojson（可直接在 QGIS / geojson.io 打开）。

用法：
    python site_map_preview.py --site data/site --out out
产物：
    out/site_map.png
    out/site_static_map.geojson
"""
import argparse
import json
import os


def load_features(site_dir, name):
    p = os.path.join(site_dir, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f).get("features", [])


POI_STYLE = {  # (颜色, 标记, 中文名)
    "load": ("#1f77b4", "^", "装载点"),
    "unload": ("#d62728", "v", "卸载点"),
    "fuel": ("#ff7f0e", "s", "加油点"),
    "parking": ("#7f7f7f", "P", "停靠区"),
    "dump": ("#8c564b", "D", "排土点"),
}


def main():
    ap = argparse.ArgumentParser(description="矿区站点静态地图预览")
    ap.add_argument("--site", default=os.path.join("data", "site"))
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    roads = load_features(args.site, "roads.geojson")
    poies = load_features(args.site, "poi.geojson")
    fences = load_features(args.site, "geofence.geojson")

    # 合并导出为一份站点静态地图 GeoJSON
    merged = {"type": "FeatureCollection",
              "features": [{"type": "Feature", "properties": {**f["properties"], "layer": "road"},
                            "geometry": f["geometry"]} for f in roads]
              + [{"type": "Feature", "properties": {**f["properties"], "layer": "poi"},
                  "geometry": f["geometry"]} for f in poies]
              + [{"type": "Feature", "properties": {**f["properties"], "layer": "geofence"},
                  "geometry": f["geometry"]} for f in fences]}
    gj_path = os.path.join(args.out, "site_static_map.geojson")
    with open(gj_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon

        # 中文字体回退：Windows 优先雅黑，Linux/mac 依次尝试，缺失时降级为英文标注
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except ImportError:
        print("[WARN] 未安装 matplotlib，仅导出 GeoJSON；pip install matplotlib 后重跑可出 PNG")
        print(f"[OK] GeoJSON: {gj_path}")
        return

    fig, ax = plt.subplots(figsize=(11, 8))

    # 1) 电子围栏（半透明面）
    for f in fences:
        ring = f["geometry"]["coordinates"][0]
        ax.add_patch(MplPolygon(ring, closed=True, facecolor="#cfe8cf", edgecolor="#2e7d32",
                                alpha=0.45, linewidth=1.5, zorder=1))
        # 标签放围栏左上角，避免与 POI 标注重叠
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        ax.text(min(lons) + 0.0003, max(lats) - 0.0004, f["properties"].get("name", ""),
                fontsize=9, color="#2e7d32", ha="left", va="top", zorder=3)

    # 2) 道路：单向实线 + 箭头感，双向虚线；坡度标在道路中点
    for f in roads:
        coords = f["geometry"]["coordinates"]
        xs, ys = [p[0] for p in coords], [p[1] for p in coords]
        props = f["properties"]
        ax.plot(xs, ys, color="#333333", linewidth=4 if props.get("oneway") else 3,
                linestyle="-" if props.get("oneway") else "--", zorder=2)
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        slope = props.get("slope_pct")
        label = f"{props.get('name', '')}"
        if slope is not None:
            label += f"  {slope:g}%"
        ax.annotate(label, (mx, my), textcoords="offset points", xytext=(0, 10),
                    fontsize=8.5, color="#333333",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#999999", alpha=0.85), zorder=5)

    # 3) POI 要素（标签交替上下偏移，降低重叠概率）
    for idx, f in enumerate(poies):
        props = f["properties"]
        pt = f["geometry"]["coordinates"]
        color, marker, _ = POI_STYLE.get(props.get("type"), ("#9467bd", "o", props.get("type", "")))
        ax.plot(pt[0], pt[1], marker=marker, color=color, markersize=11, zorder=6)
        dy = -14  # 统一放在点位下方，避开 y≈31.3022 的主运输道路
        ax.annotate(props.get("name") or props.get("poi_id", ""), pt, textcoords="offset points",
                    xytext=(8, dy), fontsize=8.5, color=color, zorder=7)

    from matplotlib.lines import Line2D
    legend = [
        Line2D([0], [0], color="#333333", lw=4, label="one-way road"),
        Line2D([0], [0], color="#333333", lw=3, ls="--", label="two-way road"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#cfe8cf", markersize=10, label="geofence"),
    ]
    for t, (c, m, label) in POI_STYLE.items():
        legend.append(Line2D([0], [0], marker=m, color="w", markerfacecolor=c, markersize=9, label=label))
    ax.legend(handles=legend, loc="lower right", fontsize=8.5)
    ax.set_title("Mine Site Static Map (sample)")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")  # 关闭 +3.13e1 这类科学计数偏移
    ax.grid(alpha=0.3)
    ax.margins(0.04)
    fig.tight_layout()
    png_path = os.path.join(args.out, "site_map.png")
    fig.savefig(png_path, dpi=150)
    plt.close(fig)

    print(f"[OK] 道路 {len(roads)} 条，POI {len(poies)} 个，围栏 {len(fences)} 个")
    print(f"[OK] PNG: {png_path}")
    print(f"[OK] GeoJSON: {gj_path}")


if __name__ == "__main__":
    main()
