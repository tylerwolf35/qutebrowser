# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

# Copyright 2014-2021 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <https://www.gnu.org/licenses/>.

"""An HTTP client based on QNetworkAccessManager."""

import functools
import urllib.parse
from typing import MutableMapping

from qutebrowser.qt.core import pyqtSignal, QObject, QTimer
from qutebrowser.qt.network import (QNetworkAccessManager, QNetworkRequest,
                             QNetworkReply)

from qutebrowser.utils import log


class HTTPRequest(QNetworkRequest):
    """A QNetworkRquest that follows (secure) redirects by default."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                          QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)


class HTTPClient(QObject):

    """An HTTP client based on QNetworkAccessManager.

    Intended for APIs, automatically decodes data.

    Attributes:
        _nam: The QNetworkAccessManager used.
        _timers: A {QNetworkReply: QTimer} dict.

    Signals:
        success: Emitted when the operation succeeded.
                 arg: The received data.
        error: Emitted when the request failed.
               arg: The error message, as string.
    """

    success = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        with log.disable_qt_msghandler():
            # WORKAROUND for a hang when messages are printed, see our
            # NetworkAccessManager subclass for details.
            self._nam = QNetworkAccessManager(self)
        self._timers: MutableMapping[QNetworkReply, QTimer] = {}

    def post(self, url, data=None):
        """Create a new POST request.

        Args:
            url: The URL to post to, as QUrl.
            data: A dict of data to send.
        """
        if data is None:
            data = {}
        encoded_data = urllib.parse.urlencode(data).encode('utf-8')
        request = HTTPRequest(url)
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                          'application/x-www-form-urlencoded;charset=utf-8')
        reply = self._nam.post(request, encoded_data)
        self._handle_reply(reply)

    def get(self, url):
        """Create a new GET request.

        Emits success/error when done.

        Args:
            url: The URL to access, as QUrl.
        """
        request = HTTPRequest(url)
        reply = self._nam.get(request)
        self._handle_reply(reply)

    def _handle_reply(self, reply):
        """Handle a new QNetworkReply."""
        if reply.isFinished():
            self.on_reply_finished(reply)
        else:
            timer = QTimer(self)
            timer.setInterval(10000)
            timer.timeout.connect(reply.abort)
            timer.start()
            self._timers[reply] = timer
            reply.finished.connect(functools.partial(
                self.on_reply_finished, reply))

    def on_reply_finished(self, reply):
        """Read the data and finish when the reply finished.

        Args:
            reply: The QNetworkReply which finished.
        """
        timer = self._timers.pop(reply)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.error.emit(reply.errorString())
            return
        try:
            data = bytes(reply.readAll()).decode('utf-8')
        except UnicodeDecodeError:
            self.error.emit("Invalid UTF-8 data received in reply!")
            return
        self.success.emit(data)
