#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Name:     imager.py
# Purpose:  Module to write ISO image to selected USB disk. Uses dd as backend.
# Authors:  Sundar
# Licence:  This file is a part of multibootusb package. You can redistribute it or modify
# under the terms of GNU General Public License, v.2 or above
# WARNING : Any boot-able USB made using this module will destroy data stored on USB disk.

import collections
import io
import os
import platform
import signal
import time
import subprocess
import traceback

from PyQt5 import QtWidgets
from .gui.ui_multibootusb import Ui_MainWindow
from .gen import *
from . import config
from . import iso
from . import osdriver
from . import progressbar
from . import osdriver
from . import udisks
from . import usb


if platform.system() == "Windows":
    import win32com.client

def dd_iso_image(dd_progress_thread):
    try:
        _dd_iso_image(dd_progress_thread)
    except:
        o = io.StringIO()
        traceback.print_exc(None, o)
        log(o.getvalue())
        dd_progress_thread.set_error(o.getvalue())

def _dd_iso_image(dd_progress_thread):
    pbar = progressbar.ProgressBar(
            maxval=100,
            widgets=[
                ' ',
                progressbar.widgets.Bar(marker='=', left='[', right=']'),
                ' ',
                progressbar.widgets.Percentage()
            ]
    ).start()


    while dd_process.poll() is None:
        time.sleep(0.1)  # If this time delay is not given, the Popen does not execute the actual command
        dd_process.send_signal(signal.SIGUSR1)
        dd_process.stderr.flush()
        while True:
            time.sleep(0.1)
            out_error = dd_process.stderr.readline().decode()
            if out_error:
                if 'bytes' in out_error:
                    copied = int(out_error.split(' ', 1)[0])
                    config.imager_percentage = round((float(copied) / float(in_file_size) * 100))
                    pbar.update(config.imager_percentage)
                    break

    if dd_process.poll() is not None:
        log("\nExecuting ==> sync")
        os.sync()
        log("ISO has been written to USB disk...")
        return


def dd_win_clean_usb(usb_disk_no):
  """

  """
  host_dir = multibootusb_host_dir()
  temp_file = os.path.join(host_dir, "preference", "disk_part.txt")
  diskpart_text_feed = 'select disk ' + str(usb_disk_no) + '\nclean\nexit'
  write_to_file(temp_file, diskpart_text_feed)
  config.status_text = 'Cleaning the disk...'
  if subprocess.call('diskpart.exe -s ' + temp_file ) == 0:
    return True
  else:
    return False


def dd_win():

    windd = quote(resource_path(os.path.join("data", "tools", "dd", "dd.exe")))
    usb_disk_no = osdriver.get_physical_disk_number(config.usb_disk)
    _input = "if=" + config.image_path.strip()
    in_file_size = float(os.path.getsize(config.image_path) / 1024 / 1024)
    _output = "of=\\\.\\PhysicalDrive" + str(usb_disk_no)
    if dd_win_clean_usb(usb_disk_no) is False:
        return
    # of=\\.\PhysicalDrive1
    # _output = "od=" + config.usb_disk # 'od=' option should also work.
    # command = [windd, _input, _output, "bs=1M", "--progress"]
    command = windd + ' ' + _input + ' ' + _output + " bs=1M" + " --progress"
    #log("Executing ==> " + " ".join(command))
    log("Executing ==> " + command)
    dd_process = subprocess.Popen(command, universal_newlines=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                  shell=False)
    time.sleep(0.1)
    while dd_process.poll() is None:
        for line in iter(dd_process.stderr.readline, ''):
            line = line.strip()
            if 'error' in line.lower() or 'invalid' in line.lower():
                config.imager_return = False
                break
            if line and line[-1] == 'M':
                copied = float(line.strip('M').replace(',', ''))
                config.imager_percentage = round((copied / float(in_file_size) * 100))

        if config.imager_return is False:
          log("Error writing to disk...")
        else:
          log("ISO has been written to USB disk...")

        return

    def gui_update(percentage):
        config.imager_percentage = percentage
        pbar.update(percentage)

    unmounted_contexts = [
        (usb.UnmountedContext(p[0], config.update_usb_mount), p[0]) for p
        in udisks.find_partitions_on(config.usb_disk)]
    really_unmounted = []
    try:
        for c, pname in unmounted_contexts:
                c.__enter__()
                really_unmounted.append((c, pname))
        error = osdriver.dd_iso_image(
            config.image_path, config.usb_disk, gui_update)
        if error:
            dd_progress_thread.set_error(error)
    finally:
        for c, pname in really_unmounted:
                c.__exit__(None, None, None)



class Imager(QtWidgets.QMainWindow, Ui_MainWindow):
    """
    Raw write to USB disk using dd.
    """

    def __init__(self):
        QtWidgets.QMainWindow.__init__(self)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)


    def add_iso_gui_label_text(self):
        """
        Simple function to add text label to GUI widgets.
        :return:
        """
        log("Testing ISO...")
        self.ui.imager_bootable.setVisible(True)
        if iso.is_bootable(config.image_path) is True:
            self.ui.imager_bootable.setText("Bootable ISO: Yes")
            log("ISO is bootable.")
        else:
            self.ui.imager_bootable.setText("Bootable ISO: No")
            log("ISO is not bootable.")

        if os.path.exists(config.image_path):
            log("Path " + config.image_path + " exists...")
            self.iso_size = str(round(os.path.getsize(config.image_path) / 1024 / 1024))
            self.ui.imager_iso_size.setVisible(True)
            self.ui.imager_iso_size.setText("ISO Size: " + self.iso_size + " MB")
            log("ISO Size is " + self.iso_size + " MB")

    @staticmethod
    def imager_list_usb(partition=1):
        """
        Function to detect whole USB disk. It uses lsblk package on Linux.
        :param partition: What to return. By default partition is set.
        :return: USB disk/partition as list
        """
        disk = []
        if platform.system() == "Linux":
            output = subprocess.check_output("lsblk -i", shell=True)
            if partition != 1:
                for line in output.splitlines():
                    line = line.split()
                    if (line[2].strip()) == b'1' and (line[5].strip()) == b'disk':
                        disk.append(str("/dev/" + str(line[0].strip().decode())))
            elif partition == 1:
                for line in output.splitlines():
                    line = line.split()
                    if (line[2].strip()) == b'1' and line[5].strip() == b'part':
                        disk.append(str("/dev/" + str(line[0].strip()[2:])))
        else:
            oFS = win32com.client.Dispatch("Scripting.FileSystemObject")
            oDrives = oFS.Drives
            for drive in oDrives:
                if drive.DriveType == 1 and drive.IsReady:
                    disk.append(drive)
        return disk

    @staticmethod
    def imager_usb_detail(usb_disk, partition=1):
        """
        Function to detect details of USB disk using lsblk
        :param usb_disk: path to usb disk
        :param partition: by default partition is set (but yet to code for it)
        :return: details of size, type and model as tuples
        """
        _ntuple_diskusage = collections.namedtuple('usage', 'total_size usb_type model')

        if platform.system() == "Linux":
            output = subprocess.check_output("lsblk -ib " + usb_disk, shell=True)
            for line in output.splitlines():
                line = line.split()
                if partition != 1:
                    if line[2].strip() == b'1' and line[5].strip() == b'disk':
                        total_size = line[3]
                        if not total_size:
                            total_size = "Unknown"
                        usb_type = "Removable"
                        model = subprocess.check_output("lsblk -in -f -o MODEL " + usb_disk, shell=True).decode().strip()
                        if not model:
                            model = "Unknown"
        else:
            try:
                selected_usb_part = str(usb_disk)
                oFS = win32com.client.Dispatch("Scripting.FileSystemObject")
                d = oFS.GetDrive(oFS.GetDriveName(oFS.GetAbsolutePathName(selected_usb_part)))
#                 selected_usb_device = d.DriveLetter
                label = (d.VolumeName).strip()
                if not label.strip():
                    label = "No label."
                total_size = d.TotalSize
                usb_type = "Removable"
                model = label
            except:
                log("Error detecting USB details.")

        return _ntuple_diskusage(total_size, usb_type, model)

    def get_usb_size(self, usb_disk):
        """
        Function to detect USB disk space. Useful but not used in multibootusb as of now.
        :param usb_disk: USB disk like "/dev/sdb"
        :return: Size of the disk as integer
        """
        if platform.system() == "Linux":
            cat_output = subprocess.check_output("cat /proc/partitions | grep  " + usb_disk[5:], shell=True)
            usb_size = int(cat_output.split()[2]) * 1024
            # log(usb_size)
            return usb_size
        else:
            usb_size = self.usb.disk_usage(self.usb.get_usb(usb_disk).mount).total
            return usb_size
