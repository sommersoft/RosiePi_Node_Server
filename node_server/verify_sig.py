# The MIT License (MIT)
#
# Copyright (c) 2020 Michael Schroeder
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

import hmac
import json
import logging
import pathlib
import re

from base64 import b64decode
from configparser import ConfigParser
from flask.logging import default_handler
from getpass import getuser
from hashlib import sha256
from socket import gethostname

_STATIC_CONFIG_FILE = pathlib.Path('/etc/opt/physaci_sub/conf.ini')

logger = logging.getLogger()
logger.addHandler(default_handler)

class PhysaCIConfig():
    """ Container class for holding local configuration results.
    """
    def __init__(self):
        self.config = ConfigParser(allow_no_value=True, default_section='local')
        read_config = self.config.read(_STATIC_CONFIG_FILE)
        if not read_config:
            logging.warning(
                'Failed to read physaCI subscription info. '
                f'User: {getuser()}'
            )
            return

        self.config_location = self.config.get('local', 'config_file',
                                               fallback=_STATIC_CONFIG_FILE)
        if self.config_location != _STATIC_CONFIG_FILE.resolve():
            alt_conf_file = pathlib.Path(self.config_location)
            read_config = self.config.read([_STATIC_CONFIG_FILE, alt_conf_file],
                                           default_section='local')

    @property
    def node_sig_key(self):
        return self.config.get('node_server','node_sig_key')

class VerifySig(PhysaCIConfig):
    """ Verifies HTTP Signatures sent with requests. Uses information
        generated by the physaci_subscriber program.
    """
    def __init__(self):
        super().__init__()

    def __parse_sig_elements(self, signature):
        """ Parses a signature string into its separate elements.

        :param: list signature: The value of the Authorization Signature
                                header.

        :returns: dict: Key/value pairs of the signature string.
        """
        sig_elements = {}
        for element in signature:
            element_re = re.search(r'^(.+)\=\"(.+)"', element)
            if element_re:
                key = element_re.group(1)
                value = element_re.group(2)
                sig_elements[key] = value

        return sig_elements

    def verify_signature(self, request):
        """ Verifies a signature message, using the header info, content,
            and the current config information.

        :param: request: The request object containing headers and content

        :returns: True/False if signature is valid.
        """

        request_sig = request.headers.get('Authorization', '')
        if not request_sig.startswith('Signature'):
            logger.warning('Authorization header not an HTTP Signature.')
            return False

        sig_elements = self.__parse_sig_elements(request_sig[10:].split(','))

        # verify desired node's hostname
        if sig_elements.get('keyID') != gethostname():
            logger.warning(
                'Signature has missing or incorrect keyID. '
                f'Supplied keyID: {sig_elements.get("keyID")}, '
                f'Local hostname: {gethostname()}'
            )
            return False

        # verify desired algorithm
        if sig_elements.get('algorithm') != 'hmac-sha256':
            logger.warning(
                'Signature uses incorrect algorithm. '
                f'Supplied algorithm: {sig_elements.get("algorithm")}'
            )
            return False

        # verfiy signature hash
        request_target = f'{request.method.lower()} {request.path}'
        sig_string = (f'(request-target) {request_target}\n'
                      f'host: {request.headers.get("Host", "")}\n'
                      f'date: {request.headers.get("Date", "")}')
        local_sig_hashed = hmac.new(
            self.node_sig_key.encode(),
            msg=sig_string.encode(),
            digestmod=sha256
        )

        compare = hmac.compare_digest(
            local_sig_hashed,
            b64decode(sig_elements['signature'])
        )

        if not compare:
            logger.warning('Failed to validate. Signatures do not match.')
            return False

        return True
