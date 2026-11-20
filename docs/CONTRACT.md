# v0.2.1 通用绝区零资源渲染合同（原生分材质）

## 用户要求与范围
- 用户自行用 MMD Tools 导入 PMX，必须选择对应角色的游戏 JSON / 贴图目录，再一键配置与渲染。
- 同一资源扫描、JSON 解析、像素 atlas 关联、材质语义与状态判断、节点构建流程用于不同绝区零角色。运行时代码不得使用角色名、专用 profile、模型路径、骨数作为准入条件或分支。
- 不开发无游戏资源从头生成 Toon 的路线。资源目录缺失/无效仍整体阻断。**（放宽，0.2.1 后期）** 单个材质槽证据不足或候选不唯一时，该槽标为“未映射”并默认保留 MMD 原材质（`keep_original`，不挂游戏材质、不生成描边），整体不再阻断；用户可在面板里从该槽自己的候选 JSON 中改选，选择写入资源目录 `zzz_mapping.json` 并标记 `user_selected`。UI 的一键渲染在仍有未映射槽时，第一次点击只提示，第二次忽略它们继续。结构推断、可选未解析项分别列出，不能伪称精确 PathID 解码或游戏原样复现。基础 JSON 与其 `_T`/`_T_UI` 变体共用同一贴图族时按基础 JSON 处理。
- 共用 atlas 不等于同一材质：Face / Eye / Brow 和透明变体保持逐原材质身份。

## 原生数据、Morph 与事务
- **实际调用** `bpy.ops.mmd_tools.separate_by_materials(clean_shape_keys=False)`，在渲染场景创建与着色之前执行；环境预检可以在先。Object / Mesh 身份、名称、局部顶点 / 材质槽 / 面索引允许改变，不承诺“不拆网格”或原 Object / Mesh ID 不变。逐面原 Material 数据块与已初始化的原生 Material ID 保留，不按 MainTex 合并、不用新渲染 Material 重定向目标，不重绑 / 自动权重。
- **exact provenance 是分离准入证据。** 临时原 POINT / EDGE / CORNER / FACE 索引核对坐标、全部命名权重（含零权重、unused 组与锁）、全部形态键坐标及元数据、UV active / render / clone 与默认颜色层结构、边 / 角 / 绕序、逐面原 Material / smooth 与作者属性原始存储；原 FACE / CORNER 恰好一次，POINT / EDGE 全覆盖并允许材质边界复制。原骨名称、rest / 父级不变。作者法线保护 signed-short2、sharp / smooth 与边 / 角拓扑，不以四舍五入语义哈希或运行时 `corner_normals` 替代；只在原层存在且来源子集全 False 时按原索引恢复分离省略的 sharp / 现有 UV pin BOOLEAN 存储，记计数与字节哈希，其它缺失阻断、不重算法线。
- **直接迁移** 材质 Morph `related_mesh_data` 至含同一原 Material 的分部 Mesh，保留 `material_data` 与数值 `material_id`；“全部材质”无专属 Mesh，使用 `None`。记录迁移及初始化证据，不删除 / 重建 Morph、不要求用户手绑。负值未初始化 Material ID 仅通过 MMD Tools 原生 API 在 `00` 后初始化，不把重复 ID 或不唯一 legacy 目标当可自动修复的输入。
- provenance、Morph 与骨架检查后清理临时标记 / 原生 SDEF 运行时缓存，建立分离后严格作者数据基线；场景 / 材质挂接须匹配该基线。旧式 UV Morph `DATA`、`_temp` 材质预览、`__uv.` 预览、特定 Mesh-only drivers、以原网格为目标的外部约束 / 修改器等按 `native_split` 诊断阻断。空网格、共享 / 只读数据与不唯一目标不隐式迁就；建议在干净导入副本配置后再加动作 / 物理，复杂自定义动画需独立验证。
- 原生 MMD shader 节点保留。私有节点组暴露实例 Diffuse / Alpha 输入，使之后正常材质 Morph 绑定仍可驱动游戏表面和描边；不保证所有 Ambient / Specular / Sphere 参数与原游戏或全部 MME 效果等效。
- 原材质 Alpha 通过同一原 Material 同时控制表面与生成描边。shell 仅存在于**分部**的修改器求值，以 FACE 属性区分原面 / shell、屏蔽 shell 的 AOV 写入，不写回分部 Mesh、不插入替代材质槽；这不否认原生分离已改变网格布局。
- 顺序为：输入预检 → **`00_配置前完整回退.blend`** → 原生分离 / provenance / Morph 迁移 → **`01_原生分材质_着色前回退.blend`** → 渲染场景 → 材质 → 严格检查与保存。`00` 是恢复原布局、重新配置的权威起点，成功配置面板默认指向它；`01` 是已分离但未着色的中间文件，报告 `separated_checkpoint` 定位它，不是半完成状态重跑入口。
- 原生物理独立显式构建已有刚体 / 关节；构建前另存最近 **`02_原生物理构建前回退.blend`**（可带序号，含新增动作），物理失败使用最新 `02`。构建不代表缓存烘焙、无穿模、任意跳帧一致或任意舞蹈认证，不清理用户缓存。
- 唯一输出目录、禁止覆盖输入 / 既有工程 / 回退点。重复配置严格验证后才 no-op，不叠加节点 / 修改器 / 物理，不重算基线掩盖改动；旧版本必须从原工程或 `00` 开始。源 / 渲染场景共享分部模型数据，切场景不撤销分离或桥接；打开完整文件回退会放弃未保存状态。

## 可验证的 Goo 视觉策略
- 新 `render_policy = mmd-game.v2-native-cull-transparent-eye-shadow` 与 mesh schema 分开验证；旧 0.2.1 配置不得自动重采样 shader 基线。必须从原 PMX / `00` 重新配置。
- 背面剔除保留原材质已开启值与 PMX 单面要求；直接 JSON 表面的明确 `_Cull=2` 不被 `_DoubleSided=1` 取消，眼 / 口 / 贴花域仍用其双面预览策略；借参数的独立叠层保留自己的原生剔除。不是角色 / 槽位特例，也不声称原游戏或所有 Unity pass 剔除等效。
- `eye_shadow` / `eye_shadow_texture` 改为有色 Transparent BSDF，分别保留常量覆盖 / 独立解析 atlas Alpha，再乘原生实例 Alpha；不执行黑色 Forward、描边或 AOV。原 Diffuse Morph 继续以比值驱动透射色；Alpha=0 白色透射。唯一可调 `EyeShadowTint` RGB(A) 是受限0..1有限值用户控件（A不作不透明度），其它链接 / 节点 / raster 状态仍严格守卫；默认线性透射(.713,.687,.687)是预览选择，不是游戏参数等效证明。

## 自带 Toon 着色器、描边与主光
- 渲染不再依赖模板内的 ForwardShader / DecodeLightTex / DecodeMatCap / OutlineShader。运行时由 `toon_surface` 为每个材质建表面：节点 `ZZZ_Toon`（共享节点组 `ZZZ_Toon_Core`）、`ZZZ_Toon_Maps`、`ZZZ_BaseTint`（颜色乘法）与 `ZZZ_AlphaMul`（Alpha 乘法）。节点组由 `toon_build` / `toon_maps` / `toon_core` / `toon_lib` 在运行时生成并带 `zzz_owner` 标记，不再从 blend 资产读取。
- `ZZZ_Toon_Core` 输出 Shader、Avatar、AOV Normal、AOV Rim。`game_bridge` 在包装组里写 Avatar / Normal / Rim AOV（shell 不写）。`Rim AOV Strength` 默认 0.18，且只在受光一侧（N·L 的平方）写入；`renderer_rim.py` 自建的合成器节点组 `ZZZ_ScreenSpaceRim` 的 Width / Fadeout 设为 6.0 / 1.5，得到约 3 像素的柔和内侧光边（与原版峰值 +7..13 亮度级同量级）。核心内置边缘光仍生效。
- 描边：`toon_outline.ZZZ_Toon_Outline` 着色器，颜色为最终线性值（`application._palette` 不再除以 0.2）；`outline_geometry` 的 shell 宽度为 距离 × Frame Scale × 宽度 × `WIDTH_K`（0.0007），Frame Scale 由场景相机 sensor/lens 驱动。面积小于画面 0.55%（`SMALL_ISLAND`）的零碎网格岛不生成 shell（耳饰、纽扣）；深色布料上线色按布料亮度压暗（`DARK_K` 0.35，`ZZZ_BaseTint` 接入描边着色器的 Base Color）。shell 在自建 `ZZZ_LightHead` 组（`light_head.py`）之后运行，保留 LightDirectionWS / LightColor / HeadCenter / HeadForward / HeadRight 属性。
- 主光：着色器实时读取`ZZZ_LightHead` 写入的点属性（光向、头部中心 / 朝向 / 右向），无写死常量。`lighting.set_main_light` 把 GN 的物体输入与 4 个驱动（颜色 r/g/b、强度）改指向用户选择的日光灯，侧栏“主光（日光灯）”在首次配置后出现；清空则回到场景自带的 Sun。`validation` 按当前主光校验驱动。
- 逐槽背面剔除覆盖：映射行的 `cull`（AUTO/ON/OFF，默认 AUTO=按游戏 `_Cull/_DoubleSided`）。ON/OFF 只改最终材质的 `use_backface_culling`（`game_bridge.culling_policy(override=)`），随 `zzz_mapping.json` 记住；保留原材质的槽位不受影响。全局强制开启会让头发、披风、裙摆等双面薄片缺失，因此不提供全局开关。
- 保留原材质的法线审计：`normal_audit.audit` 在扫描阶段检查未映射、保留 MMD 原材质的槽位；自定义法线与面法线相反的角点比例大于 50%（且至少 30 个角点）时，原生 mmd_shader 会渲染成纯黑，插件在计划警告与列表行中提示该槽位，应用时只在该材质自己的 mmd_shader 组内给 Diffuse/Glossy 节点接入几何法线（节点 `ZZZ_TrueNormal`，`normal_audit.repair`），不改写网格法线，也不动其他节点；仍建议为它选择 ZZZ JSON。选择 JSON 后走 ZZZ 着色路径，不受反向法线影响。绝区零角色目前仅星见雅的“衣内”触发。
- 金属高光为已知差异：核心的 MatCap 在光照之后叠加，原版在光照之前乘入反照率，金属件（如克拉蕾腰饰、诺姆护手）高光偏平；全局调参会让其它角色偏离，未做改动。
- 渲染场景完全由代码生成：`renderer_scene.py`（场景、相机、Sun、头部空物体、World、ViewLayer / Eye 双层与 AOV、集合）、`renderer_rim.py`（合成器与 `ZZZ_ScreenSpaceRim` 节点组）、`light_head.py`（`ZZZ_LightHead` 几何节点与 4 个灯光驱动）、`renderer.py`（挂接模型、头部坐标、相机取景）。不内嵌 .blend 资产，无哈希合同。

## 证据式 MME 重复效果层边界
- **参数关联不等于安全隐藏。** 同源叠层在 100% exact 有向位置 + 全部 UV + 三角 multiplicity 覆盖、独立语义约束及所有排名前兼容 JSON 完整路径 / 数据族唯一时才借参数，保留源色、Alpha 与可见性，不声称动画重复。`MME_DUPLICATE_OFF` 另须完整 weights / 全部 ShapeKey / 作者法线空间等精确证明、无独有三角、无相关 Morph / 动画风险、供体 / 效果层双面一致、可解码 sphere **ADD（`sphere_texture_type == '2'`）** 和源主图全部像素 **Alpha max `<= 0.35`**；主图 / sphere 必须是无 Image 动画的静态 `FILE` / `GENERATED`，序列 / 影片当前帧不能证明时间范围。独立 smooth fan 不能证明、权重不同或任何隐藏证据不足则保留；关联不唯一则阻断。禁用旧 `> 0.995` / round-6 无向位置集合判据，名字、发色与固定角色不能替代证明。
- 命中分部归入 `ZZZ_MME重复叠层_保留关闭_...`、前缀 `MME_OFF_`，默认 `hide_render=True`；保留网格、原 Material 与 Morph，不删除、不硬改发色、不改写源贴图或输入。保留 `zzz_effect_was_hide_render` 与报告 / `zzz_effect_parts` 判据，可在该分部 Outliner 相机开关恢复**当前游戏 Forward 叠层显示**，不是恢复原 MME 原样效果。
- 需要未挂接游戏着色的原生材质状态，应打开 `00`（原布局）或 `01`（已分离、未着色）完整文件；不是取消隐藏或切回旧 Scene。源数据保留不等于所有 MME、加算 / 混合状态已等效实现；工程携带贴图也不允许删除资源目录，重复运行仍校验原资源哈希。

## 模块、许可与验证
- `resources.resolve_catalog`：显式引用优先；保留原始 Name / FileID / PathID。仅唯一结构关系或独立 PMX 图像证据可标记 `inferred`；这不是 PathID 解码或游戏原绑定确证，多候选 MatCap 不猜。
- `auto_mapping.plan`：必需资源目录、每材质独立语义 / 状态，图像相似度仅关联 atlas，零误差并列不能按文件排序选择；记录重复效果层的几何 / 源 Alpha / sphere 判据。
- `native_split.separate`：实际原生分离、exact provenance、Morph 引用迁移、临时标记 / SDEF 缓存清理和分离后基线；`workflow.run` 按 `00` → 分离 → `01` → 渲染场景 / 着色执行，不能以旧的无分离入口替代。
- `application.apply`：全部选中 JSON / 图像解码与文件哈希先于任何原材质提交。`game_bridge.attach` / `outline_geometry.attach` 保留原 Material 身份，在已分离分部挂桥 / GN，独立描边色 / 宽度、动态原生 Alpha、shell AOV 屏蔽；不再承诺原 Object / Mesh ID 或原槽布局不变。
- `validation`：v3 `authored-mesh.v3-shape-attribute-uv-structure` 守护稳定 typed attrs（含 crease / 自定义名 / UV pin）、全组及权重、UV 结构、ShapeKey 相对关系 / 分组 / use_relative / reference / frame / interpolation / lock_shape / 坐标，以及原骨、Material / Morph 目标、桥、游戏节点与 GN；正常 value / eval_time、原生 slider / mute、实例 Diffuse / Alpha 与动作不冻结。未知类型阻断，旧基线不重采样，不把局部 gate 当碰撞 / 全动画认证。
- `dependencies`：当前可见依赖须有效；隐藏分部 / 断开原生节点 / 嵌套组中所有有效保留图另打包并存实际 packed bytes 哈希，重开复验。无效且不参与渲染的旧 Toon 仅诊断，不升级成必需；有效 retained pack 失败阻断。
- `transaction`：只读全文件原生 ID / Morph 预检在 `00` 前拒绝重复非负 ID、无指针数值目标与不一致；保存后比对 handler 改动。异常写出的文件旁记 `.INVALID_SAVE.json`、`trusted_checkpoint=False`，保留诊断但绝不宣称可信回退或自动回滚。
- 不内嵌任何模板 .blend；角色资产由用户提供，本地集成不授予公开配布、商业分发或角色资产再分发权。原始和已交付版本不覆盖。
- 验证仅用绝区零模型；伊芙琳、耀嘉音为用户指定无预设测试，维琳娜和旧角色为额外回归目标。**这是测试范围要求，不是已完成 / 全通过声明。** 实测记录必须区分静态检查、mock 单测、真实配置渲染、保存重开、Morph / VMD、连续物理、隔离 ZIP 安装；不把其中一项代替其它项，结论以实际记录为准。
- 用户操作细节见[完整说明](<../zzz_mmd_toon/README.md>)与[快速开始](<快速开始.md>)；链接相对目录可移植，文档不以本机绝对路径或角色预设代替合同。
