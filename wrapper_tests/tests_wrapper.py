# -*- mode: python; indent-tabs-mode: nil; py-indent-offset: 4; coding: utf-8 -*-
#
# @file   tests.py
# @author Wei-Ning Huang (AZ) <aitjcize@gmail.com>
#
# Copyright (C) 2013 - 2014 Wei-Ning Huang (AZ) <aitjcize@gmail.com>
# All Rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""Originaly from https://github.com/oxij/PyTox c-toxcore-02 branch
which itself was forked from https://github.com/aitjcize/PyTox/

Modified to work with 
"""

import hashlib
import os
import re
import sys
import unittest
import traceback
import logging
import random
import threading
import ctypes
from ctypes import *

import faulthandler
faulthandler.enable()

import warnings
warnings.filterwarnings('ignore')

try:
    import pycurl
    import certifi
    from io import BytesIO
except ImportError:
    pycurl = None

try:
    import coloredlogs
    os.environ['COLOREDLOGS_LEVEL_STYLES'] = 'spam=22;debug=28;verbose=34;notice=220;warning=202;success=118,bold;error=124;critical=background=red'
except ImportError as e:
    # logging.log(logging.DEBUG, f"coloredlogs not available:  {e}")
    coloredlogs = None

try:
    import color_runner
except ImportError as e:
    color_runner = None

import wrapper
from wrapper.tox import Tox
import wrapper.toxcore_enums_and_consts as enums
from wrapper.toxcore_enums_and_consts import TOX_CONNECTION, TOX_USER_STATUS, \
    TOX_MESSAGE_TYPE, TOX_SECRET_KEY_SIZE, TOX_FILE_CONTROL, TOX_ADDRESS_SIZE

try:
    import support_testing as ts
except ImportError:
    import wrapper_tests.support_testing as ts

try:
    from toxygen_tests import test_sound_notification
    bIS_NOT_TOXYGEN = False
except ImportError:
    bIS_NOT_TOXYGEN = True

# from PyQt5 import QtCore
if 'QtCore' in globals():
    def qt_sleep(fSec):
        if fSec > .000001: QtCore.QThread.sleep(fSec)
        QtCore.QCoreApplication.processEvents()
    sleep = qt_sleep
elif 'gevent' in globals():
    sleep = gevent.sleep
else:
    import time
    sleep = time.sleep

global LOG
LOG = logging.getLogger('TestS')
# just print to stdout so there is no complications from logging.
def LOG_ERROR(l): print('EROR+ '+l)
def LOG_WARN(l): print('WARN+ '+l)
def LOG_INFO(l): print('INFO+ '+l)
def LOG_DEBUG(l): print('DEBUG+ '+l)
def LOG_TRACE(l): pass # print('TRAC+ '+l)

ADDR_SIZE = 38 * 2
CLIENT_ID_SIZE = 32 * 2
THRESHOLD = 15

global     oTOX_OPTIONS
oTOX_OPTIONS = {}

bIS_LOCAL = 'new' in sys.argv or 'newlocal' in sys.argv

# Patch unittest for Python version <= 2.6
if not hasattr(unittest, 'skip'):
    def unittest_skip(reason):
        def _wrap1(func):
            def _wrap2(self, *args, **kwargs):
                pass
            return _wrap2
        return _wrap1
    unittest.skip = unittest_skip

def iNmapInfo(sProt, sHost, sPort, key=None, environ=None, bTest=False):
    sFile = os.path.join("/tmp", f"{sHost}.{os.getpid()}.nmap")
    if sProt in ['socks', 'socks5', 'tcp4']:
        cmd = f"nmap -Pn -n -sT -p T:{sPort} {sHost} | grep /tcp >{sFile}"
    else:
        cmd = f"nmap -Pn -n -sU -p U:{sPort} {sHost} | grep /tcp >{sFile}"
    iRet = os.system(cmd)
    LOG.debug(f"iNmapInfo cmd={cmd} {iRet}")
    if iRet != 0:
        return iRet
    assert os.path.exists(sFile), sFile
    with open(sFile, 'rt') as oFd:
        l = oFd.readlines()
    assert len(l)
    s = '\n'.join([s.strip() for s in l])
    LOG.debug(f"iNmapInfo: {s}")
    return 0

class ToxOptions():
    def __init__(self):
        self.ipv6_enabled = True
        self.udp_enabled = True
        self.proxy_type = 0
        self.proxy_host = ''
        self.proxy_port = 0
        self.start_port = 0
        self.end_port = 0
        self.tcp_port = 0
        self.savedata_type = 0  # 1=toxsave, 2=secretkey
        self.savedata_data = b''
        self.savedata_length = 0
        self.local_discovery_enabled = False
        self.dht_announcements_enabled = True
        self.hole_punching_enabled = False
        self.experimental_thread_safety = False

class App():
    def __init__(self):
        self.mode = 0
oAPP = App()

class AliceTox(Tox):

    def __init__(self, opts, app=None):

        super(AliceTox, self).__init__(opts, app=app)
        self._address = self.self_get_address()
        self.name = 'alice'
        self._opts = opts
        self._app = app

class BobTox(Tox):

    def __init__(self, opts, app=None):
        super(BobTox, self).__init__(opts, app=app)
        self._address = self.self_get_address()
        self.name = 'bob'
        self._opts = opts
        self._app = app

class BaseThread(threading.Thread):

    def __init__(self, name=None, target=None):
        if name:
            super().__init__(name=name, target=target)
        else:
            super().__init__(target=target)
        self._stop_thread = False
        self.name = name

    def stop_thread(self, timeout=-1):
        self._stop_thread = True
        if timeout < 0:
            timeout = ts.iTHREAD_TIMEOUT
        i = 0
        while i < ts.iTHREAD_JOINS:
            self.join(timeout)
            if not self.is_alive(): break
            i = i + 1
        else:
            LOG.warn(f"{self.name} BLOCKED")

class ToxIterateThread(BaseThread):

    def __init__(self, tox):
        super().__init__(name='ToxIterateThread')
        self._tox = tox

    def run(self):
        while not self._stop_thread:
            self._tox.iterate()
            sleep(self._tox.iteration_interval() / 1000)

class ToxSuite(unittest.TestCase):
    global oTOX_OARGS

    def run(self, result=None):
        """ Stop after first error """
        if not result.errors:
            super(ToxSuite, self).run(result)

    def prepare(self, *args, **kw):
        assert oTOX_OPTIONS
        assert oTOX_OARGS
        opts = oToxygenToxOptions(oTOX_OARGS)
        print(repr(opts))
        if not hasattr(self, 'alice'):
            self.alice = AliceTox(opts, app=oAPP)
            self.alice.oArgs = opts
        if not hasattr(self, 'bob'):
            self.bob = BobTox(opts, app=oAPP)
            self.bob.oArgs = opts
        if not bIS_LOCAL and not ts.bAreWeConnected():
            LOG.warn(f"prepare not local and NOT CONNECTED")
            
        self.lUdp = ts.generate_nodes(
            oArgs=oTOX_OARGS,
            nodes_count=8,
            ipv='ipv4',
            udp_not_tcp=True)

        self.lTcp = ts.generate_nodes(
            oArgs=oTOX_OARGS,
            nodes_count=8,
            ipv='ipv4',
            udp_not_tcp=False)

    def get_connection_status(self):
        # if not self.connected
        if self.bob.self_get_connection_status() == TOX_CONNECTION['NONE']:
            return False
        if self.alice.self_get_connection_status() == TOX_CONNECTION['NONE']:
            return False
        return True

    def setUp(self):
        """
        t:on_log
        """

        if not hasattr(self, 'alice') or not hasattr(self, 'bob'):
            self.prepare()
        if not hasattr(self.bob, '_main_loop'):
            self.bob._main_loop = ToxIterateThread(self.bob)
            self.bob._main_loop.start()
            # LOG.debug(f"self.bob._main_loop: {threading.enumerate()!r}")


    def tearDown(self):
        """
        t:kill
        """
        self.bob._main_loop.stop_thread()
        if False:
            self.alice.kill()
            self.bob.kill()
        del         self.bob
        del         self.alice

    def loop(self, n):
        """
        t:iterate
        t:iteration_interval
        """
        interval = self.bob.iteration_interval()
        for i in range(n):
            self.alice.iterate()
            self.bob.iterate()
            sleep(interval / 1000.0)

    def assert_connection_status(self):
        """
        t:self_get_connection_status
        """
        assert self.alice.self_get_connection_status() != TOX_CONNECTION['NONE'], \
            'ERROR: self.alice.self_get_connection_status() is ' + \
            repr(self.alice.self_get_connection_status())
        assert self.bob.self_get_connection_status() != TOX_CONNECTION['NONE'], \
            'ERROR: self.bob.self_get_connection_status() is ' + \
            repr(self.bob.self_get_connection_status())

    def call_bootstrap(self):
        LOG.debug(f"call_bootstrap")
        if oTOX_OARGS.network in ['new', 'newlocal', 'localnew']:
            ts.bootstrap_local(self.lUdp, [alice, bob])
        elif self.get_connection_status() is True:
            LOG.debug(f"call_bootstrap {self.get_connection_status()}")
        elif not ts.bAreWeConnected():
            LOG.warn('we are NOT CONNECTED ')
        elif oTOX_OARGS.proxy_port > 0:
            random.shuffle(self.lUdp)
#            LOG.debug(f"call_bootstrap ts.bootstrap_good {self.lUdp[:2]}")
            ts.bootstrap_good(self.lUdp[:iNODES], [self.alice, self.bob])
            random.shuffle(self.lTcp)
#            LOG.debug(f"call_bootstrap ts.bootstrap_tcp {self.lTcp[:8]}")
            ts.bootstrap_tcp(self.lTcp[:iNODES], [self.alice, self.bob])
        else:
            random.shuffle(self.lUdp)
#            LOG.debug(f"call_bootstrap ts.bootstrap_good {self.lUdp[:8]}")
            ts.bootstrap_good(self.lUdp[:8], [self.alice, self.bob])

    def loop_until_connected(self):
        """
        t:on_self_connection_status
        t:self_get_connection_status
        """
        i = 0
        bRet = None
        
        self.bob.mycon_status = False
        def bobs_on_self_connection_status(iTox, connection_state, *args):
            status = connection_state
            try:
                if status != TOX_CONNECTION['NONE']:
                    LOG_INFO(f"BOBS_ON_self_connection_status TRUE {status}")
                    self.bob.mycon_status = True
                else:
                    LOG_WARN(f"BOBS_ON_self_connection_status FALSE {status}")
                    self.bob.mycon_status = False
            except Exception as e:
                LOG_ERROR(f"BOBS_ON_self_connection_status {e}")
            else:
                if self.bob.self_get_connection_status() != status:
                    LOG_WARN(f"BOBS_ON_self_connection_status != {status}")

        self.alice.mycon_status = False
        def alices_on_self_connection_status(iTox, connection_state, *args):
            #FixMe connection_num
            status = connection_state
            try:
                if status != TOX_CONNECTION['NONE']:
                    LOG_INFO(f"alices_on_self_connection_status TRUE {status}")
                    self.alice.mycon_status = True
                else:
                    LOG_WARN(f"alices_on_self_connection_status FALSE {status}")
                    self.alice.mycon_status = False
            except Exception as e:
                LOG_ERROR(f"alices_on_self_connection_status error={e}")
            else:
                if self.alice.self_get_connection_status() != status:
                    LOG_WARN(f"alices_on_self_connection_status != {status}")

        try:
            self.alice.callback_self_connection_status(alices_on_self_connection_status)
            self.bob.callback_self_connection_status(bobs_on_self_connection_status)

            while i <= THRESHOLD :
                if i % 3 == 0:
                    self.call_bootstrap()
                    s = ''
                    if i == 0: s = '\n'
                    LOG.info(s+"loop_until_connected " \
                             +" #" + str(i) \
                             +" BOB=" +repr(self.bob.self_get_connection_status()) \
                             +" ALICE=" +repr(self.alice.self_get_connection_status())
                             +" BOBS=" +repr(self.bob.mycon_status) \
                             +" ALICES=" +repr(self.alice.mycon_status) \
                             )
                if (self.alice.mycon_status and self.bob.mycon_status):
                    bRet = True
                    break
                if (self.alice.self_get_connection_status() and
                    self.bob.self_get_connection_status()):
                    LOG_WARN(f"loop_until_connected disagree !=" \
                             +f' self.bob.mycon_status={self.bob.mycon_status}'
                             +f' alice.mycon_status={self.alice.mycon_status}')
                    bRet = True
                    break
                i += 1
                self.loop(100)
            else:
                bRet = False
        finally:
            self.alice.callback_self_connection_status(None)
            self.bob.callback_self_connection_status(None)
            del self.alice.mycon_status
            del self.bob.mycon_status

        if bRet or \
            ( self.bob.self_get_connection_status() != TOX_CONNECTION['NONE'] and \
              self.alice.self_get_connection_status() != TOX_CONNECTION['NONE'] ):
            LOG.info("loop_until_connected " \
                     +f" BOB={self.bob.self_get_connection_status()}" \
                     +f" ALICE={self.alice.self_get_connection_status()}")
            return True
        else:
            LOG.warn("loop_until_connected " \
                     +f" BOB={self.bob.self_get_connection_status()}" \
                     +f" ALICE={self.alice.self_get_connection_status()}")
        return bRet

    def wait_obj_attr(self, obj, attr):
        i = 0
        while i < THRESHOLD:
            if i % 3 == 0:
                self.call_bootstrap()
                LOG.debug("wait_obj_attr " +obj.name \
                          +" for " +attr \
                          +" " +str(i) \
                          +" " +repr(getattr(obj, attr)))
            if getattr(obj, attr):
                return True
            self.loop(100)
            i += 1
        else:
            LOG.error("wait_obj_attr count >= " + str(THRESHOLD)
                      + " for " +attr)
        return getattr(obj, attr)

    def wait_objs_attr(self, objs, attr):
        i = 0
        while i <= THRESHOLD:
            if i % 1 == 0:
                self.call_bootstrap()
                LOG.debug("wait_objs_attr " +repr(objs) \
                             +" for " +repr(attr) \
                             +" " +str(i))
            if all([getattr(obj, attr) for obj in objs]):
                return True
            self.loop(100)
            i += 1
        else:
            LOG.error(f"wait_obj_attr i >=  {THRESHOLD!s}")

        return all([getattr(obj, attr) for obj in objs])

    def wait_obj_attrs(self, obj, attrs):
        i = 0
        while i <= THRESHOLD:
            if i % 3 == 0:
                self.call_bootstrap()
                LOG.debug("wait_obj_attrs " +repr(obj) \
                             +" for " +repr(attrs) \
                             +" " +str(i))
            if all([getattr(obj, attr) for attr in attrs]):
                return True
            self.loop(100)
            i += 1
        else:
            LOG.warn(f"wait_obj_attrs i >= {THRESHOLD!s}")

        return all([getattr(obj, attr) for attr in attrs])

    def wait_ensure_exec(self, method, args):
        i = 0
        oRet = None
        while i <= THRESHOLD:
            if i % 3 == 0:
                self.call_bootstrap()
                LOG.debug("wait_ensure_exec " \
                             +" " +str(method)
                             +" " +str(i))
            try:
                oRet = method(*args)
                if oRet:
                    LOG.info(f"wait_ensure_exec oRet {oRet!r}")
                    return True
            except ArgumentError as e:
                #  ArgumentError('This client is currently NOT CONNECTED to the friend.')
                # dunno
                LOG.warn(f"wait_ensure_exec ArgumentError {e}")
                return False
            except Exception as e:
                LOG.warn(f"wait_ensure_exec EXCEPTION  {e}")
                return False
            sleep(3)
            i += 1
        else:
            LOG.error(f"wait_ensure_exec i >=  {1*THRESHOLD!s}")
            return False

        return oRet

    def bob_add_alice_as_friend_norequest(self):
        MSG = 'Hi, this is Bob.'
        iRet = self.bob.friend_add_norequest(self.alice._address)
        self.baid = self.bob.friend_by_public_key(self.alice._address)
        assert self.baid >= 0, self.baid
        assert self.bob.friend_exists(self.baid), "bob.friend_exists"
        assert not self.bob.friend_exists(self.baid + 1)
        assert self.baid in self.bob.self_get_friend_list()
        assert self.bob.self_get_friend_list_size() >= 1
        return iRet

    def alice_add_bob_as_friend_norequest(self):
        MSG = 'Hi Bob, this is Alice.'
        iRet = self.alice.friend_add_norequest(self.bob._address)
        self.abid = self.alice.friend_by_public_key(self.bob._address)
        assert self.abid >= 0, self.abid
        assert self.alice.friend_exists(self.abid), "alice.friend_exists"
        assert not self.alice.friend_exists(self.abid + 1)
        assert self.abid in self.alice.self_get_friend_list()
        assert self.alice.self_get_friend_list_size() >= 1
        return iRet

    def bob_just_add_alice_as_friend(self):
        """
        t:friend_add
        t:on_friend_request
        t:friend_by_public_key
        """
        MSG = 'Alice, this is Bob.'
        sSlot = 'friend_request'

        def alices_on_friend_request(iTox,
                                     public_key,
                                     message_data,
                                     message_data_size,
                                     *largs):
            # oTox = Tox(tox_pointer=iTox)
            try:
                LOG_DEBUG(f"alices_on_friend_request: " +repr(message_data))
                assert str(message_data, 'UTF-8') == MSG
            except Exception as e:
                LOG_WARN(f"alices_on_friend_request: Exception  {e}")
                # return
            else:
                self.alice.friend_added = True
                LOG_DEBUG(f"alices_on_friend_request: self.alice.friend_added = True ")

        inum = -1
        try:
            self.alice.friend_added = False
            self.alice.callback_friend_request(alices_on_friend_request)
            inum = self.bob.friend_add(self.alice._address, bytes(MSG, 'UTF-8'))
            if not inum >= 0:
                LOG.warn('bob.friend_add !>= 0 ' +repr(inum))
            if not self.wait_obj_attr(self.alice, 'friend_added'):
                return False
        except Exception as e:
            LOG.error(f"bob.friend_add EXCEPTION  {e}")
            return False

        self.baid = self.bob.friend_by_public_key(self.alice._address)
        assert self.baid >= 0, self.baid
        assert self.bob.friend_exists(self.baid)
        assert not self.bob.friend_exists(self.baid + 1)
        assert self.baid in self.bob.self_get_friend_list()
        assert self.bob.self_get_friend_list_size() >= 1
        return True

    def alice_just_add_bob_as_friend(self):
        """
        t:friend_add
        t:on_friend_request
        t:friend_by_public_key
        """
        MSG = 'Bob, this is Alice.'

        def bobs_on_friend_request(iTox,
                                     public_key,
                                     message_data,
                                     message_data_size,
                                     *largs):
            # oTox = Tox(tox_pointer=iTox)
            try:
                LOG_DEBUG(f"BOBS_ON_friend_request: " +repr(message_data))
                assert str(message_data, 'UTF-8') == MSG
                LOG_INFO(f"BOBS_ON_friend_request: friend_added = True ")
                self.bob.friend_added = True
            except Exception as e:
                LOG_WARN(f"BOBS_ON_friend_request: Exception {e}")

        inum = -1
        sSlot = 'friend_request'
        try:
            self.bob.friend_added = False
            self.bob.callback_friend_request(bobs_on_friend_request)
            inum = self.alice.friend_add(self.bob._address, bytes(MSG, 'UTF-8'))
            if not inum >= 0:
                LOG.warn('alice.friend_add !>= 0 ' +repr(inum))
            if not self.wait_obj_attr(self.bob, 'friend_added'):
                return False
        except Exception as e:
            LOG.error(f"alice.friend_add  {e}")
            return False
        finally:
            self.alice.callback_friend_message(None)
        self.abid = self.alice.friend_by_public_key(self.bob._address)
        assert self.alice.friend_exists(self.abid)
        assert self.alice.self_get_friend_list_size() >= 1
        assert self.abid in self.alice.self_get_friend_list()
        return True

    def bob_add_alice_as_friend_and_status(self):
        bRetval = self.bob_just_add_alice_as_friend()
        if not bRetval:
            LOG.error("bob_add_alice_as_friend_and_status FAILED")
            return False
        LOG.info("bob_add_alice_as_friend_and_status waiting for connections")

        #: Wait until both are online
        self.bob.friend_conn_status = False
        def bobs_on_friend_connection_status(iTox, friend_id, iStatus, *largs):
            LOG_INFO(f"BOBS_ON_friend_connection_status {friend_id} ?>=0" +repr(iStatus))
            if iStatus > 0:
                self.bob.friend_conn_status = True

        self.bob.friend_status = False
        def bobs_on_friend_status(iTox, friend_id, iStatus, *largs):
            LOG_INFO(f"BOBS_ON_friend_status {friend_id} ?>=0" +repr(iStatus))
            if iStatus > 0:
                self.bob.friend_status = True

        self.alice.friend_conn_status = False
        def alices_on_friend_connection_status(iTox, friend_id, iStatus, *largs):
            LOG_INFO(f"alices_on_friend_connection_status {friend_id} ?>=0 " +repr(iStatus))
            if iStatus > 0:
                self.alice.friend_conn_status = True

        self.alice.friend_status = False
        def alices_on_friend_status(iTox, friend_id, iStatus, *largs):
            LOG_INFO(f"alices_on_friend_status {friend_id} ?>=0 " +repr(iStatus))
            if iStatus > 0:
                self.alice.friend_status = True

        try:
            self.alice.callback_friend_connection_status(alices_on_friend_connection_status)
            self.alice.callback_friend_status(alices_on_friend_status)
            LOG.info("bob_add_alice_as_friend_and_status waiting for alice connections")
            if not self.wait_obj_attrs(self.alice,
                                            ['friend_conn_status',
                                             'friend_status']):
                return False

            self.bob.callback_friend_connection_status(bobs_on_friend_connection_status)
            self.bob.callback_friend_status(bobs_on_friend_status)

            LOG.info("bob_add_alice_as_friend_and_status waiting for bob connections")
            if not self.wait_obj_attrs(self.bob,
                                            ['friend_conn_status',
                                             'friend_status']):
                                return False
        except Exception as e:
            LOG.error(f"bob_add_alice_as_friend_and_status ERROR   {e}")
            return False
        finally:
            self.alice.callback_friend_connection_status(None)
            self.bob.callback_friend_connection_status(None)
            self.alice.callback_friend_status(None)
            self.bob.callback_friend_status(None)
        return True

    def friend_delete(self, fname, baid):
        #: Test delete friend
        assert getattr(self, fname).friend_exists(baid)
        getattr(self, fname).friend_delete(baid)
        self.loop(50)
        assert not self.bob.friend_exists(baid)

    def warn_if_no_cb(self, alice, sSlot):
        if not hasattr(alice, sSlot+'_cb') or \
          not getattr(alice, sSlot+'_cb'):
            LOG.warn(f"self.bob.{sSlot}_cb NOT EXIST")

    def warn_if_cb(self, alice, sSlot):
        if hasattr(self.bob, sSlot+'_cb') and \
          getattr(self.bob, sSlot+'_cb'):
            LOG.warn("self.bob.{sSlot}_cb EXIST")

    # tests are executed in order
    def test_tests_logging(self): # works
        with self.assertLogs('foo', level='INFO') as cm:
            logging.getLogger('foo').info('first message')
            logging.getLogger('foo.bar').error('second message')
            logging.getLogger('foo.bar.baz').debug('third message')
            self.assertEqual(cm.output, ['INFO:foo:first message',
                                         'ERROR:foo.bar:second message'])

    def test_tests_start(self): # works
        LOG.info("test_tests_start " )
        port = ts.tox_bootstrapd_port()

        assert len(self.bob._address) == 2*TOX_ADDRESS_SIZE, len(self.bob._address)
        assert len(self.alice._address) == 2*TOX_ADDRESS_SIZE, \
            len(self.alice._address)

    def test_bootstrap_local_netstat(self): # works
        """
        t:bootstrap
        """
        if oTOX_OARGS.network not in ['new', 'newlocal', 'local']:
            return

        port = ts.tox_bootstrapd_port()
        if not port:
            return
        iStatus = os.system(f"""netstat -nle4 | grep :{port}""")
        if iStatus == 0:
            LOG.info(f"bootstrap_local_netstat port {port} iStatus={iStatus}")
        else:
            LOG.warn(f"bootstrap_local_netstat NOT {port} iStatus={iStatus}")

    def test_bootstrap_local_bash(self): # works
        """
        t:bootstrap
        """
        if oTOX_OARGS.network not in ['new', 'test', 'newlocal', 'local']:
            return

        o = oTOX_OARGS.network
        sFile = bootstrap_node_info.__file__
        assert os.path.exists(sFile)
        port = ts.tox_bootstrapd_port()
        sExe = sys.executable
        iStatus = os.system(sExe +f""" {sFile} --test ipv4 localhost {port}""")
        if iStatus == 0:
            LOG.info(f"bootstrap_local_bash connected {o} iStatus={iStatus}")
        else:
            LOG.warn(f"bootstrap_local_bash NOT CONNECTED {o} iStatus={iStatus}")

    @unittest.skipIf(not bIS_LOCAL, "local test")
    def test_bootstrap_local(self): # works
        """
        t:bootstrap
        """
        # get port from /etc/tox-bootstrapd.conf 33445
        self.call_bootstrap()
        # ts.bootstrap_local(self, self.lUdp)
        i = 0
        iStatus = -1
        while i < 10:
            i = i + 1
            iStatus = self.bob.self_get_connection_status()
            if iStatus != TOX_CONNECTION['NONE']:
                break
            sleep(3)
        else:
            pass

        o1 = self.alice.self_get_dht_id()
        assert len(o1) == 64
        o2 = self.bob.self_get_dht_id()
        assert len(o2) == 64

        if o1 != o2:        
            LOG.warn(f"bootstrap_local DHT NOT same {o1} {o2} iStatus={iStatus}")
            
        iStatus = self.bob.self_get_connection_status()
        if iStatus != TOX_CONNECTION['NONE']:
            LOG.info(f"bootstrap_local connected iStatus={iStatus}")
            return True
        iStatus = self.alice.self_get_connection_status()
        if iStatus != TOX_CONNECTION['NONE']:
            LOG.info(f"bootstrap_local connected iStatus={iStatus}")
            return True
        LOG.warn(f"bootstrap_local NOT CONNECTED iStatus={iStatus}")
        return False
    
    def test_bootstrap_iNmapInfo(self): # works
        if oTOX_OARGS.network in ['new', 'newlocal', 'localnew']:
            lElts = self.lUdp
        elif oTOX_OARGS.proxy_port > 0:
            lElts = self.lTcp
        else:
            lElts = self.lUdp
        lRetval = []
        random.shuffle(lElts)
        # assert 
        ts.bootstrap_iNmapInfo(lElts, oTOX_OARGS, bIS_LOCAL, iNODES=8)

    def test_self_get_secret_key(self): # works
        """
        t:self_get_secret_key
        """
        # test_self_get_secret_key
        CRYPTO_SECRET_KEY_SIZE         = 32
        secret_key = create_string_buffer(CRYPTO_SECRET_KEY_SIZE)
        oRet0 =  self.alice.self_get_secret_key(secret_key)
        assert oRet0, repr(oRet0)
        LOG.info('test_self_get_secret_key ' +repr(oRet0))
        assert len(str(oRet0))
        del secret_key

    def test_self_get_public_keys(self): # works
        """
        t:self_get_secret_key
        t:self_get_public_key
        """

        LOG.info('test_self_get_public_keys self.alice.self_get_secret_key')
        oRet0 = self.alice.self_get_secret_key()
        assert len(oRet0)
        LOG.info('test_self_get_public_keys ' +repr(oRet0))
        oRet1 = self.alice.self_get_public_key()
        assert len(oRet1)
        LOG.info('test_self_get_public_keys ' +repr(oRet1))
        assert oRet0 != oRet1, repr(oRet0) +' != ' +repr(oRet1)

    def test_self_name(self): # works
        """
        t:self_set_name
        t:self_get_name
        t:self_get_name_size
        """
        self.alice.self_set_name('Alice')
        assert self.alice.self_get_name() == 'Alice'
        assert self.alice.self_get_name_size() == len('Alice')

    @unittest.skip('loud')
    @unittest.skipIf(bIS_NOT_TOXYGEN or oTOX_OARGS.mode == 0, 'not testing in toxygen')
    def test_sound_notification(self): # works
        """
        Plays sound notification
        :param  type of notification
        """
        from toxygen_tests import test_sound_notification
        test_sound_notification(self)

    def test_loop_until_connected(self): # works
        assert self.loop_until_connected()

    def test_self_get_udp_port(self): # works
        """
        t:self_get_udp_port
        """
        if hasattr(oTOX_OPTIONS, 'udp_port') and oTOX_OPTIONS.udp_port:
            o = self.alice.self_get_udp_port()
            LOG.info('self_get_udp_port ' +repr(o))
            assert o > 0

    def test_self_get_tcp_port(self): # works
        """
        t:self_get_tcp_port
        """
        if hasattr(oTOX_OPTIONS, 'tcp_port') and oTOX_OPTIONS.tcp_port:
            # errors if tcp_port <= 0
            o = self.alice.self_get_tcp_port()
            LOG.info('self_get_tcp_port ' +repr(o))

    def test_address(self): # works
        """
        t:self_get_address
        t:self_get_nospam
        t:self_set_nospam
        t:self_get_keys
        """
        assert len(self.alice.self_get_address()) == ADDR_SIZE
        assert len(self.bob.self_get_address()) == ADDR_SIZE

        self.alice.self_set_nospam(0x12345678)
        assert self.alice.self_get_nospam() == 0x12345678
        self.loop(50)

        if hasattr(self.alice, 'self_get_keys'):
            pk, sk = self.alice.self_get_keys()
            assert pk == self.alice.self_get_address()[:CLIENT_ID_SIZE]

    def test_get_dht_id(self): # works
        """
        t:self_get_dht_id
        """
        o1 = self.alice.self_get_dht_id()
        assert len(o1) == 64
        o2 = self.bob.self_get_dht_id()
        assert len(o2) == 64

    def test_bob_assert_connection_status(self): # works
        if self.bob.self_get_connection_status() == TOX_CONNECTION['NONE']:
            RuntimeError("ERROR: NOT CONNECTED " \
                         +repr(self.bob.self_get_connection_status()))

    def test_alice_assert_connection_status(self): # works
        if self.alice.self_get_connection_status() == TOX_CONNECTION['NONE']:
            RuntimeError("ERROR: NOT CONNECTED " \
                         +repr(self.alice.self_get_connection_status()))

    def test_status_message(self): # works
        MSG = 'Happy'

        self.alice.self_set_status_message(MSG)
        self.loop(50)
        assert self.alice.self_get_status_message() == MSG, \
            self.alice.self_get_status_message() +' is not ' +MSG
        assert self.alice.self_get_status_message_size() == len(MSG)

    def test_bob_add_alice_as_friend_norequest(self): # works
        iRet = self.bob_add_alice_as_friend_norequest()
        if iRet < 0:
            raise RuntimeError(f"bob_add_alice_as_friend_norequest {iRet}")
        #: Test last online
        assert self.bob.friend_get_last_online(self.baid) is not None
        self.bob.friend_delete(self.baid)

    def test_alice_just_add_bob_as_friend_norequest(self): # works
        iRet = self.alice_add_bob_as_friend_norequest()
        if iRet < 0:
            raise RuntimeError(f"bob_add_alice_as_friend_norequest {iRet}")
        #: Test last online
        assert self.alice.friend_get_last_online(self.abid) is not None
        self.alice.friend_delete(self.abid)

    @unittest.skipIf(bIS_LOCAL, "local test")
    def test_bob_just_add_alice_as_friend(self): # works
        assert self.bob_just_add_alice_as_friend()
        #: Test last online
        assert self.bob.friend_get_last_online(self.baid) is not None
        self.bob.friend_delete(self.baid)

    @unittest.skipIf(bIS_LOCAL, "local test")
    def test_alice_just_add_bob_as_friend(self): # works
        assert self.alice_just_add_bob_as_friend()
        #: Test last online
        assert self.alice.friend_get_last_online(self.abid) is not None
        self.alice.friend_delete(self.abid)

    def test_both_just_add_as_friend(self): # works
        LOG_DEBUG(f"bIS_LOCAL={bIS_LOCAL} oTOX_OARGS.bIS_LOCAL={oTOX_OARGS.bIS_LOCAL}")
        if oTOX_OARGS.bIS_LOCAL:
            iRet = self.bob_add_alice_as_friend_norequest()
            if iRet < 0:
                raise RuntimeError(f"bob_add_alice_as_friend_norequest {iRet}")
            iRet = self.alice_add_bob_as_friend_norequest()
            if iRet < 0:
                raise RuntimeError(f"alice_add_bob_as_friend_norequest {iRet}")
        else:
            assert self.bob_just_add_alice_as_friend()
            assert self.alice_just_add_bob_as_friend()

        #: Test last online
        assert self.alice.friend_get_last_online(self.abid) is not None
        assert self.bob.friend_get_last_online(self.baid) is not None

        self.bob.friend_delete(self.baid)
        self.alice.friend_delete(self.abid)

    @unittest.skip('unfinished?')
    def test_bob_add_alice_as_friend_and_status(self):
        assert self.bob_add_alice_as_friend_and_status()
        self.bob.friend_delete(self.baid)

    @unittest.skip('fails')
    def test_on_friend_status_message(self):
        """
        t:self_set_status_message
        t:self_get_status_message
        t:self_get_status_message_size
        t:friend_set_status_message
        t:friend_get_status_message
        t:friend_get_status_message_size
        t:on_friend_status_message
        """
        MSG = 'Happy'
        sSlot = 'friend_status_message'
        
        if oTOX_OARGS.bIS_LOCAL:
            iRet = self.bob_add_alice_as_friend_norequest()
            if iRet < 0:
                raise RuntimeError(f"bob_add_alice_as_friend_norequest {iRet}")
        else:
            assert self.bob_just_add_alice_as_friend()

        setattr(self.bob, sSlot, False)
        def bob_on_friend_status_message(iTox, friend_id, new_status_message, new_status_size, *largs):
            setattr(self.bob, sSlot, True)
            try:
                assert str(new_status_message, 'UTF-8') == MSG
                assert friend_id == self.baid
            except Exception as e:
                LOG_ERROR("BOB_ON_friend_status_message EXCEPTION "           +str(e))
            else:
                LOG_INFO("BOB_ON_friend_status_message " +repr(friend_id) \
                      +repr(new_status_message))

        try:
            self.bob.callback_friend_status_message(bob_on_friend_status_message)
            self.warn_if_no_cb(self.bob, sSlot)
            self.alice.self_set_status_message(MSG)
            assert self.wait_obj_attr(self.bob, sSlot)

            assert self.bob.friend_get_status_message(self.baid) == MSG
            assert self.bob.friend_get_status_message_size(self.baid) == len(MSG)

        except AssertionError as e:
            raise
        except Exception as e:
            LOG.error(f"test_on_friend_status_message EXCEPTION  {e}")
            raise
        finally:
            self.alice.callback_friend_status(None)

        self.bob.friend_delete(self.baid)

    @unittest.skip('fails')
    def test_friend(self):
        """
        t:friend_delete
        t:friend_exists
        t:friend_get_public_key
        t:self_get_friend_list
        t:self_get_friend_list_size
        t:self_set_name
        t:friend_get_name
        t:friend_get_name_size
        t:on_friend_name
        """

        #: Test friend request
        if oTOX_OARGS.bIS_LOCAL:
            iRet = self.bob_add_alice_as_friend_norequest()
            if iRet < 0:
                raise RuntimeError(f"bob_add_alice_as_friend_norequest {iRet}")
        else:
            assert self.bob_just_add_alice_as_friend()

        assert self.bob.friend_get_public_key(self.baid) == \
            self.alice.self_get_address()[:CLIENT_ID_SIZE]

        LOG.info("test_friend alice_just_add_bob_as_friend ")
        #? assert self.alice_just_add_bob_as_friend()
        assert self.alice_add_bob_as_friend_norequest() >= 0

        #: Test friend_get_public_key
        assert self.alice.friend_get_public_key(self.abid) == \
            self.bob.self_get_address()[:CLIENT_ID_SIZE]

        self.bob.friend_delete(self.baid)
        self.alice.friend_delete(self.abid)

    @unittest.skip('fails')
    @unittest.skipIf(not bIS_LOCAL and not ts.bAreWeConnected(), 'NOT CONNECTED')
    def test_user_status(self):
        """
        t:self_get_status
        t:self_set_status
        t:friend_get_status
        t:friend_get_status
        t:on_friend_status
        """
        sSlot = 'friend_status'
        if oTOX_OARGS.bIS_LOCAL:
            iRet = self.bob_add_alice_as_friend_norequest()
            if iRet < 0:
                raise RuntimeError(f"bob_add_alice_as_friend_norequest {iRet}")
        else:
            assert self.bob_just_add_alice_as_friend()

        sSTATUS = TOX_USER_STATUS['AWAY']
        setattr(self.bob, sSlot, False)
        def bobs_on_friend_set_status(iTox, friend_id, new_status, *largs):
            LOG_INFO(f"BOBS_ON_friend_set_status " \
                     +repr(friend_id) +repr(new_status))
            try:
                assert friend_id == self.baid
                assert new_status == sSTATUS
            except Exception as e:
                LOG_WARN(f"BOBS_ON_friend_set_status EXCEPTION {e}")
            setattr(self.bob, sSlot, True)

        try:
            assert self.loop_until_connected()
            if not self.get_connection_status():
                LOG.warn(f"test_user_status NOT CONNECTED")
                raise RuntimeError("not connected")

            self.bob.callback_friend_status(bobs_on_friend_set_status)
            self.alice.self_set_status(sSTATUS)
            self.warn_if_no_cb(self.bob, sSlot)
            assert self.wait_obj_attr(self.bob, sSlot)
            # wait_obj_attr count >= 15 for friend_status

        except AssertionError as e:
            raise
        except Exception as e:
            LOG.error(f"test_user_status EXCEPTION  {e}")
            raise
        finally:
            self.bob.callback_friend_status(None)
            self.warn_if_cb(self.bob, sSlot)

        self.alice.self_set_status(TOX_USER_STATUS['NONE'])
        assert self.alice.self_get_status() == TOX_USER_STATUS['NONE']
        assert self.bob.friend_get_status(self.baid) == TOX_USER_STATUS['NONE']

        self.bob.friend_delete(self.baid)

    @unittest.skip('crashes')
    def test_connection_status(self):
        """
        t:friend_assert_connection_status
        t:on_friend_connection_status
        """
        LOG.info("test_connection_status ")
        if oTOX_OARGS.bIS_LOCAL:
            assert self.bob_add_alice_as_friend_norequest() >= 0
        else:
            assert self.bob_just_add_alice_as_friend()

        sSlot = 'friend_connection_status'
        def bobs_on_friend_connection_status(iTox, friend_id, iStatus, *largs):
            setattr(self.bob, sSlot, True)
            LOG_INFO(f"BOBS_ON_friend_connection_status " +repr(iStatus))
            try:
                assert friend_id == self.baid
            except Exception as e:
                LOG.error(f"BOBS_ON_friend_connection_status ERROR  {e}")

        opts = oToxygenToxOptions(oTOX_OARGS)
        try:
            setattr(self.bob, sSlot, True)
            self.bob.callback_friend_connection_status(bobs_on_friend_connection_status)

            LOG.info("test_connection_status killing alice")
            self.alice.kill() #! bang
            LOG.info("test_connection_status making alice")
            self.alice = Tox(opts, app=oAPP)
            LOG.info("test_connection_status maked alice")

            assert self.wait_obj_attr(self.bob, sSlot)
        except AssertionError as e:
            raise
        except Exception as e:
            LOG.error(f"BOBS_ON_friend_connection_status  {e}")
            raise
        finally:
            self.bob.callback_friend_connection_status(None)

        #? assert self.bob.friend_assert_connection_status(self.aid) is False
        self.bob.friend_delete(self.baid)

    @unittest.skip('fails')
    def test_friend_name(self):
        """
        t:self_set_name
        t:friend_get_name
        t:friend_get_name_size
        t:on_friend_name
        """

        sSlot= 'friend_name'
        #: Test friend request

        assert self.bob_just_add_alice_as_friend()

        AID = self.baid
        #: Test friend name
        NEWNAME = 'Jenny'
        
        setattr(self.bob, sSlot, False)
        def bobs_on_friend_name(iTox, fid, newname, iNameSize, *largs):
            LOG_INFO(sSlot +" " +repr(fid))
            try:
                assert fid == AID
                assert str(newname, 'UTF-8') == NEWNAME
            except Exception as e:
                LOG.error(f"BOBS_ON_friend_name EXCEPTION {e}")
            setattr(self.bob, sSlot, True)

        try:
            assert self.loop_until_connected()

            self.bob.callback_friend_name(bobs_on_friend_name)
            self.alice.self_set_name(NEWNAME)
            assert self.wait_obj_attr(self.bob, sSlot)
            self.warn_if_no_cb(self.bob, sSlot)

            assert self.bob.friend_get_name(self.baid) == NEWNAME
            assert self.bob.friend_get_name_size(self.baid) == len(NEWNAME)
        except AssertionError as e:
            raise
        except Exception as e:
            LOG.error(f"test_friend EXCEPTION  {e}")
            raise
        finally:
            self.bob.callback_friend_name(None)
            if hasattr(self.bob, sSlot + '_cb') and \
               getattr(self.bob, sSlot + '_cb'):
                LOG.warn(sSlot + ' EXISTS')

        self.bob.friend_delete(self.baid)

    @unittest.skip('fails')
    # wait_ensure_exec ArgumentError This client is currently not connected to the friend.
    def test_friend_message(self):
        """
        t:on_friend_action
        t:on_friend_message
        t:friend_send_message
        """

       #: Test message
        MSG = 'Hi, Bob!'
        sSlot = 'friend_message'

        if oTOX_OARGS.bIS_LOCAL:
            assert self.bob_add_alice_as_friend_norequest() >= 0
        else:
            assert self.bob_just_add_alice_as_friend()
        if oTOX_OARGS.bIS_LOCAL:
            assert self.alice_add_bob_as_friend_norequest() >= 0
        else:
            # times out
            assert self.alice_just_add_bob_as_friend()

        BID = self.baid

        setattr(self.bob, sSlot, False)
        def alices_on_friend_message(self, fid, msg_type, message, iSize, *largs):
            try:
                assert fid == BID
                assert msg_type == TOX_MESSAGE_TYPE['NORMAL']
                assert str(message, 'UTF-8') == MSG
            except Exception as e:
                LOG_ERROR(f"alices_on_friend_message EXCEPTION {e}")
            else:
                LOG_INFO(f"alices_on_friend_message " +repr(message))
            setattr(self.bob, sSlot, True)

        try:
            assert self.loop_until_connected()
            if not self.get_connection_status():
                LOG.warn(f"test_friend_message NOT CONNECTED")
                raise RuntimeError("not connected")

            self.alice.callback_friend_message(alices_on_friend_message)
            self.warn_if_no_cb(self.alice, sSlot)
            if True:
                # dunno
                assert self.bob.friend_send_message(
                    self.baid,
                    TOX_MESSAGE_TYPE['NORMAL'],
                    bytes(MSG, 'UTF-8'))
            else:
                assert self.wait_ensure_exec(self.bob.friend_send_message,
                                             [self.baid,
                                              TOX_MESSAGE_TYPE['NORMAL'],
                                              bytes(MSG, 'UTF-8')])
            assert self.wait_obj_attr(self.alice, sSlot)
        except ArgumentError as e:
            #  ArgumentError('This client is currently NOT CONNECTED to the friend.')
            # dunno
            LOG.error(f"test_friend_message  {e}")
        except AssertionError as e:
            LOG.warn(f"test_friend_message  {e}")
            raise
        except Exception as e:
            LOG.error(f"test_friend_message  {e}")
            raise
        finally:
            self.alice.callback_friend_message(None)
            self.warn_if_cb(self.alice, sSlot)
        self.bob.friend_delete(self.baid)
        self.alice.friend_delete(self.abid)

    @unittest.skip('fails')
    def test_friend_action(self):
        """
        t:on_friend_action
        t:on_friend_message
        t:friend_send_message
        """

        if oTOX_OARGS.bIS_LOCAL:
            iRet = self.bob_add_alice_as_friend_norequest()
            if iRet < 0:
                raise RuntimeError(f"bob_add_alice_as_friend_norequest {iRet}")
        else:
            assert self.bob_just_add_alice_as_friend()
        if True:
            # times out
            assert self.alice_just_add_bob_as_friend()
        else:
            assert self.alice_add_bob_as_friend_norequest() >= 0

        BID = self.baid
        #: Test action
        ACTION = 'Kick'
        def alices_on_friend_action(iTox, fid, msg_type, action, *largs):
            LOG_DEBUG(f"alices_on_friend_action")
            assert fid == BID
            assert msg_type == TOX_MESSAGE_TYPE['ACTION']
            assert action == ACTION
            sSlot = 'friend_read_action'
            setattr(self.bob, sSlot, True)

        def alices_on_read_reciept(iTox, fid, msg_id, *largs):
            LOG_DEBUG(f"alices_on_read_reciept")
            sSlot = 'friend_read_receipt'
            setattr(self.alice, sSlot, True)
            try:
                assert fid == BID
            except Exception as e:
                LOG_ERROR(f"alices_on_read_reciept {e}")

        try:
            assert self.loop_until_connected()
            if not self.get_connection_status():
                LOG.warn(f"test_friend_message NOT CONNECTED")
                raise RuntimeError("not connected")

            sSlot = 'friend_read_action'
            setattr(self.bob, sSlot, False)
            sSlot = 'friend_read_receipt'
            setattr(self.alice, sSlot, False)
            
            self.alice.callback_friend_read_receipt(alices_on_read_reciept) #was alices_on_friend_action
            assert self.wait_ensure_exec(self.bob.friend_send_message,
                                  (self.baid,
                                   TOX_MESSAGE_TYPE['ACTION'],
                                   bytes(ACTION, 'UTF-8')))
            sSlot = 'friend_read_receipt'
            assert self.wait_obj_attr(self.alice, sSlot)
        except AssertionError as e:
            raise
        except ArgumentError as e:
            #  ArgumentError('This client is currently NOT CONNECTED to the friend.')
            # dunno
            LOG.warn(f"test_friend_action  {e}")
        except Exception as e:
            LOG.error(f"test_friend_action  {e}")
            raise
        finally:
            self.alice.callback_friend_read_receipt(None)

        self.bob.friend_delete(self.baid)
        self.alice.friend_delete(self.abid)

    @unittest.skip('fails')
    def test_alice_typing_status(self):
        """
        t:on_friend_read_receipt
        t:on_friend_typing
        t:self_set_typing
        t:friend_get_typing
        t:friend_get_last_online
        """

        # works
        LOG.info("test_typing_status bob adding alice")
        assert self.bob_just_add_alice_as_friend()
        self.baid = self.bob.friend_by_public_key(self.alice._address)
        assert self.bob.friend_exists(self.baid)
        AID = self.baid

        sSlot = 'friend_typing'
        LOG.info("test_typing_status alice adding bob")
        if False:
            # times out
            assert self.alice_just_add_bob_as_friend()
        else:
            assert self.alice_add_bob_as_friend_norequest() >= 0
        self.abid = self.alice.friend_by_public_key(self.bob._address)
        assert self.alice.friend_exists(self.abid)

        #: Test typing status
        def bob_on_friend_typing(iTox, fid, is_typing, *largs):
            setattr(self.bob, sSlot, True)
            try:
                assert fid == AID
                assert is_typing is True
                assert self.bob.friend_get_typing(fid) is True
            except Exception as e:
                LOG.error(f"BOB_ON_friend_typing  {e!s}")
                raise
            else:
                LOG_INFO(f"BOB_ON_friend_typing" + str(fid))

        try:
            assert self.loop_until_connected()
            if not self.get_connection_status():
                LOG.warn(f"test_friend_message NOT CONNECTED")
                if oTOX_OARGS.bIS_LOCAL: return
                raise RuntimeError("not connected")

            setattr(self.bob, sSlot, False)
            self.bob.callback_friend_typing(bob_on_friend_typing)
            self.alice.self_set_typing(self.abid, True)
            assert self.wait_obj_attr(self.bob, sSlot)
            if not hasattr(self.bob, sSlot+'_cb') or \
               not getattr(self.bob, sSlot+'_cb'):
                LOG.warn(f"self.bob.{sSlot}_cb NOT EXIST")
        except AssertionError as e:
            raise
        except Exception as e:
            LOG.error(f"test_alice_typing_status error={e}")
            raise
        finally:
            self.bob.callback_friend_typing(None)
        self.bob.friend_delete(self.baid)
        self.alice.friend_delete(self.abid)

    @unittest.skip('unfinished')
    def test_file_transfer(self): # unfinished
        """
        t:file_send
        t:file_send_chunk
        t:file_control
        t:file_seek
        t:file_get_file_id
        t:on_file_recv
        t:on_file_recv_control
        t:on_file_recv_chunk
        t:on_file_chunk_request
        """

        self.bob_add_alice_as_friend_norequest()
        self.baid = self.bob.friend_by_public_key(self.alice._address)
        BID = self.baid
        
        FRIEND_NUMBER = self.baid
        FILE_NUMBER = 1
        FILE = os.urandom(1024 * 1024)
        FILE_NAME = b"/tmp/test.bin"
        if not os.path.exists(FILE_NAME):
            with open(FILE_NAME, 'wb') as oFd:
                oFd.write(FILE)
        FILE_SIZE = len(FILE)
        OFFSET = 567

        m = hashlib.md5()
        m.update(FILE[OFFSET:])
        FILE_DIGEST = m.hexdigest()

        CONTEXT = { 'FILE': bytes(), 'RECEIVED': 0, 'START': False, 'SENT': 0 }

        def alice_on_file_recv(iTox, fid, file_number, kind, size, filename):
            LOG_DEBUG(f"ALICE_ON_file_recv fid={fid} {file_number}")
            try:
                assert fid == BID
                assert size == FILE_SIZE
                assert filename == FILE_NAME
                retv = self.alice.file_seek(fid, file_number, OFFSET)
                assert retv is True
                self.alice.file_control(fid, file_number, TOX_FILE_CONTROL['RESUME'])
            except Exception as e:
                LOG_ERROR(f"ALICE_ON_file_recv  {e!s}")
            else:
                LOG_INFO(f"ALICE_ON_file_recv " + str(fid))

        def alice_on_file_recv_control(iTox, fid, file_number, control, *largs):
            # TOX_FILE_CONTROL = {    'RESUME': 0,    'PAUSE': 1,    'CANCEL': 2,}
            LOG_DEBUG(f"ALICE_ON_file_recv_control fid={fid} {file_number} {control}")
            try:
                assert fid == BID
                assert FILE_NUMBER == file_number
                if control == Tox.FILE_CONTROL_FINISHED:
        #         assert CONTEXT['RECEIVED'] == FILE_SIZE
        #         m = hashlib.md5()
        #         m.update(CONTEXT['FILE'])
        #         assert m.hexdigest() == FILE_DIGEST
                    self.alice.completed = True
            except Exception as e:
                LOG_ERROR(f"ALICE_ON_file_recv  {e!s}")
            else:
                LOG_INFO(f"ALICE_ON_file_recv " + str(fid))

        self.alice.completed = False
        def alice_on_file_recv_chunk(iTox, fid, file_number, position, iNumBytes, *largs):
            LOG_DEBUG(f"ALICE_ON_file_recv_chunk {fid} {file_number}")
            # FixMe - use file_number and iNumBytes to get data?
            data = ''
            try:
                assert fid == BID
                if data is None:
                    assert CONTEXT['RECEIVED'] == (FILE_SIZE - OFFSET)
                    m = hashlib.md5()
                    m.update(CONTEXT['FILE'])
                    assert m.hexdigest() == FILE_DIGEST
                    self.alice.completed = True
                    self.alice.file_control(fid, file_number, TOX_FILE_CONTROL['CANCEL'])
                    return
                
                CONTEXT['FILE'] += data
                CONTEXT['RECEIVED'] += len(data)
                # if CONTEXT['RECEIVED'] < FILE_SIZE:
                #    assert self.file_data_remaining(
                #        fid, file_number, 1) == FILE_SIZE - CONTEXT['RECEIVED']
            except Exception as e:
                LOG_ERROR(f"ALICE_ON_file_recv_chunk {e!s}")
            else:
                LOG_INFO(f"ALICE_ON_file_recv_chunk {fid}")

        # AliceTox.on_file_send_request = on_file_send_request
        # AliceTox.on_file_control = on_file_control
        # AliceTox.on_file_data = on_file_data

        LOG.info(f"test_file_transfer: baid={self.baid}")
        try:
            self.alice.callback_file_recv(alice_on_file_recv)
            self.alice.callback_file_recv_control(alice_on_file_recv_control)
            self.alice.callback_file_recv_chunk(alice_on_file_recv_chunk)

            self.bob.completed = False
            def bob_on_file_recv_control2(iTox, fid, file_number, control):
                LOG_DEBUG(f"BOB_ON_file_recv_control2 {fid} {file_number} control={control}")
                if control == TOX_FILE_CONTROL['RESUME']:
                    CONTEXT['START'] = True
                elif control == TOX_FILE_CONTROL['CANCEL']:
                    self.bob.completed = True
                    pass

            def bob_on_file_chunk_request(iTox, fid, file_number, position, length, *largs):
                LOG_DEBUG(f"BOB_ON_file_chunk_request {fid} {file_number}")
                if length == 0:
                    return
                data = FILE[position:(position + length)]
                self.bob.file_send_chunk(fid, file_number, position, data)
                
            sSlot = 'file_recv_control'
            self.bob.callback_file_recv_control(bob_on_file_recv_control2)
            self.bob.callback_file_chunk_request(bob_on_file_chunk_request)

            # was FILE_ID = FILE_NAME
            FILE_ID = 32*'1' #
            FILE_NAME = b'test.in'
            
            assert self.loop_until_connected()
            if not self.get_connection_status():
                LOG.warn(f"test_file_transfer NOT CONNECTED")
                raise RuntimeError("not connected")
                
            i = 0
            iKind = 0
            while i < 2:
                i += 1
                try:
                    FN = self.bob.file_send(self.baid, iKind, FILE_SIZE, FILE_ID, FILE_NAME)
                    LOG.info(f"test_file_transfer bob.file_send {FN}")
                except ArgumentError as e:
                    LOG.debug(f"test_file_transfer bob.file_send {e} {i}")
                    # ctypes.ArgumentError: This client is currently not connected to the friend.
                    raise
                else:
                    break
                self.loop(100)
                sleep(1)
            else:
                LOG.error(f"test_file_transfer bob.file_send 2")
                raise RuntimeError(f"test_file_transfer bob.file_send {THRESHOLD // 2}")
            
            # UINT32_MAX
            FID = self.bob.file_get_file_id(self.baid, FN)
            hexFID = "".join([hex(ord(c))[2:].zfill(2) for c in FILE_NAME])
            assert FID.startswith(hexFID.upper())

            if not self.wait_objs_attr([self.alice, self.bob], 'completed'):
                LOG.warn(f"test_file_transfer not callbacks")
                return False

        except (ArgumentError, ValueError,) as e:
               # ValueError: non-hexadecimal number found in fromhex() arg at position 0
               LOG_ERROR(f"test_file_transfer: {e}")
               raise
           
        except Exception as e:
               LOG_ERROR(f"test_file_transfer:: {e}")
               LOG_DEBUG('\n' + traceback.format_exc())
               raise
                
        finally:
            self.alice.callback_file_recv(None)
            self.alice.callback_file_recv_control(None)
            self.alice.callback_file_recv_chunk(None)
            self.bob.callback_file_recv_control(None)
            self.bob.callback_file_chunk_request(None)

        LOG_INFO(f"test_file_transfer:: self.wait_objs_attr completed")

    def test_tox_savedata(self): # works sorta
        # but "{addr} != {self.alice.self_get_address()}"
        """
        t:get_savedata_size
        t:get_savedata
        """

        assert self.alice.get_savedata_size() > 0
        data = self.alice.get_savedata()
        assert data is not None
        addr = self.alice.self_get_address()
        # self._address
        
        try:
            self.alice._kill_toxav()
            self.alice._kill_tox()
            self.alice.kill()
        except: pass
            
        oArgs = oTOX_OARGS
        opts = oToxygenToxOptions(oArgs)
        opts.savedata_data = data
        opts.savedata_length = len(data)

        self.alice = Tox(tox_options=opts)
        if addr != self.alice.self_get_address():
            LOG.warn("test_tox_savedata " +
                      f"{addr} != {self.alice.self_get_address()}")
        else:
            LOG.info("passed test_tox_savedata")
        
def vOargsToxPreamble(oArgs, Tox, ToxTest):

    ts.vSetupLogging()
    
    methods = set([x for x in dir(Tox) if not x[0].isupper()
                   and not x[0] == '_'])
    docs = "".join([getattr(ToxTest, x).__doc__ for x in dir(ToxTest)
                    if getattr(ToxTest, x).__doc__ is not None])

    tested = set(re.findall(r't:(.*?)\n', docs))
    not_tested = methods.difference(tested)

    logging.info('Test Coverage: %.2f%%' % (len(tested) * 100.0 / len(methods)))
    if len(not_tested):
        logging.info('Not tested:\n    %s' % "\n    ".join(sorted(list(not_tested))))

###

def iMain(oArgs):
    failfast=True

    ts.vOargsToxPreamble(oArgs, Tox, ToxSuite)
    # https://stackoverflow.com/questions/35930811/how-to-sort-unittest-testcases-properly/35930812#35930812
    cases = ts.suiteFactory(*ts.caseFactory([ToxSuite]))
    if color_runner:
        runner = color_runner.runner.TextTestRunner(verbosity=2,failfast=failfast)
    else:
        runner = unittest.TextTestRunner(verbosity=2,failfast=failfast)
    runner.run(cases)

def oToxygenToxOptions(oArgs):
    data = None
    tox_options = wrapper.tox.Tox.options_new()
    if oArgs.proxy_type:
        tox_options.contents.proxy_type = int(oArgs.proxy_type)
        tox_options.contents.proxy_host = bytes(oArgs.proxy_host, 'UTF-8')
        tox_options.contents.proxy_port = int(oArgs.proxy_port)
        tox_options.contents.udp_enabled = False
    else:
        tox_options.contents.udp_enabled = oArgs.udp_enabled
    if not os.path.exists('/proc/sys/net/ipv6'):
        oArgs.ipv6_enabled = False

    tox_options.contents.tcp_port = int(oArgs.tcp_port)

    # overrides
    tox_options.contents.local_discovery_enabled = False
    tox_options.contents.dht_announcements_enabled = True
    tox_options.contents.hole_punching_enabled = False
    tox_options.contents.experimental_thread_safety = False
    # REQUIRED!!
    if oArgs.ipv6_enabled and not os.path.exists('/proc/sys/net/ipv6'):
        LOG.warn('Disabling IPV6 because /proc/sys/net/ipv6 does not exist' + repr(oArgs.ipv6_enabled))
        tox_options.contents.ipv6_enabled = False
    else:
        tox_options.contents.ipv6_enabled = bool(oArgs.ipv6_enabled)

    if data:  # load existing profile
        tox_options.contents.savedata_type = enums.TOX_SAVEDATA_TYPE['TOX_SAVE']
        tox_options.contents.savedata_data = c_char_p(data)
        tox_options.contents.savedata_length = len(data)
    else:  # create new profile
        tox_options.contents.savedata_type = enums.TOX_SAVEDATA_TYPE['NONE']
        tox_options.contents.savedata_data = None
        tox_options.contents.savedata_length = 0

    #? tox_options.contents.log_callback = LOG
    if tox_options._options_pointer:
        # LOG.debug("Adding logging to tox_options._options_pointer ")
        ts.vAddLoggerCallback(tox_options, ts.on_log)
    else:
        LOG.warn("No tox_options._options_pointer " +repr(tox_options._options_pointer))

    return tox_options

def oArgparse(lArgv):
    parser = ts.oMainArgparser()
    parser.add_argument('profile', type=str, nargs='?', default=None,
                        help='Path to Tox profile')
    oArgs = parser.parse_args(lArgv)

    for key in ts.lBOOLEANS:
        if key not in oArgs: continue
        val = getattr(oArgs, key)
        setattr(oArgs, key, bool(val))

    if hasattr(oArgs, 'sleep'):
        if oArgs.sleep == 'qt':
            pass # broken or gevent.sleep(idle_period)
        elif oArgs.sleep == 'gevent':
            pass # broken or gevent.sleep(idle_period)
        else:
            oArgs.sleep = 'time'

    return oArgs

def main(lArgs=None):
    global     oTOX_OARGS
    if lArgs is None: lArgs = []
    print(lArgs)
    oArgs = oArgparse(lArgs)
    global bIS_LOCAL
    bIS_LOCAL = oArgs.network in ['newlocal', 'localnew', 'local']
    oTOX_OARGS = oArgs
    setattr(oTOX_OARGS, 'bIS_LOCAL', bIS_LOCAL)
    print(oArgs)
    bIS_LOCAL = True
    setattr(oTOX_OARGS, 'bIS_LOCAL', bIS_LOCAL)
    # oTOX_OPTIONS = ToxOptions()
    global oTOX_OPTIONS
    oTOX_OPTIONS = oToxygenToxOptions(oArgs)
    if coloredlogs:
        # https://pypi.org/project/coloredlogs/
        coloredlogs.install(level=oArgs.loglevel,
                        logger=LOG,
                        # %(asctime)s,%(msecs)03d %(hostname)s [%(process)d]
                        fmt='%(name)s %(levelname)s %(message)s'
                        )
    else:
        logging.basicConfig(level=oArgs.loglevel) #  logging.INFO

    return iMain(oArgs)

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

# Ran 34 tests in 86.589s OK (skipped=12)
