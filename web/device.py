# coding: utf-8
#

import abc

import uiautomator2 as u2
import wda
from logzero import logger
from PIL import Image

from . import uidumplib


class DeviceMeta(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def screenshot(self) -> Image.Image:
        pass

    def dump_hierarchy(self) -> str:
        pass

    @abc.abstractproperty
    def device(self):
        pass


class _AndroidDevice(DeviceMeta):
    def __init__(self, device_url):
        d = u2.connect(device_url)
        # 登陆界面无法截图，就先返回空图片
        d.settings["fallback_to_blank_screenshot"] = True
        self._d = d

    def screenshot(self):
        return self._d.screenshot()

    def dump_hierarchy(self):
        return uidumplib.get_android_hierarchy(self._d)

    def dump_hierarchy2(self):
        current = self._d.app_current()
        page_xml = self._d.dump_hierarchy(pretty=True)
        page_json = uidumplib.android_hierarchy_to_json(
            page_xml.encode('utf-8'))
        return {
            "xmlHierarchy": page_xml,
            "jsonHierarchy": page_json,
            "activity": current['activity'],
            "packageName": current['package'],
            "windowSize": self._d.window_size(),
        }

    def device_info(self):
        return self._d.device_info
        
    def weight(self, classify, value,index):
        if classify == 'text':
            element = self._d(text=value, instance = index)
        elif classify == 'resource_id':
            element = self._d(resourceId=value, instance = index)
        elif classify == 'xpath':
            element = self._d.xpath(value)
        elif classify == 'description':
            element = self._d(description=value, instance = index)
        elif classify == 'className':
            element = self._d(className=value, instance = index)
        return element

    def serial(self):
        return self._d.device_info["serial"]

    def swipe(self, x1, y1, x2, y2, duration):
        return self._d.swipe(int(x1), int(y1), int(x2), int(y2), float(duration))
        

    def press(self, key):
        self._d.press(key)
    
    def long_click(self, x, y, duration):
        self._d.long_click(int(x), int(y), float(duration))

    def click(self, x, y):
        self._d.click(int(x), int(y))

    def swipe_ext(self, direction, scaleNum):
         self._d.swipe_ext(direction, scale = float(scaleNum))

    def shell(self, command):
        output, exit_code = self._d.shell(command, timeout=60)
        return {
            "result": output,
            "code": exit_code
        }
        
    def image(self):
        self._d.image

    @property
    def device(self):
        return self._d


class _AppleDevice(DeviceMeta):
    def __init__(self, device_url):
        logger.info("ios connect: %s", device_url)
        if device_url == "":
            c = wda.USBClient()
        else:
            c = wda.Client(device_url)
        self._client = c
        self.__scale = c.scale

    def screenshot(self):
        try:
            return self._client.screenshot(format='pillow')
        except:
            import tidevice
            return tidevice.Device().screenshot()

    def dump_hierarchy(self):
        return uidumplib.get_ios_hierarchy(self._client, self.__scale)

    def dump_hierarchy2(self):
        return {
            "jsonHierarchy":
            uidumplib.get_ios_hierarchy(self._client, self.__scale),
            "windowSize":
            self._client.window_size(),
        }

    @property
    def device(self):
        return self._client


cached_devices = {}


def connect_device(platform, device_url):
    """
    Returns:
        deviceId (string)
    """
    if not len(device_url) == 0:
        device_id = platform + ":" + device_url
    else:
        device_id = platform
    if platform == 'android':
        d = _AndroidDevice(device_url)
    elif platform == 'ios':
        d = _AppleDevice(device_url)
    else:
        raise ValueError("Unknown platform", platform)

    cached_devices[device_id] = d
    return device_id


def get_device(id):
    d = cached_devices.get(id)
    if d is None:
        if id.find(":")!=-1:
            platform, uri = id.split(":", maxsplit=1)
        else:
            platform = id
            uri = ""
        connect_device(platform, uri)
    return cached_devices[id]

def get_devices():
    devices = []
    for id in cached_devices:
        info = cached_devices[id].device_info()
        devices.append({
            "devicesName": id,
            "devicesInfo": {
                "udid": info["udid"],
                "serial": info["serial"],
                "model": info["model"],
                "hwaddr": info["hwaddr"],
                "port": info["port"],
                "sdk": info["sdk"]
            }
        })
    return devices