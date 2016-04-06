# -*- coding:utf-8 -*-

import log as logger
import power_state
import threading
import time


EXP_TIME = 50


logger.init("jacket-cache", output=False)


_cache_lock = threading.Lock()


def singleton(cls, *args, **kw):
    instances = {}
    def _singleton():
        if cls not in instances:
            instances[cls] = cls(*args, **kw)
        return instances[cls]
    return _singleton


@singleton()
class JacketStatusCache(object):

    def __init__(self, synchronizer):
        logger.info("init jacket status cache.")
        self.synchronizer = synchronizer
        self.status_map = self.synchronizer.synchronize_status()
        self.last_sync_time = time.time()

    def query_status(self, instance_id):
        _cache_lock.acquire()
        now = time.time()
        try:
            if now - self.last_sync_time > EXP_TIME:
                logger.info("cache have expire. sync cache. now = %s, last sync time = %s" % (now, self.last_sync_time))
                self.status_map = self.synchronizer.synchronize_status()
                self.last_sync_time = time.time()
                logger.info("sync cache success, cache size = %s." % len(self.status_map))
        except Exception as e:
            logger.error("sync cache failed.", e)
        finally:
            _cache_lock.release()

        if instance_id in self.status_map:
            status = self.status_map.get(instance_id)
            return status

        logger.debug("query status, can not find instance record, instance_id = %s." % instance_id)

        _cache_lock.acquire()
        try:
            logger.debug("query status, synchronize status.")
            self.status_map = self.synchronizer.synchronize_status()
            self.last_sync_time = time.time()
            logger.info("sync cache success, cache size = %s." % len(self.status_map))
        except Exception as e:
            logger.error("sync cache failed.", e)
        finally:
            _cache_lock.release()

        logger.debug("query status, try to find instance record after synchronize, instance_id = %s." % instance_id)
        if instance_id in self.status_map:
            status = self.status_map.get(instance_id)
            logger.debug("query status success, instance_id = %s, status = %s" % (instance_id, status))
            return status

        logger.error("can not get instance status, instance_id: %s" % instance_id)
        return power_state.NOSTATE
