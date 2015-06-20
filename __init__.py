from .orchestrator     import orchestrator
from .preferences      import preferences
from .server           import server
from .telnet_connect   import telnet_connect

import importlib
import logging
import sys
import threading
import time

__version__ = '0.1.0'
log = logging.getLogger ( __name__ )
log.setLevel ( logging.INFO )

maestro = orchestrator ( )

def config ( preferences_file_name ):
    maestro.config ( preferences_file_name )
    maestro.start ( )

def console ( input_string ):
    maestro.server.console ( input_string )

def set_log_file ( log_file_name ):
    log_handler = logging.FileHandler ( log_file_name )
    log_handler.setLevel ( logging.DEBUG )
    log_formatter = logging.Formatter ( fmt = '%(asctime)s %(name)s %(levelname)s %(message)s',
                                        datefmt = '%Y-%m-%d %H:%M:%S' )
    log_handler.setFormatter ( log_formatter )
    log.addHandler ( log_handler )

import atexit

def stop ( ):
    log.info ( "Closing everything for shutdown." )
    maestro.stop ( )
    maestro.join ( )

atexit.register ( stop )
