# coding: utf-8
#

import enum

class PlatformEnum(str, enum.Enum):
    AndroidMock = "AndroidMock"
    AndroidUIAutomator2 = "Android"
    AndroidADB = "AndroidADB"
    IOS = "iOS"
