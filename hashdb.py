
########################################################################################
##
## This plugin is the client for the HashDB lookup service operated by OALABS:
##
## https://hashdb.openanalysis.net/
##
##   _   _           _    ____________ 
##  | | | |         | |   |  _  \ ___ \ 
##  | |_| | __ _ ___| |__ | | | | |_/ /
##  |  _  |/ _` / __| '_ \| | | | ___ \ 
##  | | | | (_| \__ \ | | | |/ /| |_/ /
##  \_| |_/\__,_|___/_| |_|___/ \____/ 
##
## HashDB is a community-sourced library of hashing algorithms used in malware.
## New hash algorithms can be added here: https://github.com/OALabs/hashdb
##
## Updated for IDA 7.xx and Python 3
##
## To install:
##      Copy script into plugins directory, i.e: C:\Program Files\<ida version>\plugins
##
## To run:
##      Configure Settings:
##          Edit->Plugins->HashDB
##          click `Refresh Algorithms` to pull a list of hash algorithms
##          select the hash algorithm you need from the drop-down
##          OK
##      Lookup Hash:
##          Highlight constant in IDA disassembly or psuedocode view
##          Right-click -> HashDB Lookup
##          If a hash is found it will be added to an enum controlled in the settings
##          Right-click on the constant again -> Enum -> Select new hash enum
##
########################################################################################

import sys

import idaapi
import idc
import ida_kernwin
import ida_enum
import ida_bytes
import ida_netnode
import requests
import functools
import string
import traceback
from typing import Union

# These imports are specific to the Worker implementation
import ctypes
import logging
import asyncio
import threading
from enum import Enum
from threading import Thread
from collections.abc import Iterable
from typing import Awaitable, Callable
from asyncio.events import AbstractEventLoop
from asyncio.exceptions import CancelledError, TimeoutError


__AUTHOR__ = '@herrcore'

PLUGIN_NAME = "HashDB"
PLUGIN_HOTKEY = 'Alt+`'
VERSION = '1.7.1'

#--------------------------------------------------------------------------
# IDA Python version madness
#--------------------------------------------------------------------------

major, minor = map(int, idaapi.get_kernel_version().split("."))
assert (major > 6),"ERROR: HashDB plugin requires IDA v7+"
assert (sys.version_info >= (3, 6)), "ERROR: HashDB plugin requires Python 3.6"


#--------------------------------------------------------------------------
# Global settings/variables
#--------------------------------------------------------------------------

HASHDB_API_URL ="https://hashdb.openanalysis.net"
HASHDB_USE_XOR = False
HASHDB_XOR_VALUE = 0
HASHDB_ALGORITHM = None
HASHDB_ALGORITHM_SIZE = 0
ENUM_PREFIX = "hashdb_strings"
NETNODE_NAME = "$hashdb"

# Variables for async operations
HASHDB_REQUEST_TIMEOUT = 15 # Limit to 15 seconds
HASHDB_REQUEST_LOCK = threading.Lock()

#--------------------------------------------------------------------------
# Setup Icon
#--------------------------------------------------------------------------

HASH_ICON_DATA = b"".join([b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08',
                          b'\x04\x00\x00\x00\xb5\xfa7\xea\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfca',
                          b'\x05\x00\x00\x00 cHRM\x00\x00z&\x00\x00\x80\x84\x00\x00\xfa\x00\x00\x00\x80',
                          b'\xe8\x00\x00u0\x00\x00\xea`\x00\x00:\x98\x00\x00\x17p\x9c\xbaQ<\x00\x00\x00',
                          b'\x02bKGD\x00\xff\x87\x8f\xcc\xbf\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00',
                          b'\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x07tIME\x07\xe5\t\x18\x12\x18(\xba',
                          b'\xecz-\x00\x00\x01#IDAT(\xcfm\xd1\xbdJ\x9ba\x18\xc6\xf1_\xde<\xd5d\x08\xc1',
                          b'\xb46\x967!\x1d,\x88\xd0\xa1P\xe8\x01\x14\x0c\xb8\xbbt\xa9\xa3\x07\xd0\xb9',
                          b'\xab \x1e\x83s\x87R\xa4]K\xe8".*NEpJZL\x9b\xa2V\x90\xc6\xa4\xc6\xc7%\x92\xa0',
                          b'\xfe\xd7\xeb\xe6\xe6\xfa`\x9c\x8c\x82\x04\xe4\xe4\xdd\xc3\xb4\x0fV\x95\xf0',
                          b'\xd6\x17\x0bw\x0f\xeaz\xf6<\xf4\xc0\xa6h\x05\xc3\x877,\x98\xf0\xd5\xb1g^i\xfb',
                          b'\x06\x01AY\x10\x15\xbdv\xe9\xbb\x19\x8bf4\x0c\xa4~g\x90\xfa\xa8\xeaJ\xd6c\x89',
                          b'\x8e\xbe\xa2\xa2s\x7f\xb5\xbcI\xc6\x12\x94\x04\'\xfa\xf2\x8azNen\xa4\xac\'*^8',
                          b'\xd0\xb5\xa4\xec\xbd\xe8\xb3\xa7\xaaR!\x08\xca\x12\x03\xb3j\x9a\x0e\xe5\xbc',
                          b'\xc4\x8e\xbe\xa8c@\xcd\x96\x9f\x9a\xfe\x88\xbaZZ.D\x1d?lKG1\'\x94\\:\x11M\x99t',
                          b'\xa6;r\x10\xa4*\x96\xfd\xb7\xef\xb9Y\r\xd1;\xa9\x9aT\x18U\xb4&Z\xc7\x9c#m\xf3',
                          b'\xb7+~dOO\x1d+\xa2M\x93#);\xdc\xae\xec\x97\r\xff\x94L\xf9d\xf7\xeeL\x89\xc2',
                          b'\xd0V^n\\\xb8\x06\xd6\xa1L\xe6_H\xbf\xfc\x00\x00\x00%tEXtdate:create\x00202',
                          b'1-09-24T18:24:40+00:00\xd7;f\xf5\x00\x00\x00%tEXtdate:modify\x002021-09-24T',
                          b'18:24:40+00:00\xa6f\xdeI\x00\x00\x00WzTXtRaw profile type iptc\x00\x00x\x9c',
                          b'\xe3\xf2\x0c\x08qV((\xcaO\xcb\xccI\xe5R\x00\x03#\x0b.c\x0b\x13#\x13K\x93\x14',
                          b'\x03\x13 D\x804\xc3d\x03#\xb3T \xcb\xd8\xd4\xc8\xc4\xcc\xc4\x1c\xc4\x07\xcb',
                          b'\x80H\xa0J.\x00\xea\x17\x11t\xf2B5\x95\x00\x00\x00\x00IEND\xaeB`\x82'])
HASH_ICON = ida_kernwin.load_custom_icon(data=HASH_ICON_DATA, format="png")
XOR_ICON_DATA = b"".join([b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x04',
                         b'\x00\x00\x00\xb5\xfa7\xea\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfca\x05\x00',
                         b'\x00\x00 cHRM\x00\x00z&\x00\x00\x80\x84\x00\x00\xfa\x00\x00\x00\x80\xe8\x00\x00',
                         b'u0\x00\x00\xea`\x00\x00:\x98\x00\x00\x17p\x9c\xbaQ<\x00\x00\x00\x02bKGD\x00\xff',
                         b'\x87\x8f\xcc\xbf\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a',
                         b'\x9c\x18\x00\x00\x00\x07tIME\x07\xe5\t\x18\x12\x0b";\xd6\xd2\xa1\x00\x00\x00\xc3',
                         b'IDAT(\xcf\xa5\xd01N\x02\x01\x14\x04\xd0\x07B01\x9a\x10b\x89%\t\x8dg\xa0\xd0f-\xb8',
                         b'\x80x\x86\x8d\r\xd9#X\xee\x05(\x94\x0b\xd0\xd0@A\xcb\t4\xdb\x98\xd8Z\x90\xacv\x82',
                         b'Z,\xac\xab1P0\xdd\xfc\xcc\x9f\xcc\x0c\xfb\xa2\xf4\x8bU\x9c \xb5\xfcOPu\xe9F\x0b',
                         b'\x89{\x13\x1f\xd9\xf9 \xff\xbd\x15\x99;\xf2.\x11\xaa\x99\xfb,\x9a_y\x12 \x16#X3',
                         b'\x94\xd7>\xd7F\xc6\xb9|l\xa4\x97\xb9g\x19\xea\xa6^=*\xe9`\xe6K\xdb\xa9\x0b\x8b',
                         b'\x8d\xc3\x16T@*\xf1\xa2\x8f\x18!\xee\x9cI\x7f2\xac\x0cu7\xb1\x10\xe8z\xb0*\xd6',
                         b'|v(\xd2\xd4\xd6p.40\xccj\xee\x1c\xea\xef\xd4\xc7x+N\xbd?\xbe\x01\xa7\xee.6\xd9',
                         b'\xf6\xa5\xd2\x00\x00\x00%tEXtdate:create\x002021-09-24T18:11:34+00:00Vz\xe6\xba',
                         b'\x00\x00\x00%tEXtdate:modify\x002021-09-24T18:11:34+00:00\'\'^\x06\x00\x00\x00',
                         b'WzTXtRaw profile type iptc\x00\x00x\x9c\xe3\xf2\x0c\x08qV((\xcaO\xcb\xccI\xe5R',
                         b'\x00\x03#\x0b.c\x0b\x13#\x13K\x93\x14\x03\x13 D\x804\xc3d\x03#\xb3T \xcb\xd8\xd4',
                         b'\xc8\xc4\xcc\xc4\x1c\xc4\x07\xcb\x80H\xa0J.\x00\xea\x17\x11t\xf2B5\x95\x00\x00',
                         b'\x00\x00IEND\xaeB`\x82'])
XOR_ICON = ida_kernwin.load_custom_icon(data=XOR_ICON_DATA, format="png")
HUNT_ICON_DATA = b"".join([b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x04',
                          b'\x00\x00\x00\xb5\xfa7\xea\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfca\x05\x00',
                          b'\x00\x00 cHRM\x00\x00z&\x00\x00\x80\x84\x00\x00\xfa\x00\x00\x00\x80\xe8\x00\x00u0',
                          b'\x00\x00\xea`\x00\x00:\x98\x00\x00\x17p\x9c\xbaQ<\x00\x00\x00\x02bKGD\x00\xff\x87',
                          b'\x8f\xcc\xbf\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18',
                          b'\x00\x00\x00\x07tIME\x07\xe5\t\x1d\x10#"R\xd1XW\x00\x00\x01.IDAT(\xcf\x8d\xd1;K\x9b',
                          b'\x01\x18\xc5\xf1\x9fI\xa8C\xbd\xf1\x0e\xdd\xd2\xc5NJ\x07;h\xd5\xa1\xf1\x0bT\xd4M',
                          b'\x14//\x82\xad\x8b\x83\x93`\xf1\x02~\x84\x08-b\x1c\xea\xe6\xe2 \x08^\x9aAQ\x07\x87',
                          b'R\x9d:\x99Atx\x15\xab`\xbc\xd0\x0eitS\xcf\xf2\xc0\xe1\xf0\x1c\xf8\x9f\x12\x0f*Q!@',
                          b'\xe4\xdc\xdf\x07\xb3xkuz\xe7\x05\xae\xedY\xb0_\x08\x15\x02\t=\x06l\xdap\x89\x97Z4',
                          b'\xfbf\xde-\t\xd0#4\xa1J\xef\xff\x8aE\xab\xc60[\xf8\xf0\xd6W\x93\xde\xfb`\xce!^\xeb',
                          b'\x93\xb5\xed\x8b\x01\xbf\xe2\x18v\xe4T\xbbQ\xcd\xba\xa4\\I\xebw\xe0N\x8d\xb5\x98Ju~h',
                          b'\x93\xd1\xaa\xda\xb8q\xd5>\xcah\x93U\xa72&P\xeaB \xa7\xde\x8cA\x83f4\xc8\t\xfcQ*\x88yB',
                          b'\t\x91\xbc2\x91\xa4]\x9f\xa4\xf1\xd9\x8e\xa4H\xb9\xbc(.\xaf\xd6\x1b\xebBi\xaftK\xf9i',
                          b'\xc9\x88\xef\x1a\xe5,\xc7ql\xc8\x8a;\xa1UK\xb2n\x8c\xc8\xfa\xad\xcb\xb4\x93\x02\xc9PhJ',
                          b'\x95\x8e{Pg\xc6\xcc\x16A\x15Qo\xd9p\x812-\x9a\x8a\xa8\x9f9\xd6#s\xff\x03\xabm^\xab\xaf',
                          b'\xe8z\xc0\x00\x00\x00%tEXtdate:create\x002021-09-29T16:35:34+00:00\xf4Q\xb1\xe8\x00\x00',
                          b'\x00%tEXtdate:modify\x002021-09-29T16:35:34+00:00\x85\x0c\tT\x00\x00\x00WzTXtRaw prof',
                          b'ile type iptc\x00\x00x\x9c\xe3\xf2\x0c\x08qV((\xcaO\xcb\xccI\xe5R\x00\x03#\x0b.c\x0b',
                          b'\x13#\x13K\x93\x14\x03\x13 D\x804\xc3d\x03#\xb3T \xcb\xd8\xd4\xc8\xc4\xcc\xc4\x1c',
                          b'\xc4\x07\xcb\x80H\xa0J.\x00\xea\x17\x11t\xf2B5\x95\x00\x00\x00\x00IEND\xaeB`\x82'])
HUNT_ICON = ida_kernwin.load_custom_icon(data=HUNT_ICON_DATA, format="png")
SCAN_ICON_DATA = b"".join([b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x04\x00\x00',
                          b'\x00\xb5\xfa7\xea\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfca\x05\x00\x00\x00 cHRM',
                          b'\x00\x00z&\x00\x00\x80\x84\x00\x00\xfa\x00\x00\x00\x80\xe8\x00\x00u0\x00\x00\xea`\x00',
                          b'\x00:\x98\x00\x00\x17p\x9c\xbaQ<\x00\x00\x00\x02bKGD\x00\xff\x87\x8f\xcc\xbf\x00\x00',
                          b'\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x07tIME\x07',
                          b'\xe5\n\x08\x17\x1c\x04\xfd*<n\x00\x00\x01#IDAT(\xcfe\xd1\xb1K\xe2\x01\x18\xc6\xf1\x8f',
                          b'\xf6\xcb\xeb\xd0\x04\xc7 \xa8Ii\x89\xa2\xed~\x16\xc4m\xd6\xbf\xd0\x18\xed\xd1m\x07F-ECK',
                          b'\xa0K\xc49_\rACk\x10\xdc\x12\x04\x91qR\xd2\xd0PS\xd7\xa0h\x905\xe8\x85\xd9\xf7\x1d\xdfgx',
                          b'\xdf\xe7K\x9b@\xa8\xa8\xa2aO\x9f.\x02\x90\xb2l\xc9\x80\xb2s\'ZzH)i\xda\x17\x8a\x8b\x89',
                          b'\xf6\xae\xa3\xd65m\x88\xcbXud\xa57\x12z\xf0[\xc2\xbc\xaa\xbaK?{\x03EO\xa6e\\\xbb\x94',
                          b'\x93\xfcx"\xfc\xf5GB^MN\xca\x8a\x1f\x86\x0c\xf8\xda\x99\xfe\xc0\xb0s\xcf\xa6T\x9dZ\xb4',
                          b'\xe5\xc5\x82G-\x11Q-\xd5\xc0g^}1\xe9\x9f\x8aq\x13\x81;#b\xce|\x97\xb5\x8bW\xbf\xcc*)',
                          b'\xd8q,A\xe1\xfd\xc8\xb2\x9c\xa4\xa49W\xae\xa5\xcdxR t\xdfy\xf3F\xdd\x85\x0bu7\xe6\r:p/',
                          b'\xec.*-\xef\xd0\xa1\xbc\xb4\x84MMk\xedN\xfeW\x9d\x15\x17\x13\x13\x97u\xa0\xa9$E\xe4\x83',
                          b'\xac+\xb7\x185\xa6\xa1h\xdbc\xb7\xd5\xb6\xee\x9a\x9a\x8a\xa2o\x1d\xcf\xde\x00\x9fhY\xc0',
                          b'\x9b\x9d\xab^\x00\x00\x00%tEXtdate:create\x002021-10-08T23:28:04+00:00\xee\x90\xd3~\x00',
                          b'\x00\x00%tEXtdate:modify\x002021-10-08T23:28:04+00:00\x9f\xcdk\xc2\x00\x00\x00WzTXtRaw ',
                          b'profile type iptc\x00\x00x\x9c\xe3\xf2\x0c\x08qV((\xcaO\xcb\xccI\xe5R\x00\x03#\x0b.c\x0b',
                          b'\x13#\x13K\x93\x14\x03\x13 D\x804\xc3d\x03#\xb3T \xcb\xd8\xd4\xc8\xc4\xcc\xc4\x1c\xc4\x07',
                          b'\xcb\x80H\xa0J.\x00\xea\x17\x11t\xf2B5\x95\x00\x00\x00\x00IEND\xaeB`\x82'])
SCAN_ICON = ida_kernwin.load_custom_icon(data=SCAN_ICON_DATA, format="png")



#--------------------------------------------------------------------------
# Error class
#--------------------------------------------------------------------------
class HashDBError(Exception):
    pass


#--------------------------------------------------------------------------
# Worker implementation
#--------------------------------------------------------------------------
class Signal(Enum):
    """
    The `Signal` class is an `Enum`,
    which contains all the possible constants
    used when communicating between threads.
    """
    NONE = 0
    STOP = 1


class Worker(Thread):
    """
    The `Worker` class represents a custom `Thread` object.

    A `Worker` can have a timeout, where the execution will end abruptly, if its exceeded.
    """
    # Private variables:
    __timeout = None
    __done_callback = None
    __error_callback = None
    __target = None
    __loop = None
    __coroutine_target = None

    def __wrapper(self, *args, **kwargs):
        """
        The `__wrapper` method serves as an exception handling wrapper for functions.
         When a `Worker` is sent a `Signal` it handles it.

        If a done callback is provided it will be invoked when the target routine is finished.

        If an unexpected exception is thrown from the target/callback, it's raised.
        """
        # Run
        try:
            result = self.__target(*args, **kwargs)
            # Support for multiple return values
            if not isinstance(result, Iterable):
                result = [result]
            # If we have a done callback, invoke it
            if self.__done_callback is not None:
                self.__done_callback(*result)
        except SystemExit as exception:
            logging.debug("Caught an expected exception: {}".format(type(exception).__name__))
            # Execute the error callback
            if self.__error_callback is not None:
                self.__error_callback(exception)
        except Exception as exception:
            logging.exception("Caught an unexpected exception: {}, raising.".format(type(exception).__name__))
            raise exception
        finally:
            # Decrement the reference count, no longer required
            if self.__done_callback is not None:
                del self.__done_callback
            if self.__error_callback is not None:
                del self.__error_callback
            del self.__target

    def __async_wrapper(self, *args, **kwargs):
        """
        The `__async_wrapper` method serves as an exception handling wrapper for coroutines.
         When a `Worker` is sent a `Signal` it handles it.

        If a done callback is provided it will be invoked when the target routine is finished.

        If an unexpected exception is thrown from the target/callback, it's raised.
        """
        # Setup the loop
        loop = asyncio.new_event_loop()
        self.__loop = loop
        asyncio.set_event_loop(loop)

        # Wait until the callback is finished
        try:
            coroutine = None
            # Do we have a defined timeout?
            if self.__timeout:
                coroutine = asyncio.wait_for(self.__coroutine_target(*args, **kwargs), self.__timeout)
            else:
                coroutine = self.__coroutine_target(*args, **kwargs)

            # Wait for the coroutine to finish
            result = loop.run_until_complete(coroutine)
            # Support for multiple return values
            if not isinstance(result, Iterable):
                result = [result]

            # If we have a done callback, invoke it
            if self.__done_callback is not None:
                if asyncio.iscoroutinefunction(self.__done_callback):
                    loop.run_until_complete(self.__done_callback(*result))
                else:
                    self.__done_callback(*result)
        except (CancelledError, TimeoutError, RuntimeError) as exception:
            logging.debug("Caught an expected exception: {}".format(type(exception).__name__))

            # Was an error callback set?
            if self.__error_callback is not None:
                if asyncio.iscoroutinefunction(self.__error_callback):
                    loop.run_until_complete(self.__error_callback(exception))
                else:
                    self.__error_callback(exception)
        except Exception as exception:
            logging.exception("Caught an unexpected exception: {}, raising.".format(type(exception).__name__))
            raise exception
        finally:
            loop.close()
            # Decrement the reference count, no longer required
            if self.__timeout is not None:
                del self.__timeout
            if self.__done_callback is not None:
                del self.__done_callback
            if self.__error_callback is not None:
                del self.__error_callback
            del self.__coroutine_target, self.__loop

    def start(self, timeout: Union[int, float] = 0,
              done_callback: Union[Callable, Awaitable] = None,
              error_callback: Union[Callable, Awaitable] = None):
        """
        The `start` method is invoked when we attempt to start a new thread.
        
        If a done callback is provided, it's invoked after the target is gracefully finished.

        If an error callback is provided, it's invoked if the target throws an expected exception.

        If a timeout is provided, and the taget/callback is a coroutine,
         the internal timeout variable is set.
        """
        # Set the timeout (only supported for coroutines)
        is_target_coroutine = asyncio.iscoroutinefunction(self._target)
        if is_target_coroutine and timeout:
            self.__timeout = timeout

        # Set the done callback
        if done_callback is not None:
            is_callback_coroutine = asyncio.iscoroutinefunction(done_callback)
            # If the target function is not a coroutine function the callback must not be a coroutine
            if is_target_coroutine or not is_target_coroutine and not is_callback_coroutine:
                self.__done_callback = done_callback
            else:
                raise TypeError("Type mismatch between the target and done callbacks.")

        # Set the error callback
        if error_callback is not None:
            is_callback_coroutine = asyncio.iscoroutinefunction(error_callback)
            # If the target function is not a coroutine function the callback must not be a coroutine
            if is_target_coroutine or not is_target_coroutine and not is_callback_coroutine:
                self.__error_callback = error_callback
            else:
                raise TypeError("Type mismatch between the target and error callbacks.")

        # Call Thread.start()
        super().start()

    def run(self):
        """
        The `run` method is invoked after the thread is started.

        This is where we setup the wrappers, and call the `Thread.run`.
        """
        # Is the target a coroutine?
        if asyncio.iscoroutinefunction(self._target):
            # Wrap the target to assure an event loop is created in its context
            self.__coroutine_target = self._target
            self._target = self.__async_wrapper
        else:
            # Wrap the target to enable catching exceptions for signals
            self.__target = self._target
            self._target = self.__wrapper
        # Call Thread.run()
        super().run()

    async def signal(self, signal: Signal) -> None:
        """
        The `signal` method is used for inter thread communication.

        The thread is sent a signal constant in the form of an exception,
         which is then handled by its wrapper.
        """
        # Is the thread still running?
        if not self.is_alive():
            return

        # Are we running a coroutine?
        if self.__loop is not None and self.__coroutine_target is not None:
            return await self.__signal_to_coroutine(signal)

        # Is it a valid signal?
        if signal is Signal.NONE:
            return

        # Throw an unhandled exception inside of the thread
        threadId = self.ident
        if threading._HAVE_THREAD_NATIVE_ID:
            threadId = self.native_id

        # Handle the signal
        if signal == Signal.STOP:
            logging.debug("STOP signal received, stopping the thread and waiting until it's finished.")

            # Throw an exception in the thread's context
            exception = SystemExit
            thread_states_modified = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(threadId), ctypes.py_object(exception))
            if not thread_states_modified:
                return  # invalid thread id
            if thread_states_modified != 1:
                logging.warn("Exception could not be set successfully, clearing any exception states.")

                # Clear any pending exception (cleanup)
                nullptr = 0
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(threadId), nullptr)
            else:
                logging.debug("Exception set successfully, joining thread.")
                self.join()

    async def __signal_to_coroutine(self, signal: Signal):
        """
        The `signal` method is used for inter thread communication when the
         target/callback is a coroutine.

        Based on the signal constant, a specific function or method is queued
         on the thread's event loop.
        """
        # Fetch the loop and execute a function
        loop = self.__loop
        # Is the loop still running?
        if not loop.is_running():
            return

        # Handle the signal
        if signal is Signal.NONE:
            return
        elif signal is Signal.STOP:
            logging.debug("STOP signal received, stopping the thread and waiting until it's finished.")
            # Stop the loop and wait for the thread to exit
            loop.call_soon_threadsafe(loop.stop)
            self.join()
            return


#--------------------------------------------------------------------------
# HashDB API 
#--------------------------------------------------------------------------

def get_algorithms(api_url='https://hashdb.openanalysis.net', timeout=None):
    # Handle an empty timeout
    global HASHDB_REQUEST_TIMEOUT
    if timeout is None:
        timeout = HASHDB_REQUEST_TIMEOUT

    algorithms_url = api_url + '/hash'
    r = requests.get(algorithms_url, timeout=timeout)
    if not r.ok:
        raise HashDBError("Get algorithms API request failed, status %s" % r.status_code)
    results = r.json()

    algorithms = []
    for algorithm in results.get('algorithms',[]):
        size = determine_algorithm_size(algorithm.get('type', None))
        if size == 'Unknown':
            idaapi.msg("ERROR: Unknown algorithm type encountered when fetching algorithms: %s" % size)
        algorithms.append([algorithm.get('algorithm'), size])
    return algorithms


def get_strings_from_hash(algorithm, hash_value, xor_value=0, api_url='https://hashdb.openanalysis.net', timeout=None):
    # Handle an empty timeout
    global HASHDB_REQUEST_TIMEOUT
    if timeout is None:
        timeout = HASHDB_REQUEST_TIMEOUT

    hash_value ^= xor_value
    hash_url = api_url + '/hash/%s/%d' % (algorithm, hash_value)
    r = requests.get(hash_url, timeout=timeout)
    if not r.ok:
        raise HashDBError("Get hash API request failed, status %s" % r.status_code)
    results = r.json()
    # Remove null bytes from non-api strings
    hashes = results.get('hashes',[])
    out_hashes = []
    for hash_info in hashes:
        if not hash_info.get('string',{}).get('is_api',True):
            hash_info['string']['string'] = hash_info['string']['string'].replace('\x00','')
        out_hashes.append(hash_info)
    return {'hashes':out_hashes}


def get_module_hashes(module_name, algorithm, permutation, api_url='https://hashdb.openanalysis.net', timeout=None):
    # Handle an empty timeout
    global HASHDB_REQUEST_TIMEOUT
    if timeout is None:
        timeout = HASHDB_REQUEST_TIMEOUT
    
    module_url = api_url + '/module/%s/%s/%s' % (module_name, algorithm, permutation)
    r = requests.get(module_url, timeout=timeout)
    if not r.ok:
        raise HashDBError("Get hash API request failed, status %s" % r.status_code)
    results = r.json()
    return results


def hunt_hash(hash_value, api_url='https://hashdb.openanalysis.net', timeout = None):
    # Handle an empty timeout
    global HASHDB_REQUEST_TIMEOUT
    if timeout is None:
        timeout = HASHDB_REQUEST_TIMEOUT
    
    matches = []
    hash_list = [hash_value]
    module_url = api_url + '/hunt'
    r = requests.post(module_url, json={"hashes": hash_list}, timeout=timeout)
    if not r.ok:
        print(module_url)
        print(hash_list)
        print(r.json())
        raise HashDBError("Get hash API request failed, status %s" % r.status_code)
    for hit in r.json().get('hits',[]):
        algo = hit.get('algorithm',None)
        if (algo != None) and (algo not in matches):
            matches.append(algo)
    return matches


#--------------------------------------------------------------------------
# Save and restore settings
#--------------------------------------------------------------------------
def load_settings():
    global HASHDB_API_URL 
    global HASHDB_USE_XOR
    global HASHDB_XOR_VALUE 
    global HASHDB_ALGORITHM
    global ENUM_PREFIX
    global NETNODE_NAME
    node = ida_netnode.netnode(NETNODE_NAME)
    if ida_netnode.exist(node):
        if bool(node.hashstr("HASHDB_API_URL")):
            HASHDB_API_URL = node.hashstr("HASHDB_API_URL")
        if bool(node.hashstr("HASHDB_USE_XOR")):
            if node.hashstr("HASHDB_USE_XOR").lower() == "true":
                HASHDB_USE_XOR = True
            else: 
                HASHDB_USE_XOR = False
        if bool(node.hashstr("HASHDB_XOR_VALUE")):
            HASHDB_XOR_VALUE = int(node.hashstr("HASHDB_XOR_VALUE"))
        if bool(node.hashstr("HASHDB_ALGORITHM")) and bool(node.hashstr("HASHDB_ALGORITHM_SIZE")):
            successful = set_algorithm(node.hashstr("HASHDB_ALGORITHM"), node.hashstr("HASHDB_ALGORITHM_SIZE"))
            if not successful:
                idaapi.msg("HashDB failed to set the algorithm when parsing the saved config!\n")
        if bool(node.hashstr("ENUM_PREFIX")):
            ENUM_PREFIX = node.hashstr("ENUM_PREFIX")
        idaapi.msg("HashDB configuration loaded!\n")
    else:
        idaapi.msg("No saved HashDB configuration\n")
    return


def save_settings():
    global HASHDB_API_URL 
    global HASHDB_USE_XOR
    global HASHDB_XOR_VALUE 
    global HASHDB_ALGORITHM
    global ENUM_PREFIX
    global NETNODE_NAME
    node = ida_netnode.netnode()
    if node.create(NETNODE_NAME):
        if HASHDB_API_URL != None:
            node.hashset_buf("HASHDB_API_URL", str(HASHDB_API_URL))
        if HASHDB_USE_XOR != None:
            node.hashset_buf("HASHDB_USE_XOR", str(HASHDB_USE_XOR))
        if HASHDB_XOR_VALUE != None:
            node.hashset_buf("HASHDB_XOR_VALUE", str(HASHDB_XOR_VALUE))
        if HASHDB_ALGORITHM != None:
            node.hashset_buf("HASHDB_ALGORITHM", str(HASHDB_ALGORITHM))
        if HASHDB_ALGORITHM != None:
            node.hashset_buf("HASHDB_ALGORITHM_SIZE", str(HASHDB_ALGORITHM_SIZE))
        if ENUM_PREFIX != None:
            node.hashset_buf("ENUM_PREFIX", str(ENUM_PREFIX))
        idaapi.msg("HashDB settings saved\n")
    else:
        idaapi.msg("ERROR: Unable to save HashDB settings\n")
    return


#--------------------------------------------------------------------------
# Settings form
#--------------------------------------------------------------------------
class hashdb_settings_t(ida_kernwin.Form):
    """Global settings form for hashdb"""

    class algorithm_chooser_t(ida_kernwin.Choose):
        """
        A simple chooser to be used as an embedded chooser
        """
        def __init__(self, algo_list):
            ida_kernwin.Choose.__init__(
                self,
                "",
                [
                    ["Algorithm", 15],
                    ["Size (Bits)", 5]
                ],
                flags=0,
                embedded=True,
                width=30,
                height=6)
            self.items = algo_list
            self.icon = None

        def OnGetLine(self, n):
            return self.items[n]

        def OnGetSize(self):
            return len(self.items)


    def __init__(self, algorithms):
        self.__n = 0
        F = ida_kernwin.Form
        F.__init__(self,
r"""BUTTON YES* Ok
BUTTON CANCEL Cancel
HashDB Settings

{FormChangeCb}
<##API URL          :{iServer}>
<##Enum Prefix      :{iEnum}>
<Enable XOR:{rXor}>{cXorGroup}>  |  <##:{iXor}>(hex)
<Select algorithm :{cAlgoChooser}><Refresh Algorithms:{iBtnRefresh}>

""", {      'FormChangeCb': F.FormChangeCb(self.OnFormChange),
            'iServer': F.StringInput(),
            'iEnum': F.StringInput(),
            'cXorGroup': F.ChkGroupControl(("rXor",)),
            'iXor': F.NumericInput(tp=F.FT_RAWHEX),
            'cAlgoChooser' : F.EmbeddedChooserControl(hashdb_settings_t.algorithm_chooser_t(algorithms)),
            'iBtnRefresh': F.ButtonInput(self.OnBtnRefresh),
        })

    def OnBtnRefresh(self, code=0):
        api_url = self.GetControlValue(self.iServer)
        try:
            ida_kernwin.show_wait_box("HIDECANCEL\nPlease wait...")
            algorithms = get_algorithms(api_url=api_url)
        except Exception as e:
            idaapi.msg("ERROR: HashDB API request failed: %s\n" % e)
        finally:
            ida_kernwin.hide_wait_box()
        # Sort the algorithms by algorithm name (lowercase)
        sorted_algorithms = sorted(algorithms, key = lambda algorithm: algorithm[0].lower())
        self.cAlgoChooser.chooser.items = sorted_algorithms
        self.RefreshField(self.cAlgoChooser)


    def OnFormChange(self, fid):
        if fid == -1:
            # Form is initialized
            # Hide Xor input if dissabled 
            if self.GetControlValue(self.cXorGroup) == 1:
                self.EnableField(self.iXor, True)
            else:
                self.EnableField(self.iXor, False)
            self.SetFocusedField(self.cAlgoChooser)
        elif fid == self.cXorGroup.id:
            if self.GetControlValue(self.cXorGroup) == 1:
                self.EnableField(self.iXor, True)
            else:
                self.EnableField(self.iXor, False)
        else:
            pass
            #print("Unknown fid %r" % fid)
        return 1

    @staticmethod
    def show(api_url="https://hashdb.openanalysis.net",
             enum_prefix="hashdb_strings",
             use_xor=False,
             xor_value=0,
             algorithms=[]):
        global HASHDB_API_URL
        global HASHDB_USE_XOR
        global HASHDB_XOR_VALUE
        global HASHDB_ALGORITHM
        global ENUM_PREFIX
        # Sort the algorithms
        sorted_algorithms = sorted(algorithms, key = lambda algorithm: algorithm[0].lower())
        f = hashdb_settings_t(sorted_algorithms)
        f, args = f.Compile()
        # Set default values
        f.iServer.value = api_url
        f.iEnum.value = enum_prefix
        if use_xor:
            f.rXor.checked = True
        else:
            f.rXor.checked = False
        f.iXor.value = xor_value
        # Show form
        ok = f.Execute()
        if ok == 1:
            # Save default settings first
            HASHDB_USE_XOR = f.rXor.checked
            HASHDB_XOR_VALUE = f.iXor.value
            HASHDB_API_URL = f.iServer.value
            ENUM_PREFIX = f.iEnum.value
            # Check if algorithm is selected
            if f.cAlgoChooser.selection == None:
                # No algorithm selected bail!
                idaapi.msg("HashDB: No algorithm selected!\n")
                f.Free()
                return False
            # Set the algorithm
            algorithm = f.cAlgoChooser.chooser.items[f.cAlgoChooser.selection[0]]
            set_algorithm(algorithm[0], algorithm[1]) # Error messages handled inside of set_algorithm
            f.Free()
            return True
        else:
            f.Free()
            return False


#--------------------------------------------------------------------------
# Hash collision select form
#--------------------------------------------------------------------------
class match_select_t(ida_kernwin.Form):
    """Simple form to select string match during hash collision"""
    def __init__(self, collision_strings):
        self.__n = 0
        F = ida_kernwin.Form
        F.__init__(self,
r"""BUTTON YES* Ok
HashDB Hash Collision

{FormChangeCb}
More than one string matches this hash!
<Select the correct string :{cbCollisions}>

""", {      'FormChangeCb': F.FormChangeCb(self.OnFormChange),
            'cbCollisions': F.DropdownListControl(
                        items=collision_strings,
                        readonly=True,
                        selval=0),
        })


    def OnFormChange(self, fid):
        if fid == -1:
            # Form is initialized
            self.SetFocusedField(self.cbCollisions)
        elif fid == self.cbCollisions.id:
            sel_idx = self.GetControlValue(self.cbCollisions)
        else:
            pass
            #print("Unknown fid %r" % fid)
        return 1

    @staticmethod
    def show(collision_strings):
        global HASHDB_API_URL
        global HASHDB_USE_XOR
        global HASHDB_XOR_VALUE
        global HASHDB_ALGORITHM
        f = match_select_t(collision_strings)
        f, args = f.Compile()
        # Show form
        ok = f.Execute()
        if ok == 1:
            string_selection = f.cbCollisions[f.cbCollisions.value]
            f.Free()
            return string_selection
        else:
            f.Free()
            return None


#--------------------------------------------------------------------------
# Hash hunt results form
#--------------------------------------------------------------------------

class hunt_result_form_t(ida_kernwin.Form):

    class algorithm_chooser_t(ida_kernwin.Choose):
        """
        A simple chooser to be used as an embedded chooser
        """
        def __init__(self, algo_list):
            ida_kernwin.Choose.__init__(
                self,
                "",
                [
                    ["Algorithm", 10],
                    ["Size (Bits)", 5]
                ],
                flags=0,
                embedded=True,
                width=30,
                height=6)
            self.items = algo_list
            self.icon = None

        def OnGetLine(self, n):
            return self.items[n]

        def OnGetSize(self):
            return len(self.items)

    def __init__(self, algo_list, msg):
        self.invert = False
        F = ida_kernwin.Form
        F.__init__(
            self,
            r"""BUTTON YES* OK
Matched Algorithms

{FormChangeCb}
{cStrStatus}
<:{cAlgoChooser}>
""", {
            'cStrStatus': F.StringLabel(msg),
            'FormChangeCb': F.FormChangeCb(self.OnFormChange),
            'cAlgoChooser' : F.EmbeddedChooserControl(hunt_result_form_t.algorithm_chooser_t(algo_list))
        })

    def OnFormChange(self, fid):
        if fid == -1:
            # Hide algorithm chooser if empty
            if self.cAlgoChooser.chooser.items == []:
                self.ShowField(self.cAlgoChooser, False)
        return 1

    def show(algo_list):
        global HASHDB_API_URL
        global HASHDB_USE_XOR
        global HASHDB_XOR_VALUE
        global HASHDB_ALGORITHM
        # Set default values
        if len(algo_list) == 0:
            msg = "No algorithms matched the hash."
            f = hunt_result_form_t(algo_list, msg)
        else:
            msg = "The following algorithms contain a matching hash.\nSelect an algorithm to set as the default for HashDB."
            f = hunt_result_form_t(algo_list, msg)
        f, args = f.Compile()
        # Show form
        ok = f.Execute()
        if ok == 1:
            if f.cAlgoChooser.selection == None:
                # No algorithm selected bail!
                f.Free()
                return False
            # Set the algorithm
            algorithm = f.cAlgoChooser.chooser.items[f.cAlgoChooser.selection[0]]
            set_algorithm(algorithm[0], algorithm[1]) # Error messages handled inside of set_algorithm
            f.Free()
            return True
        else:
            f.Free()
            return False


#--------------------------------------------------------------------------
# Module import select form
#--------------------------------------------------------------------------
class api_import_select_t(ida_kernwin.Form):
    """Simple form to select module to import apis from"""
    def __init__(self, string_value, module_list):
        self.__n = 0
        F = ida_kernwin.Form
        F.__init__(self,
r"""BUTTON YES* Import
BUTTON CANCEL No
HashDB Bulk Import

{FormChangeCb}
{cStr1} 
Do you want to import all function hashes from this module?
<Select module :{cbModules}>

""", {      'FormChangeCb': F.FormChangeCb(self.OnFormChange),
            'cStr1': F.StringLabel("<span style='float:left;'>The hash for <b>"+string_value+"</b> is a module function.<span>", tp=F.FT_HTML_LABEL),
            'cbModules': F.DropdownListControl(
                        items=module_list,
                        readonly=True,
                        selval=0),
        })


    def OnFormChange(self, fid):
        if fid == -1:
            # Form is initialized
            self.SetFocusedField(self.cbModules)
        elif fid == self.cbModules.id:
            sel_idx = self.GetControlValue(self.cbModules)
        else:
            pass
            #print("Unknown fid %r" % fid)
        return 1

    @staticmethod
    def show(string_value, module_list):
        f = api_import_select_t(string_value, module_list)
        f, args = f.Compile()
        # Show form
        ok = f.Execute()
        if ok == 1:
            module_selection = f.cbModules[f.cbModules.value]
            f.Free()
            return module_selection
        else:
            f.Free()
            return None


#--------------------------------------------------------------------------
# IDA helper functions
#--------------------------------------------------------------------------
def add_enums(enum_name, hash_list, enum_size = 0):
    '''
    Add a list of string,hash pairs to enum.
    hash_list = [(string1,hash1),(string2,hash2)]
    '''
    # Resolve the enum size
    if not enum_size:
        global HASHDB_ALGORITHM_SIZE
        enum_size = int(HASHDB_ALGORITHM_SIZE / 8)

    # Create enum
    enum_id = idc.add_enum(-1, enum_name, ida_bytes.hex_flag())
    if enum_id == idaapi.BADNODE:
        # Enum already exists attempt to find it
        enum_id = ida_enum.get_enum(enum_name)
    if enum_id == idaapi.BADNODE:
        # Can't create or find enum
        return None
    # Set the enum size/width (expected to return True for valid sizes)
    if not ida_enum.set_enum_width(enum_id, enum_size):
        return None
    
    # IDA API defines (https://hex-rays.com/products/ida/support/idapython_docs/ida_enum.html)
    ENUM_MEMBER_ERROR_SUCCESS = 0 # successfully added
    ENUM_MEMBER_ERROR_NAME    = 1 # a member with this name already exists

    MAXIMUM_ATTEMPTS = 256 # ENUM_MEMBER_ERROR_VALUE -> only allows 256 members with this value
    for member_name, value in hash_list:
        # First, we have to check if this name and value already exist in the enum
        if ida_enum.get_enum_member(enum_id, value, 0, 0) != idaapi.BADNODE:
            continue # Skip if the value already exists in the enum

        # Attempt to generate a name, and insert the value
        for index in range(MAXIMUM_ATTEMPTS):
            result = ida_enum.add_enum_member(enum_id, member_name if not index else member_name + '_' + str(index), value)
            # Successfully added to the list
            if result == ENUM_MEMBER_ERROR_SUCCESS:
                break

            # Unhandled error (TODO: add logging)
            if result != ENUM_MEMBER_ERROR_NAME:
                return None
    return enum_id


def generate_enum_name(prefix: str) -> str:
    """
    Generates an enum name from a prefix
    """
    global HASHDB_ALGORITHM
    return prefix + '_' + HASHDB_ALGORITHM


def make_const_enum(enum_id, hash_value):
    # We are in the disassembler we can set the enum directly
    ea = idc.here()
    start = idaapi.get_item_head(ea)
    # Determind if this is code or data/undefined
    if idc.is_code(idc.get_full_flags(ea)):
        # Find the operand position
        if idc.get_operand_value(ea,0) == hash_value:
            ida_bytes.op_enum(start, 0, enum_id, 0)
            return True
        elif idc.get_operand_value(ea,1) == hash_value:
            ida_bytes.op_enum(start, 1, enum_id, 0)
            return True
        else:
            return False
    else:
        ida_bytes.op_enum(start, 0, enum_id, 0)


def parse_highlighted_value():
    identifier = None

    v = ida_kernwin.get_current_viewer()
    thing = ida_kernwin.get_highlight(v)
    if thing and thing[1]:
        identifier = thing[0]
    if identifier is None:
        return None

    # Represents the type of the value
    type = "decimal"
    if identifier.endswith('h'):
        # IDA View
        identifier = identifier[:-1]
        type = "hex"
    elif identifier.startswith("0x"):
        # Pseudocode
        identifier = identifier[2:]
        type = "hex"
    elif identifier.endswith('o'):
        identifier = identifier[:-1]
        type = "octal"
    elif identifier.endswith('b'):
        identifier = identifier[:-1]
        type = "binary"
    
    character_set = {
        "binary": "01",
        "octal": string.octdigits,
        "decimal": string.digits,
        "hex": string.hexdigits
    }
    # Find the first invalid character and trim the string accordingly
    for index, character in enumerate(identifier):
        if character not in character_set[type]:
            identifier = identifier[:index]
            break
    if not identifier: # The first character was bad
        return None

    types = {
        "binary": 2,
        "octal": 8,
        "decimal": 10,
        "hex": 16
    }
    return int(identifier, types[type])


def determine_highlighted_type_size(ea: int) -> int:
    '''Guess the highlighted type and return the size in bytes.'''
    type = idaapi.idc_guess_type(ea)
    if type == '__int64':
        return 8
    if type == 'int':
        return 4
    if type == '__int16':
        return 2
    if type == 'char':
        return 1
    # If IDA couldn't guess the type (undefined, etc.) type will be empty
    return 0


def read_integer_from_db(ea: int, default_size: int = 0) -> int:
    '''
    Read the highlighted data from the database.
    Returns: [value, size, was_type_valid]
    '''
    type_size = determine_highlighted_type_size(ea)
    # 64-bit
    if type_size == 8 or (not type_size and default_size == 8):
        return [ida_bytes.get_64bit(ea), 8, bool(type_size)]
    # 32-bit
    if type_size == 4 or (not type_size and default_size == 4):
        return [ida_bytes.get_32bit(ea), 4, bool(type_size)]
    # 16-bit
    if type_size == 2 or (not type_size and default_size == 2):
        return [ida_bytes.get_16bit(ea), 2, bool(type_size)]
    # 8-bit and "undefined" values
    if type_size == 1 or (not type_size and not default_size) or (not type_size and default_size == 1):
        return [ida_bytes.get_byte(ea), 1, bool(type_size)]

    # Should never get executed
    raise HashDBError("Failed to read integer from database at location: {} with size {}.".format(hex(ea), default_size))


def convert_data_to_integer(ea, size: int = 0) -> int:
    '''
    Converts the data into a QWORD, DWORD, WORD, or BYTE based on the size provided
    '''
    global HASHDB_ALGORITHM_SIZE
    if not size:
        size = int(HASHDB_ALGORITHM_SIZE / 8)

    if size == 8:
        ida_bytes.create_qword(ea, size, True)
    elif size == 4:
        ida_bytes.create_dword(ea, size, True)
    elif size == 2:
        ida_bytes.create_word(ea, size, True)
    elif size == 1:
        ida_bytes.create_byte(ea, size, True)
    return size


#--------------------------------------------------------------------------
# Global settings
#--------------------------------------------------------------------------
def global_settings():
    global HASHDB_API_URL
    global HASHDB_USE_XOR
    global HASHDB_XOR_VALUE
    global HASHDB_ALGORITHM
    global ENUM_PREFIX
    if HASHDB_ALGORITHM != None:
        algorithms = [[HASHDB_ALGORITHM, str(HASHDB_ALGORITHM_SIZE)]]
    else:
        algorithms = []
    settings_results = hashdb_settings_t.show(api_url=HASHDB_API_URL, 
                                              enum_prefix=ENUM_PREFIX,
                                              use_xor=HASHDB_USE_XOR,
                                              xor_value=HASHDB_XOR_VALUE,
                                              algorithms=algorithms)
    if settings_results:
        idaapi.msg("HashDB configured successfully!\nHASHDB_API_URL: %s\nHASHDB_USE_XOR: %s\nHASHDB_XOR_VALUE: %s\nHASHDB_ALGORITHM: %s\nHASHDB_ALGORITHM_SIZE: %s\n" % 
                   (HASHDB_API_URL, HASHDB_USE_XOR, hex(HASHDB_XOR_VALUE), HASHDB_ALGORITHM, HASHDB_ALGORITHM_SIZE))
    else:
        idaapi.msg("HashDB configuration cancelled!\n")
    return 


#--------------------------------------------------------------------------
# Set the algorithm and its size
#--------------------------------------------------------------------------
def set_algorithm(algorithm: str, size: int) -> bool:
    global HASHDB_ALGORITHM
    global HASHDB_ALGORITHM_SIZE

    # Type checks to prevent accidental errors
    if not isinstance(algorithm, str):
        idaapi.msg("HashDB encountered an error while trying to set the algorithm: provided algorithm is a string type: %s\n", algorithm)
        return False
    
    if isinstance(size, str):
        size = int(size)
    if not isinstance(size, int):
        idaapi.msg("HashDB encountered an error while trying to set the algorithm: provided size is not an integer: %s\n" % size)
        return False
    
    # More checks for supported sizes
    supported_algorithm_sizes = [32, 64]
    if size not in supported_algorithm_sizes or size % 8 != 0:
        idaapi.msg("HashDB encountered an error while trying to set the algorithm: the size provided was invalid: %s\n" % size)
        return False
    
    # Set the algorithm and size
    HASHDB_ALGORITHM = algorithm
    HASHDB_ALGORITHM_SIZE = size
    return True


def determine_algorithm_size(algorithm_type: str) -> str:
    size = 'Unknown'
    if algorithm_type is None:
        return size
    
    if algorithm_type == 'unsigned_int':
        size = '32'
    elif algorithm_type == 'unsigned_long':
        size = '64'
    return size


#--------------------------------------------------------------------------
# Set xor key
#--------------------------------------------------------------------------
def set_xor_key():
    """
    Set xor key from selection
    """
    global HASHDB_USE_XOR
    global HASHDB_XOR_VALUE
    xor_value = parse_highlighted_value()
    if xor_value is None:
        idaapi.msg("HashDB ERROR: Invalid xor value selection.\n")
        return False
    else:
        idaapi.msg("HashDB: Set xor value to: {}\n".format(hex(xor_value)))
    HASHDB_XOR_VALUE = xor_value
    HASHDB_USE_XOR = True
    idaapi.msg("XOR key set: {}\n".format(hex(xor_value)))
    return True
    

#--------------------------------------------------------------------------
# Hash lookup
#--------------------------------------------------------------------------
def hash_lookup_done_handler(hash_list: Union[None, list], hash_value: int = None):
    global ENUM_PREFIX
    def add_enums_wrapper(enum_name, hash_list):
        nonlocal enum_id
        enum_id = add_enums(enum_name, hash_list)
        return 0 # execute_sync dictates an int return value
    
    if hash_list is None or hash_value is None:
        return

    # Parse the hash list
    hash_string = None
    if len(hash_list) == 1:
        hash_string = hash_list[0].get("string", {})
    else:
        # Multiple hashes found, allow the user to
        #  select the best match
        collisions = {}
        for string_match in hash_list:
            string_value = string_match.get("string", {})
            if string_value.get('is_api', False):
                collisions[string_value.get("api", "")] = string_value
            else:
                collisions[string_value.get("string", "")] = string_value
        
        # Execute the match_select_t form on the main thread
        def match_select_show(collision_strings):
            nonlocal selected_string
            selected_string = match_select_t.show(collision_strings)
            return 0 # execute_sync dictates an int return value

        selected_string = None
        match_select_callable = functools.partial(match_select_show, [*collisions.keys()])
        ida_kernwin.execute_sync(match_select_callable, ida_kernwin.MFF_FAST)
        if selected_string is None:
            return
        
        hash_string = collisions[selected_string]
    
    # Parse the string from the hash_string match
    string_value = ""
    if hash_string.get("is_api", False):
        string_value = hash_string.get("api", "")
    else:
        string_value = hash_string.get("string", "")

    # Handle empty string values
    if not len(string_value):
        string_value = "empty_string"

    # Hash found!
    idaapi.msg("HashDB: Hash match found: {}\n".format(string_value))

    # Add the hash to the global enum, and exit if we can't create it
    enum_id = None
    add_enums_callable = functools.partial(add_enums_wrapper, generate_enum_name(ENUM_PREFIX), [(string_value, hash_value)])
    ida_kernwin.execute_sync(add_enums_callable, ida_kernwin.MFF_FAST)
    if enum_id is None:
        idaapi.msg("ERROR: Unable to create or find enum: {}\n".format(generate_enum_name(ENUM_PREFIX)))
        return
    
    # If the hash was pulled from the disassembly window
    # make the constant an enum 
    # TODO: I don't know how to do this in the decompiler window
    def make_const_enum_wrapper(enum_id, hash_value):
        if ida_kernwin.get_viewer_place_type(ida_kernwin.get_current_viewer()) == ida_kernwin.TCCPT_IDAPLACE:
            make_const_enum(enum_id, hash_value)
        return 0 # execute_sync dictates an int return value
    
    make_const_enum_wrapper_callable = functools.partial(make_const_enum_wrapper, enum_id, hash_value)
    ida_kernwin.execute_sync(make_const_enum_wrapper_callable, ida_kernwin.MFF_FAST)

    # Handle API hashes
    if not hash_string.get("is_api", False):
        return

    # Execute the api_import_select_t form on the main thread
    def api_import_select_show(string_value, module_list) -> int:
        nonlocal module_name
        module_name = api_import_select_t.show(string_value, module_list)
        return 0 # execute_sync dictates an int return value

    module_name = None
    api_import_select_callable = functools.partial(api_import_select_show, string_value, hash_string.get("modules", []))
    ida_kernwin.execute_sync(api_import_select_callable, ida_kernwin.MFF_FAST)
    if module_name is None:
        return

    # Import all of the hashes from the module and permutation
    module_hash_list = None
    try:
        global HASHDB_ALGORITHM, HASHDB_API_URL, HASHDB_REQUEST_TIMEOUT
        module_hash_list = get_module_hashes(module_name, HASHDB_ALGORITHM, hash_string.get("permutation", ""), HASHDB_API_URL, timeout=HASHDB_REQUEST_TIMEOUT)
    except requests.Timeout:
        idaapi.msg("ERROR: HashDB API module hashes request timed out.\n")
        logging.exception("API request to {} timed out.".format(HASHDB_API_URL))
        return

    # Add the hash list to the global enum
    global HASHDB_USE_XOR, HASHDB_XOR_VALUE
    enum_list = []
    for function_entry in module_hash_list.get("hashes", []):
        hash = function_entry.get("hash", 0)
        enum_list.append((function_entry.get("string", {}).get("api", ""),
                          hash ^ HASHDB_XOR_VALUE if HASHDB_USE_XOR else hash))
    
    # Add hashes to enum
    enum_id = None
    add_enums_callable = functools.partial(add_enums_wrapper, generate_enum_name(ENUM_PREFIX), enum_list)
    ida_kernwin.execute_sync(add_enums_callable, ida_kernwin.MFF_FAST)
    if enum_id is None:
        idaapi.msg("ERROR: Unable to create or find enum: {}\n".format(generate_enum_name(ENUM_PREFIX)))
    else:
        idaapi.msg("Added {} hashes for module {}\n".format(len(enum_list), module_name))


def hash_lookup_done(hash_list: Union[None, list] = None, hash_value: int = None):
    global HASHDB_REQUEST_LOCK
    hash_lookup_done_handler(hash_list, hash_value)

    # Release the lock
    HASHDB_REQUEST_LOCK.release()


def hash_lookup_error(exception: Exception):
    global HASHDB_REQUEST_LOCK
    exception_string = traceback.format_exc()
    logging.critical("hash_lookup_request {}".format("timed out." if type(exception) == TimeoutError else "errored: {}".format(exception_string)))
    idaapi.msg("ERROR: HashDB hash scan failed: {}\n".format(exception_string))
    HASHDB_REQUEST_LOCK.release()


async def hash_lookup_request(api_url: str, algorithm: str,
                              hash_value: int, xor_value: Union[None, int],
                              timeout: Union[int, float]):
    # Perform the request
    hash_results = None
    try:
        hash_results = get_strings_from_hash(algorithm, hash_value, xor_value if xor_value is not None else 0, api_url, timeout)
    except requests.Timeout:
        idaapi.msg("ERROR: HashDB API lookup hash request timed out.\n")
        logging.exception("API request to {} timed out:".format(HASHDB_API_URL))
        return None

    hash_list = hash_results.get("hashes", [])
    # Did `hashes` exist, was the array empty?
    if not hash_list:
        idaapi.msg("HashDB: No hash found for {}\n".format(hex(hash_value)))
        return None
    return hash_list, hash_value


def hash_lookup_run(timeout: Union[int, float] = 0) -> bool:
    # Check if an algorithm is selected
    global HASHDB_ALGORITHM, HASHDB_ALGORITHM_SIZE, HASHDB_API_URL, \
           ENUM_PREFIX, HASHDB_USE_XOR, HASHDB_XOR_VALUE
    if HASHDB_ALGORITHM is None:
        idaapi.warning("Please select a hash algorithm before using HashDB.")
        settings_results = hashdb_settings_t.show(api_url=HASHDB_API_URL, 
                                                  enum_prefix=ENUM_PREFIX,
                                                  use_xor=HASHDB_USE_XOR,
                                                  xor_value=HASHDB_XOR_VALUE)
        if settings_results:
            idaapi.msg("HashDB configured successfully!\n" +
                       "HASHDB_API_URL:        {}\n".format(HASHDB_API_URL) +
                       "HASHDB_USE_XOR:        {}\n".format(HASHDB_USE_XOR) +
                       "HASHDB_XOR_VALUE:      {}\n".format(hex(HASHDB_XOR_VALUE)) +
                       "HASHDB_ALGORITHM:      {}\n".format(HASHDB_ALGORITHM) +
                       "HASHDB_ALGORITHM_SIZE: {}\n".format(HASHDB_ALGORITHM_SIZE))
        else:
            idaapi.msg("HashDB configuration cancelled!\n")
            return True # Release the lock
    
    # Get the selected hash value
    hash_value = parse_highlighted_value()
    if hash_value is None:
        idaapi.msg("HashDB ERROR: Invalid hash value selection.\n")
        return True # Release the lock
    else:
        idaapi.msg("HashDB: Found hash value: {}\n".format(hex(hash_value)))

    # Lookup the hash and show a match select form
    worker = Worker(target=hash_lookup_request, args=(
        HASHDB_API_URL, HASHDB_ALGORITHM, hash_value, HASHDB_XOR_VALUE if HASHDB_USE_XOR else None, timeout))
    worker.start(timeout=timeout, done_callback=hash_lookup_done, error_callback=hash_lookup_error)
    return False # Do not release the lock


def hash_lookup():
    """
    Lookup a hash value from the highlighted text.

    The function will spawn a new thread with a timeout (`HASHDB_REQUEST_TIMEOUT`).
     While executing, the request lock is acquired.
    """
    # Check if we're already running a request
    global HASHDB_REQUEST_LOCK, HASHDB_REQUEST_TIMEOUT
    timeout_string = "{}".format(HASHDB_REQUEST_TIMEOUT) + "second{}".format('s' if HASHDB_REQUEST_TIMEOUT != 1 else "")
    if HASHDB_REQUEST_LOCK.locked():
        logging.debug("An async operation was requested, but the response lock was locked. Aborting.")
        ida_kernwin.info("Please wait until the previous request is finished.\n" +
                         "Requests timeout after {}.".format(timeout_string))
        return

    # Acquire the lock and execute the request
    HASHDB_REQUEST_LOCK.acquire()
    idaapi.msg("HashDB: Searching for a hash, please wait! Timeout: {}.\n".format(timeout_string))
    release_lock = hash_lookup_run(timeout=HASHDB_REQUEST_TIMEOUT)
    if release_lock:
        HASHDB_REQUEST_LOCK.release()


#--------------------------------------------------------------------------
# Dynamic IAT hash scan
# TODO: convert_values should be fetched from the UI (add a checkbox)
#--------------------------------------------------------------------------
def hash_scan_done(convert_values: bool = False, hash_list: Union[None, list] = None):
    global HASHDB_REQUEST_LOCK
    logging.debug("hash_scan_done callback invoked, result: {}".format("none" if hash_list is None else "{}".format(hash_list)))

    global ENUM_PREFIX
    def add_enums_wrapper(enum_name: str, hash_list):
        nonlocal enum_id
        enum_id = add_enums(enum_name, hash_list)
        return 0 # execute_sync dictates an int return value
    
    # Check if the `hash_scan_request` function failed (a caught exception should return `None`)
    if hash_list is not None:
        for hash_entry in hash_list:
            hashes = hash_entry["hashes"]
            hash_string_object = {}

            entries_count = len(hashes)
            if not entries_count:
                idaapi.msg("HashDB: Couldn't find any matches for hash value {} ({} bytes) at {}\n".format(hex(hash_entry["hash_value"]), hash_entry["size"], hex(hash_entry["ea"])))
                continue

            # Resolve the hash string object from the response
            if entries_count == 1:
                hash_string_object = hashes[0].get("string", {})
            else:
                # Check for collisions
                collisions = {}
                for entry in hashes:
                    string_object = entry.get("string", {})
                    if string_object.get("is_api", False):
                        collisions[string_object.get("api", "")] = string_object
                    else:
                        collisions[string_object.get("string", "")] = string_object
                
                # Execute the match_select_t form on the main thread
                def match_select_show(collision_strings):
                    nonlocal selected_string
                    selected_string = match_select_t.show(collision_strings)
                    return 0 # execute_sync dictates an int return value

                selected_string = None
                match_select_callable = functools.partial(match_select_show, [*collisions.keys()])
                ida_kernwin.execute_sync(match_select_callable, ida_kernwin.MFF_FAST)
                if selected_string is None:
                    HASHDB_REQUEST_LOCK.release() # Release the lock
                    return
                
                hash_string_object = collisions[selected_string]
            
            # Parse the string from hash_string_object
            hash_string_value = ""
            if hash_string_object.get("is_api", False):
                hash_string_value = hash_string_object.get("api", "")
            else:
                hash_string_value = hash_string_object.get("string", "")
            
            # Handle empty string values
            if not len(hash_string_value):
                hash_string_value = "empty_string"
            
            # Add hash to enum
            enum_id = None
            add_enums_callable = functools.partial(add_enums_wrapper, generate_enum_name(ENUM_PREFIX), [(hash_string_value, hash_entry["hash_value"])])
            ida_kernwin.execute_sync(add_enums_callable, ida_kernwin.MFF_FAST)
            if enum_id is None:
                idaapi.msg("ERROR: Unable to create or find enum: {}\n".format(generate_enum_name(ENUM_PREFIX)))
                HASHDB_REQUEST_LOCK.release() # Release the lock
                return
            
            # Should we convert the values in the database?
            if convert_values:
                # Convert to integer (this step is required due to an IDA api bug - `ida_bytes.op_enum` will set the wrong size)
                def convert_to_integer(ea: int, size: int):
                    convert_data_to_integer(ea, size)

                convert_to_integer_callable = functools.partial(convert_to_integer, hash_entry["ea"], hash_entry["size"])
                ida_kernwin.execute_sync(convert_to_integer_callable, ida_kernwin.MFF_FAST)

                # Convert to enum
                def convert_to_enum(ea: int, enum_id: int):
                    NUMBER_OF_OPERANDS = 0
                    SERIAL = 0
                    ida_bytes.op_enum(ea, NUMBER_OF_OPERANDS, enum_id, SERIAL)
                    return 0 # execute_sync dictates an int return value
                
                convert_to_enum_callable = functools.partial(convert_to_enum, hash_entry["ea"], enum_id)
                ida_kernwin.execute_sync(convert_to_enum_callable, ida_kernwin.MFF_FAST)

                # Add a label
                def set_name(ea: int, name: str):
                    if not name: # is the name empty?
                        return 0 # execute_sync dictates an int return value
                    
                    # Does the name already exist? If so, modify it!
                    index = 1
                    suffix = ""
                    while idc.get_name_ea_simple(name + suffix) != idaapi.BADADDR:
                        suffix = "_{}".format(index)
                        index += 1

                    idc.set_name(ea, name + suffix, idc.SN_CHECK)
                    return 0 # execute_sync dictates an int return value
                
                set_name_callable = functools.partial(set_name, hash_entry["ea"], "ptr_" + hash_string_value)
                ida_kernwin.execute_sync(set_name_callable, ida_kernwin.MFF_FAST)
    
    # Release the lock
    HASHDB_REQUEST_LOCK.release()


def hash_scan_error(exception: Exception):
    global HASHDB_REQUEST_LOCK
    exception_string = traceback.format_exc()
    logging.critical("hash_scan_request {}".format("timed out." if type(exception) == TimeoutError else "errored: {}".format(exception_string)))
    idaapi.msg("ERROR: HashDB hash scan failed: {}\n".format(exception_string))
    HASHDB_REQUEST_LOCK.release()


async def hash_scan_request(convert_values: bool, hash_list: list,
                            api_url: str, algorithm: str, xor_value: int,
                            timeout: Union[int, float]) -> Union[None, list]:
    for hash_entry in hash_list:
        try:
            hash_results = get_strings_from_hash(algorithm, hash_entry["hash_value"], xor_value if xor_value is not None else 0, api_url, timeout)
        except requests.Timeout:
            idaapi.msg("ERROR: HashDB API lookup scan request timed out.\n")
            logging.exception("API request to {} timed out:".format(HASHDB_API_URL))
            return None
        
        hash_entry["hashes"] = hash_results.get("hashes", [])
    return convert_values, hash_list


def hash_scan_run(convert_values: bool, timeout: Union[int, float] = 0) -> bool:
    # Only scan for data in the dissassembler
    if ida_kernwin.get_viewer_place_type(ida_kernwin.get_current_viewer()) != ida_kernwin.TCCPT_IDAPLACE:
        idaapi.msg("ERROR: Scan only available in dissassembler.\n")
        return True # Release the lock
    
    # Get the highlighted range
    start = idc.read_selection_start()
    end = idc.read_selection_end()
    if idaapi.BADADDR in (start, end):
        ea = idc.here()
        start = idaapi.get_item_head(ea)
        end = idaapi.get_item_end(ea)
    
    # If an algorithm isn't selected, give the user a chance to choose one
    global HASHDB_ALGORITHM, HASHDB_ALGORITHM_SIZE, HASHDB_API_URL, \
           ENUM_PREFIX, HASHDB_USE_XOR, HASHDB_XOR_VALUE
    if HASHDB_ALGORITHM is None:
        idaapi.warning("Please select a hash algorithm before using HashDB.")
        settings_results = hashdb_settings_t.show(api_url=HASHDB_API_URL, 
                                                  enum_prefix=ENUM_PREFIX,
                                                  use_xor=HASHDB_USE_XOR,
                                                  xor_value=HASHDB_XOR_VALUE)
        if settings_results:
            idaapi.msg("HashDB configured successfully!\n" +
                       "HASHDB_API_URL:        {}\n".format(HASHDB_API_URL) +
                       "HASHDB_USE_XOR:        {}\n".format(HASHDB_USE_XOR) +
                       "HASHDB_XOR_VALUE:      {}\n".format(hex(HASHDB_XOR_VALUE)) +
                       "HASHDB_ALGORITHM:      {}\n".format(HASHDB_ALGORITHM) +
                       "HASHDB_ALGORITHM_SIZE: {}\n".format(HASHDB_ALGORITHM_SIZE))
        else:
            idaapi.msg("HashDB configuration cancelled!\n")
            return True # Release the lock
    
    # Check for a valid algorithm size
    if not HASHDB_ALGORITHM_SIZE == 32 and not HASHDB_ALGORITHM_SIZE == 64:
        idaapi.msg("ERROR: Unexpected algorithm size provided: {}\n".format(HASHDB_ALGORITHM_SIZE))
        return True # Release the lock
    
    # Look through the selected range and lookup each (valid) entry
    def scan_range(start: int, end: int) -> list:
        """
        Find hash values in a given (highlighted) range.
         This function won't modify any data types in the database.
        
        Undefined types will be interpreted appropriately.
         As a result, the user is required to define the types if they
         expect valid results.
        """
        hash_values = []
        ea = start
        while ea < end:
            # Read the hash value and determine the step size:
            [hash_value, step_size, was_type_valid] = read_integer_from_db(ea)
            # If the type wasn't valid (undefined), convert it in the database
            #   and modify the hash value and step size accordingly:
            if convert_values and not was_type_valid:
                [hash_value, step_size, was_type_valid] = read_integer_from_db(ea, int(HASHDB_ALGORITHM_SIZE / 8))

            # Insert the hash value into the list
            hash_values.append({"ea": ea, "hash_value": hash_value, "size": step_size})

            # Next hash
            ea += step_size
        return hash_values
    
    hash_list = scan_range(start, end)
    for index, hash_entry in enumerate(hash_list, start=1):
        idaapi.msg("HashDB: [{}] Found hash value {} ({} bytes) at {}\n".format(index, hex(hash_entry["hash_value"]), hash_entry["size"], hex(hash_entry["ea"])))
    
    # Hunt all hashes, and provide the `hash_scan_done` callback with the results
    worker = Worker(target=hash_scan_request, args=(convert_values, hash_list,
                                                    HASHDB_API_URL, HASHDB_ALGORITHM,
                                                    HASHDB_XOR_VALUE if HASHDB_USE_XOR else None,
                                                    timeout))
    worker.start(timeout=timeout, done_callback=hash_scan_done, error_callback=hash_scan_error)
    return False # Do not release the lock


def hash_scan(convert_values = True):
    """
    Scan for a dynamic hash table.

    The function will spawn a new thread with a timeout (`HASHDB_REQUEST_TIMEOUT`).
     While executing, the request lock is acquired.
    """
    # Check if we're already running a request
    global HASHDB_REQUEST_LOCK, HASHDB_REQUEST_TIMEOUT
    timeout_string = "{}".format(HASHDB_REQUEST_TIMEOUT) + "second{}".format('s' if HASHDB_REQUEST_TIMEOUT != 1 else "")
    if HASHDB_REQUEST_LOCK.locked():
        logging.debug("An async operation was requested, but the response lock was locked. Aborting.")
        ida_kernwin.info("Please wait until the previous request is finished.\n" +
                         "Requests timeout after {}.".format(timeout_string))
        return

    # Acquire the lock and execute the request
    HASHDB_REQUEST_LOCK.acquire()
    idaapi.msg("HashDB: Scanning for hashes, please wait! Timeout: {}.\n".format(timeout_string))
    release_lock = hash_scan_run(convert_values=convert_values, timeout=HASHDB_REQUEST_TIMEOUT)
    if release_lock:
        HASHDB_REQUEST_LOCK.release()


#--------------------------------------------------------------------------
# Algorithm search function
#--------------------------------------------------------------------------
def hunt_algorithm_done(response: Union[None, list] = None):
    global HASHDB_REQUEST_LOCK
    logging.debug("hunt_algorithm_done callback invoked, result: {}".format("none" if response is None else "{}".format(response)))

    # Display the result
    if response is not None:
        logging.debug("Displaying hash_result_form_t.")
        hunt_result_form_callable = functools.partial(hunt_result_form_t.show, [response])
        ida_kernwin.execute_sync(hunt_result_form_callable, ida_kernwin.MFF_FAST)
    else:
        logging.debug("Couldn't find any algorithms that match the provided hash.")
        idaapi.msg("HashDB: Couldn't find any algorithms that match the provided hash.")
    
    # Release the lock
    HASHDB_REQUEST_LOCK.release()


def hunt_algorithm_error(exception: Exception):
    global HASHDB_REQUEST_LOCK
    exception_string = traceback.format_exc()
    logging.critical("hunt_algorithm_request {}".format("timed out." if type(exception) == TimeoutError else "errored: {}".format(exception_string)))
    idaapi.msg("ERROR: HashDB hash scan failed: {}\n".format(exception_string))
    HASHDB_REQUEST_LOCK.release()


async def hunt_algorithm_request(hash_value: int, timeout=None) -> Union[None, list]:
    """
    Perform the actual request, and provide the results to the
     `hunt_algorithm_done` callback.
    
    This function is required to be a coroutine for seamless timeout handling.
    """
    global HASHDB_REQUEST_LOCK, HASHDB_API_URL

    # Attempt to find matches
    match_results = None
    try:
        # Send the hunt request
        match_results = hunt_hash(hash_value, api_url=HASHDB_API_URL, timeout=timeout)
    except requests.exceptions.Timeout:
        idaapi.msg("ERROR: HashDB API hunt hash request timed out.\n")
        logging.exception("API request to {} timed out.".format(HASHDB_API_URL))
        return None
    
    # Fix the results (algorithm sizes)
    # TODO: At the moment we have to fetch the algorithms again to determine their sizes
    #       (the hunt_result_form_t form expects the algorithm name and size)
    algorithms = None
    try:
        # Send the hunt request
        algorithms = get_algorithms(timeout=timeout)
    except requests.exceptions.Timeout:
        idaapi.msg("ERROR: HashDB API algorithms request timed out.\n")
        logging.exception("API request to {} timed out.".format(HASHDB_API_URL))
        return None
    results = []
    for match in match_results:
        for algorithm in algorithms:
            if match == algorithm[0]:
                results.append(algorithm)
                break
    
    # Return the results
    return results


def hunt_algorithm_run(timeout: Union[int, float] = 0) -> bool:
    global HASHDB_REQUEST_LOCK, HASHDB_USE_XOR, HASHDB_XOR_VALUE
    
    # Get the selected hash value
    hash_value = parse_highlighted_value()
    if hash_value is None:
        idaapi.msg("HashDB ERROR: Invalid hash hash selection.\n")
        logging.warn("Failed to parse a hash value from the highligted text.")
        return True # Release the lock
    
    # Xor option
    if HASHDB_USE_XOR:
        hash_value ^= HASHDB_XOR_VALUE

    # Hunt the algorithm and show the hunt result form
    worker = Worker(target=hunt_algorithm_request, args=(hash_value, timeout))
    worker.start(timeout=timeout, done_callback=hunt_algorithm_done, error_callback=hunt_algorithm_error)
    return False # Do not release the lock


def hunt_algorithm():
    """
    Search for an algorithm using a hash value.

    The function will spawn a new thread with a timeout (`HASHDB_REQUEST_TIMEOUT`).
     While executing, the request lock is acquired.
    """
    # Check if we're already running a request
    global HASHDB_REQUEST_LOCK, HASHDB_REQUEST_TIMEOUT
    timeout_string = "{}".format(HASHDB_REQUEST_TIMEOUT) + "second{}".format('s' if HASHDB_REQUEST_TIMEOUT != 1 else "")
    if HASHDB_REQUEST_LOCK.locked():
        logging.debug("An async operation was requested, but the response lock was locked. Aborting.")
        ida_kernwin.info("Please wait until the previous request is finished.\n" +
                         "Requests timeout after {}.".format(timeout_string))
        return

    # Acquire the lock and execute the request
    HASHDB_REQUEST_LOCK.acquire()
    idaapi.msg("HashDB: Hunting for a hash algorithm, please wait! Timeout: {}.\n".format(timeout_string))
    release_lock = hunt_algorithm_run(timeout=HASHDB_REQUEST_TIMEOUT)
    if release_lock:
        HASHDB_REQUEST_LOCK.release()


#--------------------------------------------------------------------------
# Plugin
#--------------------------------------------------------------------------
class HashDB_Plugin_t(idaapi.plugin_t):
    """
    IDA Plugin for HashDB lookup service
    """
    comment = "HashDB Lookup Service"
    help = ""
    wanted_name = PLUGIN_NAME
    # We only want a hotkey for the actual hash lookup
    wanted_hotkey = ''
    flags = idaapi.PLUGIN_KEEP

    #--------------------------------------------------------------------------
    # Plugin Overloads
    #--------------------------------------------------------------------------
    def init(self):
        """
        This is called by IDA when it is loading the plugin.
        """
        global p_initialized

        # Check if already initialized 
        if p_initialized is False:
            p_initialized = True
            ## Print a nice header
            print("=" * 80)
            print(r"   _   _           _    ____________ ")
            print(r"  | | | |         | |   |  _  \ ___ \ ")
            print(r"  | |_| | __ _ ___| |__ | | | | |_/ /")
            print(r"  |  _  |/ _` / __| '_ \| | | | ___ \ ")
            print(r"  | | | | (_| \__ \ | | | |/ /| |_/ /")
            print(r"  \_| |_/\__,_|___/_| |_|___/ \____/ ")
            print("")                 
            print("\nHashDB v{0} by @herrcore".format(VERSION))
            print("\nHashDB search shortcut key is {0}".format(PLUGIN_HOTKEY))
            print("=" * 80)
            # Load saved settings if they exist
            load_settings()
            # initialize the menu actions our plugin will inject
            self._init_action_hash_lookup()
            self._init_action_set_xor()
            self._init_action_hunt()
            self._init_action_iat_scan()
            # initialize plugin hooks
            self._init_hooks()
            return idaapi.PLUGIN_KEEP


    def run(self, arg):
        """
        This is called by IDA when the plugin is run from the plugins menu
        """
        global_settings()
        


    def term(self):
        """
        This is called by IDA when it is unloading the plugin.
        """
        # Save settings
        save_settings()
        # unhook our plugin hooks
        self._hooks.unhook()
        # unregister our actions & free their resources
        self._del_action_hash_lookup()
        self._del_action_set_xor()
        self._del_action_hunt()
        self._del_action_iat_scan()
        # done
        idaapi.msg("%s terminated...\n" % self.wanted_name)


    #--------------------------------------------------------------------------
    # IDA Actions
    #--------------------------------------------------------------------------
    ACTION_HASH_LOOKUP  = "hashdb:hash_lookup"
    ACTION_SET_XOR  = "hashdb:set_xor"
    ACTION_HUNT  = "hashdb:hunt"
    ACTION_IAT_SCAN = "hashdb:iat_scan"

    def _init_action_hash_lookup(self):
        """
        Register the hash lookup action with IDA.
        """
        action_desc = idaapi.action_desc_t( self.ACTION_HASH_LOOKUP,         # The action name.
                                            "HashDB Lookup",                     # The action text.
                                            IDACtxEntry(hash_lookup),        # The action handler.
                                            PLUGIN_HOTKEY,                  # Optional: action shortcut
                                            "Lookup hash",   # Optional: tooltip
                                            HASH_ICON
                                            )
        # register the action with IDA
        assert idaapi.register_action(action_desc), "Action registration failed"


    def _init_action_set_xor(self):
        """
        Register the set xor action with IDA.
        """
        action_desc = idaapi.action_desc_t(
            self.ACTION_SET_XOR,         # The action name.
            "HashDB set XOR key",                     # The action text.
            IDACtxEntry(set_xor_key),        # The action handler.
            None,                  # Optional: action shortcut
            "Set XOR key",   # Optional: tooltip
            XOR_ICON
        )
        # register the action with IDA
        assert idaapi.register_action(action_desc), "Action registration failed"


    def _init_action_hunt(self):
        """
        Register the hunt action with IDA.
        """
        action_desc = idaapi.action_desc_t(
            self.ACTION_HUNT,         # The action name.
            "HashDB Hunt Algorithm",                     # The action text.
            IDACtxEntry(hunt_algorithm),        # The action handler.
            None,                  # Optional: action shortcut
            "Identify algorithm based on hash",   # Optional: tooltip
            HUNT_ICON
        )
        # register the action with IDA
        assert idaapi.register_action(action_desc), "Action registration failed"


    def _init_action_iat_scan(self):
        """
        Register the scan action with IDA.
        """
        action_desc = idaapi.action_desc_t(
            self.ACTION_IAT_SCAN,         # The action name.
            "HashDB Scan IAT",                     # The action text.
            IDACtxEntry(hash_scan),        # The action handler.
            None,                  # Optional: action shortcut
            "Scan dynamic import address table hashes",   # Optional: tooltip
            SCAN_ICON
        )
        # register the action with IDA
        assert idaapi.register_action(action_desc), "Action registration failed"

    
    def _del_action_hash_lookup(self):
        idaapi.unregister_action(self.ACTION_HASH_LOOKUP)


    def _del_action_set_xor(self):
        idaapi.unregister_action(self.ACTION_SET_XOR)


    def _del_action_hunt(self):
        idaapi.unregister_action(self.ACTION_HUNT)

    def _del_action_iat_scan(self):
        idaapi.unregister_action(self.ACTION_IAT_SCAN)


    #--------------------------------------------------------------------------
    # Initialize Hooks
    #--------------------------------------------------------------------------

    def _init_hooks(self):
        """
        Install plugin hooks into IDA.
        """
        self._hooks = Hooks()
        self._hooks.ready_to_run = self._init_hexrays_hooks
        self._hooks.hook()


    def _init_hexrays_hooks(self):
        """
        Install Hex-Rays hooks (when available).
        NOTE: This is called when the ui_ready_to_run event fires.
        """
        if idaapi.init_hexrays_plugin():
            idaapi.install_hexrays_callback(self._hooks.hxe_callback)


#------------------------------------------------------------------------------
# Plugin Hooks
#------------------------------------------------------------------------------
class Hooks(idaapi.UI_Hooks):

    def finish_populating_widget_popup(self, widget, popup):
        """
        A right click menu is about to be shown. (IDA 7)
        """
        inject_actions(widget, popup, idaapi.get_widget_type(widget))
        return 0

    def hxe_callback(self, event, *args):
        """
        HexRays event callback.
        We lump this under the (UI) Hooks class for organizational reasons.
        """

        #
        # if the event callback indicates that this is a popup menu event
        # (in the hexrays window), we may want to install our menu
        # actions depending on what the cursor right clicked.
        #

        if event == idaapi.hxe_populating_popup:
            form, popup, vu = args

            idaapi.attach_action_to_popup(
                form,
                popup,
                HashDB_Plugin_t.ACTION_HASH_LOOKUP,
                "HashDB Lookup",
                idaapi.SETMENU_APP,
            )
            idaapi.attach_action_to_popup(
                form,
                popup,
                HashDB_Plugin_t.ACTION_SET_XOR,
                "HashDB set XOR key",
                idaapi.SETMENU_APP,
            )
            idaapi.attach_action_to_popup(
                form,
                popup,
                HashDB_Plugin_t.ACTION_HUNT,
                "HashDB Hunt Algorithm",
                idaapi.SETMENU_APP,
            )
            idaapi.attach_action_to_popup(
                form,
                popup,
                HashDB_Plugin_t.ACTION_IAT_SCAN,
                "HashDB Scan IAT",
                idaapi.SETMENU_APP,
            )

        # done
        return 0

#------------------------------------------------------------------------------
# Prefix Wrappers
#------------------------------------------------------------------------------
def inject_actions(form, popup, form_type):
    """
    Inject actions to popup menu(s) based on context.
    """

    #
    # disassembly window
    #

    if (form_type == idaapi.BWN_DISASMS) or (form_type == idaapi.BWN_PSEUDOCODE):
        # insert the action entry into the menu
        #

        idaapi.attach_action_to_popup(
            form,
            popup,
            HashDB_Plugin_t.ACTION_HASH_LOOKUP,
            "HashDB Lookup",
            idaapi.SETMENU_APP
        )

        idaapi.attach_action_to_popup(
            form,
            popup,
            HashDB_Plugin_t.ACTION_SET_XOR,
            "HashDB set XOR key",
            idaapi.SETMENU_APP
        )

        idaapi.attach_action_to_popup(
            form,
            popup,
            HashDB_Plugin_t.ACTION_HUNT,
            "HashDB Hunt Algorithm",
            idaapi.SETMENU_APP
        )
        if form_type != idaapi.BWN_PSEUDOCODE:
            idaapi.attach_action_to_popup(
                form,
                popup,
                HashDB_Plugin_t.ACTION_IAT_SCAN,
                "HashDB Scan IAT",
                idaapi.SETMENU_APP
            )

    # done
    return 0

#------------------------------------------------------------------------------
# IDA ctxt
#------------------------------------------------------------------------------

class IDACtxEntry(idaapi.action_handler_t):
    """
    A basic Context Menu class to utilize IDA's action handlers.
    """

    def __init__(self, action_function):
        idaapi.action_handler_t.__init__(self)
        self.action_function = action_function

    def activate(self, ctx):
        """
        Execute the embedded action_function when this context menu is invoked.
        """
        self.action_function()
        return 1

    def update(self, ctx):
        """
        Ensure the context menu is always available in IDA.
        """
        return idaapi.AST_ENABLE_ALWAYS


#--------------------------------------------------------------------------
# Plugin Registration
#--------------------------------------------------------------------------

# Global flag to ensure plugin is only initialized once
p_initialized = False

# Register IDA plugin
def PLUGIN_ENTRY():
    return HashDB_Plugin_t()
