#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Modified to connect to a PI stage using the E861 controller 
and the N-725.2A z-stages.

using Physik Instrumente (PI) GmbH & Co. KG
sc_hardware.physikInstrumente.E861.py

Xiaodong Guan, Nov 2024

"""
# 每次连接时的初始化关掉了  较耗时，需要初始化或打开servo时使用


from pipython import GCSDevice, pitools

CONTROLLERNAME = 'E-861.1A1'  # 'C-884' will also work
STAGES = ['N-725.2A']  
REFMODES = 'FRF'     # ['FNL', 'FRF']   

class PIE861ZStage(object):

    ## __init__
    #
    # Connect to the PI E861 stage.
    #
    #
    def __init__(self, com =4,baud = 115200):   # should become a parameter, see other stages
        self.com = com
        self.baud = baud
        # print('PI zstage COM: ',self.com,' baudrate: ',self.baud)
    
        # Connect to the PI E861 controller.
        # with GCSDevice(CONTROLLERNAME) as pidevice:    
        pidevice = GCSDevice(CONTROLLERNAME) 
        pidevice.ConnectRS232(comport=com, baudrate=baud) #   pidevice.ConnectUSB(serialnum='119006811')
        print('connected: {}'.format(pidevice.qIDN().strip()))

        # Show the version info which is helpful for PI support when there
        # are any issues.

        if pidevice.HasqVER():
            print('version info:\n{}'.format(pidevice.qVER().strip()))
        
        # The device itself does not support hasqver 
        # else:
        #      raise PiException("PI_GetProductInfo failed.")


        # In the module pipython.pitools there are some helper
        # functions to make using a PI device more convenient. The "startup"
        # function will initialize your system. There are controllers that
        # cannot discover the connected stages hence we set them with the
        # "stages" argument. The desired referencing method (see controller
        # user manual) is passed as "refmode" argument. All connected axes
        # will be stopped if they are moving and their servo will be enabled.

        # 需要初始化或打开servo时使用
        # print('initialize connected stages...')
        # pitools.startup(pidevice, stages=STAGES, refmodes=REFMODES)

        # Now we query the allowed motion range and current position of all
        # connected stages. GCS commands often return an (ordered) dictionary
        # with axes/channels as "keys" and the according values as "values".

        self.pidevice = pidevice
        
        self.wait = 1 # move commands wait for motion to stop
        self.unit_to_um = 1000.0 # needs calibration
        self.um_to_unit = 1.0/self.unit_to_um


        # Connect to the stage.
        self.good = 1

        # get min and max range
        self.rangemin = pidevice.qTMN()
        self.rangemax = pidevice.qTMX()
        self.curpos = pidevice.qPOS()
        self.velocity = pidevice.qVEL()
        print("Stage Properties:")
        print('rangmin(mm):',self.rangemin['1'])
        print('rangmax(mm):',self.rangemax['1'])
        print('current position of axis 1 is {:.4f} um'.format( self.unit_to_um*self.curpos['1']))
        print('velocity(mm/s):',self.velocity['1'])
        print('PI Zstage ok')
        

    ## getStatus
    #
    # @return True/False if we are actually connected to the stage.
    #
    def getStatus(self):
        return self.good

    ## goAbsolute
    #
    # @param x Stage x position in um.
    # @param y Stage y position in um.
    #


    ## goRelative
    #
    # @param dx Amount to displace the stage in x in um.
    # @param dy Amount to displace the stage in y in um.
    # 
            
    ## position
    #
    # @return [stage z (um)]
    #

     
    def zMoveTo(self, z):
        """
        Move the z stage to the specified position (in microns).
        """
        if self.good:
            Z = z * self.um_to_unit
            if Z > self.rangemin['1'] and Z < self.rangemax['1']:
                self.pidevice.MOV(1, Z)
                pitools.waitontarget(self.pidevice, axes=1)
                # print('z stage moved to {:.4f} um'.format(z))
            else:
                print('requested move outside max range!')
        

    def zPosition(self):
        """
        Query for current z position in microns.
        """
        if self.good:
            z0 = self.pidevice.qPOS(1)[1]  # query single axis
            z_n = z0 * self.unit_to_um
            return {"current z (μm)" : z_n}
        
    def zPos(self):
        """
        Query for current z position in microns.
        """
        if self.good:
            z0 = self.pidevice.qPOS(1)[1]  # query single axis
            z_n = z0 * self.unit_to_um
            return z_n

    def zSetVelocity(self, z_vel):
        # E861/N725 default velocity is 10 mm/s   unit: mm/s
        # 10 mm/s = 10 um/ms = 10,000 nm/ms
        
        self.pidevice.VEL(1, z_vel)
        print('z velocity (mm/s) set to:', self.pidevice.qVEL()['1'])

    def zZero(self):
        if self.good:
            pitools._ref_with_pos(self, self.pidevice.axes([0])) # added axes [0,1], not sure this ever worked anyway
            print("zZero done.",self.zPosition())
    ## jog
    #

   
    ## joystickOnOff
    #
    # @param on True/False enable/disable the joystick.
    #
    def joystickOnOff(self, on):
        pass
        # No joystick used

    ## lockout
    #
    # Calls joystickOnOff.
    #
    # @param flag True/False.
    #
    def lockout(self, flag):
        self.joystickOnOff(not flag)

            

    ## setVelocity
    #
    # FIXME: figure out how to set velocity..
    #


    ## shutDown
    #
    # Disconnect from the stage.
    #
    def shutDown(self):
        # Disconnect from the stage
        if self.good:
            self.pidevice.StopAll(noraise=True)
            pitools.waitonready(self.pidevice)  # there are controllers that need some time to halt all axes
            print('PI Zstage shut down')
    ## zero
    #
    # Set the current position as the new zero position.
    #
    

if (__name__ == "__main__"):

    def printDict(a_dict):
        for key in sorted(a_dict):
            print(key, '\t', a_dict[key])

    print("Initializing Stage")
    stage = PIE861ZStage( com =4,baud = 115200)
    if not stage.getStatus():
        exit()
    else:
        print("Stage Properties:")
        print('rangmin(mm):',stage.rangemin)
        print('rangmax(mm):',stage.rangemax)
        print('current pos(mm):',stage.curpos)
        print('velocity:',stage.velocity)
        print("")

    # stage.zSetVelocity(1)

    print("")
    stage.shutDown()
