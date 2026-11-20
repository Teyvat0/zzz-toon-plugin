# 仿ZZZ渲染 · MMD

在 Goo Engine 4.4 里，把 MMD Tools 导入的《绝区零》PMX 一键配置成接近游戏的卡通渲染。

选好对应角色的游戏材质 JSON 与贴图目录，扫描、点一下按钮即可出图。插件是普通 Blender 插件（不是 DSH 插件），当前版本 0.2.1。

## 特性

- **按材质映射，无角色名单。** 每个 PMX 材质独立匹配游戏 JSON 与贴图。证据不足的槽不会硬配，会红色置顶并保留 MMD 原材质，你可以手动选 JSON，选择保存在资源目录的 `zzz_mapping.json`。
- **自带 Toon 着色器。** 运行时生成 `ZZZ_Toon_Core` / `ZZZ_Toon_Maps` 节点组，覆盖亮暗分层、面部 SDF 阴影、鼻线、MatCap 金属、头发高光、屏幕空间边缘光。
- **自带描边。** 逐面背面壳，宽度随相机距离与焦距缩放，颜色按材质 ID 分区，深色衣料上自动压暗，细小碎片不生成描边壳。
- **主光可选。** 面板里选一盏日光灯作主光，光向量与头部朝向由几何节点实时写入着色器。
- **逐槽背面剔除。** 每个槽可设自动 / 开 / 关，用来处理双面的头发、裙摆和内衬。
- **法线朝内检测。** 保留原材质的槽若法线整体朝内（原材质会渲染成黑色），会提示并自动改用几何法线渲染。
- **原生分材质与回退点。** 配置前调用 MMD Tools 原生「按材质分离」，并核对顶点、权重、形态键、UV 和作者法线等数据。材质 Morph 迁移到新分部，原骨骼和动作入口保持不变。每个阶段写完整回退文件。

## 环境要求

- Goo Engine 4.4（普通 Blender 没有等效降级）。
- 已启用的 MMD Tools。
- 你自己有权使用的绝区零 PMX，以及对应角色、对应外观的完整游戏资源目录（含 `Materials` 与 `Textures`）。
- 插件包不含角色模型、贴图、游戏 JSON 或 MMD Tools。

## 安装与使用

1. 在 Goo 中打开 编辑 → 偏好设置 → 插件 → 从磁盘安装，选择 `dist/` 下的发行 ZIP，启用「仿ZZZ渲染 · MMD」。已装旧版要先卸载，否则新旧版本冲突。
2. 用 MMD Tools 导入 PMX（常用比例 0.08），切到对象模式，选中 MMD 根物体。
3. 按 `N` 打开侧栏「仿ZZZ渲染」，选择资源目录和输出目录，点「扫描」。
4. 处理列表顶部红色的未映射槽，也可以直接忽略。
5. 点「一键配置并渲染」。输出目录里会得到新工程、PNG 和配置验证报告。

配置后想换映射或描边，请从 `00_配置前完整回退.blend` 重做，不支持在已配置的工程上热重建。完整说明见 [快速开始](<docs/快速开始.md>) 与 [插件说明](<zzz_mmd_toon/README.md>)。

## 渲染实现要点

| 部分 | 做法 |
|---|---|
| 着色 | `toon_build.py` 在运行时构建 `ZZZ_Toon_Core`，由 `toon_surface.py` 接到每个材质，三个节点组被所有材质共享 |
| 描边 | `outline_geometry.py` 生成壳，`toon_outline.py` 的 `WIDTH_K` 控制整体粗细，宽度由修改器输入 `Frame Scale`（传感器宽度 / 焦距）驱动 |
| 边缘光 | Core 内置屏幕空间边缘光，另写 `Rim` AOV 给合成器的 `ScreenSpaceRim`（默认强度 0.18，宽度 6.0，衰减 1.5） |
| 光与头部 | 插件自建的 Geometry Nodes 组 `ZZZ_LightHead` 写入 `LightDirectionWS`、`LightColor`、`HeadCenter`、`HeadForward`、`HeadRight` 属性，着色器直接读取 |
| 主光 | `lighting.py` 把 `ZZZ_LightHead` 的灯光引用与驱动改指向所选日光灯 |

## 已知限制

- 金属质感比游戏平：MatCap 是在光照之后叠加的，高光不如原作锐利。
- 部分衣料的色调与游戏有差别，例如维琳娜的蓝色裙子偏亮。
- 一次只处理一个角色，不支持多角色同场景配置。
- 渲染场景（相机、Sun、头部三个空物体、World、双 ViewLayer / AOV、合成器与 ScreenSpaceRim 节点组）、Toon 着色器、描边和灯光属性节点组全部由代码生成，不内嵌 .blend 资产。
- 渲染预览不是逐像素复现。Eye_E、物理透射、变身与武器特效未实现。
- 只用《绝区零》角色验证，其它游戏的模型不在支持范围内。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `zzz_mmd_toon/` | 插件运行时代码 |
| `build_release.py` | 打包脚本，只打包允许清单里的模块，输出到 `dist/` |
| `docs/` | `CONTRACT.md` 设计合同，`快速开始.md` 用户说明 |
| `tests/unit/` | 纯 Python 单元测试 |
| `tests/blender/` | 需要 Goo 的集成测试 |
| `tests/tools/` | 辅助脚本 |

## 开发与测试

```bash
# 单元测试
python -m unittest discover -s tests/unit -p "test_*.py"

# 检查打包清单，然后构建 ZIP
python build_release.py --check
python build_release.py

# 集成测试（Goo Engine，工作目录为仓库根；kind 可选 evelyn astra velina ye remielle）
blender --factory-startup -b --python tests/blender/blender_universal.py -- astra

# 隔离安装测试（需要 BLENDER_USER_SCRIPTS 指向一个全新目录）
blender --factory-startup -b --python tests/blender/blender_zip_install.py -- /绝对路径/发行.zip astra
```

运行 Blender 测试时请加 `--factory-startup`，否则已安装的同名插件会和源码版冲突。测试会在 `test_outputs/` 写入大量输出，可随时删除。

`blender_normal_guards.py` 有一个受 MMD Tools 导入影响的固定用例：伊芙琳每次导入得到的法线对数量在 0 到 4 之间波动，该用例要求至少 4 个，偶尔会失败，这不是插件本身的问题。

## 许可

- 插件代码（`zzz_mmd_toon/`、`build_release.py`、`tests/`）以 **GPL-3.0-or-later** 发布，全文见 [LICENSE](<LICENSE>)。
- Toon 着色器（`ZZZ_Toon_Core`、`ZZZ_Toon_Maps`、`ZZZ_Toon_Outline` 节点组）另以 **CC BY 4.0** 单独发布，署名即可自由使用、修改与商用。插件里的 `toon_*.py` 是该着色器的代码生成版本，随插件按 GPL 分发；同一作者可以对同一份作品使用两种许可。
- 本项目是同人性质的非官方项目，与米哈游无关。「绝区零」及相关名称、角色和美术资源的权利归其权利人所有。
- 仓库不含任何角色模型、游戏贴图或游戏 JSON，也不授予它们的再分发权。使用时请遵守模型、游戏资源、MMD Tools 各自的使用条款。
- 渲染场景、着色器、描边、自动映射、原生分材质和回退逻辑均由本项目代码生成，不内嵌第三方 .blend 模板。
