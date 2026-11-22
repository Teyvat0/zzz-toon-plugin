"""仿ZZZ渲染: user imports PMX, chooses material folder, clicks render."""
bl_info = {
    'name': '仿ZZZ渲染 · MMD',
    'author': 'Teyvat0',
    'version': (0, 3, 0),
    'blender': (4, 4, 0),
    'location': '3D View > Sidebar > 仿ZZZ渲染',
    'description': '无角色白名单：PMX加对应游戏JSON/贴图，通用关联与渲染，保留原骨架和材质Morph',
    'category': 'Material',
    'warning': 'Requires Goo Engine 4.4 and MMD Tools; scene, shaders and compositor are built by code',
}


def register():
    from . import ui
    ui.register()


def unregister():
    from . import ui
    ui.unregister()
