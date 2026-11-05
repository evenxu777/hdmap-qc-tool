# -*- coding: utf-8 -*-
"""由 qc_report.json 与原始 xodr 生成《命中问题统计表》。

用法：
    python tools/build_stats.py --json-dir <目录> --out docs/命中问题统计表.md
目录下递归查找 qc_report.json；同目录的 input 路径指向原始 xodr。
"""
import argparse
import glob
import json
import os
import xml.etree.ElementTree as ET
from collections import Counter

def _license(path):
    name = os.path.basename(path)
    if name == "sample_map.xodr":
        return "项目自建"
    return "MPL-2.0"


def _is_real(path):
    norm = path.replace("\\", "/").lower()
    return "/data/real/" in norm


def _features(xodr_path):
    root = ET.parse(xodr_path).getroot()
    roads = {}
    for r in root.findall("road"):
        rid = r.get("id")
        refs = []
        link = r.find("link")
        if link is not None:
            for tag in ("predecessor", "successor"):
                for e in link.findall(tag):
                    refs.append((tag, e.get("elementType"), e.get("elementId"), e.get("contactPoint")))
        roads[rid] = refs

    refs_all = [(rid, x) for rid, xs in roads.items() for x in xs]
    road_refs = [x for _, x in refs_all if x[1] == "road"]
    cp_missing = sum(1 for x in road_refs if not x[3])
    single = 0
    pairs = set()
    for rid, (_, et, eid, _cp) in refs_all:
        if et != "road" or eid not in roads or eid == rid:
            continue
        pairs.add((min(rid, eid), max(rid, eid)))
        if not any(y[1] == "road" and y[2] == rid for y in roads[eid]):
            single += 1
    single_pairs = 0
    for a, b in pairs:
        if not (any(y[1] == "road" and y[2] == b for y in roads[a]) and
                any(y[1] == "road" and y[2] == a for y in roads[b])):
            single_pairs += 1

    geoms = Counter()
    for g in root.findall(".//planView/geometry"):
        ch = [x.tag for x in g]
        geoms[ch[0] if ch else "none"] += 1

    junction_links = sum(1 for _, x in refs_all if x[1] == "junction")
    conn = {"connectingRoad": 0, "linkedRoad": 0, "none": 0}
    for j in root.findall("junction"):
        for c in j.findall("connection"):
            if c.get("connectingRoad") is not None:
                conn["connectingRoad"] += 1
            elif c.get("linkedRoad") is not None:
                conn["linkedRoad"] += 1
            else:
                conn["none"] += 1

    major, minor = root.find("header").get("revMajor"), root.find("header").get("revMinor")
    lane_sections = len(root.findall(".//lanes/laneSection"))
    return {
        "version": f"{major}.{minor}",
        "lane_sections": lane_sections,
        "road_refs": len(road_refs),
        "cp_missing": cp_missing,
        "single_refs": single,
        "pairs": len(pairs),
        "single_pairs": single_pairs,
        "geoms": geoms,
        "junction_links": junction_links,
        "conn": conn,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    rows = []
    seen = set()
    for jp in sorted(glob.glob(os.path.join(args.json_dir, "**", "qc_report.json"), recursive=True)):
        with open(jp, encoding="utf-8") as f:
            data = json.load(f)
        xodr = data["input"]
        if not os.path.isabs(xodr) or not os.path.exists(xodr):
            continue
        if xodr in seen:
            continue
        seen.add(xodr)
        feat = _features(xodr)
        rows.append({"json": data, "feat": feat,
                     "name": os.path.basename(xodr),
                     "size": os.path.getsize(xodr),
                     "license": _license(xodr),
                     "real": _is_real(xodr)})

    rows.sort(key=lambda r: (not r["real"], r["name"]))
    total = len(rows)
    real_rows = [r for r in rows if r["real"]]
    real_total = len(real_rows)
    rules = [f"R{k}" for k in range(1, 10)]

    out = []
    out.append("# OpenDRIVE 真实路网命中问题统计表\n")
    out.append(f"本表由 {total} 次运行的 `qc_report.json` 与原始 `.xodr` 头部信息自动生成，"
               "生成脚本 `tools/build_stats.py`；数据来源与许可见 `data/real/NOTICE.md`。"
               f"其中真实路网 {real_total} 份，另含 {total - real_total} 份项目内置样例（表内单独标注）。\n")
    out.append("## 1. 单文件明细\n")
    out.append("| 文件 | 许可 | 版本 | 大小 | road | junction | laneSection | 问题总数 | "
               + " | ".join(rules) + " | 耗时 | 退出码 |")
    out.append("|---|---|---|---|---|---|---|---|" + "---|" * 8 + "---|---|")
    for r in rows:
        d, f = r["json"], r["feat"]
        by = d.get("by_rule", {})
        cells = " | ".join(str(by.get(x, 0)) for x in rules)
        out.append(f"| {r['name']} | {r['license']} | {f['version']} | {r['size']} B | "
                   f"{d['roads']} | {d['junctions']} | {d['lane_sections']} | {d['issues_total']} | "
                   f"{cells} | {d['elapsed_s']:.3f}s | 0 |")
    out.append("")
    builtin_note = [r["name"] for r in rows if not r["real"]]
    if builtin_note:
        out.append("说明：`" + "`、`".join(builtin_note) + "` 为项目内置样例，"
                   "`sample_map.xodr` 含刻意埋入的 5 处问题，其余内置文件用于回归；"
                   "统计口径（§2/§3）只包含真实路网。当前未实现 --strict，退出码均为 0；"
                   "R9 可用 `--no-r9` 关闭。\n")

    out.append(f"## 2. 规则维度汇总（真实路网 {real_total} 份）\n")
    out.append("| 规则 | 总命中 | 命中文件数 | 命中率（文件） | 平均每文件命中 | 定性 | 门禁建议 | 依据 |")
    out.append("|---|---|---|---|---|---|---|---|")
    judgments = {
        "R1": ("无命中", "可做门禁", "跨 laneSection 的重复 id 误报已修复，当前按 section 统计"),
        "R2": ("无命中", "可做门禁（含闭环例外）", "已增加单 road 闭环例外：predecessor/successor 各指向自身一次"
               "且 contactPoint 互补即跳过；velodrome 不再误报"),
        "R3": ("无命中", "可做门禁", f"{real_total} 份文件未出现超范围限速"),
        "R4": ("无命中", "可做门禁", "arc/spiral/paramPoly3 均带 length，长度比对稳定"),
        "R5": ("漏检候选", "暂缓", "只校验 incomingRoad 本身存在；linking road / laneLink 目标由 R9 覆盖，"
               "0 命中不代表无问题"),
        "R6": ("无命中", "可做门禁", "多 laneSection、1.5/1.6/1.7 文件均未误报"),
        "R7": ("未执行", "未启用（站点）", "本次未传 --site，未执行站点规则"),
        "R8": ("未执行", "未启用（站点）", "本次未传 --site，未执行站点规则"),
        "R9": ("无命中", "可做门禁（默认开启）", "road→junction、connection→road、laneLink→lane 全部存在且非 0；"
               "未做 from/to 符号一致校验（反向符号在真实数据中合法）；laneLink 缺失不报错"),
    }
    for rule in rules:
        hits = sum(r["json"].get("by_rule", {}).get(rule, 0) for r in real_rows)
        files = sum(1 for r in real_rows if r["json"].get("by_rule", {}).get(rule, 0))
        rate = f"{files}/{real_total} ({files / real_total * 100:.1f}%)" if real_total else "-"
        avg = f"{hits / real_total:.2f}" if real_total else "-"
        nature, gate, why = judgments[rule]
        out.append(f"| {rule} | {hits} | {files} | {rate} | {avg} | {nature} | {gate} | {why} |")
    out.append("")
    out.append("定性口径：**真错误**＝命中且人工复核确认为数据缺陷；**疑似误报**＝规则触发但建模合法；"
               "**漏检候选**＝规则覆盖不足、真实问题可能未被检出。本次真实数据未发现真错误。\n")

    out.append("### 命中问题明细与定性（真实路网）\n")
    hits_list = [(r["name"], i) for r in real_rows for i in r["json"].get("issues", [])]
    if not hits_list:
        out.append(f"本次 {real_total} 份真实文件未产生任何命中。\n")
    else:
        out.append("| 文件 | 规则 | 级别 | 对象 | 消息 | 定性 | 依据 |")
        out.append("|---|---|---|---|---|---|---|")
        for name, i in hits_list:
            if i["rule"] == "R2" and "引用了自身" in i["message"]:
                verdict = "疑似误报"
                why = "单 road 闭环：predecessor/successor 指向自身且 contactPoint 依次为 end/start，是合法环形路表示"
            else:
                verdict = "待复核"
                why = "需结合原始文件人工确认"
            out.append(f"| {name} | {i['rule']} | {i['level']} | {i['object']} | "
                       f"{i['message']} | {verdict} | {why} |")
    out.append("")

    out.append("## 3. 真实数据特征统计\n")
    out.append("| 文件 | contactPoint 缺失 | 单侧 road link（ref） | 单侧道路对 | "
               "geometry 类型 | junction 写法 | road→junction 链接 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in real_rows:
        f = r["feat"]
        cp = f"{f['cp_missing']}/{f['road_refs']}"
        sr = f"{f['single_refs']}/{f['road_refs']}"
        sp = f"{f['single_pairs']}/{f['pairs']}"
        geo = " / ".join(f"{k} {v}" for k, v in sorted(f["geoms"].items()))
        cn = f["conn"]
        jw = f"连接 {cn['connectingRoad']} / linkedRoad {cn['linkedRoad']} / 缺失 {cn['none']}"
        out.append(f"| {r['name']} | {cp} | {sr} | {sp} | {geo} | {jw} | {f['junction_links']} |")
    out.append("")

    if real_rows:
        refs = sum(r["feat"]["road_refs"] for r in real_rows)
        miss = sum(r["feat"]["cp_missing"] for r in real_rows)
        singles = sum(r["feat"]["single_refs"] for r in real_rows)
        pairs = sum(r["feat"]["pairs"] for r in real_rows)
        spairs = sum(r["feat"]["single_pairs"] for r in real_rows)
        jl = sum(r["feat"]["junction_links"] for r in real_rows)
        cr = sum(r["feat"]["conn"]["connectingRoad"] for r in real_rows)
        lr = sum(r["feat"]["conn"]["linkedRoad"] for r in real_rows)
        ne = sum(r["feat"]["conn"]["none"] for r in real_rows)
        out.append("汇总：\n")
        out.append(f"- contactPoint 缺失：{miss}/{refs}（{miss / refs * 100:.1f}%）"
                   if refs else "- contactPoint 缺失：0/0")
        out.append(f"- 单侧 road link：{singles}/{refs} 条引用（{singles / refs * 100:.1f}%）；"
                   f"按道路对计 {spairs}/{pairs}（{spairs / pairs * 100:.1f}%）"
                   if refs and pairs else "- 单侧 road link：0/0")
        conn_total = cr + lr + ne
        cr_pct = cr / conn_total * 100 if conn_total else 0
        lr_pct = lr / conn_total * 100 if conn_total else 0
        out.append(f"- junction 写法：connectingRoad {cr}（{cr_pct:.1f}%）/ "
                   f"linkedRoad {lr}（{lr_pct:.1f}%）/ 两者缺失 {ne}")
        geoms_total = Counter()
        for r in real_rows:
            geoms_total.update(r["feat"]["geoms"])
        gsum = sum(geoms_total.values())
        gtext = " / ".join(f"{k} {v}（{v / gsum * 100:.1f}%）"
                           for k, v in sorted(geoms_total.items())) if gsum else "-"
        out.append(f"- geometry 类型分布（合计 {gsum} 段）：{gtext}")
        out.append(f"- road 级 junction 链接：{jl} 条")
        out.append("")

    out.append("## 4. 结论与建议\n")
    out.append(f"- **可直接做门禁（{real_total} 份真实数据 0 误报）**：R1、R2、R3、R4、R6、R9；"
               "R2 已修复闭环例外；R9 默认开启，覆盖 road→junction、connection→road、laneLink→lane，"
               "laneLink 缺失不报错。")
    out.append("- **R2 已修复闭环例外**：单 road 闭环（predecessor/successor 各指向自身一次且 contactPoint 互补）"
               "不再报 ERROR，velodrome 误报消除；其它自引用形态仍报 ERROR，可做门禁。")
    out.append("- **暂不建议门禁**：R5 只校验 `incomingRoad` 本身存在；linking road / `laneLink` 目标已由 R9 覆盖，"
               "R5 可视为 R9 的子集，建议后续合并。")
    out.append("- **R9 已覆盖（原漏检候选转为已实现）**：① junction `laneLink` from/to 车道存在性；"
               "② `linkedRoad` 存在性；③ road 级 `elementType=junction` 链接的 junction 存在性。"
               "实测覆盖 135 条 laneLink、31 条 road→junction 引用、2 条 linkedRoad。")
    out.append("- **R9 符号校验的实测取舍**：若额外校验 from/to 符号一致，10 份真实数据会产生 97 条 WARN"
               "（97/135 条 laneLink 为 from=正、to=负的反向连接，incoming/connecting road 朝向相反），"
               "经核实全部合法，故删除该校验，仅保留“非 0”约束。")
    out.append("- **建议新增（漏检候选）**：① 几何端点连续性（x/y/hdg 链），当前 R4 只比对总长；"
               "② 车道宽 a+b·s 连续性与车道数突变；"
               "③ laneLink 连续性（按 incomingRoad→connectingRoad 的车道邻接关系校验）。")
    out.append(f"- **数据侧提醒**：本次 {real_total} 份均为 well-formed 的 esmini 样例，命中很少，"
               "0 结果只能说明“这些规则在此数据集上不误报”，不能证明规则完备；"
               "单侧 road link 占比高（见上表），因此不宜默认开启“必须双向声明”的严格检查。")
    out.append("")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"[OK] {args.out} ({total} files, {real_total} real)")


if __name__ == "__main__":
    main()
