# -*- coding:utf-8 -*-

from jacketcache import JacketStatusCache
from vcloudsynchronizer import HCVCS
import log as logger
logger.init("test", output=True)

vcloud_info = {}
a = HCVCS(host="162.4.110.132", username="vdc3-user", org="vdc3", password="huawei")
j = JacketStatusCache(a)

status = j.query_status("server@64140b17-b76a-47dc-8d7f-37d8b22f361e")
print status

status = j.query_status("server@d26ad237-6997-425a-9d94-713e07653b71")
print status

status = j.query_status("server@64140b17-b76a-47dc-8d7f-37d8b22f361e")
print status

status = j.query_status("server@d26ad237-6997-425a-9d94-713e07653b71")
print status