#!/usr/bin/env python
"""
HAL module for controlling a Pi controller.
Adapted from Hal module for a tiger controller by Hazen 05/18.

Modified to connect PI controller (E-861.1A1) which controls a N-725.2A z-stage.

Xiaddong Guan 12/23
单独锁焦版本未使用
"""


from PyQt5 import QtCore

import sc_library.halExceptions as halExceptions

import halLib.halMessage as halMessage

import sc_hardware.baseClasses.stageZModule as stageZModule

import sc_hardware.physikInstrumente.piE861Controller as piE861Controller 



class PIZStageFunctionality(stageZModule.ZStageFunctionality):
    """
    The z sign convention of this stage is the opposite from the expected
    so we have to adjust.
    """
    def __init__(self, **kwds):
        super().__init__(**kwds)
        
        if self.parameters is not None: 
            self.maximum = self.getParameter("maximum")
            self.minimum = self.getParameter("minimum")

        # # Set initial z velocity.
        # update_interval=500
        # velocity=1
        # print('Initial velocity set 1')
        # self.mustRun(task = self.z_stage.zSetVelocity,
        #              args = [velocity])
        

        # # # This timer to restarts the update timer after a move. It appears
        # # # that if you query the position during a move the stage will stop
        # # # moving.
        # self.restart_timer = QtCore.QTimer()
        # self.restart_timer.setInterval(2000)
        # self.restart_timer.timeout.connect(self.handleRestartTimer)
        # self.restart_timer.setSingleShot(True)

        # # Each time this timer fires we'll query the z stage position. We need
        # # to do this as the user might use the controller to directly change
        # # the stage z position.
        # self.update_timer = QtCore.QTimer()
        # self.update_timer.setInterval(update_interval)
        # self.update_timer.timeout.connect(self.handleUpdateTimer)
        # self.update_timer.start()
        
    def goAbsolute(self, z_pos):
        # We have to stop the update timer because if it goes off during the
        # move it will stop the move.
        self.update_timer.stop()
        super().goAbsolute(z_pos)
        self.restart_timer.start()

    def goRelative(self, z_delta):
        z_pos = -1.0*self.z_position + z_delta  # note move directions are reversed here 
        self.goAbsolute(z_pos)        

    def handleRestartTimer(self):
        self.update_timer.start()
        
    def handleUpdateTimer(self):
        self.mustRun(task = self.position,
                     ret_signal = self.zStagePosition)

    def position(self):
        self.z_position = self.z_stage.zPosition()['z']   # unit: um
        # print('now piezo z_position (um) before reverse : ', self.z_position)
        return self.z_position
        # return -1.0*self.z_position    # note move directions are reversed here    
        #  

    def zero(self):
        self.mustRun(task = self.z_stage.zZero)
        self.zStagePosition.emit(0.0)
    
    def zMoveTo(self, z_pos):
        return super().zMoveTo(-z_pos)
        # return -1.0*super().zMoveTo(-z_pos)    # note move directions are reversed here 
    
        
#
# Inherit from stageModule.StageModule instead of the base class so we don't
# have to duplicate most of the stage stuff, particularly the TCP control.
#
class PIZStage(stageZModule.ZStage):
    def __init__(self,**kwds):
        super().__init__(**kwds)

        
        self.functionalities = {} # a list of the functionalities 
        if hasattr(self, "configuration"):
            configuration = self.configuration    #.get("configuration") # get the config parameters from the xml file under <PiController>
        self.z_stage = piE861Controller.PIE861ZStage() # connect to the controller 
        
        if self.z_stage.getStatus():
            # Note: We are not checking whether the devices that the user requested
            #       are actually available, we're just assuming that they know what
            #       they are doing.
            #

            self.z_stage_functionality = PIZStageFunctionality(z_stage = self.z_stage,
                parameters = None)
            self.functionalities[self.module_name] = self.z_stage_functionality

            
        else:
            self.z_stage = None
    
    def cleanUp(self, qt_settings):
        if self.z_stage is not None:
            for fn in self.functionalities.values():
                if hasattr(fn, "wait"):
                    fn.wait()
            self.z_stage.shutDown()

    def getFunctionality(self, message):
        if message.getData()["name"] in self.functionalities:
            fn = self.functionalities[message.getData()["name"]]
            message.addResponse(halMessage.HalMessageResponse(source = self.module_name,
                                                              data = {"functionality" : fn}))

    def processMessage(self, message):
        if message.isType("get functionality"):
            self.getFunctionality(message)

        #
        # The rest of the message are only relevant if we actually have a XY stage.
        #
        # if self.stage_functionality is None:
        #     return

        # if message.isType("configuration"):
        #     if message.sourceIs("tcp_control"):
        #         self.tcpConnection(message.getData()["properties"]["connected"])

        #     elif message.sourceIs("mosaic"):
        #         self.pixelSize(message.getData()["properties"]["pixel_size"])

        # elif message.isType("start film"):
        #     self.startFilm(message)

        # elif message.isType("stop film"):
        #     self.stopFilm(message)

        # elif message.isType("tcp message"):
        #     self.tcpMessage(message)
