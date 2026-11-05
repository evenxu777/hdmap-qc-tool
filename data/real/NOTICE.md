# data/real 第三方数据说明

本目录存放用于解析与质检回归测试的真实 OpenDRIVE 路网文件，全部来自
[esmini](https://github.com/esmini/esmini) 仓库的 `resources/xodr/`。
文件内容未做修改（直接下载原始版本）。

| 文件 | 来源 URL | 许可 | 版本 | 大小 | road | junction | laneSection | 特征 |
|---|---|---|---|---|---|---|---|---|
| `multi_intersections.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/multi_intersections.xodr | MPL-2.0 | 1.4 | 501,563 B | 63 | 5 | 63 | 多 junction、多 road、signals |
| `fabriksgatan.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/fabriksgatan.xodr | MPL-2.0 | 1.4 | 65,320 B | 16 | 1 | 16 | 城市路网、多 road |
| `fabriksgatan_traffic_lights.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/fabriksgatan_traffic_lights.xodr | MPL-2.0 | 1.4 | 66,474 B | 16 | 1 | 16 | signals + objects |
| `soderleden.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/soderleden.xodr | MPL-2.0 | 1.7 | 44,002 B | 5 | 1 | 7 | revMinor 1.7、多 laneSection |
| `parking_demo.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/parking_demo.xodr | MPL-2.0 | 1.7 | 45,730 B | 7 | 1 | 7 | revMinor 1.7、objects（停车位） |
| `tunnels.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/tunnels.xodr | MPL-2.0 | 1.6 | 12,064 B | 2 | 0 | 2 | revMinor 1.6、objects（隧道） |
| `two_plus_one.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/two_plus_one.xodr | MPL-2.0 | 1.5 | 9,597 B | 1 | 0 | 5 | revMinor 1.5、单 road 多 laneSection 变宽 |
| `velodrome.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/velodrome.xodr | MPL-2.0 | 1.5 | 5,410 B | 1 | 0 | 1 | 单 road 闭环（自引用链接） |
| `curves.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/curves.xodr | MPL-2.0 | 1.4 | 9,893 B | 1 | 0 | 1 | arc / spiral / paramPoly3 几何混合 |
| `curves_elevation.xodr` | https://github.com/esmini/esmini/blob/master/resources/xodr/curves_elevation.xodr | MPL-2.0 | 1.4 | 12,533 B | 1 | 0 | 1 | 曲线 + 高程（elevationProfile） |

合计 10 份、772,986 B（约 755 KB），远低于 30 MB 上限。

- 上游许可：Mozilla Public License 2.0，许可证全文见本目录 `LICENSE-esmini.txt`
  （原始文件：https://github.com/esmini/esmini/blob/master/LICENSE，16,726 B）
- 下载日期：2026-11-05；上游分支：`master`
- MPL-2.0 允许再分发原始文件，需保留本说明与许可证信息；修改后的文件需同样以 MPL-2.0 发布。
- 这些文件仅用于本项目测试，不参与构建产物分发。

## 未采用的来源

- **CARLA**：`Unreal/CarlaUE4/Content/Carla/Maps/OpenDrive` 在 master 分支不存在（404），
  未找到稳定的纯 OpenDRIVE 目录；其地图导出需要 UE 资产，不适合直接下载，故本轮未采用。
- **Apollo**：官方地图以 `base_map.bin` / `sim_map.bin` 为主，`xodr` 导出需经工具链转换，
  未找到许可清晰的纯 `.xodr` 静态样例，故本轮未采用。
- 其余需登录、来源不明或未标注许可的站点一律未采用。
