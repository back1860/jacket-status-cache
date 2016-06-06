
import subprocess
import time


from nova import exception
from nova.openstack.common import log as logging
from nova.virt.hybrid.vcloud.vcloud import RetryDecorator
from nova.virt.hybrid.vcloud.vcloud import VCloudAPISession
from nova.virt.hybrid.vcloud.vcloud import exceptions
from oslo.config import cfg
from setuptools.command.egg_info import overwrite_arg

from jacketstatuscache.jacketcache import JacketStatusCache
from jacketstatuscache.vcloudsynchronizer import HCVCS
from nova.virt.hybrid.vcloud.vcloud import VCLOUD_STATUS
from nova.compute import power_state

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

status_dict_vapp_to_instance = {
    VCLOUD_STATUS.FAILED_CREATION: power_state.CRASHED,
    VCLOUD_STATUS.UNRESOLVED: power_state.NOSTATE,
    VCLOUD_STATUS.RESOLVED: power_state.NOSTATE,
    VCLOUD_STATUS.DEPLOYED: power_state.NOSTATE,
    VCLOUD_STATUS.SUSPENDED: power_state.SUSPENDED,
    VCLOUD_STATUS.POWERED_ON: power_state.RUNNING,
    VCLOUD_STATUS.WAITING_FOR_INPUT: power_state.NOSTATE,
    VCLOUD_STATUS.UNKNOWN: power_state.NOSTATE,
    VCLOUD_STATUS.UNRECOGNIZED: power_state.NOSTATE,
    VCLOUD_STATUS.POWERED_OFF: power_state.SHUTDOWN,
    VCLOUD_STATUS.INCONSISTENT_STATE: power_state.NOSTATE,
    VCLOUD_STATUS.MIXED: power_state.NOSTATE,
    VCLOUD_STATUS.DESCRIPTOR_PENDING: power_state.NOSTATE,
    VCLOUD_STATUS.COPYING_CONTENTS: power_state.NOSTATE,
    VCLOUD_STATUS.DISK_CONTENTS_PENDING: power_state.NOSTATE,
    VCLOUD_STATUS.QUARANTINED: power_state.NOSTATE,
    VCLOUD_STATUS.QUARANTINE_EXPIRED: power_state.NOSTATE,
    VCLOUD_STATUS.REJECTED: power_state.NOSTATE,
    VCLOUD_STATUS.TRANSFER_TIMEOUT: power_state.NOSTATE,
    VCLOUD_STATUS.VAPP_UNDEPLOYED: power_state.NOSTATE,
    VCLOUD_STATUS.VAPP_PARTIALLY_DEPLOYED: power_state.NOSTATE,
}


class VCloudClient(object):

    def __init__(self, scheme):
        self._metadata_iso_catalog = CONF.vcloud.metadata_iso_catalog
        self._session = VCloudAPISession(
            host_ip=CONF.vcloud.vcloud_host_ip,
            host_port=CONF.vcloud.vcloud_host_port,
            server_username=CONF.vcloud.vcloud_host_username,
            server_password=CONF.vcloud.vcloud_host_password,
            org=CONF.vcloud.vcloud_org,
            vdc=CONF.vcloud.vcloud_vdc,
            version=CONF.vcloud.vcloud_version,
            service=CONF.vcloud.vcloud_service,
            verify=CONF.vcloud.vcloud_verify,
            service_type=CONF.vcloud.vcloud_service_type,
            retry_count=CONF.vcloud.vcloud_api_retry_count,
            create_session=True,
            scheme=scheme)

        # add for status cache
        hcvcs = HCVCS(
           host=CONF.vcloud.vcloud_host_ip,
           username=CONF.vcloud.vcloud_host_username,
           org=CONF.vcloud.vcloud_org,
           password=CONF.vcloud.vcloud_host_password,
           scheme="https")

        self.cache = JacketStatusCache(hcvcs)
        # add end for status cache

    @property
    def org(self): 
        return self._session.org

    @property
    def username(self): 
        return self._session.username

    @property
    def password(self): 
        return self._session.password

    @property
    def vdc(self): 
        return self._session.vdc

    @property
    def host_ip(self): 
        return self._session.host_ip

    def _get_vcloud_vdc(self):
        return self._invoke_api("get_vdc",
                                self._session.vdc)

    def _get_vcloud_vapp(self, vapp_name):
        the_vapp = self._invoke_api("get_vapp",
                                    self._get_vcloud_vdc(),
                                    vapp_name)

        if not the_vapp:
            #raise exception.NovaException("can't find the vapp")
            LOG.info("can't find the vapp %s" % vapp_name)
            return None
        else:
            return the_vapp

    def _invoke_api(self, method_name, *args, **kwargs):
        res = self._session.invoke_api(self._session.vca,
                                       method_name,
                                       *args, **kwargs)
        LOG.info("_invoke_api (%s, %s, %s) = %s" %
                 (method_name, args, kwargs, res))
        return res

    def _invoke_vapp_api(self, the_vapp, method_name, *args, **kwargs):
        res = self._session.invoke_api(the_vapp, method_name, *args, **kwargs)
        LOG.info("_invoke_vapp_api (%s, %s, %s) = %s" %
                 (method_name, args, kwargs, res))
        return res

    def get_disk_ref(self, disk_name):
        disk_refs = self._invoke_api('get_diskRefs',
                                     self._get_vcloud_vdc())
        link = filter(lambda link: link.get_name() == disk_name, disk_refs)
        if len(link) == 1:
            return True, link[0]
        elif len(link) == 0:
            return False, 'disk not found'
        elif len(link) > 1:
            return False, 'more than one disks found with that name.'

    def get_vcloud_vapp_status(self, vapp_name):
        # return self._get_vcloud_vapp(vapp_name).me.status
        # add for status cache
        status = self.cache.query_status(vapp_name)
        if not status:
            LOG.debug("get vcloud vapp status from cache failed, status is None. vapp = %s" % vapp_name)

            try:
                vapp = self._get_vcloud_vapp(vapp_name)
            except Exception:
                vapp = None

            if not vapp:
                return power_state.NOSTATE
            vapp_status = vapp.me.status
            return status_dict_vapp_to_instance.get(vapp_status)
        else:
            return status

        # add end for status cache
 
    def power_off_vapp(self, vapp_name):
        @RetryDecorator(max_retry_count=10,
                        exceptions=exception.NovaException)
        def _power_off(vapp_name):
            expected_vapp_status = 8
            the_vapp = self._get_vcloud_vapp(vapp_name)
            vapp_status = self._get_status_first_vm(the_vapp)
            if vapp_status == expected_vapp_status:
                return the_vapp

            task_stop = self._invoke_vapp_api(the_vapp, "undeploy")
            if not task_stop:
                raise exception.NovaException(
                    "power off vapp failed, task")
            self._session.wait_for_task(task_stop)

            retry_times = 60
            while vapp_status != expected_vapp_status and retry_times > 0:
                time.sleep(3)
                the_vapp = self._get_vcloud_vapp(vapp_name)
                vapp_status = self._get_status_first_vm(the_vapp)
                LOG.debug('During power off vapp_name: %s, %s' % (vapp_name, vapp_status))
                retry_times -= 1
            return the_vapp

        return _power_off(vapp_name)

    def _get_status_first_vm(self, the_vapp):
        children = the_vapp.me.get_Children()
        if children:
            vms = children.get_Vm()
            for vm in vms:
                return vm.get_status()
        return None

    def power_on_vapp(self, vapp_name):
        @RetryDecorator(max_retry_count=10,
                        exceptions=exception.NovaException)
        def _power_on(vapp_name):
            the_vapp = self._get_vcloud_vapp(vapp_name)

            vapp_status = self._get_status_first_vm(the_vapp)
            expected_vapp_status = 4
            if vapp_status == expected_vapp_status:
                return the_vapp

            task = self._invoke_vapp_api(the_vapp, "poweron")
            if not task:
                raise exception.NovaException("power on vapp failed, task")
            self._session.wait_for_task(task)

            retry_times = 60
            while vapp_status != expected_vapp_status and retry_times > 0:
                time.sleep(3)
                the_vapp = self._get_vcloud_vapp(vapp_name)
                vapp_status = self._get_status_first_vm(the_vapp)
                LOG.debug('During power on vapp_name: %s, %s' %
                        (vapp_name, vapp_status))
                retry_times -= 1
            return the_vapp

        return _power_on(vapp_name)

    def delete_vapp(self, vapp_name):
        the_vapp = self._get_vcloud_vapp(vapp_name)
        task = self._invoke_vapp_api(the_vapp, "delete")
        if not task:
            raise exception.NovaException(
                "delete vapp failed, task: %s" % task)
        self._session.wait_for_task(task)

    def reboot_vapp(self, vapp_name):
        the_vapp = self._get_vcloud_vapp(vapp_name)
        task = self._invoke_vapp_api(the_vapp, "reboot")
        if not task:
            raise exception.NovaException(
                "reboot vapp failed, task: %s" % task)
        self._session.wait_for_task(task)

    def query_vmdk_url(self, vapp_name):
        # 0. shut down the app first
        try:
            the_vapp = self.power_off_vapp(vapp_name)
        except:
            LOG.error('power off failed')

        # 1.enable download.
        task = self._invoke_vapp_api(the_vapp, 'enableDownload')
        if not task:
            raise exception.NovaException(
                "enable vmdk file download failed, task:")
        self._session.wait_for_task(task)

        # 2.get vapp info and ovf descriptor
        the_vapp = self._get_vcloud_vapp(vapp_name)

        ovf = self._invoke_vapp_api(the_vapp, 'get_ovf_descriptor')

        # 3.get referenced file url
        referenced_file_url = self._invoke_vapp_api(the_vapp,
                                                    'get_referenced_file_url',
                                                    ovf)
        if not referenced_file_url:
            raise exception.NovaException(
                "get vmdk file url failed")
        return referenced_file_url

    def attach_disk_to_vm(self, vapp_name, disk_ref):
        @RetryDecorator(max_retry_count=16,
                        exceptions=exception.NovaException)
        def _attach_disk(vapp_name, disk_ref):
            the_vapp = self._get_vcloud_vapp(vapp_name)
            task = the_vapp.attach_disk_to_vm(disk_ref)
            if not task:
                raise exception.NovaException(
                    "Unable to attach disk to vm %s" % vapp_name)
            else:
                self._session.wait_for_task(task)
                return True

        return _attach_disk(vapp_name, disk_ref)

    def detach_disk_from_vm(self, vapp_name, disk_ref):
        @RetryDecorator(max_retry_count=16,
                        exceptions=exception.NovaException)
        def _detach_disk(vapp_name, disk_ref):
            the_vapp = self._get_vcloud_vapp(vapp_name)
            task = the_vapp.detach_disk_from_vm(disk_ref)
            if not task:
                raise exception.NovaException(
                    "Unable to detach disk from vm %s" % vapp_name)
            else:
                self._session.wait_for_task(task)
                return True

        return _detach_disk(vapp_name, disk_ref)
        
    def modify_vm_cpu(self, vapp_name, cpus):
        the_vapp = self._get_vcloud_vapp(vapp_name)
        task = the_vapp.modify_vm_cpu(vapp_name, cpus)
        if not task:
            raise exception.NovaException(
                "Unable to modify vm %s cpu" % vapp_name)
        else:
            self._session.wait_for_task(task)
            return True

    def insert_media(self, vapp_name, iso_file):
        the_vapp = self._get_vcloud_vapp(vapp_name)
        task = the_vapp.vm_media(iso_file, 'insert')
        if not task:
            raise exception.NovaException(
                "Unable to insert media vm %s" % vapp_name)
        else:
            self._session.wait_for_task(task)
            return True

    def upload_vm(self, ovf_name, vapp_name, api_net, tun_net):
        cmd = ('ovftool --net:"vmnetwork-0=%s"'
               ' --net:"vmnetwork-1=%s"'
               ' %s "vcloud://%s:%s@%s?org=%s&vdc=%s&vapp=%s"' %
               (api_net,
                tun_net,
                ovf_name,
                self.username,
                self.password,
                self.host_ip,
                self.org,
                self.vdc,
                vapp_name))
        LOG.debug("begin run create vapp command '%s'." % cmd)
        cmd_result = subprocess.call(cmd, shell=True)
        LOG.debug("end run create vapp command '%s'." % cmd)
        if cmd_result != 0:
            raise exception.NovaException(
                "Unable to upload vm %s" % vapp_name)

    def _upload_metadata_iso(self, iso_file, media_name, overwrite=False):
        overw = ''
        if overwrite:
            overw = '--overwrite'
        cmd = ('ovftool %s --sourceType="ISO" '
               ' --vCloudTemplate="false"'
               ' "%s" "vcloud://%s:%s@%s?org=%s&vdc=%s&media=%s'
               '&catalog=%s"' %
               (overw,
                iso_file,
                self.username,
                self.password,
                self.host_ip,
                self.org,
                self.vdc,
                media_name,
                self._metadata_iso_catalog))
        LOG.debug("begin run upload iso command '%s'." % cmd)
        cmd_result = subprocess.call(cmd, shell=True)
        LOG.debug("end run upload iso command '%s'." % cmd)
        return cmd_result
        
    def upload_metadata_iso(self, iso_file, vapp_name):
        media_name = "metadata_%s.iso" % vapp_name
        try:
            cmd_result = self._upload_metadata_iso(iso_file, media_name)
        except Exception as e:
            cmd_result = 1
            LOG.error('upload meta-data failed without overwrite %s.' % (e))
        if cmd_result != 0:
            cmd_result = self._upload_metadata_iso(iso_file, media_name, True)
        if cmd_result != 0:
            raise exception.NovaException(
                "Unable to upload meta-data iso file %s" % vapp_name)
        return self._invoke_api("get_media",
                                            self._metadata_iso_catalog,
                                            media_name)        
         

    def delete_metadata_iso(self, vapp_name):
        media_name = "metadata_%s.iso" % vapp_name
        # not work for pyvcloud10 but for pyvcloud14
        result = self._invoke_api("delete_catalog_item",
                                self._metadata_iso_catalog,
                                media_name)
        if not result:
            raise exception.NovaException(
                "delete metadata iso failed vapp_name:%s" % vapp_name)

    def get_network_configs(self, network_names):
        return self._session.invoke_api(self._session.vca, "get_network_configs", self._session._vdc, network_names)

    def get_network_connections(self, vapp, network_names):
        return self._session.invoke_api(vapp, "get_network_connections", network_names)

    def update_vms_connections(self, vapp, network_connections):
        result, task = self._session.invoke_api(vapp, "update_vms_connections", network_connections)

        # check the task is success or not
        if not result:
            raise exceptions.VCloudDriverException(
                "Update_vms_connections error, task:" +
                task)

        self._session.wait_for_task(task)

    def modify_vm_cpu(self, vapp, cpus):
        result, task = self._session.invoke_api(vapp, "modify_vm_cpu", cpus)

        # check the task is success or not
        if not result:
            raise exceptions.VCloudDriverException(
                "Modify_vm_cpu error, task:" +
                task)

        self._session.wait_for_task(task)

    def modify_vm_memory(self, vapp, new_size):
        result, task = self._session.invoke_api(vapp, "modify_vm_memory", new_size)

        # check the task is success or not
        if not result:
            raise exceptions.VCloudDriverException(
                "Modify_vm_memory error, task:" +
                task)

        self._session.wait_for_task(task)


    def create_vapp(self, vapp_name, template_name, network_configs, root_gb=None):
        result, task = self._session.invoke_api(self._session.vca,
                                                "create_vapp",
                                                self._session._vdc, vapp_name,
                                                template_name, network_configs=network_configs, root_gb=root_gb)

        # check the task is success or not
        if not result:
            raise exceptions.VCloudDriverException(
                "Create_vapp error, task:" +
                task)
        self._session.wait_for_task(task)
        the_vdc = self._session.invoke_api(self._session.vca, "get_vdc", self._session._vdc)

        return self._session.invoke_api(self._session.vca, "get_vapp", the_vdc, vapp_name)
