#!/usr/bin/python
#
## @file
#
# Focus lock control specialized for STORM4.
#
# Hazen 03/12
#
import os
from pathlib import Path

import sc_library.parameters as params
from simple_pid import PID

# camera and stage.
import sc_hardware.prior.priorZController as priorZController
import sc_hardware.thorlabs.uc480Camera as uc480Cam

# focus lock control thread.
import focusLock.stageOffsetControl_bx as stageOffsetControl

# ir laser control
#import sc_hardware.thorlabs.LDC210 as LDC210

# focus lock dialog.
import focusLock.focusLockZ as focusLockZ


VENDOR_ROOT = Path(__file__).resolve().parents[1]

#
# Focus Lock Dialog Box specialized for STORM4 with 
# USB offset detector and MCL objective Z positioner.
#
class AFocusLockZ(focusLockZ.FocusLockZCam):
    def __init__(self, hardware, parameters, parent = None):

        # STORM4 specific focus lock parameters
#        lock_params = parameters.addSubSection("focuslock")
#        #lock_params.add("qpd_zcenter", params.ParameterRangeFloat("Piezo center position in microns",
#                                                                  #"qpd_zcenter",
#                                                                  #50.0, 0.0, 100.0))
#        lock_params.add("qpd_scale", params.ParameterRangeFloat("Offset to nm calibration value",
#                                                                "qpd_scale",
#                                                                50.0, 0.1, 1000.0))
#        lock_params.add("qpd_sum_min", 50.0)
#        lock_params.add("qpd_sum_max", 256.0)
#        lock_params.add("is_locked_buffer_length", 3)
#        lock_params.add("is_locked_offset_thresh", 1)
#        lock_params.add("ir_power", params.ParameterInt("", "ir_power", 6, is_mutable = False))

        # STORM4 Initialization
#        cam = uc480Cam.CameraQPD(camera_id = 1,
#                                 x_width = 500,
#                                 y_width = 500,
#                                 offset_file = "cam_offsets_storm4_1.txt",
#                                 background = 0)
        cam = uc480Cam.CameraQPD(camera_id = 1,
                                 x_width = 200,
                                 y_width = 200,
                                 offset_file = str(VENDOR_ROOT / "cam_offsets_IX83_2.txt"),
                                 ini_file = str(VENDOR_ROOT / "uc480_settings.ini"),
                                 background = 0)
                                #
        # offset_file  provides the top-left coordinates of the ROI (int)
        # x_width,y_width   ROI size (int)

#        image = cam.cam.captureImage()
#        im = Image.fromarray(image)
#        im.save("haha.png")

        try:
            stage = priorZController.PriorZStage(com = int(os.environ.get("SMLM_PRIOR_COM", "20")))
            if not stage.getStatus():
                raise RuntimeError("Prior z-stage connection failed. Check the controller power and COM20 connection.")
            stage.zMoveTo(200)  # 移动到中间
            stage.zPosition()
        except Exception as exc:
            try:
                cam.shutDown()
            except Exception:
                pass
            raise RuntimeError(f"Focus lock startup aborted because the Prior z-stage is unavailable: {exc}") from exc
        # 之前使用lambda函数封装，现取消封装
        # 定义 PID 控制器
        pid = PID(Kp=0.05,Ki=0.025, Kd=0.001, setpoint=0)
        pid.output_limits = (-0.03, 0.03)  # 设置输出范围，防止控制器输出过大
        # 定义反馈函数 以μm为单位
        # lock_fn = lambda x: pid(x)  # x 是输入误差，pid(x) 是输出控制量
        # lock_fn = lambda x: 0.09 * x
        
        # buffer_length 存储最近几次的锁焦判断，对locked状态要求更严格
        # offset_thresh 锁焦判断的阈值
        control_thread = stageOffsetControl.StageCamThread(cam,
                                                           stage,
                                                           pid,
                                                           parameters.get("focuslock.qpd_sum_min", 25),
                                                           parameters.get("focuslock.qpd_zcenter"),
                                                           parameters.get("focuslock.is_locked_buffer_length", 1),
                                                           parameters.get("focuslock.is_locked_offset_thresh", 0.1))
        

       
        #ir_laser = LDC210.LDC210PWMLJ()
        ir_laser = 0
        focusLockZ.FocusLockZCam.__init__(self,
                                          parameters,
                                          control_thread,
                                          ir_laser,
                                          parent)

#
# The MIT License
#
# Copyright (c) 2012 Zhuang Lab, Harvard University
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
