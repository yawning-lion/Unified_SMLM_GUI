import importlib
import os
import sys

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取 sc_library 的父目录路径
project_root = os.path.join(current_dir, "../../")
# 添加到 sys.path
sys.path.append(project_root)
print(project_root)


import sc_library.parameters as params


general_parameters = params.halParameters("settings_default.xml")

# 输出 general_parameters 文件的路径
general_parameters_file = os.path.abspath("settings_default.xml")
print("General parameters file path:", general_parameters_file)

setup_name = False

if setup_name:
    general_parameters.set("setup_name", setup_name)
else:
    setup_name = general_parameters.get("setup_name")

hardware_file = os.path.abspath("xml/" + setup_name + "_hardware.xml")
print("Hardware file path:", hardware_file)

hardware = params.hardware("xml/" + setup_name + "_hardware.xml")
print("Hardware:", hardware)    # Hardware: StormXMLObject: {'ui_mode': <sc_library.parameters.ParameterString object at 0x0000019709839F90>, 'control': <sc_library.parameters.StormXMLObject object at 0x000001970983A0B0>, 'display': <sc_library.parameters.StormXMLObject object at 0x000001970983A110>, 'modules': <sc_library.parameters.StormXMLObject object at 0x0000019709CE5E70>}

for module in hardware.get("modules").getProps():
    print("module:", module)
    print("Module content:", module.toString())

modules = hardware.get("modules")
print("Modules:", modules)

parameters = hardware.get("modules").parameters
print("parameters:", parameters)

# configuration0 =  modules_props.get("configuration")    # .get("configuration")
# print("Configuration0:", configuration0)


# print("Configuration:", configuration.toString())
# print("configuration:", configuration)  
