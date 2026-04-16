#!/usr/bin/python
#
## @file
#
# Captures pictures from a Thorlabs uc480 (software) series cameras.
#
# NOTE: For reasons unclear, but perhaps due to a change in
#       ctypes, this module only works well with (64 bit) Python 
#       versions that are <= 2.7.8.
#
# Hazen 02/13
# 
# qpdscan()中reps默认由4改为1

import ctypes
import ctypes.util
import ctypes.wintypes
import numpy
import os
from pathlib import Path
from PIL import Image

import platform
import scipy
import scipy.optimize
import time
import cv2
from scipy.ndimage import label, center_of_mass

import sc_library.hdebug as hdebug


RESOURCE_ROOTS = [
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[2],
]
DLL_ROOTS = [
    Path(os.environ["SMLM_UC480_DLL"]) if os.environ.get("SMLM_UC480_DLL", "").strip() else None,
    Path(__file__).resolve().parents[4] / "assets" / "bin" / "uc480_64.dll",
]
_DLL_DIR_HANDLE = None


def _resolve_resource_path(resource_name):
    candidate = Path(resource_name)
    if candidate.is_absolute():
        return str(candidate)
    if candidate.exists():
        return str(candidate.resolve())
    for root in RESOURCE_ROOTS:
        resolved = root / candidate
        if resolved.exists():
            return str(resolved)
    return str(candidate)

uc480 = None

Handle = ctypes.wintypes.HANDLE

# some definitions
IS_AOI_IMAGE_GET_AOI = 0x0002
IS_AOI_IMAGE_SET_AOI = 0x0001
IS_DONT_WAIT = 0
IS_ENABLE_ERR_REP = 1
IS_GET_STATUS = 0x8000
IS_IGNORE_PARAMETER = -1
IS_SEQUENCE_CT = 2
IS_SET_CM_Y8 = 6
IS_SET_GAINBOOST_OFF = 0x0000
IS_SUCCESS = 0
IS_TRIGGER_TIMEOUT = 0
IS_WAIT = 1
IS_EXPOSURE_CMD_SET_EXPOSURE = 6

## CameraInfo
#
# The uc480 camera info structure.
#
class CameraInfo(ctypes.Structure):
    _fields_ = [("CameraID", ctypes.wintypes.DWORD),
                ("DeviceID", ctypes.wintypes.DWORD),
                ("SensorID", ctypes.wintypes.DWORD),
                ("InUse", ctypes.wintypes.DWORD),
                ("SerNo", ctypes.c_char * 16),
                ("Model", ctypes.c_char * 16),
                ("Reserved", ctypes.wintypes.DWORD * 16)]

## CameraProperties
#
# The uc480 camera properties structure.
#
class CameraProperties(ctypes.Structure):
    _fields_ = [("SensorID", ctypes.wintypes.WORD),
                ("strSensorName", ctypes.c_char * 32),
                ("nColorMode", ctypes.c_char),
                ("nMaxWidth", ctypes.wintypes.DWORD),
                ("nMaxHeight", ctypes.wintypes.DWORD),
                ("bMasterGain", ctypes.wintypes.BOOL),
                ("bRGain", ctypes.wintypes.BOOL),
                ("bGGain", ctypes.wintypes.BOOL),
                ("bBGain", ctypes.wintypes.BOOL),
                ("bGlobShutter", ctypes.wintypes.BOOL),
                ("Reserved", ctypes.c_char * 16)]

## AOIRect
#
# The uc480 camera AOI structure.
#
class AOIRect(ctypes.Structure):
    _fields_ = [("s32X", ctypes.wintypes.INT),
                ("s32Y", ctypes.wintypes.INT),
                ("s32Width", ctypes.wintypes.INT),
                ("s32Height", ctypes.wintypes.INT)]

# load the DLL
#uc480_dll = ctypes.util.find_library('uc480')
#if uc480_dll is None:
#    print 'uc480.dll not found'

# if (platform.architecture()[0] == "32bit"):
#     uc480 = ctypes.cdll.LoadLibrary("c:\windows\system32\uc480.dll")
# else:
#     uc480 = ctypes.cdll.LoadLibrary("c:\windows\system32\uc480_64.dll")

def loadDLL(dll_name):
    global uc480
    global _DLL_DIR_HANDLE
    if uc480 is None:
        dll_path = _resolve_uc480_dll(dll_name)
        if hasattr(os, "add_dll_directory"):
            try:
                _DLL_DIR_HANDLE = os.add_dll_directory(str(Path(dll_path).resolve().parent))
            except OSError:
                _DLL_DIR_HANDLE = None
        uc480 = ctypes.cdll.LoadLibrary(dll_path)


def _resolve_uc480_dll(dll_name):
    candidate = Path(dll_name)
    if candidate.is_absolute() and candidate.exists():
        return str(candidate)
    for dll_candidate in DLL_ROOTS:
        if dll_candidate is not None and dll_candidate.exists():
            return str(dll_candidate)
    return str(candidate)


loadDLL("uc480_64.dll")

# Helper functions

## check
#
# @param fn_return The uc480 function return code.
# @param fn_name (Optional) The name of the function that was called, defaults to "".
#
def check(fn_return, fn_name = ""):
    if not (fn_return == IS_SUCCESS):
        hdebug.logText("uc480: Call failed with error " + str(fn_return) + " " + fn_name)
        #print "uc480: Call failed with error", fn_return, fn_name

## create_camera_list
#
# Creates a empty CameraList structure.
#
# @param num_cameras The number of cameras.
#
# @return A camera list structure.
#
def create_camera_list(num_cameras):
    class CameraList(ctypes.Structure):
        _fields_ = [("Count", ctypes.c_long),
                    ("Cameras", CameraInfo*num_cameras)]
    a_list = CameraList()
    a_list.Count = num_cameras
    return a_list


## fitAFunctionLS
#
# Does least squares fitting of a function.
#
# @param data The data to fit.
# @param params The initial values for the fit.
# @param fn The function to fit.
#
def fitAFunctionLS(data, params, fn):
    result = params
    errorfunction = lambda p: numpy.ravel(fn(*p)(*numpy.indices(data.shape)) - data)
    good = True
    [result, cov_x, infodict, mesg, success] = scipy.optimize.leastsq(errorfunction, params, full_output = 1, maxfev = 1000)
    if (success < 1) or (success > 4):
        hdebug.logText("Fitting problem: " + mesg)
        #print "Fitting problem:", mesg
        good = False
    return [result, good]

# 极大似然法拟合

# def fitAFunctionMLE(data, params, fn):
#     result = params
#     neg_log_likelihood = lambda p: -numpy.ravel(fn(*p)(*numpy.indices(data.shape)) - data)
#     good = True

## symmetricGaussian
#
# Returns a function that will return the amplitude of a symmetric 2D-gaussian at a given x, y point.
#
# @param background The gaussian's background.
# @param height The gaussian's height.
# @param center_x The gaussian's center in x.
# @param center_y The gaussian's center in y.
# @param width The gaussian's width.
#
# @return A function.
#
def symmetricGaussian(background, height, center_x, center_y, width):
    return lambda x,y: background + height*numpy.exp(-(((center_x-x)/width)**2 + ((center_y-y)/width)**2) * 2)

## fixedEllipticalGaussian
#
# Returns a function that will return the amplitude of a elliptical gaussian (constrained to be oriented
# along the XY axis) at a given x, y point.
#
# @param background The gaussian's background.
# @param height The gaussian's height.
# @param center_x The gaussian's center in x.
# @param center_y The gaussian's center in y.
# @param width_x The gaussian's width in x.
# @param width_y The gaussian's width in y.
#
# @return A function.
#
def fixedEllipticalGaussian(background, height, center_x, center_y, width_x, width_y):
    return lambda x,y: background + height*numpy.exp(-(((center_x-x)/width_x)**2 + ((center_y-y)/width_y)**2) * 2)

## fitSymmetricGaussian
#
# Fits a symmetric gaussian to the data.
#
# @param data The data to fit.
# @param sigma An initial value for the sigma of the gaussian.
#
# @return [[fit results], good (True/False)]
#
def fitSymmetricGaussian(data, sigma,background = None):
    if background is None:
        background = numpy.min(data)
    params = [background,
              numpy.max(data),
              int(0.5 * data.shape[0]),
              int(0.5 * data.shape[1]),
              2.0 * sigma]
    return fitAFunctionLS(data, params, symmetricGaussian)

## fitFixedEllipticalGaussian
#
# Fits a fixed-axis elliptical gaussian to the data.
#
# @param data The data to fit.
# @param sigma An initial value for the sigma of the gaussian.
#
# @return [[fit results], good (True/False)]
#
def fitFixedEllipticalGaussian(data, params_0 = None):
    if params_0 is None:
        params = [numpy.min(data),
                numpy.max(data),
                0.5 * data.shape[0],
                0.5 * data.shape[1],
                6,
                6]   # sigma初始值
    else:
        params = params_0
    return fitAFunctionLS(data, params, fixedEllipticalGaussian)


## Camera
#
# UC480 Camera Interface Class
#
class Camera(Handle):

    ## __init__
    #
    # @param camera_id The identification number of the camera to connect to.
    # @param ini_file (Optional) A settings file to use to configure the camera, defaults to uc480_settings.ini.
    #
    def __init__(self, camera_id, ini_file = "uc480_settings.ini"):
        Handle.__init__(self, camera_id)
        ini_file = _resolve_resource_path(ini_file)

        # Initialize camera.
        check(uc480.is_InitCamera(ctypes.byref(self), ctypes.wintypes.HWND(0)), "is_InitCamera")
        #check(uc480.is_SetErrorReport(self, IS_ENABLE_ERR_REP))

        # Get some information about the camera.
        self.info = CameraProperties()
        # print("\ncamera_properties:",self.info)
        self.caminfo = CameraInfo()
        # print("\ncamera_info:",self.caminfo)

        check(uc480.is_GetSensorInfo(self, ctypes.byref(self.info)), "is_GetSensorInfo")
        self.im_width = self.info.nMaxWidth
        self.im_height = self.info.nMaxHeight

        # Initialize some general camera settings.
        if (os.path.exists(ini_file)):
        #if 0:
            self.loadParameters(ini_file)
            hdebug.logText("uc480 loaded parameters file " + ini_file, to_console = False)
        else:
            check(uc480.is_SetColorMode(self, IS_SET_CM_Y8), "is_SetColorMode")
            check(uc480.is_SetGainBoost(self, IS_SET_GAINBOOST_OFF), "is_SetGainBoost")
            check(uc480.is_SetGamma(self, 1), "is_SetGamma")
            check(uc480.is_SetHardwareGain(self,
                                           0,
                                           IS_IGNORE_PARAMETER,
                                           IS_IGNORE_PARAMETER,
                                           IS_IGNORE_PARAMETER),
                  "is_SetHardwareGain")
            hdebug.logText("uc480 used default settings.", to_console = False)

        # Setup capture parameters.
        self.bitpixel = 8     # This is correct for a BW camera anyway..
        self.cur_frame = 0
        self.data = False
        self.id = 0
        self.image = False
        self.running = False
        self.setBuffers()
        self.exposure_time = 30 # exposure time (ms)
        print("uc480 OK")

    ## captureImage
    #
    # Wait for the next frame from the camera, then call self.getImage().
    #
    # @return An image (8 bit numpy array) from the camera.
    #
    def captureImage(self):
        check(uc480.is_FreezeVideo(self, IS_WAIT), "is_FreezeVideo")
        return self.getImage()

    ## captureImageTest
    #
    # For testing..
    def captureImageTest(self):
        check(uc480.is_FreezeVideo(self, IS_WAIT), "is_FreezeVideo")

    ## getCameraStatus
    #
    # @param status_code A status code.
    #
    # @return The camera status based on the status code.
    #
    def getCameraStatus(self, status_code):
        return uc480.is_CameraStatus(self, status_code, IS_GET_STATUS, "is_CameraStatus")
        
    
    def getCameraType(self,camera_id):
        return uc480.is_GetCameraType(self,camera_id,ctypes.byref(self.caminfo))

    ## getImage
    #
    # Copy an image from the camera into self.data and return self.data
    #
    # @return A 8 bit numpy array containing the data from the camera.
    #
    def getImage(self):
        check(uc480.is_CopyImageMem(self, self.image, self.id, ctypes.c_char_p(self.data.ctypes.data)), "is_CopyImageMem")
        return self.data

    ## getNextImage
    #
    # Waits until an image is available from the camera, then call self.getImage() to return the new image.
    #
    # @return The new image from the camera (as a 8 bit numpy array).
    #
    def getNextImage(self):
        print(self.cur_frame, self.getCameraStatus(IS_SEQUENCE_CT))
        while (self.cur_frame == self.getCameraStatus(IS_SEQUENCE_CT)):
            print("waiting..")
            time.sleep(0.05)
        self.cur_frame += 1
        return self.getImage()

    ## getSensorInfo
    #
    # @return The camera properties structure for this camera.
    #
    def getSensorInfo(self):
        return self.info

    ## getTimeout
    #
    # @return The timeout value for the camera.
    #
    def getTimeout(self):
        nMode = IS_TRIGGER_TIMEOUT
        pTimeout = ctypes.c_int(1)
        check(uc480.is_GetTimeout(self,
                                  ctypes.c_int(nMode),
                                  ctypes.byref(pTimeout)),
              "is_GetTimeout")
        return pTimeout.value

    ## loadParameters
    #
    # @param file The file name of the camera parameters file to load.
    #
    def loadParameters(self, file):
        check(uc480.is_LoadParameters(self,
                                      ctypes.c_char_p(file.encode())))

    ## saveParameters
    #
    # Save the current camera settings to a file.
    #
    # @param file The file name to save the settings in.
    #
    def saveParameters(self, file):
        check(uc480.is_SaveParameters(self,
                                      ctypes.c_char_p(file.encode())))

    ## setAOI
    #
    # @param x_start The x pixel of the camera AOI.
    # @param y_start The y pixel of the camera AOI.
    # @param width The width in pixels of the AOI.
    # @param height The height in pixels of the AOI.
    #
    def setAOI(self, x_start, y_start, width, height):
        # x and y start have to be multiples of 2.
        x_start = int(x_start/2)*2
        y_start = int(y_start/2)*2

        self.im_width = width
        self.im_height = height
        aoi_rect = AOIRect(x_start, y_start, width, height)
        check(uc480.is_AOI(self,
                           IS_AOI_IMAGE_SET_AOI,
                           ctypes.byref(aoi_rect),
                           ctypes.sizeof(aoi_rect)),
              "is_AOI")
        self.setBuffers()

    ## setBuffers
    #
    # Based on the AOI, create the internal buffer that the camera will use and
    # the intermediate buffer that we will copy the data from the camera into.
    #
    def setBuffers(self):
        self.data = numpy.zeros((self.im_height, self.im_width), dtype = numpy.uint8)
        if self.image:
            check(uc480.is_FreeImageMem(self, self.image, self.id))
        self.image = ctypes.c_char_p()
        self.id = ctypes.c_int()
        check(uc480.is_AllocImageMem(self,
                                     ctypes.c_int(self.im_width),
                                     ctypes.c_int(self.im_height),
                                     ctypes.c_int(self.bitpixel),
                                     ctypes.byref(self.image),
                                     ctypes.byref(self.id)),
              "is_AllocImageMem")
        check(uc480.is_SetImageMem(self, self.image, self.id), "is_SetImageMem")

    ## setFrameRate
    #
    # @param frame_rate (Optional) The desired frame rate in frames per second, defaults to 1000.
    # @param verbose (Optional) True/False, print the actual frame rate, defaults to False.
    #
    def setFrameRate(self, frame_rate = 33, verbose = True):
        new_fps = ctypes.c_double()
        # exposure_now = ctypes.c_double(0)  # 创建一个 double 类型变量来存储曝光时间
        # exposure_range = (ctypes.c_double * 3)()  # 存储最小值、最大值和增量

        check(uc480.is_SetFrameRate(self,
                                    ctypes.c_double(frame_rate),
                                    ctypes.byref(new_fps)),
              "is_SetFrameRate")
        # if frame_rate <33:
        #     check(uc480.is_Exposure(self,ctypes.c_uint(7),
        #                             ctypes.byref(ctypes.c_double(self.exposure_time)),
        #                             ctypes.c_uint(8)),
        #       "is_SetExposure")
        #     # 编号从2开始？
        #     check(uc480.is_Exposure(self, ctypes.c_uint(2), 
        #                             ctypes.byref(exposure_now),
        #                             ctypes.c_uint(8)),
        #         "now_Exposure")
        #     check(uc480.is_Exposure(self, ctypes.c_uint(6), 
        #                             ctypes.byref(exposure_range),
        #                             ctypes.c_uint(24)),
        #         "range_Exposure") 
        #      # 获取曝光时间范围
        #     min_exposure, max_exposure, increment = exposure_range
        #     print("Exposure time range:", min_exposure, max_exposure, increment)

        #     print("current exposure time(s):",exposure_now.value)
        if verbose:
            print("uc480: Set frame rate to", new_fps.value, "FPS")

    ## setPixelClock
    #
    # 43MHz seems to be the max for this camera.
    #
    # @param pixel_clock_MHz (Optional) The desired pixel clock speed in MHz, defaults to 30.
    #
    def setPixelClock(self, pixel_clock_MHz = 25):
        check(uc480.is_SetPixelClock(self,
                                     ctypes.c_int(pixel_clock_MHz)))

    ## setTimeout
    #
    # @param timeout Set the camera time out.
    #
    def setTimeout(self, timeout):
        nMode = IS_TRIGGER_TIMEOUT
        check(uc480.is_SetTimeout(self,
                                  ctypes.c_int(nMode),
                                  ctypes.c_int(timeout)),
              "is_SetTimeout")

    ## shutDown
    #
    # Shut down the camera.
    #
    def shutDown(self):
        check(uc480.is_ExitCamera(self), "is_ExitCamera")

    ## startCapture
    #
    # Start video capture (as opposed to single frame capture, which is done with self.captureImage().
    #
    def startCapture(self):
        check(uc480.is_CaptureVideo(self, IS_DONT_WAIT), "is_CaptureVideo")

    ## stopCapture
    #
    # Stop video capture
    #
    def stopCapture(self):
        check(uc480.is_StopLiveVideo(self, IS_WAIT), "is_StopLiveVideo")


## CameraQPD
#
# QPD emulation class. The default camera ROI of 200x200 pixels.
# The focus lock is configured so that there are two laser spots on the camera.
# The distance between these spots is fit and the difference between this distance and the
# zero distance is returned as the focus lock offset. The maximum value of the camera
# pixels is returned as the focus lock sum.
#
class CameraQPD():

    ## __init__
    #
    # @param camera_id (Optional) The camera ID number, defaults to 1.
    # @param fit_mutex (Optional) A QMutex to use for fitting (to avoid thread safety issues with numpy), defaults to False.
    # @param x_width (Optional) AOI size in x, defaults to 200.
    # @param y_width (Optional) AOI size in y, defaults to 200.
    # @param sigma (Optional) Initial sigma for the fit, defaults to 8.0.
    #
    #def __init__(self, camera_id = 1, fit_mutex = False, x_width = 200, y_width = 200, sigma = 8.0, offset_file = False, background = 0):
    def __init__(self, camera_id = 1, fit_mutex = False, x_width = 200, y_width = 200, sigma = 8.0, offset_file = False, ini_file = "uc480_settings.ini", background = 0):
        self.offset_file = _resolve_resource_path(offset_file) if offset_file else False
        self.background = background
        self.fit_mode = 1
        self.fit_mutex = fit_mutex
        self.fit_size = int(2 * sigma)
        self.image = None
        self.sigma = sigma
        self.x_off1 = 0.0
        self.y_off1 = 0.0
        self.x_off2 = 0.0
        self.y_off2 = 0.0
        self.zero_dist = 0.5 * x_width

        # Open camera
        self.cam = Camera(camera_id, ini_file = ini_file)

        image = self.cam.captureImage()
        
        # Set timeout
        self.cam.setTimeout(1)

        # Set camera AOI x_start, y_start.
        if self.offset_file and (os.path.exists(self.offset_file)):
            with open(self.offset_file) as fp:
                [self.x_start, self.y_start] = map(int, fp.readline().split(",")[:2])
        else:
            print("Warning! No focus lock camera offset file found!", self.offset_file)
            self.x_start = 0
            self.y_start = 0

        # Set camera AOI.
        self.x_width = x_width
        self.y_width = y_width
        self.setAOI()

        # Run at maximum speed.
        self.cam.setPixelClock()   # default is 30MHz
        self.cam.setFrameRate()   # decrease ROI to increase framrate 

        # Some derived parameters
        self.half_x = self.x_width/2
        self.half_y = self.y_width/2
        self.X = numpy.arange(self.y_width) - 0.5*float(self.y_width)

    ## adjustAOI
    #
    # @param dx Amount to displace the AOI in pixels in x, needs to be a multiple of 2.
    # @param dy Amount to displace the AOI in pixels in y, needs to be a multiple of 2.
    #
    def adjustAOI(self, dx, dy):
        self.x_start += dx
        self.y_start += dy
        if(self.x_start < 0):
            self.x_start = 0
        if(self.y_start < 0):
            self.y_start = 0
        if((self.x_start + self.x_width + 2) > self.cam.info.nMaxWidth):
            self.x_start = self.cam.info.nMaxWidth - (self.x_width + 2)
        if((self.y_start + self.y_width + 2) > self.cam.info.nMaxHeight):
            self.y_start = self.cam.info.nMaxHeight - (self.y_width + 2)
        self.setAOI()

    ## adjustZeroDist
    #
    # @param inc The amount to increment the zero distance value by.
    #
    def adjustZeroDist(self, inc):
        self.zero_dist += inc

    ## capture
    #
    # Get the next image from the camera.
    #
    def capture(self):
        self.image = self.cam.captureImage()
        return self.image

    ## changeFitMode
    #
    # @param mode 1 = gaussian fit, any other value = first moment calculation.
    #
    def changeFitMode(self, mode):
        self.fit_mode = mode

    ## fitGaussian
    #
    # @param data The data to fit a gaussian to.
    #
    def fitGaussian(self, data):
        if (numpy.max(data) < 25):
            return [False, False, False, False]
        x_width = data.shape[0]
        y_width = data.shape[1]
        max_i = data.argmax()
        max_x = int(max_i/y_width)
        max_y = int(max_i%y_width)
        if (max_x > (self.fit_size-1)) and (max_x < (x_width - self.fit_size)) and (max_y > (self.fit_size-1)) and (max_y < (y_width - self.fit_size)):
            if self.fit_mutex:
                self.fit_mutex.lock()
            #[params, status] = fitSymmetricGaussian(data[max_x-self.fit_size:max_x+self.fit_size,max_y-self.fit_size:max_y+self.fit_size], 8.0)
            #[params, status] = fitFixedEllipticalGaussian(data[max_x-self.fit_size:max_x+self.fit_size,max_y-self.fit_size:max_y+self.fit_size], 8.0)
            [params, status] = fitFixedEllipticalGaussian(data[max_x-self.fit_size:max_x+self.fit_size,max_y-self.fit_size:max_y+self.fit_size], self.sigma)
            if self.fit_mutex:
                self.fit_mutex.unlock()
            params[2] -= self.fit_size
            params[3] -= self.fit_size
            return [max_x, max_y, params, status]
        else:
            return [False, False, False, False]
    
    # new fitting method
    def fitGaussianNew(self, cropped_data,params_0):
        if self.fit_mutex:
            self.fit_mutex.lock()
        #[params, status] = fitSymmetricGaussian(data[max_x-self.fit_size:max_x+self.fit_size,max_y-self.fit_size:max_y+self.fit_size], 8.0)
        #[params, status] = fitFixedEllipticalGaussian(data[max_x-self.fit_size:max_x+self.fit_size,max_y-self.fit_size:max_y+self.fit_size], 8.0)
        [params, status] = fitFixedEllipticalGaussian(cropped_data, params_0)
        if self.fit_mutex:
            self.fit_mutex.unlock()
        # 应该在最终计算distance前限制小数位
        # params[2] = round((params[2] - self.fit_size),3)    # sub_pix_x  保留3位小数
        # params[3] = round((params[3] - self.fit_size),3)    # sub_pix_y

        params[2] -= self.fit_size
        params[3] -= self.fit_size

        return [params, status]

    ## getImage
    #
    # @return [camera image, spot 1 x fit, spot 1 y fit, spot 2 x fit, spot 2 y fit]
    #
    def getImage(self):
        return [self.image, self.x_off1, self.y_off1, self.x_off2, self.y_off2, self.sigma]

    ## getZeroDist
    #
    # @return The distance between the spots that is considered to be zero offset.
    #
    def getZeroDist(self):
        return self.zero_dist

    ## qpdScan
    #
    # Returns sum and offset data from the camera in the same format as what would be measured using a QPD.
    #
    # @param reps (Optional) The number of measurements to average together, defaults to 4.
    #
    # @return [sum signal, x offset, 0].
    #
    def qpdScan(self, reps = 3):
        power_total = 0.0
        offset_total_x = 0.0
        offset_total_y = 0.0
        good_total = 0.0
        for i in range(reps):
            data = self.singleQpdScan()
            if (data[0] > 0):
                power_total += data[0]
                offset_total_x += data[1]
                offset_total_y += data[2]
                good_total += 1.0
        if (good_total > 0):
            inv_good = 1.0/good_total
            return [power_total * inv_good, offset_total_x * inv_good, offset_total_y * inv_good]   
        else:
            return [0, 0, 0]

    ## setAOI
    #
    # Set the camera AOI to current AOI.
    #
    def setAOI(self):
        self.cam.setAOI(self.x_start,
                        self.y_start,
                        self.x_width,
                        self.y_width)

    ## shutDown
    #
    # Save the current camere AOI location and offset. Shutdown the camera.
    #
    def shutDown(self):
        if self.offset_file:
            with open(self.offset_file, "w") as fp:
                fp.write(str(self.x_start) + "," + str(self.y_start))
        self.cam.shutDown()
    
    def prefit(self, img_1):
        # 使用大津阈值法进行二值化
        # _, binary_img = cv2.threshold(data, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # # # 腐蚀膨胀处理
        # kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))  # 定义椭圆形核
        # binary_img = cv2.morphologyEx(binary_img, cv2.MORPH_OPEN, kernel)  # 腐蚀+膨胀（开运算）
        # 二值化处理定位不准

        # 连接组件分析，找到所有光斑
        labeled, num_features = label(img_1)
        properties = []
        for i in range(1, num_features + 1):
            mask = (labeled == i)
            area = numpy.sum(mask)  # 计算面积

            # 计算加权质心
            # 创建一个包含每个像素值的矩阵，作为权重
            y, x = numpy.indices(mask.shape)  # 获取图像的坐标

            x = x[mask]  # 只保留光斑区域的x坐标
            y = y[mask]  # 只保留光斑区域的y坐标
            cal_data = img_1[mask]  # 只保留光斑区域的像素值
            
            weighted_x = numpy.sum(x * cal_data) / numpy.sum(cal_data)  # 加权x坐标
            weighted_y = numpy.sum(y * cal_data) / numpy.sum(cal_data)  # 加权y坐标
            # 小数点后保留3位    最终结果限制小数位即可？
            # weighted_x = round(weighted_x, 3)
            # weighted_y = round(weighted_y, 3)

            centroid = (weighted_y, weighted_x)  # 质心坐标   row,col
            properties.append((area,centroid))
        # print("发现%d个光斑" % num_features)

        # 如果未找到光斑，返回默认值
        if len(properties) > 2:
            properties = sorted(properties, key=lambda x: x[0], reverse=True)[:2] 
        elif len(properties) < 2:
            # print("Less than 2 spots found!")
            if len(properties) == 1:
                print("Only one spot found!")
                return [properties[0][1], (0, 0)]
            else:   
                print("No spot found!")
                return [(0,0),(0,0)]
        
        # 按照面积排序，选取面积最大的两个光斑 基本用不到
        # properties = sorted(properties, key=lambda x: x[0], reverse=True)[:2]        
        # properties = properties[:2]
        # centers = [prop[2] for prop in properties]  # 提取两个光斑的质心

        centers = [prop[1] for prop in properties]  # 提取两个光斑的质心
        centers = sorted(centers, key=lambda x: x[1])  # 按照列坐标排序

        # print("centers:",centers)
        # print("centers[0]:",centers[0])
        # print("centers[1]:",centers[1])
        return centers

    def cropFit(self, data, center):
        # center = (y,x)
        # y0, x0 = int(round(center[0],0)), int(round(center[1],0))  # 转换为整数坐标
        y0, x0 = int(center[0]), int(center[1])
        x_min = max(0, x0 - self.fit_size)
        x_max = min(data.shape[1], x0 + self.fit_size+1)
        y_min = max(0, y0 - self.fit_size)
        y_max = min(data.shape[0], y0 + self.fit_size+1)

        # 裁剪区域
        cropped_data = data[y_min:y_max, x_min:x_max]
        yc = round(center[0] - y_min,2)   # 裁剪区域的中心坐标 拟合初始值 小数位应为0
        xc = round(center[1] - x_min,2)    

        return cropped_data,yc,xc,y0,x0    # ,(yc,xc)

    def dofit(self, data, centers):
        
        # if centers[1][0] == 0 :
        #     if centers[0][0] == 0:
        #         print("Pixel coords not found!")
        #     else:
                
        #     return [0,0,0,0]
        # 准备高斯拟合
        results = []
        # spot_size = 2*self.fit_size  # 裁剪区域大小，例如24*24
        gFitSigma0 = 0.9*self.fit_size   # 初始高斯拟合sigma值

        if centers[0][0] >0:
            for index,center in enumerate(centers):
                if center[0] > 0:
                    # 裁剪区域
                    cropped_data,yc,xc,y0,x0= self.cropFit(data, center)
                    params_0 = [self.background, numpy.max(cropped_data)-self.background,
                                    yc, xc, gFitSigma0, gFitSigma0]   
                    # print("params_0:",params_0)
                    # xc,yc是裁剪区域的中心亚像素坐标（由加权质心 + 取整），坐标系为剪裁区域
                    # x0,y0坐标系是原图像 
                    # 高斯拟合
                    [params, status] = self.fitGaussianNew(cropped_data,params_0)
                    if status:
                        # print("center int:",y0,x0)
                        # print("center crop int:",yc,xc)
                        # print("center subpix:",params[2],params[3])
                        adjusted_x = x0 + params[3]  # 将拟合结果映射回原图坐标
                        adjusted_y = y0 + params[2]   # x0,y0是加权质心得到的中心整数坐标
                        results.append((adjusted_y, adjusted_x))
                    else:
                        results.append((center[0], center[1]))  # 如果拟合失败，用加权质心得到的亚像素坐标
                        print(f"{index+1} st/nd dot Gaussian fiting failed! Use Moments coords instead.")
                else:
                    results.append((0,0))
                    print("Only One valid dots!")          
        else:
            print("No efficient spots!")
            return [0,0,0,0]

        # 计算两点间的偏移
        (y1, x1), (y2, x2) = results
        
        return [y1,x1,y2,x2]
    
    ## singleQpdScan
    #
    # Perform a single measurement of the focus lock offset and camera sum signal.
    #
    # @return [sum, x-offset, y-offset].
    """
    # def singleQpdScan(self):
    #     data = self.capture().copy()

    #     if self.background > 0: # Toggle between sum signal calculations
    #         power = numpy.sum(data) - self.background
    #     else:
    #         power = numpy.max(data)
        
    #     if (power < 25):
    #         # This hack is because if you bombard the USB camera with 
    #         # update requests too frequently it will freeze. Or so I
    #         # believe, not sure if this is actually true.
    #         #
    #         # It still seems to freeze?
    #         time.sleep(0.02)
    #         return [0, 0, 0]

    #     # Determine offset by fitting gaussians to the two beam spots.
    #     # In the event that only beam spot can be fit then this will
    #     # attempt to compensate. However this assumes that the two
    #     # spots are centered across the mid-line of camera ROI.
    #     if (self.fit_mode == 1):
    #         dist1 = 0
    #         dist2 = 0
    #         self.x_off1 = 0.0
    #         self.y_off1 = 0.0
    #         self.x_off2 = 0.0
    #         self.y_off2 = 0.0

    #         # Fit first gaussian to data in the left half of the picture.
    #         total_good =0
    #         [max_x, max_y, params, status] = self.fitGaussian(data[:,:int(self.half_x)])
    #         if status:
    #             total_good += 1
    #             self.x_off1 = float(max_x) + params[2] - self.half_y
    #             self.y_off1 = float(max_y) + params[3] - self.half_x
    #             dist1 = abs(self.y_off1)

    #         # Fit second gaussian to data in the right half of the picture.
    #         [max_x, max_y, params, status] = self.fitGaussian(data[:,-int(self.half_x):])
    #         if status:
    #             total_good += 1
    #             self.x_off2 = float(max_x) + params[2] - self.half_y
    #             self.y_off2 = float(max_y) + params[3]
    #             dist2 = abs(self.y_off2)

    #         if (total_good == 0):
    #             offset = 0
    #         elif (total_good == 1):
    #             offset = ((dist1 + dist2) - 0.5*self.zero_dist)*power 
    #         else:
    #             offset = ((dist1 + dist2) - self.zero_dist)*power

    #         return [power, offset, 0]

    #     # Determine offset by moments calculation.
    #     else:
    #         self.x_off1 = 1.0e-6
    #         self.y_off1 = 0.0
    #         self.x_off2 = 1.0e-6
    #         self.y_off2 = 0.0

    #         total_good = 0
    #         data_band = data[self.half_y-15:self.half_y+15,:]

    #         # Moment for the object in the left half of the picture.
    #         x = numpy.arange(self.half_x)
    #         data_ave = numpy.average(data_band[:,:self.half_x], axis = 0)
    #         power1 = numpy.sum(data_ave)

    #         dist1 = 0.0
    #         if (power1 > 0.0):
    #             total_good += 1
    #             self.y_off1 = numpy.sum(x * data_ave) / power1 - self.half_x
    #             dist1 = abs(self.y_off1)

    #         # Moment for the object in the right half of the picture.
    #         data_ave = numpy.average(data_band[:,self.half_x:], axis = 0)
    #         power2 = numpy.sum(data_ave)

    #         dist2 = 0.0
    #         if (power2 > 0.0):
    #             total_good += 1
    #             self.y_off2 = numpy.sum(x * data_ave) / power2
    #             dist2 = abs(self.y_off2)

    #         if (total_good == 0):
    #             offset = 0
    #         elif (total_good == 1):
    #             offset = ((dist1 + dist2) - 0.5*self.zero_dist)*power
    #         else:
    #             offset = ((dist1 + dist2) - self.zero_dist)*power

    #         # The moment calculation is too fast. This is to slow things
    #         # down so that (hopefully) the camera doesn't freeze up.
    #         time.sleep(0.02)

    #         return [power, offset, 0]
    """    

    # new singleQpdScan    2024.11
    def singleQpdScan(self):
        data = self.capture().copy()

        # if self.background > 0: # Toggle between sum signal calculations
        #     power = numpy.max(data) - self.background
        # else:
        #     power = numpy.max(data)
        
        power = numpy.max(data)           # - self.background

        if (power < 40):
            # This hack is because if you bombard the USB camera with 
            # update requests too frequently it will freeze. Or so I
            # believe, not sure if this is actually true.
            #
            # It still seems to freeze?
            time.sleep(0.02)
            return [0, 0, 0]

        # Determine offset by fitting gaussians to the two beam spots.
        # In the event that only beam spot can be fit then this will
        # attempt to compensate. However this assumes that the two
        # spots are centered across the mid-line of camera ROI.
        
        # 使用mean + 3*std作为阈值去除背景
        mean_cv2, std_dev_cv2 = cv2.meanStdDev(data)
        threshold_cv2 = int(numpy.ceil(mean_cv2 + 3*std_dev_cv2))
        self.background = round(mean_cv2[0][0],1)

        ret,img_1 = cv2.threshold(data,threshold_cv2,255,cv2.THRESH_TOZERO)

        centers = self.prefit(img_1)
        # print("center 1 :",centers[0])
        # print("center 2 :",centers[1])  

        if (self.fit_mode == 1):
            [y1,x1,y2,x2] = self.dofit(img_1, centers)
            num_save = 4
            # print("Gaussian 1:",(y1,x1))
            # print("Gaussian 2:",(y2,x2))
        # Determine offset by moments calculation.
        else:
            print("Moment calculation used!")
            # temp = []
            # for center in centers:
            #     y, x = center[0], center[1]
            #     temp.append((y, x))
            (y1, x1), (y2, x2) = centers
            num_save = 3

        #  两点相对运动时
        # x_offset = round((x1 - x2) ** 2,num_save)
        # y_offset = round((y1 - y2) ** 2,num_save)

        # 两点平行运动时
        x_offset = round((x1 + x2)-2*self.half_x,num_save)
        y_offset = round((y1 + y2)-2*self.half_y,num_save)
        
        self.x_off1 = x1
        self.y_off1 = y1
        self.x_off2 = x2
        self.y_off2 = y2    

        return [power, x_offset, y_offset]


# Testing
if __name__ == "__main__":

    from PIL import Image
    import matplotlib.pyplot as plt

    # cam = Camera(1)
    cam = CameraQPD(camera_id = 1,
                                 x_width = 200,
                                 y_width = 200,
                                 offset_file = "cam_offsets_IX83_2.txt",
                                 background = 0)
    #print(cam.getCameraType(1))
    reps = 50

    if 0:
        cam.setAOI(772, 566, 200, 200)
        cam.setFrameRate(verbose = True)
        for i in range(100):
            print("start", i)
            for j in range(100):
                image = cam.captureImage()
            print(" stop")

        #im = Image.fromarray(image)
        #im.save("temp.png")

    if 0:
        cam.setAOI(100, 100, 300, 300)
        cam.setPixelClock()
        cam.setFrameRate()
        cam.startCapture()
        st = time.time()
        for i in range(reps):
            #print i
            image = cam.getNextImage()
            #print i, numpy.sum(image)
        print("time:", time.time() - st)
        cam.stopCapture()

    if 0:
        cam.setAOI(100, 100, 300, 300)
        cam.setPixelClock()
        cam.setFrameRate()
        st = time.time()
        for i in range(reps):
            #print i
            image = cam.captureImage()
            print(i, numpy.sum(image))
        print("time:", time.time() - st)

    if 0:
        cam.setAOI(450, 545, 200, 200)
        image = cam.captureImage()
        im = Image.fromarray(image)

        # 显示图像
        plt.figure(figsize=(6, 6))  # 设置图像窗口大小
        plt.imshow(image, cmap='gray')  # 显示为灰度图
        plt.colorbar()  # 显示颜色条（可选）
        plt.title("Captured Image")  # 图像标题
        plt.axis("off")  # 关闭坐标轴
        plt.show()

        im.save("FL_test_22.8.png")
        cam.saveParameters("cam2.ini")
        
    if 0:
        cam.cam.setAOI(450, 545, 200, 200)
        #cam.cam.setAOI(550, 200, 500, 500)
        image = cam.cam.captureImage()
        # 显示图像
        plt.figure(figsize=(6, 6))  # 设置图像窗口大小
        plt.imshow(image, cmap='gray')  # 显示为灰度图
        plt.colorbar()  # 显示颜色条（可选）
        plt.title("Captured Image")  # 图像标题
        plt.axis("off")  # 关闭坐标轴
        plt.show()
        print("image dtype:", image.dtype)
        im = Image.fromarray(image)
        im.save("FL_test_22.8.png")
        #cam.cam.saveParameters("cam2.ini")

    cam.shutDown()

#
# The MIT License
#
# Copyright (c) 2013 Zhuang Lab, Harvard University
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
