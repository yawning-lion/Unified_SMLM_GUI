#!/usr/bin/python
#
## @file
#
# For running modules outside of HAL.
#
# Hazen 03/14
#

# Add current storm-control directory to sys.path
import imp
imp.load_source("setPath", "D:/GXD/Python_control_gxd/Focus_lock_IX83_Prior/sc_library/setPath.py")

import os
import importlib
import sys

from PyQt5 import QtCore, QtGui, QtWidgets

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))
# 获取 sc_library 的父目录路径
project_root = os.path.join(current_dir, "../../")
# 添加到 sys.path
sys.path.append(project_root)
# print("\nproject_root:",project_root)
# print("\nsys.path:",sys.path)

import sc_library.parameters as params

def runModule(module_type, setup_name = False):
    app = QtWidgets.QApplication(sys.argv)

    # 打印当前工作目录
    # print("Current working directory:", os.getcwd())
    
    general_parameters = params.halParameters("D:/GXD/Python_control_gxd/Focus_lock_IX83_Prior/IX83/settings_default.xml")
    print("\ngeneral_parameters:", general_parameters)
    # print("\ngeneral_parameters to string:", general_parameters.toString())
    
    if setup_name:
        general_parameters.set("setup_name", setup_name)
    else:
        setup_name = general_parameters.get("setup_name")

    setup_parameters = params.halParameters("D:/GXD/Python_control_gxd/Focus_lock_IX83_Prior/IX83/xml/" + setup_name + "_default.xml")
    setup_parameters.set("setup_name", setup_name)
    hardware = params.hardware("xml/" + setup_name + "_hardware.xml")
    
    found = False

    # print("\nhardware.get_modules",hardware.get("modules"))
    # print("\nhardware.get_modules.getProps",hardware.get("modules").getProps())

    for module in hardware.get("modules").getProps():
        if (module.get("hal_type") == module_type):
            # a_module = importlib.import_module("storm_control.hal4000." + module.get("module_name"))
            # print("\nmodule:",module)
            # print("\nmodule content:", module.toString())
            
            module_name = module.get("module_name")
            a_module = importlib.import_module(module_name)
            a_class = getattr(a_module, module.get("class_name"))
            print("\nmodule name: ", module_name)
            print("\na_Class: ", a_class)
            
            # print("Configuration:", module.get("configuration", False).toString())
            # print(f"Parameters: {module.get('parameters', False)}, {general_parameters}, None")
            # instance = a_class(module.get("parameters", False), general_parameters)
            # qt_settings = QtCore.QSettings("storm-control", "IX83 Focus Lock")
            # instance = a_class(module_name="focuslock",module_params = module,qt_settings = qt_settings)
            
            instance = a_class(module.get("parameters", False), setup_parameters,None)
            # params.setDefaultParameters(general_parameters)
            print("\ninstance:", instance)
            instance.newParameters(setup_parameters)
            instance.show()
            found = True
            break

    if found:
        sys.exit(app.exec_())
        instance.cleanup()
    else:
        print(module_type, "not found for", setup_name, "setup")

#
# The MIT License
#
# Copyright (c) 2014 Zhuang Lab, Harvard University
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
