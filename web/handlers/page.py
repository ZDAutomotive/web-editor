# coding: utf-8
#

import base64
import io
import json
import os
import traceback

import tornado
from logzero import logger
from PIL import Image
from tornado.escape import json_decode

from ..device import connect_device, get_device
from ..version import __version__


pathjoin = os.path.join


class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header("Access-Control-Allow-Credentials",
                        "true")  # allow cookie
        self.set_header('Access-Control-Allow-Methods',
                        'POST, GET, PUT, DELETE, OPTIONS')

    def options(self, *args):
        self.set_status(204)  # no body
        self.finish()

    def check_origin(self, origin):
        """ allow cors request """
        return True


class VersionHandler(BaseHandler):
    def get(self):
        ret = {
            'name': "weditor",
            'version': __version__,
        }
        self.write(ret)


class MainHandler(BaseHandler):
    def get(self):
        self.render("index.html")


class DeviceConnectHandler(BaseHandler):
    def post(self):
        platform = self.get_argument("platform").lower()
        device_url = self.get_argument("deviceUrl")

        try:
            id = connect_device(platform, device_url)
        except RuntimeError as e:
            self.set_status(500)
            self.write({
                "success": False,
                "description": str(e),
            })
        except Exception as e:
            logger.warning("device connect error: %s", e)
            self.set_status(500)
            self.write({
                "success": False,
                "description": traceback.format_exc(),
            })
        else:
            ret = {
                "deviceId": id,
                'success': True,
            }
            if platform == "android":
                ws_addr = get_device(id).device.address.replace("http://", "ws://") # yapf: disable
                ret['screenWebSocketUrl'] = ws_addr + "/minicap"
            self.write(ret)


class DeviceHierarchyHandler(BaseHandler):
    def get(self, device_id):
        d = get_device(device_id)
        self.write(d.dump_hierarchy())


class DeviceHierarchyHandlerV2(BaseHandler):
    def get(self, device_id):
        d = get_device(device_id)
        self.write(d.dump_hierarchy2())


class WidgetPreviewHandler(BaseHandler):
    def get(self, id):
        self.render("widget_preview.html", id=id)


class DeviceWidgetListHandler(BaseHandler):
    __store_dir = os.path.expanduser("~/.weditor/widgets")

    def generate_id(self):
        os.makedirs(self.__store_dir, exist_ok=True)
        names = [
            name for name in os.listdir(self.__store_dir)
            if os.path.isdir(os.path.join(self.__store_dir, name))
        ]
        return "%05d" % (len(names) + 1)

    def get(self, widget_id: str):
        data_dir = os.path.join(self.__store_dir, widget_id)
        with open(pathjoin(data_dir, "hierarchy.xml"), "r",
                  encoding="utf-8") as f:
            hierarchy = f.read()

        with open(os.path.join(data_dir, "meta.json"), "rb") as f:
            meta_info = json.load(f)
            meta_info['hierarchy'] = hierarchy
            self.write(meta_info)

    def json_parse(self, source):
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)

    def put(self, widget_id: str):
        """ update widget data """
        data = json_decode(self.request.body)
        target_dir = os.path.join(self.__store_dir, widget_id)
        with open(pathjoin(target_dir, "hierarchy.xml"), "w",
                  encoding="utf-8") as f:
            f.write(data['hierarchy'])

        # update meta
        meta_path = pathjoin(target_dir, "meta.json")
        meta = self.json_parse(meta_path)
        meta["xpath"] = data['xpath']
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(meta, indent=4, ensure_ascii=False))

        self.write({
            "success": True,
            "description": f"widget {widget_id} updated",
        })

    def post(self):
        data = json_decode(self.request.body)
        widget_id = self.generate_id()
        target_dir = os.path.join(self.__store_dir, widget_id)
        os.makedirs(target_dir, exist_ok=True)

        image_fd = io.BytesIO(base64.b64decode(data['screenshot']))
        im = Image.open(image_fd)
        im.save(pathjoin(target_dir, "screenshot.jpg"))

        lx, ly, rx, ry = bounds = data['bounds']
        im.crop(bounds).save(pathjoin(target_dir, "template.jpg"))

        cx, cy = (lx + rx) // 2, (ly + ry) // 2
        # TODO(ssx): missing offset
        # pprint(data)
        widget_data = {
            "resource_id": data["resourceId"],
            "text": data['text'],
            "description": data["description"],
            "target_size": [rx - lx, ry - ly],
            "package": data["package"],
            "activity": data["activity"],
            "class_name": data['className'],
            "rect": dict(x=lx, y=ly, width=rx-lx, height=ry-ly),
            "window_size": data['windowSize'],
            "xpath": data['xpath'],
            "target_image": {
                "size": [rx - lx, ry - ly],
                "url": f"http://localhost:17310/widgets/{widget_id}/template.jpg",
            },
            "device_image": {
                "size": im.size,
                "url": f"http://localhost:17310/widgets/{widget_id}/screenshot.jpg",
            },
            # "hierarchy": data['hierarchy'],
        } # yapf: disable

        with open(pathjoin(target_dir, "meta.json"), "w",
                  encoding="utf-8") as f:
            json.dump(widget_data, f, ensure_ascii=False, indent=4)

        with open(pathjoin(target_dir, "hierarchy.xml"), "w",
                  encoding="utf-8") as f:
            f.write(data['hierarchy'])

        self.write({
            "success": True,
            "id": widget_id,
            "note": data['text'] or data['description'],  # 备注
            "data": widget_data,
        })


class DeviceScreenshotHandler(BaseHandler):
    def get(self, serial):
        logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            buffer = io.BytesIO()
            d.screenshot().convert("RGB").save(buffer, format='JPEG')
            b64data = base64.b64encode(buffer.getvalue())
            response = {
                "type": "jpeg",
                "encoding": "base64",
                "data": b64data.decode('utf-8'),
            }
            self.write(response)
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(500, "Environment Error")
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(500)  # Gone
            self.write({"description": traceback.format_exc()})
class WindowSizeHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            size = d.device.window_size()
            response = {
                "width": size[0],
                "height": size[1]
            }
            logger.info("device window size: %s", response) 
            self.write(response)
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device window size: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device window size: %s", e)
            self.write({"description": traceback.print_exc()})

# class LogcatHandler(BaseHandler):
#     def get(self, serial):
#         # logger.info("Serial: %s", serial)
#         try:
#             d = get_device(serial)
#             r = d.device.shell("logcat", stream=True)
#             # r: requests.models.Response
#             deadline = time.time() + 1 # run maxium 10s
#             try:
#                 for line in r.iter_lines(): # r.iter_lines(chunk_size=512, decode_unicode=None, delimiter=None)
#                     if time.time() > deadline:
#                         break
#                     # logger.info("Read:", line.decode('utf-8'))
#             finally:
#                 r.close() # this method must be called
#                 response = {
#                     "msg": line.decode('utf-8')
#                 }
#             self.write(response)
#         except EnvironmentError as e:
#             traceback.print_exc()
#             self.set_status(430, "Environment Error")
#             self.write({"description": str(e)})
#         except RuntimeError as e:
#             self.set_status(410)  # Gone
#             self.write({"description": traceback.print_exc()})

class SelectedHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(parse.unquote(self.get_argument("origin")))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            device = d.weight(origin, flag, index)
            if device.exists:
                result = device.info['selected']
                logger.info("element %s selected: %s", d.serial() , result)
                self.write({
                    "success": True,
                    "selected": result
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "success": False,
                    "selected": False,
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.info("element selected: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.info("element selected: %s", e)
            self.write({"description": traceback.print_exc()})

class AssertSelectHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            target = parse.unquote(self.get_argument("target"))
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            device = d.weight(origin, flag, index)
            if device.exists:
                result = target == device.info['selected']
                logger.info("element %s assert selected: %s", d.serial() , str(result))
                self.write({
                    "success": True,
                    "result": result
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "success": False,
                    "result": False,
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            logger.info("element assert selected: %s", e)
            self.set_status(430, "Environment Error")
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.info("element assert selected: %s", e)
            self.write({"description": traceback.print_exc()})

class EnabledHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            device = d.weight(origin, flag, index)
            if device.exists:
                result = device.info['enabled']
                logger.info("element %s enabled: %s", d.serial() , result)
                self.write({
                    "success": True,
                    "enabled": result
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "success": False,
                    "enabled": False,
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.info("element enabled: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.info("element enabled: %s", e)
            self.write({"description": traceback.print_exc()})


class AssertEnabledHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            target = parse.unquote(self.get_argument("target"))
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            device = d.weight(origin, flag, index)
            if device.exists:
                result = target == device.info['enabled']
                logger.info("element %s enabled: %s", d.serial() , str(result))
                self.write({
                    "success": True,
                    "result": result
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "success": False,
                    "result": False,
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("element assert enabled: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("element assert enabled: %s", e)
            self.write({"description": traceback.print_exc()})

class ActivityHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            package = self.get_argument("package", "")
            activity = self.get_argument("activity", "")
            if not all([package, activity]):
                d.device.app_start(package, activity)
            elif not package:
                d.device.app_start(package)
            logger.info("device start app: %s %s", package, activity)   
            self.write({
                "success": True
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device start app: %s", e)   
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device start app: %s", e)   
            self.write({"description": traceback.print_exc()})

class PackageHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            current = d.device.app_current()
            logger.info("device current app: %s", str(current))   
            self.write({
                "success": True,
                "activity": current["activity"],
                "package": current["package"]
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device current app: %s", e)  
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device current app: %s", e)  
            self.write({"description": traceback.print_exc()})



class ClickHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            device = d.weight(origin, flag, index)
            if device.exists:
                device.click()
                logger.info("device click: %s", d.serial())  
                self.write({
                    "success": True
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "success": False,
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device click: %s", e)  
            self.write({"description": str(e)})
            logger.error(e)
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device click: %s", e)  
            self.write({"description": traceback.print_exc()})

class TapHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            x = self.get_argument("x", '0')
            y = self.get_argument("y", '0')
            d.click(int(x), int(y))
            logger.info("device tap: %s", d.serial())  
            self.write({
                "success": True
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device tap: %s", e)  
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device tap: %s", e)  
            self.write({"description": traceback.print_exc()})

class LongTapHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            x = self.get_argument("x", '0')
            y = self.get_argument("y", '0')
            duration = self.get_argument("duration", '0.5')
            d.long_click(int(x), int(y), float(duration))
            logger.info("device long tap: %s", d.serial())  
            self.write({
                "success": True
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device long tap: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device long tap: %s", e)
            self.write({"description": traceback.print_exc()})

class SwipeHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            x1 = self.get_argument("x1", '0')
            y1 = self.get_argument("y1", '0')
            x2 = self.get_argument("x2", '0')
            y2 = self.get_argument("y2", '0')
            duration = self.get_argument("duration", '0.5')
            d.swipe(x1, y1, x2, y2, duration)
            logger.info("device swipe: %s", d.serial())
            self.write({
                "success": True
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device swipe: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device swipe: %s", e)
            self.write({"description": traceback.print_exc()})

class PressHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            key = self.get_argument("key", "back")
            d.press(key)
            logger.info("device press: %s key %s", d.serial(), key)
            self.write({
                "success": True
            })
        except EnvironmentError as e:
            traceback.print_exc()
            logger.error("device press: %s", e)
            self.set_status(430, "Environment Error")
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device press: %s", e)
            self.write({"description": traceback.print_exc()})

class SwipeExtHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            direction = self.get_argument("direction", 'up')
            scaleNum = self.get_argument("scale", '0.8')
            d.swipe_ext(direction, scaleNum)
            logger.info("device swipe ext: %s direction %s", d, direction)
            self.write({
                "success": True
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("device swipe ext: %s ", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("device swipe ext: %s ", e)
            self.write({"description": traceback.print_exc()})


class TextHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            device = d.weight(origin, flag, index)
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            if device.exists:
                text = device.get_text()
                logger.info("element: %s get text: %s", device, text)
                self.write({
                    "text": text
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "text": "",
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("element get text: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("element get text: %s", e)
            self.write({"description": traceback.print_exc()})

class AssertTextHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            target = parse.unquote(self.get_argument("target"))
            device = d.weight(origin, flag, index)
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            if device.exists:
                text = device.get_text()
                result = text == target
                logger.info("element: %s get text: %s, assert text result: %s", device, text, str(result))
                self.write({
                    "success": True,
                    "result": result
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "result": False,
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("element assert text: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("element assert text: %s", e)
            self.write({"description": traceback.print_exc()})
            
class InputHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            inputText = self.get_argument("input", "")
            device = d.weight(origin, flag, index)
            # if origin == 'text':
            #     device = d.device(text=flag, instance = index)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            
            if device.exists:
                device.set_text(inputText)
                logger.info("element: %s set text: %s", device, inputText)
                self.write({
                    "success": True
                })
            else:
                logger.info("element %s is not exists", d.serial())
                self.write({
                    "result": False,
                    "msg": 'element is not exists'
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("element set text: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("element set text: %s", e)
            self.write({"description": traceback.print_exc()})


class ExistsHandler(BaseHandler):
    def get(self, serial):
        logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            # if origin == 'text':
            #     device = d.device(text=flag, instance = index)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            device = d.weight(origin, flag, index)
            result = device.exists
            logger.info("element %s is exists result: %s", d.serial(), result)
            self.write({
                    "success": True,
                    "exists": result
                })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("element exists: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("element exists: %s", e)
            self.write({"description": traceback.print_exc()})


class AssertExistsHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            d = get_device(serial)
            origin = parse.unquote(self.get_argument("origin"))
            flag = parse.unquote(self.get_argument("flag"))
            index = self.get_argument("index", 0)
            target = parse.unquote(self.get_argument("target"))
            device = d.weight(origin, flag, index)
            # if origin == 'text':
            #     device = d.device(text=flag)
            # elif origin == 'resource_id':
            #     device = d.device(resourceId=flag, instance = index)
            # elif origin == 'xpath':
            #     device = d.device.xpath(flag)
            # elif origin == 'description':
            #     device = d.device(description=flag, instance = index)
            exists = device.exists
            print(str(exists).lower() ==  target)
            result = str(exists).lower() ==  target
            logger.info("element: %s  is exists: %s, assert exists result: %s", device, str(exists), str(result))
            self.write({
                "success": True,
                "exists": result
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("element assert exists: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("element assert exists: %s", e)
            self.write({"description": traceback.print_exc()})

class InstallHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            if serial.find(":")!=-1:
                platform, uri = serial.split(":", maxsplit=1)
            else:
                uri = get_device(serial).device.device_info["serial"]
            installUrl = self.get_argument("installUrl")
            cmd = "adb -s " + uri + " install " + installUrl
            logger.info("install apk:" + cmd)
            pi= subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
            result = pi.stdout.read().decode()
            logger.info("install apk result:" + result)
            self.write({
                "success": result.find("Success") != -1,
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("adb install result: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("adb install result: %s", e)
            self.write({"description": traceback.print_exc()})

class UnInstallHandler(BaseHandler):
    def get(self, serial):
        # logger.info("Serial: %s", serial)
        try:
            if serial.find(":")!=-1:
                platform, uri = serial.split(":", maxsplit=1)
            else:
                uri = get_device(serial).device.device_info["serial"]
            package = self.get_argument("package")
            cmd = "adb -s " + uri + " uninstall " + package
            logger.info("uninstall apk:" + cmd)
            pi= subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
            result = pi.stdout.read().decode()
            print(result)
            logger.info("uninstall apk result:" + result)
            self.write({
                "success": result.find("Success") != -1,
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("adb uninstall result: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("adb uninstall result: %s", e)
            self.write({"description": traceback.print_exc()})


class DevicesHandler(BaseHandler):
    def get(self):
        try:
            devices = get_devices()
            self.write({
                "success": True,
                "result": devices
            })
        except EnvironmentError as e:
            traceback.print_exc()
            self.set_status(430, "Environment Error")
            logger.error("devices list failed: %s", e)
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("devices list failed: %s", e)
            self.write({"description": traceback.print_exc()})
    

class TellHandler(BaseHandler):
    def get(self, serial):
        try:
            d = get_device(serial)
            phone = self.get_argument("phone", "")
            cmd = "adb -s " + d.serial() + " shell am start -a android.intent.action.CALL tel:" + phone
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read()
            logger.info("devices send call command: %s ,result: success", cmd)
            self.write({
                "success": True,
                "result": parse.quote(process)
            })
        except EnvironmentError as e:
            traceback.print_exc()
            logger.error("devices send call failed: %s", e)
            self.set_status(430, "Environment Error")
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("devices send call failed: %s", e)
            self.write({"description": traceback.print_exc()})
            
class EndTellHandler(BaseHandler):
    def get(self, serial):
        try:
            d = get_device(serial)
            cmd = "adb -s " + d.serial() + " shell input  keyevent  KEYCODE_ENDCALL"
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read()
            logger.info("devices end call command: %s ,result: success", cmd)
            self.write({
                "success": True,
                "result": parse.quote(process)
            })
        except EnvironmentError as e:
            traceback.print_exc()
            logger.error("devices end call failed: %s", e)
            self.set_status(430, "Environment Error")
            self.write({"description": str(e)})
        except RuntimeError as e:
            self.set_status(410)  # Gone
            logger.error("devices end call failed: %s", e)
            self.write({"description": traceback.print_exc()})
