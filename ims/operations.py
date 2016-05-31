#!/usr/bin/python
import subprocess

from ceph_wrapper import *
from config import BMIConfig
from database import *
from haas_wrapper import *


# logging will be submitted later

class BMI:
    def __init__(self, usr, passwd):
        self.config = create_config()
        self.haas = HaaS(base_url=self.config.haas_url, usr=usr, passwd=passwd)

    # Provisions from HaaS and Boots the given node with given image
    def provision(self, node_name, img_name="hadoopMaster.img",
                  snap_name="HadoopMasterGoldenImage",
                  network="bmi-provision"):
        try:
            self.haas.attach_node_to_project_network(node_name, network)

            with RBD(self.config.fs[constants.CEPH_CONFIG_SECTION_NAME]) as fs:
                fs.clone(img_name.encode('utf-8'), snap_name.encode('utf-8'),
                         node_name.encode("utf-8"))

                ceph_config = self.config.fs[constants.CEPH_CONFIG_SECTION_NAME]
                # Should be changed to python script
                iscsi_output = call_shellscript(self.config.iscsi_update,
                                                ceph_config[
                                                    constants.CEPH_KEY_RING_KEY],
                                                ceph_config[
                                                    constants.CEPH_ID_KEY],
                                                ceph_config[
                                                    constants.CEPH_POOL_KEY],
                                                node_name,
                                                constants.ISCSI_CREATE_COMMAND)
                if constants.ISCSI_UPDATE_SUCCESS in iscsi_output[0]:
                    return return_success(True)
                elif constants.ISCSI_UPDATE_FAILURE in iscsi_output[0]:
                    # Was not able to test this exception in test cases as the haas
                    # call was blocking this exception
                    # But it was raised during preparation of tests
                    # Rare exception
                    raise iscsi_exceptions.NodeAlreadyInUseException()

        except (HaaSException, ISCSIException, FileSystemException) as e:
            return return_error(e)

    # This is for detach a node and removing it from iscsi
    # and destroying its image
    def detach_node(self, node_name, network="bmi-provision"):
        try:

            self.haas.detach_node_from_project_network(node_name,
                                                       network)

            with RBD(self.config.fs[constants.CEPH_CONFIG_SECTION_NAME]) as fs:
                ceph_config = self.config.fs[constants.CEPH_CONFIG_SECTION_NAME]

                iscsi_output = call_shellscript(self.config.iscsi_update,
                                                ceph_config[
                                                    constants.CEPH_KEY_RING_KEY],
                                                ceph_config[
                                                    constants.CEPH_ID_KEY],
                                                ceph_config[
                                                    constants.CEPH_POOL_KEY],
                                                node_name,
                                                constants.ISCSI_DELETE_COMMAND)
                if constants.ISCSI_UPDATE_SUCCESS in iscsi_output[0]:
                    return return_success(fs.remove(node_name.encode("utf-8")))
                elif constants.ISCSI_UPDATE_FAILURE in iscsi_output[0]:
                    raise iscsi_exceptions.NodeAlreadyUnmappedException()
        except (HaaSException, ISCSIException, FileSystemException) as e:
            return return_error(e)

    # Creates snapshot for the given image with snap_name as given name
    # fs_obj will be populated by decorator
    def create_snapshot(self, project, img_name, snap_name):
        try:
            self.haas.validate_project(project)
            self.__does_project_exist(project)
            img_id = self.__get_image_id(project, img_name)

            with RBD(self.config.fs[constants.CEPH_CONFIG_SECTION_NAME]) as fs:
                return return_success(fs.snap_image(img_id,str(snap_name)))

        except (HaaSException, DBException, FileSystemException) as e:
            return return_error(e)

    # Lists snapshot for the given image img_name
    # URL's have to be read from BMI config file
    # fs_obj will be populated by decorator
    def list_snaps(self, project, img_name):
        try:
            self.haas.validate_project(project)
            self.__does_project_exist(project)
            img_id = self.__get_image_id(project, img_name)

            with RBD(self.config.fs[constants.CEPH_CONFIG_SECTION_NAME]) as fs:
                return return_success(fs.list_snapshots(img_id))

        except (HaaSException, DBException, FileSystemException) as e:
            return return_error(e)

    # Removes snapshot snap_name for the given image img_name
    # fs_obj will be populated by decorator
    def remove_snaps(self, project, img_name, snap_name):
        try:
            self.haas.validate_project(project)
            self.__does_project_exist(project)
            img_id = self.__get_image_id(project, img_name)

            with RBD(self.config.fs[constants.CEPH_CONFIG_SECTION_NAME]) as fs:
                return return_success(fs.remove_snapshots(img_id, str(snap_name)))

        except (HaaSException, DBException, FileSystemException) as e:
            return return_error(e)

    # Lists the images for the project which includes the snapshot
    def list_all_images(self, project):
        try:
            self.haas.validate_project(project)
            self.__does_project_exist(project)
            imgr = ImageRepository()
            return return_success(imgr.fetch_names_from_project(project))
        except (HaaSException, DBException) as e:
            return return_error(e)

    def __does_project_exist(self, name):
        pr = ProjectRepository()
        pid = pr.fetch_id_with_name(name)
        # None as a query result implies that the project does not exist.
        if pid is None:
            raise db_exceptions.ProjectNotFoundException(name)

    def __get_image_id(self, project, name):
        imgr = ImageRepository()
        img_id = imgr.fetch_id_with_name_from_project(name, project)
        if img_id is None:
            raise db_exceptions.ImageNotFoundException(name)
        return str(img_id)


# Calling shell script which executes a iscsi update as we don't have
# rbd map in documentation.
def call_shellscript(*args):
    arglist = list(args)
    proc = subprocess.Popen(arglist, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    return proc.communicate()


# Creates a filesystem configuration object
def create_config():
    try:
        config = BMIConfig()
        config.parse_config()
        return config
    except ConfigException:  # Should be logged
        raise  # Crashing it for now


# A custom function which is wrapper around only success code that
# we are creating.
def return_success(obj):
    return {constants.STATUS_CODE_KEY: 200, constants.RETURN_VALUE_KEY: obj}


# Parses the Exception and returns the dict that should be returned to user
def return_error(ex):
    ex_parser = ExceptionParser()
    if FileSystemException in ex.__class__.__bases__:
        return {constants.STATUS_CODE_KEY: ex_parser.parse(ex),
                constants.MESSAGE_KEY: swap_id_with_name(str(ex))}
    return {constants.STATUS_CODE_KEY: ex_parser.parse(ex),
            constants.MESSAGE_KEY: str(ex)}


# Replaces the image name with id in error string
def swap_id_with_name(err_str):
    parts = err_str.split(" ")
    imgr = ImageRepository()
    name = imgr.fetch_name_with_id(parts[0].strip())
    if name is not None:
        parts[0] = name
    return " ".join(parts)


if __name__ == "__main__":
    # print check_auth('http://127.0.0.1:6500/', "haasadmin", "admin1234", 'bmipenultimate')
    # print list_all_images('http://127.0.0.1:6500/', "haasadmin", "admin1234", 'test')
    # print list_all_images('http://127.0.0.1:6500/', "haasadmin", "admin1234", 'bmipenultimate')
    # print provision("http://127.0.0.1:6500/", "haasadmin", "admin1234",
    #                 "super-37")
    # print detach_node("http://127.0.0.1:6500/", "haasadmin", "admin1234", "super-37")
    # print list_snaps('http://127.0.0.1:6500/', "haasadmin", "admin1234", 'bmi_penultimate', 'testimage')
    # print create_snapshot('http://127.0.0.1:6500/', "haasadmin", "admin1234", 'bmi_penultimate','testimage', 'blblb1')
    # print remove_snaps('http://127.0.0.1:6500/', "haasadmin", "admin1234", 'bmi_penultimate', 'testimage', 'blblb1')

    bmi = BMI('haasadmin',"admin123##")
    met = getattr(BMI,'create_snapshot')
    met(bmi,'test','test','test')

    '''
    print list_free_nodes('http://127.0.0.1:6500/', "haasadmin", "admin1234",  debug = True)['retval']
    time.sleep(5)

    print attach_node_haas_project('http://127.0.0.1:6500/', "bmi_penultimate", 'sun-12',\
            usr = "haasadmin", passwd = "admin1234", debug = True)
    print "above is attach node to a proj"

    print query_project_nodes('http://127.0.0.1:6500/',  "bmi_penultimate", "haasadmin", "admin1234")
    time.sleep(5)

    print attach_node_to_project_network('http://127.0.0.1:7000/', 'cisco-27',\
            "enp130s0f0", "bmi-provision","test", "test",  debug = True)
    time.sleep(5)
    print "above is attach network"

    print detach_node_from_project_network('http://127.0.0.1:7000/','cisco-27',\
            'bmi-provision', "test", "test", "enp130s0f0", debug = True)
    time.sleep(5)


    print "above is detach from net"
    print detach_node_from_project('http://127.0.0.1:6500/',\
              "bmi_penultimate", 'sun-12',  usr = "haasadmin", passwd = "admin1234",  debug = True)
    time.sleep(5)
    print "above is detach from the proj"
    print query_project_nodes('http://127.0.0.1:6500/', "bmi_penultimate", "haasadmin", "admin1234")
    time.sleep(5)
    try:
        raise ShellScriptException("lljl")
    except Exception as e:
        print ResponseException(e).parse_curr_err()
    '''
