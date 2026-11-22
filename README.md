# 仿ZZZ渲染 · MMD

把 MMD Tools 导入的《绝区零》PMX 模型，在 Goo Engine 4.4 里一键配置成接近游戏的卡通渲染。

你只需要提供模型对应的游戏材质 JSON 和贴图目录，点「扫描」，再点「一键配置并渲染」，就能得到一个可以继续编辑的 .blend 工程和一张预览图。之后导入动作、烘焙物理、摆相机、渲染视频，都按平常的 MMD 流程来。

> 本项目是同人性质的非官方项目，与米哈游无关。仓库不含任何角色模型、游戏贴图或游戏数据。

当前版本 0.2.2，下载见 [Releases](https://github.com/Teyvat0/zzz-toon-plugin/releases)。着色器部分单独开源：[zzz-toon-shader](https://github.com/Teyvat0/zzz-toon-shader)。

## 特性

- **按材质匹配，没有角色名单。** 每个 PMX 材质单独关联游戏 JSON 与贴图。证据不足的槽不会硬配：它们在列表顶部标红并保留 MMD 原材质，你可以手动选择 JSON，选择会保存在资源目录的 `zzz_mapping.json`，下次扫描自动沿用。
- **自带 Toon 着色器。** 三段明暗、脸部 SDF 阴影、鼻尖线、MatCap 金属、头发高光、屏幕空间边缘光，节点组在运行时由代码生成。
- **自带描边。** 逐面背面壳，线宽随相机距离和焦距缩放，颜色按材质 ID 分区，深色衣料上自动压暗，细小零件不描边。
- **可选主光。** 在面板里选一盏日光灯作为主光，着色器实时读取它的方向和颜色。
- **逐槽背面剔除。** 每个槽可设自动 / 开 / 关，用来处理双面的头发、裙摆和内衬。
- **法线朝内检测。** 对保留原材质的槽，如果法线整体朝内（原材质会渲染成黑色），会提示并自动改用几何法线渲染。
- **回退点。** 配置前调用 MMD Tools 原生的「按材质分离」，并核对顶点、权重、形态键、UV 和自定义法线是否一致；每个阶段都会写一个完整的回退 .blend。原骨骼、动作入口和材质 Morph 保持可用。

## 环境要求

- Goo Engine 4.4（普通 Blender 没有等效降级，版本不符时插件会中止）。
- 已启用的 [MMD Tools](https://github.com/MMD-Blender/blender_mmd_tools)。
- 你有权使用的《绝区零》PMX 模型。
- 与该角色、该外观对应的游戏资源目录，里面要有 `Materials`（材质 JSON）和 `Textures`（贴图）两个子目录。
- 插件本身不带模型、贴图、JSON，也不会替你安装 MMD Tools。
## 安装

1. 从 [Releases](https://github.com/Teyvat0/zzz-toon-plugin/releases) 下载 `zzz_mmd_toon_*.zip`，不要解压。
2. 用 Goo Engine 打开 编辑 → 偏好设置 → 插件 → 从磁盘安装，选择这个 ZIP，勾选启用「仿ZZZ渲染 · MMD」。
3. 如果装过旧版，先卸载旧版再安装，否则两个版本会冲突。

## 使用

1. 用 MMD Tools 导入 PMX（常用导入比例 0.08），切到对象模式，选中 MMD 根物体。
2. 在 3D 视图按 `N` 打开侧栏，进入「仿ZZZ渲染」页签。
3. 填「资源目录」（角色的游戏资源）和「输出目录」，点「扫描」。
4. 看一眼列表顶部标红的未映射槽。可以为它们选 JSON，也可以不管，它们会保留 MMD 原材质。
5. 点「一键配置并渲染」。如果还有未映射的槽，第一次点击只给提示，再点一次才会继续。
6. 输出目录里会得到新的 .blend 工程、一张 PNG 预览和一份配置验证报告。

配置完成后，主光、描边倍率等设置可以继续调。想换映射，请回到 `00_配置前完整回退.blend` 重新做，插件不支持在已配置的工程上热重建。

更详细的说明见 [快速开始](docs/快速开始.md) 和 [插件说明](zzz_mmd_toon/README.md)。

## 常见问题

**某个材质渲染成纯黑。** 多半是该材质的法线朝内。如果它是保留原材质的槽，插件会自动改用几何法线并在列表里提示；更好的做法是为它选一个对应的游戏 JSON。

**头发或裙摆的背面不见了 / 多出一层。** 这是背面剔除的问题。游戏数据里很多材质是双面的，插件按数据自动决定；个别槽不对时，在该槽的「背面剔除」里改成「开」或「关」。

**描边偏粗或偏细。** 每个槽有自己的描边宽度，面板里还有整体的描边倍率。

**换角色或换外观。** 一个工程一次只配置一个角色。换角色请新开工程。

## 已知限制

- 金属质感比游戏平。MatCap 是在光照之后叠加的，高光不如原作锐利。
- 部分衣料的色调与游戏有差别，比如维琳娜的蓝色裙子偏亮。
- 一次只处理一个角色，不支持同一场景里配置多个角色。
- 不是逐像素复现。Eye_E、物理透射、变身和武器特效没有实现。
- 只用《绝区零》的角色验证过，其它游戏的模型不在支持范围内。
## 仓库结构

| 路径 | 内容 |
|---|---|
| `zzz_mmd_toon/` | 插件运行时代码 |
| `build_release.py` | 打包脚本，只打包白名单里的模块，输出到 `dist/` |
| `docs/` | `CONTRACT.md` 设计约定，`快速开始.md` 使用说明 |
| `tests/unit/` | 纯 Python 单元测试 |
| `tests/blender/` | 需要 Goo Engine 的集成测试 |
| `tests/tools/` | 辅助脚本 |

## 实现概览

| 部分 | 做法 |
|---|---|
| 着色 | `toon_build.py` 在运行时构建 `ZZZ_Toon_Core`，`toon_surface.py` 把它接到每个材质；三个节点组被所有材质共享 |
| 描边 | `outline_geometry.py` 生成壳，`toon_outline.py` 的 `WIDTH_K` 决定整体粗细，宽度由修改器输入 `Frame Scale`（传感器宽度 / 焦距）驱动 |
| 边缘光 | Core 内置屏幕空间边缘光，同时写 `Rim` AOV 给合成器节点组 `ZZZ_ScreenSpaceRim` |
| 光与头部朝向 | `light_head.py` 的几何节点组 `ZZZ_LightHead` 把光向、光色、头部中心 / 朝向 / 右向写成点属性，着色器直接读取 |
| 渲染场景 | `renderer*.py` 用代码建立相机、Sun、头部空物体、World、双 ViewLayer 与合成器，不内嵌任何 .blend 资产 |

## 开发与测试

```bash
# 单元测试
python -m unittest discover -s tests/unit -p "test_*.py"

# 检查打包清单，然后构建 ZIP
python build_release.py --check
python build_release.py
```

集成测试需要 Goo Engine，并且要告诉测试在哪里找依赖和你自己的模型：

```bash
cp tests/fixtures.example.json tests/fixtures.json   # 填入自己的 PMX 与资源目录，该文件已被 .gitignore 忽略
export ZZZ_MMD_TOOLS_PARENT=/path/to/extensions/blender_org   # 包含 mmd_tools 的目录，可省略（会尝试 Blender 4.4 默认位置）
export ZZZ_GOO_EXE=/path/to/blender   # Goo 可执行文件，可省略（在 Goo 内运行时自动取当前程序）

# 端到端：导入 PMX、配置、渲染并校验（kind 为 fixtures.json 里的键）
blender --factory-startup -b --python tests/blender/blender_universal.py -- astra

# 隔离安装测试（BLENDER_USER_SCRIPTS 需指向一个全新目录）
blender --factory-startup -b --python tests/blender/blender_zip_install.py -- /绝对路径/发行.zip astra
```

运行 Blender 测试时要加 `--factory-startup`，否则已安装的同名插件会和源码版冲突。测试输出写在 `test_outputs/`，可随时删除。

`blender_normal_guards.py` 里有一个用例依赖 MMD Tools 导入的结果：同一个模型每次导入得到的特定法线对数量在 0 到 4 之间波动，用例要求至少 4 个，所以偶尔会失败。这与插件本身无关。

## 许可

- 插件代码（`zzz_mmd_toon/`、`build_release.py`、`tests/`）以 **GPL-3.0-or-later** 发布，全文见 [LICENSE](LICENSE)。
- Toon 着色器的节点组（`ZZZ_Toon_Core`、`ZZZ_Toon_Maps`、`ZZZ_Toon_Outline`）另以 **CC BY 4.0** 发布，见 [zzz-toon-shader](https://github.com/Teyvat0/zzz-toon-shader)。插件里的 `toon_*.py` 是它的代码生成版本，随插件按 GPL 分发。
- 「绝区零」及相关名称、角色和美术资源的权利归其权利人所有。本仓库不授予这些内容的再分发权，使用时请遵守模型、游戏资源和 MMD Tools 各自的条款。

## 开发方式

本插件的代码、测试与文档由 [dsh（DeepSeek Harness）](https://github.com/deepseek-ai/deepseek-harness) 驱动的 AI 编程代理完成，使用的模型有 Opus 5.5、Sonnet 5.5、GPT 6.1 Sol 和 DeepSeek V4.1 Flash。作者负责需求、方向与验收。

[![](https://img.shields.io/badge/powered_by-dsh-4D6BFE?style=flat-square&logo=deepseek&logoColor=white)](https://github.com/deepseek-ai/deepseek-harness)
