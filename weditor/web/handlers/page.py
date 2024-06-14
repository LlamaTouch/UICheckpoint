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
from ..proto import PlatformEnum

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


class AndroidMockAnnotationHandler(BaseHandler):
    def clean_annotation(self, annotations):
        """
        function: clean repeated annotations
        """
        cleaned_data = []  
        seen = set()  
        for annotation in annotations:
            for key, value in annotation.items():
                identifier = f"{key}:{value}"
                if identifier not in seen:
                    seen.add(identifier)
                    cleaned_data.append({key: value})        
        
        return cleaned_data

    def post(self):
        '''
            data example:
                {
                    deviceId: AndroidMock:/data/AndroidMockData/,
                    index: 0,
                    data: [
                        {
                        "activity": "-1",
                        "fuzzyScreen": "-1"
                        },
                        {
                        "install": "com.google.android.apps.youtube.music",
                        "uninstall": "com.google.android.apps.youtube.music",
                        },
                        {
                        "textbox": "//*[@resource-id="rendered-content"]/android.view.View[3]/android.view.View[1]/android.view.View[1]",
                        "exact": "//*[@resource-id="com.google.android.apps.youtube.music:id/chip_cloud"]/android.widget.FrameLayout[4]",
                        "exclude": "//*[@resource-id="com.google.android.apps.youtube.music:id/chip_cloud"]/android.widget.FrameLayout[4]"
                        },
                    ],
                }
        '''
        try:
            data = json.loads(self.request.body.decode('utf-8'))  # Ensure correct decoding from bytes
            print(data)
            # Extract device ID and index for file path
            device_path = data.get('deviceId', '').split(':')[1]
            index = data.get('index', 0)
            checkpoint_fp = os.path.join(device_path, f'{index}.ess')
            
            # Prepare to write annotations
            annotations = data.get('data', {})
           
            cleaned_annotation = self.clean_annotation(annotations)
            content_to_write = []
            for item in cleaned_annotation:
                for key, value in item.items():
                    if key == "textbox" or key == "fuzzyScreen":
                        content_to_write.append(f"fuzzy<{value}>")
                    else:
                        content_to_write.append(f"{key}<{value}>")
            
            print(content_to_write)
            # Write the annotations to a file
            if content_to_write:  # Check if there is something to write
                with open(checkpoint_fp, "w") as file:
                    file.write("|".join(content_to_write))
                self.write({"success": True, "message": "Data received and processed successfully."})
            else:
                self.write({"success": False, "message": "No valid annotations to process."})

        except json.JSONDecodeError as e:
            self.set_status(400)  # Bad Request
            self.write({"success": False, "message": "Invalid JSON data.", "error": str(e)})
        except OSError as e:
            self.set_status(500)  # Internal Server Error
            self.write({"success": False, "message": "File operation failed.", "error": str(e)})
        except Exception as e:
            self.set_status(500)  # Internal Server Error
            self.write({"success": False, "message": "An unexpected error occurred.", "error": str(e)})



class AndroidMockUpdateIndexHandler(BaseHandler):
    def post(self):
        data = json.loads(self.request.body)
        device_id = data.get("deviceId")
        index = int(data.get("index"))
        d = get_device(device_id)
        if index > d.maxindex:
            index = d.maxindex  # Set index to maxindex if it's out of range
            self.write({
                "success": False,
                "description": "Have reached the end of the data!",
                "index": index
            })
        else:
            d.setIndex(index)
            self.write({
                "success": True,
                "description": f"Updated index to {index}",
                "index": index
            })


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
        _platform = self.get_argument("platform")
        device_url = self.get_argument("deviceUrl")

        platform = PlatformEnum(_platform)
        del _platform
        try:
            id = connect_device(platform, device_url)
        except RuntimeError as e:
            logger.exception("connect failed")
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
                # ws_addr = get_device(id).device.address.replace("http://", "ws://") # yapf: disable
                ret['screenWebSocketUrl'] = None #ws_addr + "/minicap"
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

